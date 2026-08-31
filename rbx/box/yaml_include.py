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

import dataclasses
import pathlib
from typing import Any, List, Optional, Set, Tuple

import ruyaml
import typer
from ruyaml.comments import CommentedMap, CommentedSeq
from ruyaml.constructor import RoundTripConstructor
from ruyaml.nodes import ScalarNode

from rbx.box.exception import RbxException
from rbx.console import console

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


def _any_include(node: Any) -> bool:
    if is_include(node):
        return True
    if isinstance(node, CommentedMap):
        return any(
            _is_merge_key(key) and is_include(node[key]) or _any_include(node[key])
            for key in node.keys()
        )
    if isinstance(node, CommentedSeq):
        return any(_any_include(item) for item in node)
    return False


def file_has_includes(path: pathlib.Path) -> bool:
    """Whether `path` contains an `!include` anywhere in its own text.

    Purely syntactic -- it does not follow or require the fragments to exist,
    so it is safe to call on a broken include graph. Writers use it to avoid
    re-serialising a file from a Pydantic model, which would inline every
    fragment and silently destroy the sharing.
    """
    try:
        tree = make_yaml().load(path.read_text())
    except (OSError, ruyaml.YAMLError):
        return False
    return _any_include(tree)


@dataclasses.dataclass
class EditTarget:
    """A value to edit, in whichever file actually owns it.

    Resolution follows `!include` tags, so `path` is the fragment the value
    lives in rather than the file the caller started from. Mutate `value` in
    place (it is a live round-trip node, so comments survive) or call
    `replace`; either marks the owning file dirty. Then `save`.
    """

    session: 'EditSession'
    path: pathlib.Path
    # Container and key holding the value, or None when the value *is* the
    # document root of `path`.
    parent: Optional[Any]
    key: Optional[Any]

    @property
    def value(self) -> Any:
        """The node to edit, or None when the key is not present yet."""
        if self.parent is None:
            node = self.session.tree(self.path)
        elif self.key not in self.parent:
            return None
        else:
            node = self.parent[self.key]
        # Mutating a container in place cannot notify us, so assume any read of
        # a mutable node is about to change it.
        if isinstance(node, (CommentedMap, CommentedSeq)):
            self.session.mark_dirty(self.path)
        return node

    def replace(self, new_value: Any) -> None:
        self.session.mark_dirty(self.path)
        if self.parent is None:
            self.session.set_tree(self.path, new_value)
        else:
            self.parent[self.key] = new_value

    def save(self) -> None:
        """Write every file this target's session touched."""
        self.session.save()


def _merge_include_sources(node: CommentedMap) -> List[str]:
    return [
        node[key].value
        for key in node.keys()
        if _is_merge_key(key) and is_include(node[key])
    ]


class EditSession:
    """Targeted, include-aware edits across one config and its fragments.

    A config's values can live in several files, and one logical change may
    touch more than one of them. The session keeps a single round-trip tree per
    file, so two edits to the same file cannot clobber each other, and writes
    only the files an edit actually touched.
    """

    def __init__(self, path: pathlib.Path):
        self.root_path = path.resolve()
        self.yaml = make_yaml()
        self._trees: dict = {}
        self._dirty: Set[pathlib.Path] = set()

    def tree(self, path: pathlib.Path) -> Any:
        path = path.resolve()
        if path not in self._trees:
            self._trees[path] = self.yaml.load(path.read_text())
        return self._trees[path]

    def set_tree(self, path: pathlib.Path, value: Any) -> None:
        self._trees[path.resolve()] = value

    def mark_dirty(self, path: pathlib.Path) -> None:
        self._dirty.add(path.resolve())

    def touched_files(self) -> Set[pathlib.Path]:
        """Every file `save` would write."""
        return set(self._dirty)

    def _follow_includes(
        self, node: Any, base_dir: pathlib.Path, stack: IncludeStack
    ) -> Tuple[Any, pathlib.Path, IncludeStack]:
        """Resolve a chain of `!include`s, returning the node and its owner."""
        while is_include(node):
            target = _resolve_path(node.value, base_dir, stack)
            stack = stack + (target,)
            node = self.tree(target)
            base_dir = target.parent
        return node, stack[-1], stack

    def target(self, *keys: Any) -> EditTarget:
        """Descend `keys` from the root file, crossing into fragments.

        Raises IncludeError when a fragment cannot be read, or when the
        requested key exists only by way of a `<<: !include` merge -- the value
        lives in the fragment's map, and rbx will not guess whether the caller
        meant to edit the shared value or shadow it here.
        """
        stack: IncludeStack = (self.root_path,)
        node, owner, stack = self._follow_includes(
            self.tree(self.root_path), self.root_path.parent, stack
        )
        parent: Optional[Any] = None
        key: Optional[Any] = None

        for index, seg in enumerate(keys):
            if isinstance(node, CommentedMap) and seg not in node:
                merged_from = _merge_include_sources(node)
                if merged_from:
                    with IncludeError() as err:
                        err.print(
                            f'[error]Cannot edit [item]'
                            f'{".".join(str(k) for k in keys)}[/item] in [item]'
                            f'{self.root_path}[/item]: [item]{seg}[/item] is not set '
                            f'there and would come from [item]'
                            f'{", ".join(merged_from)}[/item] via `<<: !include`.'
                            f'[/error]\n'
                            f'[warning]Edit that fragment directly, or set '
                            f'[item]{seg}[/item] explicitly here first.[/warning]'
                        )
                if index == len(keys) - 1:
                    # A brand new key: the caller may create it with `replace`.
                    return EditTarget(self, owner, node, seg)
                with IncludeError() as err:
                    err.print(
                        f'[error][item]{seg}[/item] is not set in [item]'
                        f'{self.root_path}[/item].[/error]'
                    )

            parent, key = node, seg
            node = node[seg]
            resolved, owner_candidate, stack = self._follow_includes(
                node, owner.parent, stack
            )
            if resolved is not node:
                # The value came from a fragment: continue there, and forget the
                # parent -- the fragment's document root *is* the value.
                node, owner = resolved, owner_candidate
                parent, key = None, None

        return EditTarget(self, owner, parent, key)

    def save(self) -> None:
        for path in sorted(self._dirty):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w') as handle:
                self.yaml.dump(self._trees[path], handle)
        self._dirty.clear()


