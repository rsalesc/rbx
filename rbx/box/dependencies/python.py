import ast
import pathlib
from typing import List, Optional

from rbx import utils
from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, Reference


def _rel_if_package_file(path: pathlib.Path) -> Optional[pathlib.Path]:
    package_root = utils.abspath(pathlib.Path())
    abs_path = utils.abspath(path)
    if abs_path.is_file() and abs_path.is_relative_to(package_root):
        return abs_path.relative_to(package_root)
    return None


def _module_references(base: pathlib.Path, dots: str, dotted: str) -> List[Reference]:
    """References for a dotted module name resolved under ``base``: every existing
    intermediate ``__init__.py`` package marker (so ``import a.b.c`` also ships
    ``a/__init__.py`` and ``a/b/__init__.py`` when they exist) plus the leaf module
    (``a/b/c.py`` or ``a/b/c/__init__.py``). The leaf is always emitted, with
    ``target=None`` when it is not a package file (stdlib/third-party/a bare name)."""
    parts = [p for p in dotted.split('.') if p]
    if not parts:
        return []
    refs: List[Reference] = []
    for i in range(1, len(parts)):
        marker = _rel_if_package_file(base.joinpath(*parts[:i], '__init__.py'))
        if marker is not None:
            refs.append(Reference(f'{dots}{".".join(parts[:i])}', marker))
    leaf = _rel_if_package_file(
        base.joinpath(*parts).with_suffix('.py')
    ) or _rel_if_package_file(base.joinpath(*parts, '__init__.py'))
    refs.append(Reference(f'{dots}{dotted}', leaf))
    return refs


@scanner.register
class PythonScanner(scanner.DependencyScanner):
    kinds = {DependencyKind.EXECUTION}
    can_rewrite = False

    def handles(self, language: str) -> bool:
        return language == 'py'

    def references(self, file: pathlib.Path) -> List[Reference]:
        file = pathlib.Path(file)
        try:
            tree = ast.parse(file.read_text())
        except SyntaxError:
            return []
        base_dir = file.parent
        refs: List[Reference] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Absolute imports: resolve as a sibling of the importing file.
                for alias in node.names:
                    refs.extend(_module_references(base_dir, '', alias.name))
            elif isinstance(node, ast.ImportFrom):
                # Relative imports ascend ``level - 1`` directories from the file dir.
                anchor = base_dir
                for _ in range(max(node.level - 1, 0)):
                    anchor = anchor.parent
                dots = '.' * node.level
                if node.module:
                    refs.extend(_module_references(anchor, dots, node.module))
                    # An imported name may itself be a submodule file of ``module``.
                    for alias in node.names:
                        if alias.name == '*':
                            continue
                        refs.extend(
                            _module_references(
                                anchor, dots, f'{node.module}.{alias.name}'
                            )
                        )
                elif node.level > 0:
                    # ``from . import a, b`` -> each name is a sibling submodule.
                    for alias in node.names:
                        if alias.name == '*':
                            continue
                        refs.extend(_module_references(anchor, dots, alias.name))
        return refs
