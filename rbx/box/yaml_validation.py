"""Pretty-rendered YAML loading and validation for user-authored configs.

Loads a YAML file with ruyaml (round-trip mode, so every node carries its
source line/column) and validates it against a Pydantic model. On either a
YAML syntax error or a Pydantic validation error, raises a typed
RbxException whose ``str(exc)`` is a rust-style caret diagnostic showing
file, line, snippet, caret, and message.

The single public entry point is :func:`load_yaml_model`.
"""

from __future__ import annotations

import pathlib
from typing import Any, Tuple, Type, TypeVar

import pydantic
from ruyaml.comments import CommentedMap, CommentedSeq

from rbx.box.exception import RbxException

T = TypeVar('T', bound=pydantic.BaseModel)

PYDANTIC_INTERNAL_LOC_SEGMENTS = frozenset({'union_tag', 'tagged-union'})


class YamlSyntaxError(RbxException):
    """Raised when a YAML file cannot be parsed."""


class YamlValidationError(RbxException):
    """Raised when a YAML file parses but fails Pydantic schema validation."""


def _locate(
    loc: Tuple[Any, ...],
    root: Any,
) -> Tuple[int, int, int]:
    """Walk a Pydantic ``loc`` tuple against a ruyaml-parsed tree.

    ruyaml's ``CommentedMap`` and ``CommentedSeq`` carry source positions
    via ``.lc``: ``lc.key(name)``, ``lc.value(name)``, and ``lc.item(i)``
    each return ``(line, col)`` 0-based. This function normalises to
    1-based line/column for display and computes a caret span.

    Algorithm (see design doc, "Locating the source line"):

    - Walk each segment. If the current node is a CommentedMap and the
      segment is a string key that exists, record its key position and
      descend.
    - If the current node is a CommentedSeq and the segment is an int
      index in range, record its item position and descend.
    - If the segment is a Pydantic-internal marker (``union_tag``,
      ``tagged-union``), skip it and continue.
    - Otherwise, stop walking and return the last known position
      (the deepest resolvable ancestor).

    The caret span widens to the length of the final node's scalar
    representation when applicable; otherwise it stays at the length of
    the last walked key.

    Args:
        loc: Pydantic error ``loc`` tuple; segments are ``str`` (map
            keys), ``int`` (sequence indices), or internal markers.
        root: ruyaml-parsed root node (CommentedMap or CommentedSeq).

    Returns:
        ``(line, col, span)``, all 1-based for line/col.
    """
    # ruyaml uses 0-based line/col; we convert to 1-based on return.
    if hasattr(root, 'lc'):
        last_line, last_col = root.lc.line, root.lc.col
    else:
        last_line, last_col = 0, 0
    last_span = 1

    node: Any = root
    parent: Any = None
    last_seg: Any = None
    walked_any = False
    broke_on_missing_map_key = False
    for seg in loc:
        if isinstance(node, CommentedMap) and isinstance(seg, str) and seg in node:
            line, col = node.lc.key(seg)
            last_line, last_col = line, col
            last_span = len(seg)
            parent, last_seg = node, seg
            node = node[seg]
            walked_any = True
            continue
        if (
            isinstance(node, CommentedSeq)
            and isinstance(seg, int)
            and 0 <= seg < len(node)
        ):
            line, col = node.lc.item(seg)
            last_line, last_col = line, col
            last_span = 1
            parent, last_seg = node, seg
            node = node[seg]
            walked_any = True
            continue
        if seg in PYDANTIC_INTERNAL_LOC_SEGMENTS:
            continue
        # Failed to walk -- note whether it was a missing key in a map.
        if isinstance(node, CommentedMap) and isinstance(seg, str):
            broke_on_missing_map_key = True
        break

    # Anchor on the first key when a map walk fails, so the caret spans
    # something visible instead of a single-char position.
    if broke_on_missing_map_key and isinstance(node, CommentedMap) and len(node) > 0:
        first_key = next(iter(node))
        if isinstance(first_key, str):
            try:
                line, col = node.lc.key(first_key)
                last_line, last_col = line, col
                last_span = len(first_key)
            except KeyError, AttributeError:
                pass

    # Scalar-value widening: when we descended fully into a scalar inside
    # a map, point the caret at the value (not the key) so users see what
    # is wrong, not where it is.
    if (
        walked_any
        and not isinstance(node, (CommentedMap, CommentedSeq))
        and node is not None
        and isinstance(parent, CommentedMap)
        and isinstance(last_seg, str)
    ):
        try:
            v_line, v_col = parent.lc.value(last_seg)
            last_line, last_col = v_line, v_col
            last_span = max(1, len(str(node)))
        except KeyError, AttributeError:
            pass

    return last_line + 1, last_col + 1, last_span


def load_yaml_model(path: pathlib.Path, model: Type[T]) -> T:
    """Load a YAML file and validate it against a Pydantic model.

    Args:
        path: Path to a YAML file. Must exist; ``FileNotFoundError`` from
            ``read_text`` propagates unchanged.
        model: A ``pydantic.BaseModel`` subclass to validate the loaded
            data against.

    Returns:
        An instance of ``model`` populated from the YAML file.

    Raises:
        YamlSyntaxError: The file is not valid YAML.
        YamlValidationError: The file parses but does not match ``model``.
        FileNotFoundError: The file does not exist.
    """
    raise NotImplementedError
