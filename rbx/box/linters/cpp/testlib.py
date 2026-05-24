from typing import List, Set, Tuple

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from rbx.box.linters import registry
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity
from rbx.box.schema import CodeItem

# Known side-effecting calls, as (object, method) pairs matching `obj.method(...)`.
# Seeded with the testlib/tgen/jngen `rnd.next` family. Extend as needed.
# TODO: SIDE_EFFECT macro detection + header expansion (follow-up to #476)
# Detect SIDE_EFFECT-macro-annotated functions and expand headers so
# side-effecting functions declared in tgen.h/jngen.h/testlib.h are seen.
SIDE_EFFECT_CALLS: Set[Tuple[str, str]] = {
    ('rnd', 'next'),
}

_LANGUAGE = Language(tree_sitter_cpp.language())


def _parser() -> Parser:
    return Parser(_LANGUAGE)


def _text(node: Node) -> str:
    return node.text.decode('utf8')


def _is_side_effect_call(node: Node) -> bool:
    """True if `node` is a call_expression to a known side-effecting function."""
    if node.type != 'call_expression':
        return False
    fn = node.child_by_field_name('function')
    if fn is None or fn.type != 'field_expression':
        return False
    obj = fn.child_by_field_name('argument')
    field = fn.child_by_field_name('field')
    if obj is None or field is None:
        return False
    return (_text(obj), _text(field)) in SIDE_EFFECT_CALLS


def _contains_side_effect_call(node: Node) -> bool:
    if _is_side_effect_call(node):
        return True
    return any(_contains_side_effect_call(child) for child in node.named_children)


def _argument_nodes(call: Node) -> List[Node]:
    args = call.child_by_field_name('arguments')
    if args is None:
        return []
    return list(args.named_children)


class TestlibLinter(Linter):
    """Lints testlib/tgen/jngen-based C++ code.

    Its first check flags side-effecting `rnd.next()` calls passed as multiple
    arguments to the same call; more testlib-specific checks may be added later.
    """

    name = 'testlib'
    applies_to = {AssetKind.GENERATOR}

    def lint(self, code: CodeItem, source: str) -> List[LinterMessage]:
        tree = _parser().parse(bytes(source, 'utf8'))
        messages: List[LinterMessage] = []
        self._visit(tree.root_node, messages)
        return messages

    def _visit(self, node: Node, messages: List[LinterMessage]) -> None:
        if node.type == 'call_expression':
            side_effect_args = sum(
                1 for arg in _argument_nodes(node) if _contains_side_effect_call(arg)
            )
            if side_effect_args >= 2:
                row, col = node.start_point
                messages.append(
                    LinterMessage(
                        severity=LinterSeverity.WARNING,
                        message=(
                            'Call passes multiple side-effecting arguments '
                            '(e.g. rnd.next()); C++ leaves argument evaluation '
                            'order unspecified, so results may differ across '
                            'compilers. Compute each value into a variable first.'
                        ),
                        line=row + 1,
                        col=col + 1,
                    )
                )
        for child in node.named_children:
            self._visit(child, messages)


registry.register(TestlibLinter)
