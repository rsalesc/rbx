"""How CMS scores an rbx problem."""

import collections
from typing import Dict, List, Sequence, Union

from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.schema import Package, ScoreType

# A GroupMin subtask: its score and a regex over the codenames of its tests.
Subtask = List[Union[int, str]]

SCORE_TYPE = 'GroupMin'


def codename(index: int) -> str:
    """CMS's name for the test at `index` (0-based): `000`, `001`, ..."""
    return f'{index:03d}'


def _closure(name: str, deps: Dict[str, List[str]]) -> List[str]:
    res = [name]
    for dep in deps.get(name, []):
        for member in _closure(dep, deps):
            if member not in res:
                res.append(member)
    return res


def group_min_parameters(
    pkg: Package, entries: Sequence[GenerationTestcaseEntry]
) -> List[Subtask]:
    """GroupMin `score_type_parameters` that score the way rbx does.

    A group scores only if its tests and those of every group it (transitively)
    depends on pass, so each subtask matches all of them. A BINARY problem is a
    single all-or-nothing subtask. `entries` are the built tests, in order.
    """
    if pkg.scoring != ScoreType.POINTS:
        return [[100, '.*']]
    codenames = collections.defaultdict(list)
    for i, entry in enumerate(entries):
        codenames[entry.group_entry.group].append(codename(i))
    deps = {group.name: group.deps for group in pkg.testcases}

    subtasks = []
    for group in pkg.testcases:
        # A group with no built tests has nothing to judge.
        if group.name not in codenames:
            continue
        names = [
            name
            for member in _closure(group.name, deps)
            for name in codenames.get(member, [])
        ]
        subtasks.append([group.score, '^(' + '|'.join(names) + ')$'])
    return subtasks