def open_for_edit(path: pathlib.Path, *keys: Any) -> EditTarget:
    """Open `path`, descend `keys`, and return a handle on the owning file.

    Convenience wrapper around a single-target `EditSession`; use the session
    directly when one change touches several keys.
    """
    return EditSession(path).target(*keys)


CONTEST_GLOB = 'contest*.rbx.yml'


def _include_closure(path: pathlib.Path) -> Set[pathlib.Path]:
    """Every file `path` reaches through includes, itself included.

    Best-effort: an unresolvable or unparseable include stops that branch
    rather than raising, so a broken sibling cannot break a scan over many.
    """
    seen: Set[pathlib.Path] = set()

    def walk(current: pathlib.Path) -> None:
        current = current.resolve()
        if current in seen or not current.is_file():
            return
        seen.add(current)
        try:
            tree = make_yaml().load(current.read_text())
        except (OSError, ruyaml.YAMLError):
            return
        for raw in _include_targets(tree):
            candidate = pathlib.Path(raw)
            if candidate.is_absolute():
                continue
            walk(current.parent / candidate)

    walk(path)
    return seen


def _include_targets(node: Any) -> List[str]:
    if is_include(node):
        return [node.value]
    found: List[str] = []
    if isinstance(node, CommentedMap):
        for key in node.keys():
            found.extend(_include_targets(node[key]))
    elif isinstance(node, CommentedSeq):
        for item in node:
            found.extend(_include_targets(item))
    return found


def including_files(
    fragment: pathlib.Path,
    search_root: pathlib.Path,
    glob: str = CONTEST_GLOB,
) -> List[pathlib.Path]:
    """Every config under `search_root` that reaches `fragment` via includes.

    Used to report the blast radius before editing a shared fragment.
    """
    fragment = fragment.resolve()
    reachers = [
        candidate
        for candidate in sorted(search_root.glob(glob))
        if candidate.resolve() != fragment and fragment in _include_closure(candidate)
    ]
    return reachers


def confirm_shared_edit(
    target: EditTarget,
    started_from: pathlib.Path,
    search_root: pathlib.Path,
    yes: bool = False,
) -> bool:
    """Report the blast radius of editing a shared fragment and confirm.

    Returns True when the edit should proceed. Silent (and True) when the
    target is the file the caller started from, or when no other config
    reaches it.
    """
    if target.path == started_from.resolve():
        return True
    reachers = including_files(target.path, search_root)
    others = [path for path in reachers if path.resolve() != started_from.resolve()]
    try:
        shown = target.path.relative_to(search_root)
    except ValueError:
        shown = target.path
    if not others:
        console.print(f'Editing [item]{shown}[/item].')
        return True

    names = ', '.join(sorted(path.name for path in reachers))
    console.print(
        f'[warning]Editing [item]{shown}[/item], which is included by '
        f'{len(reachers)} contests: {names}.[/warning]'
    )
    if yes:
        return True
    return typer.confirm('Proceed?', default=True)


def die_if_write_would_inline_includes(path: pathlib.Path) -> None:
    """Refuse to re-serialise a whole config that uses `!include`.

    A writer that rebuilds a file from its Pydantic model loses the includes --
    they do not survive validation -- so writing that back inlines every
    fragment and silently undoes the sharing.

    Targeted writers do not need this: `EditSession` navigates the round-trip
    tree and lands each edit in the file that owns it. This guards the
    whole-model writers, which have no way to know where a value came from.
    """
    if not file_has_includes(path):
        return
    with IncludeError() as err:
        err.print(
            f'[error]Refusing to rewrite [item]{path}[/item]: it uses '
            f'[item]!include[/item], and saving would inline every fragment and '
            f'lose the sharing.[/error]\n'
            f'[warning]Edit the file (or the fragment that owns the value) by '
            f'hand instead.[/warning]'
        )


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
