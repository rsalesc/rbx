"""The dependency graph between the test groups of a points problem.

The only module that knows `scoring.dependencies` exists. Everything else -- rbx's
own scoring, the testset manifest, the packagers -- reads the resolved graph from
here, so a new policy never needs teaching to its consumers.

Deliberately free of any `rbx.box.schema` import: the schema imports the enums
below and calls `resolve_edges` from its own validators.
"""

import collections
from typing import Dict, List, Mapping, Sequence, Tuple, TypeVar

from rbx.autoenum import AutoEnum, alias

SAMPLES_GROUP = 'samples'

T = TypeVar('T')


class DependencyPolicy(AutoEnum):
    MANUAL = alias('manual')  # type: ignore
    """Only the `deps` each group declares."""

    SAMPLES = alias('samples')  # type: ignore
    """Every group depends on `samples`, plus the `deps` it declares."""

    LADDER = alias('ladder')  # type: ignore
    """Every group depends on the one declared before it (the first on `samples`),
    plus the `deps` it declares."""


class Aggregation(AutoEnum):
    MIN = alias('min')  # type: ignore
    """A group scores its points times the lowest score among its tests (CMS's
    `GroupMin`, Polygon's `complete-group`): fully if every test passes, nothing if
    any fails."""

    SUM = alias('sum')  # type: ignore
    """Each test is worth an even share of the group's points and pays its own
    score (Polygon's `each-test`)."""


class FlatteningError(ValueError):
    """The aggregation cannot be reproduced by duplicating tests across groups."""


def resolve_edges(
    groups: Sequence[Tuple[str, Sequence[str]]], policy: DependencyPolicy
) -> Dict[str, List[str]]:
    """Each group's direct dependencies: the policy's edges, then its declared ones.

    `groups` is every top-level group in declaration order, as `(name, deps)`.
    """
    names = [name for name, _ in groups]
    res: Dict[str, List[str]] = {}
    for i, (name, declared) in enumerate(groups):
        edges: List[str] = []
        if name != SAMPLES_GROUP:
            if policy == DependencyPolicy.SAMPLES and SAMPLES_GROUP in names:
                edges.append(SAMPLES_GROUP)
            elif policy == DependencyPolicy.LADDER and i > 0:
                edges.append(names[i - 1])
        for dep in declared:
            if dep not in edges:
                edges.append(dep)
        res[name] = edges
    return res


class GroupDependencies:
    """The resolved dependency graph. Assumed acyclic: the schema rejects cycles."""

    def __init__(self, edges: Mapping[str, Sequence[str]]):
        self._edges = {name: list(deps) for name, deps in edges.items()}
        self._order = list(self._edges)
        self._dependents: Dict[str, List[str]] = collections.defaultdict(list)
        for name, deps in self._edges.items():
            for dep in deps:
                self._dependents[dep].append(name)

    def direct(self, group: str) -> List[str]:
        return list(self._edges.get(group, []))

    def closure(self, group: str) -> List[str]:
        """Every group `group` depends on, directly or not, in declaration order."""
        return self._reach(group, self._edges)

    def dependents(self, group: str) -> List[str]:
        """Every group depending on `group`, directly or not, in declaration order."""
        return self._reach(group, self._dependents)

    def over(self, present: Sequence[str]) -> 'GroupDependencies':
        """The graph between `present` groups only, each depending on every
        present group it reaches.

        For consumers that drop the groups with no built tests: dropping the
        group alone would also drop what it chained together, so the dependents
        of an empty rung in a ladder would stop depending on the rungs below it.
        """
        keep = set(present)
        return GroupDependencies(
            {
                name: [dep for dep in self.closure(name) if dep in keep]
                for name in self._order
                if name in keep
            }
        )

    def _reach(self, group: str, adjacency: Mapping[str, Sequence[str]]) -> List[str]:
        seen = set()
        stack = list(adjacency.get(group, []))
        while stack:
            name = stack.pop()
            if name in seen or name == group:
                continue
            seen.add(name)
            stack.extend(adjacency.get(name, []))
        return [name for name in self._order if name in seen]


def resolve(pkg) -> GroupDependencies:
    """The resolved graph of a `Package`. A binary problem has no edges."""
    scoring = pkg.points_scoring
    policy = scoring.dependencies if scoring is not None else DependencyPolicy.MANUAL
    return GroupDependencies(
        resolve_edges([(group.name, group.deps) for group in pkg.testcases], policy)
    )


def flatten(
    deps: GroupDependencies,
    tests_by_group: Mapping[str, Sequence[T]],
    aggregation: Aggregation = Aggregation.MIN,
) -> Dict[str, List[T]]:
    """Each group's own tests followed by those of every group it depends on.

    Scoring each resulting group independently reproduces the dependencies exactly
    under `min`: the group passes iff its own tests and all of its dependencies'
    pass. This is how a judge with no notion of dependencies is made to agree with
    `rbx run`. Groups absent from `tests_by_group` are left out.
    """
    if aggregation != Aggregation.MIN:
        raise FlatteningError(
            'Dependencies cannot be expressed by duplicating tests under '
            f'aggregation {aggregation}.'
        )
    res: Dict[str, List[T]] = {}
    for group, own in tests_by_group.items():
        tests = list(own)
        for dep in deps.closure(group):
            tests.extend(tests_by_group.get(dep, []))
        res[group] = tests
    return res
