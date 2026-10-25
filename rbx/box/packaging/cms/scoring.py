"""How CMS scores an rbx problem."""

import collections
from typing import List, Sequence, Union

from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.schema import Package
from rbx.box.scoring import partial

# A GroupMin subtask: its score and a regex over the codenames of its tests.
Subtask = List[Union[int, float, str]]

SCORE_TYPE = 'GroupMin'
# How CMS turns a contestant's submissions into the task score, unless the CMS
# settings say otherwise (`settings.task_keys`). CMS's default,
# `max_tokened_last`, takes the *last* submission when tokens are off; `max`
# takes the best one, which is what rbx's per-submission score means.
SCORE_MODE = 'max'


def codename(index: int) -> str:
    """CMS's name for the test at `index` (0-based): `000`, `001`, ..."""
    return f'{index:03d}'


def group_min_parameters(
    pkg: Package, entries: Sequence[GenerationTestcaseEntry]
) -> List[Subtask]:
    """GroupMin `score_type_parameters` that score the way rbx does.

    A dependency caps a group at its lowest test, so each subtask also matches
    the tests of every group it (transitively) depends on; a `sum` group is one
    subtask per test (`partial.subtasks`). A BINARY problem is a single
    all-or-nothing subtask. `entries` are the built tests, in order.
    """
    points = pkg.points_scoring
    if points is None:
        return [[100, '.*']]
    codenames = collections.defaultdict(list)
    for i, entry in enumerate(entries):
        codenames[entry.group_entry.group].append(codename(i))
    # GroupMin regexes may overlap, so the subtasks need no copies of the tests.
    # A group with no built tests has nothing to judge and is left out.
    return [
        [points, '^(' + '|'.join(tests) + ')$']
        for _, points, tests in partial.subtasks(
            pkg.group_dependencies.over(list(codenames)),
            codenames,
            [
                partial.GroupSpec(
                    group.name, group.score, pkg.aggregation_for(group.name)
                )
                for group in pkg.testcases
            ],
        )
    ]
