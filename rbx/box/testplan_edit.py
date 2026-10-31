"""Text-level edits of rbx-format testplans (``.txt`` generator scripts).

Everything here is a pure function from a script's text to a new text, so a
promotion can be computed (and shown as a diff) before anything is written.
The structure comes from the testplan grammar in
:mod:`rbx.box.stressing.generator_script_parser`; the edits themselves are
line splices, so comments, blank lines and indentation the setter wrote are
kept as they were.

A **scope** is where a line lands: ``None`` for the top level of the file, or
a ``/``-joined ``@testgroup`` path (``main`` or ``main/large``) for the inside
of a block with that full path -- either written as one ``@testgroup
main/large`` or as nested blocks.
"""

import dataclasses
import pathlib
from typing import List, Optional

import lark

from rbx.box.stressing import generator_script_parser

DEFAULT_INDENT = '  '


@dataclasses.dataclass(frozen=True)
class Statement:
    """One leaf statement of a testplan: one test."""

    start_line: int
    end_line: int
    # 'generator_call', 'copy_test' or 'inline_input'.
    kind: str
    # The full ``@testgroup`` path it sits in, or None at the top level.
    group: Optional[str]
    # The file a ``@copy`` reads, as written.
    copy_path: Optional[pathlib.Path] = None


@dataclasses.dataclass(frozen=True)
class Block:
    """One ``@testgroup { ... }`` block."""

    # The full path, including the enclosing blocks'.
    path: str
    start_line: int
    # Character offset of the block's closing ``}``.
    close_pos: int


def _join(prefix: Optional[str], name: str) -> str:
    return name if prefix is None else f'{prefix}/{name}'


def _walk(tree: lark.Tree, statements: List[Statement], blocks: List[Block]) -> None:
    def walk(node: lark.Tree, group: Optional[str]) -> None:
        for child in node.children:
            if not isinstance(child, lark.Tree):
                continue
            rule = str(child.data)
            if rule == 'testgroup':
                path = _join(group, str(child.children[1]))
                blocks.append(
                    Block(
                        path=path,
                        start_line=child.meta.line,
                        close_pos=child.meta.end_pos - 1,
                    )
                )
                walk(child, path)
            elif rule in ('generator_call', 'copy_test', 'inline_input'):
                copy_path = None
                if rule == 'copy_test':
                    filepath, _ = generator_script_parser.split_allow_duplicate(
                        str(child.children[1])
                    )
                    copy_path = pathlib.Path(filepath)
                statements.append(
                    Statement(
                        start_line=child.meta.line,
                        end_line=child.meta.end_line,
                        kind=rule,
                        group=group,
                        copy_path=copy_path,
                    )
                )

    walk(tree, None)


def statements(script: str) -> List[Statement]:
    """Every leaf statement of ``script``, in file order."""
    res: List[Statement] = []
    _walk(generator_script_parser.parse(script), res, [])
    res.sort(key=lambda s: s.start_line)
    return res


def blocks(script: str) -> List[Block]:
    """Every ``@testgroup`` block of ``script``, in file order."""
    res: List[Block] = []
    _walk(generator_script_parser.parse(script), [], res)
    res.sort(key=lambda b: b.start_line)
    return res


def statement_at(script: str, line: int) -> Optional[Statement]:
    """The statement starting on 1-based ``line``, if any."""
    for statement in statements(script):
        if statement.start_line == line:
            return statement
    return None


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _line_start(script: str, pos: int) -> int:
    return script.rfind('\n', 0, pos) + 1


def _child_indent(script: str, block: Block) -> str:
    """How the statements of ``block`` are indented: as its first child is, or
    one level deeper than the block itself when it has none."""
    lines = script.splitlines()
    close_line = script.count('\n', 0, block.close_pos) + 1
    for statement in statements(script):
        if block.start_line < statement.start_line <= close_line:
            text = lines[statement.start_line - 1]
            if statement.start_line != block.start_line and text.strip():
                return _indent_of(text)
    return _indent_of(lines[block.start_line - 1]) + DEFAULT_INDENT


def _render(lines: List[str], comment: Optional[str], indent: str) -> List[str]:
    out = []
    if comment:
        out.append(f'{indent}# {comment}')
    out.extend(f'{indent}{line}' for line in lines)
    return out


