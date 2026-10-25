"""How per-test scores combine into group scores under points scoring.

A test scores a fraction in [0, 1]: 1 when it passes, 0 when it fails, and what a
checker's `quitp` awards in between. This module is the one place that turns those
fractions into points, so `rbx run`, the Polygon package and the CMS configuration
cannot disagree -- including by a rounding cent.

The rule reproduces what Polygon measures with "Treat points from checker as a
percent" and what CMS computes once dependencies are flattened into `GroupMin`
subtasks (see docs/plans/2026-10-25-partial-scoring-design.md): a dependency caps
every test of the dependent group at the lowest score among the dependency's own
tests, whatever the dependency's aggregation.
"""

import dataclasses
from typing import Callable, Dict, Iterable, List, Mapping, Sequence

from rbx.box.scoring.dependencies import Aggregation

# Scores are kept to the cent, as Polygon shows them.
PRECISION = 2


def round_score(score: float) -> float:
    return round(score, PRECISION)


def test_points(score: int, n: int) -> List[float]:
    """A `sum` group's points split evenly across its `n` tests.

    Each share is rounded to the cent and the last one absorbs the remainder, so
    the shares add up to exactly `score`.
    """
    if n <= 0:
        return []
    share = round_score(score / n)
    return [share] * (n - 1) + [round_score(score - share * (n - 1))]


@dataclasses.dataclass(frozen=True)
class GroupSpec:
    name: str
    score: int
    aggregation: Aggregation


def group_scores(
    groups: Sequence[GroupSpec],
    fractions: Mapping[str, Sequence[float]],
    closure: Callable[[str], Iterable[str]],
) -> Dict[str, float]:
    """Each group's score, given every group's per-test fractions in test order.

    `closure(name)` is the group's dependency closure. A dependency with no tests
    in `fractions` caps nothing; a group with no tests scores nothing.
    """
    res: Dict[str, float] = {}
    for group in groups:
        own = list(fractions.get(group.name, []))
        if not own:
            res[group.name] = 0.0
            continue
        cap = min(
            (f for dep in closure(group.name) for f in fractions.get(dep, [])),
            default=1.0,
        )
        if group.aggregation == Aggregation.SUM:
            score = sum(
                points * min(f, cap)
                for points, f in zip(test_points(group.score, len(own)), own)
            )
        else:
            score = group.score * min(min(own), cap)
        res[group.name] = round_score(score)
    return res
