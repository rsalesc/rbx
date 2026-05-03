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
from typing import Any, List, Tuple, Type, TypeVar

import pydantic
import rich.text
import ruyaml
from rich.console import Group
from rich.syntax import Syntax
from ruyaml.comments import CommentedMap, CommentedSeq

from rbx.box.exception import RbxException

T = TypeVar('T', bound=pydantic.BaseModel)

PYDANTIC_INTERNAL_LOC_SEGMENTS = frozenset({'union_tag', 'tagged-union'})

WINDOW = 2  # lines of context before and after the offending line


class YamlSyntaxError(RbxException):
    """Raised when a YAML file cannot be parsed.

    Wraps a ``ruyaml.YAMLError`` and renders a single caret diagnostic
    pointing at ``problem_mark.line / .column``.
    """

    def __init__(
        self,
        path: pathlib.Path,
        source: str,
        cause: ruyaml.YAMLError,
    ):
        super().__init__()
        # Prefer context_mark (where the broken construct began) over
        # problem_mark (which often points at the stream end for
        # unterminated flow collections), falling back as needed.
        mark = getattr(cause, 'context_mark', None) or getattr(
            cause, 'problem_mark', None
        )
        if mark is not None:
            line = mark.line + 1
            col = mark.column + 1
        else:
            line, col = 1, 1
        msg = getattr(cause, 'problem', None) or str(cause)

        self.print(
            _render_diagnostic(
                source=source,
                path=path,
                line=line,
                col=col,
                span=1,
                msg=str(msg),
                loc_label='<root>',
                header='YAML syntax error',
            )
        )


class YamlValidationError(RbxException):
    """Raised when a YAML file parses but does not match a Pydantic model.

    Wraps a ``pydantic.ValidationError``. On construction, every error
    (after deduplication) is rendered as its own caret diagnostic block,
    sorted by source line/column. A trailing hint reminds the user to
    check they are running the latest ``rbx``.
    """

    def __init__(
        self,
        path: pathlib.Path,
        source: str,
        root: Any,
        cause: pydantic.ValidationError,
    ):
        super().__init__()
        deduped = _dedupe(list(cause.errors()))

        rendered_blocks: List[Tuple[int, int, Group]] = []
        for err in deduped:
            line, col, span = _locate(tuple(err['loc']), root)
            block = _render_diagnostic(
                source=source,
                path=path,
                line=line,
                col=col,
                span=span,
                msg=str(err['msg']),
                loc_label=_format_loc(tuple(err['loc'])),
                header='error',
            )
            rendered_blocks.append((line, col, block))

        rendered_blocks.sort(key=lambda t: (t[0], t[1]))

        n = len(rendered_blocks)
        plural = 's' if n != 1 else ''
        self.print(
            rich.text.Text.from_markup(
                f'[error]Failed to load[/error] [item]{path}[/item] '
                f'-- {n} validation error{plural}'
            )
        )
        self.print('')
        for _, _, block in rendered_blocks:
            self.print(block)
            self.print('')
        self.print(
            rich.text.Text.from_markup(
                '[error]If you believe this is a bug, ensure you are on the latest rbx.[/error]'
            )
        )


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
            except Exception:
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
        except Exception:
            pass

    return last_line + 1, last_col + 1, last_span


def _format_loc(loc: Tuple[Any, ...]) -> str:
    """Render a Pydantic loc tuple as ``a.b[2].c``.

    Empty tuples render as ``<root>``. Pydantic-internal segments
    (``union_tag`` etc.) are skipped so users do not see them.
    """
    if not loc:
        return '<root>'
    parts: List[str] = []
    for seg in loc:
        if seg in PYDANTIC_INTERNAL_LOC_SEGMENTS:
            continue
        if isinstance(seg, int):
            parts.append(f'[{seg}]')
        else:
            parts.append(f'.{seg}' if parts else str(seg))
    return ''.join(parts) or '<root>'