def append_top_level(
    script: str, lines: List[str], comment: Optional[str] = None
) -> str:
    """``lines`` appended at the end of the file, at the top level.

    A comment opens a block of its own, so it is set apart by a blank line.
    """
    if script and not script.endswith('\n'):
        script += '\n'
    if comment and script.strip() and not script.endswith('\n\n'):
        script += '\n'
    return script + ''.join(f'{line}\n' for line in _render(lines, comment, ''))


def insert_in_scope(
    script: str,
    scope: Optional[str],
    lines: List[str],
    comment: Optional[str] = None,
) -> str:
    """``lines`` (each one statement, unindented) added at the end of ``scope``.

    For a ``@testgroup`` scope, that is just before the closing ``}`` of the
    last block with that full path, indented like the block's statements. When
    no block has that path yet, a new one is appended to the file.
    """
    if scope is None:
        return append_top_level(script, lines, comment)

    matching = [b for b in blocks(script) if b.path == scope]
    if not matching:
        body = '\n'.join(_render(lines, comment, DEFAULT_INDENT))
        prefix = script
        if prefix and not prefix.endswith('\n'):
            prefix += '\n'
        if prefix.strip():
            prefix += '\n'
        return f'{prefix}@testgroup {scope} {{\n{body}\n}}\n'

    block = matching[-1]
    indent = _child_indent(script, block)
    rendered = ''.join(f'{line}\n' for line in _render(lines, comment, indent))
    start = _line_start(script, block.close_pos)
    if not script[start : block.close_pos].strip():
        # The `}` sits on a line of its own: the new lines go right above it.
        return script[:start] + rendered + script[start:]
    # `... }` shares its line with a statement: break the line before the `}`.
    head = script[: block.close_pos].rstrip()
    close_indent = _indent_of(script[start : block.close_pos])
    return f'{head}\n{rendered}{close_indent}{script[block.close_pos :]}'


def replace_statement(script: str, start_line: int, lines: List[str]) -> str:
    """The statement starting on ``start_line`` replaced by ``lines``.

    The comments above it stay, and the new lines take its indentation. Text
    sharing the statement's first or last line (an opening ``{``, a closing
    ``}``) stays where it was.
    """
    statement = statement_at(script, start_line)
    if statement is None:
        raise ValueError(f'No statement starts on line {start_line}.')
    col, end_col = _columns(script, statement)
    text_lines = script.split('\n')
    head = text_lines[statement.start_line - 1][:col]
    tail = text_lines[statement.end_line - 1][end_col:]
    if head.strip():
        indent = _indent_of(head)
        new = [head + lines[0]] + [f'{indent}{line}' for line in lines[1:]]
    else:
        new = [f'{head}{line}' for line in lines]
    if tail.strip():
        new[-1] = new[-1].rstrip() + ' ' + tail.lstrip()
    text_lines[statement.start_line - 1 : statement.end_line] = new
    return '\n'.join(text_lines)


def _columns(script: str, statement: Statement):
    """The 0-based column the statement starts at on its first line, and the
    one it ends at on its last."""
    tree = generator_script_parser.parse(script)
    for node in tree.iter_subtrees():
        if str(node.data) == statement.kind and node.meta.line == statement.start_line:
            return node.meta.column - 1, node.meta.end_column - 1
    raise AssertionError('unreachable')  # pragma: no cover


def remove_statements(script: str, start_lines: List[int]) -> str:
    """The statements starting on ``start_lines`` removed, with the comment
    lines directly above each. Blank lines left behind are collapsed."""
    spans = {s.start_line: s for s in statements(script)}
    lines = script.splitlines()
    drop = set()
    for start in start_lines:
        span = spans.get(start)
        if span is None:
            continue
        drop.update(range(span.start_line, span.end_line + 1))
        prev = span.start_line - 1
        while prev >= 1:
            stripped = lines[prev - 1].strip()
            if stripped.startswith('//') or stripped.startswith('#'):
                drop.add(prev)
                prev -= 1
            else:
                break
    kept = [line for i, line in enumerate(lines, start=1) if i not in drop]
    out = []
    for line in kept:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    text = '\n'.join(out)
    return text + '\n' if text else ''


def copy_line(path: pathlib.Path) -> str:
    return f'@copy {path.as_posix()}'
