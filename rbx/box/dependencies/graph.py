import collections
import dataclasses
import pathlib
from typing import Dict, List, Optional, Set

from rbx import utils
from rbx.box.dependencies import scanner
from rbx.box.dependencies.scanner import DependencyKind, Reference
from rbx.box.schema import CodeItem


@dataclasses.dataclass
class DependencyGraph:
    root: pathlib.Path
    nodes: Dict[pathlib.Path, List[Reference]]
    kinds: Set[DependencyKind]

    def files(self) -> List[pathlib.Path]:
        """All discovered dependency files (package-relative), excluding the root,
        in deterministic order."""
        return sorted(p for p in self.nodes if p != self.root)


def expand(code: CodeItem) -> Optional[DependencyGraph]:
    """Transitively discover ``code``'s quoted-include / relative-import dependencies.

    Returns ``None`` when there is no scanner for the language, or the source lives
    outside the package root (remote/temporary files stay flat). Cycle-safe; only
    references that resolve to an existing file under the package root are followed.
    """
    # Lazy import avoids a code <-> dependencies import cycle.
    from rbx.box.code import find_language_name

    instance = scanner.get_scanner(find_language_name(code))
    if instance is None:
        return None
    package_root = utils.abspath(pathlib.Path())
    abs_path = utils.abspath(code.path)
    if not abs_path.is_relative_to(package_root):
        return None
    root = abs_path.relative_to(package_root)

    nodes: Dict[pathlib.Path, List[Reference]] = {}
    queue = collections.deque([root])
    while queue:
        current = queue.popleft()
        if current in nodes:
            continue
        refs = instance.references(current)
        nodes[current] = refs
        for ref in refs:
            if ref.target is not None and ref.target not in nodes:
                queue.append(ref.target)
    return DependencyGraph(root=root, nodes=nodes, kinds=set(instance.kinds))
