import pathlib
from typing import List, Optional

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from rbx.box.linters import registry
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity
from rbx.box.schema import CodeItem

_HEADER_NAME = 'rbx.h'

_MESSAGE = (
    'Generators must not #include "rbx.h". It exposes the problem\'s '
    'variables/constraints via getVar, so a generator that reads them '
    'silently changes its tests whenever a constraint changes.\n'
    '  - To intentionally allow it here: add '
    '`// rbx-header-linter: disable` after the include line.\n'
    '  - To turn this check off everywhere: remove `rbx-header` from '
    '`linters` in your env.rbx.yml.\n'
    '  - Why this matters: https://rbx.rsalesc.dev/generators-and-rbx-h/'
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


class RbxHeaderLinter(Linter):
    """Flags generators that directly depend on ``rbx.h``.

    ``rbx.h`` exposes the problem's variables/constraints via ``getVar``. A
    generator reading them produces tests that change silently when a
    constraint changes, so depending on it from a generator is an error.
    """

    name = 'rbx-header'
    applies_to = {AssetKind.GENERATOR}

    def lint(self, code: CodeItem, source: str) -> List[LinterMessage]:
        tree = _parser().parse(bytes(source, 'utf8'))
        messages: List[LinterMessage] = []
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            if node.type == 'preproc_include':
                spelling = _include_spelling(node)
                if (
                    spelling is not None
                    and pathlib.PurePosixPath(spelling).name == _HEADER_NAME
                ):
                    row, col = node.start_point
                    messages.append(
                        LinterMessage(
                            severity=LinterSeverity.ERROR,
                            message=_MESSAGE,
                            line=row + 1,
                            col=col + 1,
                        )
                    )
            stack.extend(node.children)
        return messages


registry.register(RbxHeaderLinter)
