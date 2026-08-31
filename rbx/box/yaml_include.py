"""Resolution of the `!include` YAML tag for user-authored configs.

A contest variant duplicates nearly all of the canonical contest's
configuration (design doc: `docs/plans/2026-08-31-yaml-include-fragments-design.md`).
`!include` lets the shared parts live in fragment files that several configs
splice in:

    statements: !include shared/statements.yml
    vars:
      <<: !include shared/vars.yml
      warmup: true

Resolution happens on the ruyaml *round-trip* tree, between parsing and
Pydantic validation, so spliced subtrees keep their own source positions and
diagnostics can name the fragment that actually owns an error.
"""

from __future__ import annotations

import pathlib
from typing import Any, Optional, Set, Tuple

import ruyaml
from ruyaml.comments import CommentedMap, CommentedSeq
from ruyaml.constructor import RoundTripConstructor
from ruyaml.nodes import ScalarNode

from rbx.box.exception import RbxException

INCLUDE_TAG = '!include'
MERGE_TAG = 'tag:yaml.org,2002:merge'

# Stamped on a spliced fragment root, naming the file it came from. Diagnostics
# read it to blame the fragment that actually owns a validation error rather
# than the file that included it.
SOURCE_ATTR = '_rbx_include_source'


class IncludeError(RbxException):
    """Raised when an `!include` cannot be resolved."""


def tag_value(obj) -> str:
    """The tag of a node or constructed scalar, as a plain string.

    ruyaml is inconsistent about this: parser-level nodes carry `tag` as a
    `str`, while a constructed `TaggedScalar` wraps it in a `Tag` object whose
    `str()` is the repr `"Tag('!include')"`. Normalise both.
    """
    tag = getattr(obj, 'tag', None)
    if tag is None:
        return ''
    return getattr(tag, 'value', None) or str(tag)


def _is_include_node(node) -> bool:
    return isinstance(node, ScalarNode) and tag_value(node) == INCLUDE_TAG


def is_include(obj) -> bool:
    """Whether a constructed round-trip value is an unresolved `!include`."""
    return tag_value(obj) == INCLUDE_TAG


class IncludeTolerantConstructor(RoundTripConstructor):
    """A round-trip constructor that tolerates `<<: !include ...`.

    ruyaml resolves merge keys during construction and raises on a value node
    that is not already a mapping. An `!include` is still a scalar at that
    point -- the fragment has not been read yet -- so those pairs are lifted
    out before delegating to `super()` and reinserted afterwards. The actual
    merge happens later, during include resolution, once the fragment is
    loaded.

    Without this, `<<: !include x.yml` fails at load time with
    "expected a mapping or list of mappings for merging, but found scalar".
    """

    def flatten_mapping(self, node):
        includes = []
        kept = []
        for key, value in node.value:
            if (
                isinstance(key, ScalarNode)
                and tag_value(key) == MERGE_TAG
                and _is_include_node(value)
            ):
                includes.append((key, value))
            else:
                kept.append((key, value))
        node.value = kept
        merge = super().flatten_mapping(node)
        node.value = includes + node.value
        return merge


def make_yaml() -> ruyaml.YAML:
    """A round-trip YAML instance that can parse `!include`, merge form included."""
    yaml = ruyaml.YAML(typ='rt')
    yaml.Constructor = IncludeTolerantConstructor
    return yaml


IncludeStack = Tuple[pathlib.Path, ...]


def _resolve_path(
    raw: str, base_dir: pathlib.Path, stack: IncludeStack
) -> pathlib.Path:
    """Turn an `!include` payload into an existing file path, or raise."""
    includer = stack[-1]
    candidate = pathlib.Path(raw)
    if candidate.is_absolute():
        with IncludeError() as err:
            err.print(
                f'[error]`!include {raw}` in [item]{includer}[/item] is an absolute '
                f'path. Includes must be relative to the including file.[/error]'
            )
    target = (base_dir / candidate).resolve()
    if target in stack:
        chain = ' -> '.join(str(path) for path in stack + (target,))
        with IncludeError() as err:
            err.print(f'[error]`!include` cycle detected: {chain}[/error]')
    if not target.is_file():
        with IncludeError() as err:
            err.print(
                f'[error]`!include {raw}` in [item]{includer}[/item] points at '
                f'[item]{target}[/item], which does not exist.[/error]'
            )
    return target


def _stamp(tree: Any, path: pathlib.Path) -> None:
    if isinstance(tree, (CommentedMap, CommentedSeq)):
        try:
            setattr(tree, SOURCE_ATTR, path)
        except AttributeError:
            # Not fatal: the tree still resolves, diagnostics just fall back to
            # blaming the including file.
            pass


def source_of(tree: Any) -> Optional[pathlib.Path]:
    """The fragment a spliced subtree came from, or None if it was inline."""
    return getattr(tree, SOURCE_ATTR, None)


def _splice(
    node: Any,
    base_dir: pathlib.Path,
    stack: IncludeStack,
    sources: Set[pathlib.Path],
) -> Any:
    """Replace one `!include` node with the fragment's resolved tree."""
    target = _resolve_path(node.value, base_dir, stack)
    sources.add(target)
    sub = make_yaml().load(target.read_text())
    sub = _resolve_node(sub, target.parent, stack + (target,), sources)
    _stamp(sub, target)
    return sub


def _is_merge_key(key: Any) -> bool:
    return key == '<<' or tag_value(key) == MERGE_TAG


def _apply_merge_includes(
    node: CommentedMap,
    base_dir: pathlib.Path,
    stack: IncludeStack,
    sources: Set[pathlib.Path],
) -> None:
    """Resolve `<<: !include ...` pairs, merging *under* the explicit keys."""
    for key in [k for k in list(node.keys()) if _is_merge_key(k)]:
        value = node[key]
        del node[key]
        if not is_include(value):
            continue
        fragment = _splice(value, base_dir, stack, sources)
        if not isinstance(fragment, CommentedMap):
            with IncludeError() as err:
                err.print(
                    f'[error]`<<: !include {value.value}` expects the fragment to be '
                    f'a mapping, but it is a {type(fragment).__name__}.[/error]'
                )
        for fragment_key, fragment_value in fragment.items():
            if fragment_key not in node:
                node[fragment_key] = fragment_value


def _resolve_node(
    node: Any,
    base_dir: pathlib.Path,
    stack: IncludeStack,
    sources: Set[pathlib.Path],
) -> Any:
    if is_include(node):
        return _splice(node, base_dir, stack, sources)
    if isinstance(node, CommentedMap):
        _apply_merge_includes(node, base_dir, stack, sources)
        for key in list(node.keys()):
            node[key] = _resolve_node(node[key], base_dir, stack, sources)
        return node
    if isinstance(node, CommentedSeq):
        for index in range(len(node)):
            node[index] = _resolve_node(node[index], base_dir, stack, sources)
        return node
    return node


def resolve_yaml_file(path: pathlib.Path) -> Tuple[Any, Set[pathlib.Path]]:
    """Load `path` and splice in every transitive `!include`.

    Returns the resolved round-trip tree and the set of every file read, so
    callers can invalidate caches when any of them changes.
    """
    path = path.resolve()
    sources = {path}
    tree = make_yaml().load(path.read_text())
    tree = _resolve_node(tree, path.parent, (path,), sources)
    return tree, sources
