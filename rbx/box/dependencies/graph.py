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


def expand(
    code: CodeItem, require_kind: Optional[DependencyKind] = None
) -> Optional[DependencyGraph]:
    """Transitively discover ``code``'s quoted-include / relative-import dependencies.

    The scanners are chosen by the language's :func:`~rbx.box.environment.language_kinds`
    (plus any explicitly named in the language's ``scanners`` field), never by the raw
    language name. Returns ``None`` when no scanner applies, the source lives outside
    the package root (remote/temporary files stay flat), or ``require_kind`` is given
    and no applicable scanner contributes that kind. The last case short-circuits
    **before** the (potentially expensive) transitive walk, so e.g. a C++ source skips
    scanning entirely on the execution path. Cycle-safe; only references that resolve
    to an existing file under the package root are followed.
    """
    # Lazy import avoids a code <-> dependencies import cycle.
    from rbx.box.code import find_language
    from rbx.box.environment import language_kinds

    language = find_language(code)
    scanners = scanner.get_scanners_for_kinds(
        language_kinds(language), language.scanners
    )
    if require_kind is not None:
        scanners = [s for s in scanners if require_kind in s.dependency_kinds]
    if not scanners:
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
        refs: List[Reference] = []
        for instance in scanners:
            refs.extend(instance.references(current))
        nodes[current] = refs
        for ref in refs:
            if ref.target is not None and ref.target not in nodes:
                queue.append(ref.target)
    kinds: Set[DependencyKind] = set()
    for instance in scanners:
        kinds |= instance.dependency_kinds
    return DependencyGraph(root=root, nodes=nodes, kinds=kinds)