def _dedupe(errors: List[dict]) -> List[dict]:
    """Collapse Pydantic ``ValidationError.errors()`` for cleaner output.

    - Identical ``(loc, msg)`` pairs are deduplicated.
    - Multiple errors at the same ``loc`` whose ``type`` starts with
      ``union_`` are folded into a single synthetic message of the form
      ``"value did not match any of the allowed types (... | ...)"``.
    - Errors at distinct ``loc`` values stay distinct (covers
      discriminated unions where each branch lives at a different path).

    Output order matches first appearance per ``loc``; final
    line/column ordering is applied later by the renderer.
    """
    by_loc: 'dict[tuple, list[dict]]' = {}
    order: List[tuple] = []
    for e in errors:
        key = tuple(e['loc'])
        if key not in by_loc:
            by_loc[key] = []
            order.append(key)
        by_loc[key].append(e)

    out: List[dict] = []
    for key in order:
        group = by_loc[key]
        seen_msgs = set()
        unique = []
        for e in group:
            if e['msg'] in seen_msgs:
                continue
            seen_msgs.add(e['msg'])
            unique.append(e)

        union_branches = [
            e for e in unique if str(e.get('type', '')).startswith('union_')
        ]
        if len(union_branches) >= 2 and len(union_branches) == len(unique):
            joined = ' | '.join(e['msg'] for e in union_branches)
            out.append(
                {
                    'loc': key,
                    'msg': f'value did not match any of the allowed types ({joined})',
                    'type': 'union_folded',
                }
            )
        else:
            out.extend(unique)

    return out


def _render_diagnostic(
    *,
    source: str,
    path: pathlib.Path,
    line: int,
    col: int,
    span: int,
    msg: str,
    loc_label: str,
    header: str,
) -> Group:
    """Build a single caret diagnostic block.

    Layout::

        <header>: <loc_label> -- <msg>
          --> <path>:<line>:<col>
          [snippet via rich.syntax.Syntax with line numbers]
          [caret line aligned under the offending column]

    Args:
        source: Full source text of the file (for the snippet window).
        path: Path used in the ``--> path:line:col`` header.
        line: 1-based line of the offending token.
        col: 1-based column of the offending token (within ``line``).
        span: Number of caret characters to emit.
        msg: Short, plain-English error message.
        loc_label: Human-readable dotted path (from ``_format_loc``).
        header: ``"error"`` or ``"YAML syntax error"``.

    Returns:
        A ``rich.console.Group`` ready to ``console.print``.
    """
    lines = source.splitlines()
    total = len(lines)
    start = max(1, line - WINDOW)
    end = min(total, line + WINDOW)
    snippet_text = '\n'.join(lines[start - 1 : end])

    syntax = Syntax(
        snippet_text,
        'yaml',
        line_numbers=True,
        start_line=start,
        highlight_lines={line},
        theme='ansi_dark',
    )

    # Caret line: align under the correct column.
    # rich.syntax.Syntax renders a gutter of ``len(str(end)) + 2`` chars
    # before the source (line number + space + pipe + space). Adjust if
    # the caret column drifts in tests.
    gutter = len(str(end)) + 3
    caret = rich.text.Text(
        ' ' * (gutter + col - 1) + '^' * max(1, span), style='bold red'
    )

    header_text = rich.text.Text.from_markup(
        f'[error]{header}[/error]: [item]{loc_label}[/item] -- {msg}'
    )
    location_text = rich.text.Text.from_markup(
        f'  [info]-->[/info] {path}:{line}:{col}'
    )

    return Group(header_text, location_text, syntax, caret)


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
    source = path.read_text()
    try:
        data = ruyaml.YAML(typ='rt').load(source)
    except ruyaml.YAMLError as exc:
        raise YamlSyntaxError(path, source, exc) from exc

    try:
        return model.model_validate(data)
    except pydantic.ValidationError as exc:
        raise YamlValidationError(path, source, data, exc) from exc
