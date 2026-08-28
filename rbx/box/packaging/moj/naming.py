import dataclasses
import re
from typing import List, Sequence

from rbx.box.exception import RbxException

# Samples must be named `sample*`: MOJ picks the statement's examples from
# tests/input/sample*. A package with no samples is legal -- `validate-problem.sh`
# only requires one input/output pair, of any name -- but then MOJ falls back to
# publishing the first two tests as examples, so the packager pins that case with an
# empty `samples` file (see `MojPackager._write_empty_samples_pin`).
SAMPLE_PREFIX = 'sample'
SAMPLES_GLOB = 'sample*'

# Non-sample tests carry a prefix that sorts AFTER `sample`, so MOJ's lexicographic
# judging loop over `tests/input/*` reports samples first -- the same order the
# statement presents them in.
TESTSET_PREFIX = 't'


class MojNamingError(RbxException):
    """A package cannot be expressed in MOJ's naming or scoring conventions."""

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


def sanitize_group_name(name: str) -> str:
    """Reduce a group name to ``[A-Za-z0-9_]``.

    A ``-`` in particular must not survive: ``score-summary.sh`` parses each
    ``tests/score`` line with ``IFS='-'``, so a dash would corrupt the weight.
    """
    return re.sub(r'[^A-Za-z0-9_]', '_', name)


def group_prefix(group_name: str, group_index: int) -> str:
    """The shared prefix of every test in a group, without the trailing ``*``.

    The group's index in ``problem.rbx.yml`` is part of the prefix so the emitted
    order matches the authored order regardless of the group names, and so two groups
    can never share a prefix.
    """
    return f'{TESTSET_PREFIX}{group_index:02d}_{sanitize_group_name(group_name)}_'


def group_glob(group_name: str, group_index: int) -> str:
    return f'{group_prefix(group_name, group_index)}*'


def testcase_name(
    group_name: str, group_index: int, index: int, is_sample: bool
) -> str:
    if is_sample:
        return f'{SAMPLE_PREFIX}{index:03d}'
    return f'{group_prefix(group_name, group_index)}{index:03d}'


@dataclasses.dataclass(frozen=True)
class ScoreGroup:
    glob: str
    weight: float


def build_score_file(groups: Sequence[ScoreGroup]) -> str:
    """Render ``tests/score``.

    One ``<glob> - <weight> pontos`` line per group. Groups are all-or-nothing and the
    problem's value is the sum of the weights.
    """
    lines: List[str] = []
    for group in groups:
        if float(group.weight) != int(group.weight):
            misread = str(group.weight).replace('.', '')
            raise MojNamingError(
                f'MOJ group weights must be integers, but group {group.glob!r} scores '
                f'{group.weight}. MOJ parses a weight by stripping every non-digit '
                f'from the line, so {group.weight} would be read as {misread}.'
            )
        lines.append(f'{group.glob} - {int(group.weight)} pontos')
    return '\n'.join(lines) + '\n'
