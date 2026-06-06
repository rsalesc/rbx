import pathlib
from typing import Callable, Iterator, List, Optional

import tree_sitter_cpp
from tree_sitter import Language, Node, Parser

from rbx import utils
from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, Reference

_LANGUAGE = Language(tree_sitter_cpp.language())


def _parser() -> Parser:
    return Parser(_LANGUAGE)


def _quoted_include_nodes(root: Node) -> Iterator[Node]:
    """Yield the ``string_literal`` path node of each quoted ``#include`` (skips
    ``<...>`` system includes and never matches includes inside comments)."""
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == 'preproc_include':
            for child in node.children:
                if child.type == 'string_literal':
                    yield child
                    break
                if child.type == 'system_lib_string':
                    break
        stack.extend(node.children)


def _spelling(path_node: Node) -> str:
    text = path_node.text.decode('utf-8')
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _resolve(including_file: pathlib.Path, spelling: str) -> Optional[pathlib.Path]:
    package_root = utils.abspath(pathlib.Path())
    candidate = utils.abspath(including_file.parent / spelling)
    if not candidate.is_file() or not candidate.is_relative_to(package_root):
        return None
    return candidate.relative_to(package_root)


@scanner.register
class CppScanner(scanner.DependencyScanner):
    kinds = {DependencyKind.COMPILATION}
    can_rewrite = True

    def handles(self, language: str) -> bool:
        return language in ('cpp', 'c')

    def references(self, file: pathlib.Path) -> List[Reference]:
        tree = _parser().parse(pathlib.Path(file).read_bytes())
        refs: List[Reference] = []
        for path_node in _quoted_include_nodes(tree.root_node):
            spelling = _spelling(path_node)
            refs.append(Reference(spelling=spelling, target=_resolve(file, spelling)))
        return refs

    def rewrite(self, text: str, rename: Callable[[str], Optional[str]]) -> str:
        tree = _parser().parse(text.encode('utf-8'))
        edits = []  # (start_byte, end_byte, replacement_text)
        for path_node in _quoted_include_nodes(tree.root_node):
            new = rename(_spelling(path_node))
            if new is not None:
                edits.append((path_node.start_byte, path_node.end_byte, f'"{new}"'))
        if not edits:
            return text
        data = bytearray(text.encode('utf-8'))
        for start, end, repl in sorted(edits, reverse=True):
            data[start:end] = repl.encode('utf-8')
        return data.decode('utf-8')
