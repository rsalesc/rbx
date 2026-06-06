import ast
import pathlib
from typing import List, Optional

from rbx import utils
from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, Reference


def _resolve_dotted(base: pathlib.Path, dotted: str) -> Optional[pathlib.Path]:
    """Resolve a dotted module name under ``base`` to a package-relative ``.py`` /
    ``__init__.py`` file, or ``None`` if it is not a package file (stdlib/third-party)."""
    parts = [p for p in dotted.split('.') if p]
    if not parts:
        return None
    package_root = utils.abspath(pathlib.Path())
    for candidate in (
        base.joinpath(*parts).with_suffix('.py'),
        base.joinpath(*parts, '__init__.py'),
    ):
        cand = utils.abspath(candidate)
        if cand.is_file() and cand.is_relative_to(package_root):
            return cand.relative_to(package_root)
    return None


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
                    refs.append(
                        Reference(alias.name, _resolve_dotted(base_dir, alias.name))
                    )
            elif isinstance(node, ast.ImportFrom):
                # Relative imports ascend ``level - 1`` directories from the file dir.
                anchor = base_dir
                for _ in range(max(node.level - 1, 0)):
                    anchor = anchor.parent
                dots = '.' * node.level
                if node.module:
                    refs.append(
                        Reference(
                            f'{dots}{node.module}',
                            _resolve_dotted(anchor, node.module),
                        )
                    )
                    # An imported name may itself be a submodule file of ``module``.
                    for alias in node.names:
                        if alias.name == '*':
                            continue
                        dotted = f'{node.module}.{alias.name}'
                        refs.append(
                            Reference(
                                f'{dots}{dotted}', _resolve_dotted(anchor, dotted)
                            )
                        )
                elif node.level > 0:
                    # ``from . import a, b`` -> each name is a sibling submodule.
                    for alias in node.names:
                        if alias.name == '*':
                            continue
                        refs.append(
                            Reference(
                                f'{dots}{alias.name}',
                                _resolve_dotted(anchor, alias.name),
                            )
                        )
        return refs
