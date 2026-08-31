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

import ruyaml
from ruyaml.constructor import RoundTripConstructor
from ruyaml.nodes import ScalarNode

INCLUDE_TAG = '!include'
MERGE_TAG = 'tag:yaml.org,2002:merge'


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
