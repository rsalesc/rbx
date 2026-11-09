import pathlib
from typing import Iterator, List, Optional

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from rbx.box.linters import registry
from rbx.box.linters.asset_kind import AssetKind, infer_asset_kind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity
from rbx.box.schema import CodeItem

_HEADER_NAME = 'rbx.h'

# Headers rbx injects next to a source. A grader including one of them is not
# including a task header.
_BUILTIN_HEADERS = frozenset({'rbx.h', 'testlib.h', 'jngen.h', 'tgen.h'})

_DISABLE_HINTS = (
    '  - To intentionally allow it here: add '
    '`// rbx-header-linter: disable` after the include line.\n'
    '  - To turn this check off everywhere: remove `rbx-header` from '
    '`linters` in your env.rbx.yml.\n'
)

_GENERATOR_MESSAGE = (
    'Generators must not #include "rbx.h". It exposes the problem\'s '
    'variables/constraints via getVar, so a generator that reads them '
    'silently changes its tests whenever a constraint changes.\n'
    + _DISABLE_HINTS
    + '  - Why this matters: https://rbx.rsalesc.dev/generators-and-rbx-h/'
)

_GRADER_MESSAGE = (
    'Graders must #include "rbx.h" after the task header ("{task_header}"). '
    'rbx.h pulls in standard headers and declarations of its own, so a task '
    'header parsed after it can compile in the grader while it is missing '
    "something it needs, then fail in the contestant's solution, which "
    'includes it without rbx.h.\n'
    + _DISABLE_HINTS
    + '  - Fix: move `#include "rbx.h"` below `#include "{task_header}"`.'
)

_LANGUAGE = Language(tree_sitter_cpp.language())


def _parser() -> Parser:
    return Parser(_LANGUAGE)


def _include_spelling(node: Node) -> Optional[str]:
    """The header path of a ``preproc_include`` node, quoted or angled."""
    for child in node.children:
        if child.type in ('string_literal', 'system_lib_string'):
            text = child.text.decode('utf-8')
            # Strip the surrounding "..." or <...>.
            return text[1:-1] if len(text) >= 2 else text
    return None


def _is_quoted(node: Node) -> bool:
    return any(child.type == 'string_literal' for child in node.children)


def _includes(source: str) -> Iterator[Node]:
    """Every ``preproc_include`` node of `source`, in source order."""
    tree = _parser().parse(bytes(source, 'utf8'))
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == 'preproc_include':
            yield node
        stack.extend(reversed(node.children))


def _is_rbx_header(spelling: str) -> bool:
    return pathlib.PurePosixPath(spelling).name == _HEADER_NAME


def _message_at(node: Node, message: str) -> LinterMessage:
    row, col = node.start_point
    return LinterMessage(
        severity=LinterSeverity.ERROR,
        message=message,
        line=row + 1,
        col=col + 1,
    )


def _is_task_header(code: CodeItem, node: Node, spelling: str) -> bool:
    """Whether a quoted include names a header shipped beside the grader.

    Those are the headers contestants receive and include from their own
    solution (`sumgame.h`), as opposed to rbx's builtin headers or system
    headers spelled with quotes.
    """
    if not _is_quoted(node) or pathlib.PurePosixPath(spelling).name in (
        _BUILTIN_HEADERS
    ):
        return False
    return (pathlib.Path(code.path).parent / spelling).is_file()


class RbxHeaderLinter(Linter):
    """Polices how sources depend on ``rbx.h``.

    - A generator must not include it: ``rbx.h`` exposes the problem's
      variables/constraints via ``getVar``, and a generator reading them
      produces tests that change silently when a constraint changes.
    - A grader must include it only after its task headers, so each task
      header compiles in the grader exactly as it does in the contestant's
      solution, without ``rbx.h`` in front of it.
    """

    name = 'rbx-header'
    applies_to = {AssetKind.GENERATOR, AssetKind.GRADER}

    def lint(self, code: CodeItem, source: str) -> List[LinterMessage]:
        if infer_asset_kind(code) == AssetKind.GRADER:
            return self._lint_grader(code, source)
        return self._lint_generator(source)

    def _lint_generator(self, source: str) -> List[LinterMessage]:
        return [
            _message_at(node, _GENERATOR_MESSAGE)
            for node in _includes(source)
            if (spelling := _include_spelling(node)) is not None
            and _is_rbx_header(spelling)
        ]

    def _lint_grader(self, code: CodeItem, source: str) -> List[LinterMessage]:
        first_rbx: Optional[Node] = None
        for node in _includes(source):
            spelling = _include_spelling(node)
            if spelling is None:
                continue
            if _is_rbx_header(spelling):
                if first_rbx is None:
                    first_rbx = node
            elif first_rbx is not None and _is_task_header(code, node, spelling):
                return [
                    _message_at(first_rbx, _GRADER_MESSAGE.format(task_header=spelling))
                ]
        return []


registry.register(RbxHeaderLinter)
