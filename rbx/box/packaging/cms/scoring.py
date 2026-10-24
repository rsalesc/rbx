"""How CMS scores an rbx problem."""

import collections
from typing import List, Sequence, Union

from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.schema import Package
from rbx.box.scoring import dependencies

# A GroupMin subtask: its score and a regex over the codenames of its tests.
Subtask = List[Union[int, str]]

SCORE_TYPE = 'GroupMin'
# How CMS turns a contestant's submissions into the task score. Its default,
# `max_tokened_last`, takes the *last* submission when tokens are off; `max`
# takes the best one, which is what rbx's per-submission score means. To be
# made configurable (#946).
SCORE_MODE = 'max'


def codename(index: int) -> str:
    """CMS's name for the test at `index` (0-based): `000`, `001`, ..."""
    return f'{index:03d}'


def group_min_parameters(
    pkg: Package, entries: Sequence[GenerationTestcaseEntry]
) -> List[Subtask]:
    """GroupMin `score_type_parameters` that score the way rbx does.

    A group scores only if its tests and those of every group it (transitively)
    depends on pass, so each subtask matches all of them. A BINARY problem is a
    single all-or-nothing subtask. `entries` are the built tests, in order.
    """
    points = pkg.points_scoring
    if points is None:
        return [[100, '.*']]
    codenames = collections.defaultdict(list)
    for i, entry in enumerate(entries):
        codenames[entry.group_entry.group].append(codename(i))
    # GroupMin regexes may overlap, so the flattened groups need no copies of
    # the tests. A group with no built tests has nothing to judge and is left out.
    flattened = dependencies.flatten(
        pkg.group_dependencies, codenames, points.aggregation
    )
    return [
        [group.score, '^(' + '|'.join(flattened[group.name]) + ')$']
        for group in pkg.testcases
        if group.name in flattened
    ]
