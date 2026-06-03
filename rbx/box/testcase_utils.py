import pathlib
import shutil
from typing import List, Optional, Tuple

import rich
import rich.text
from pydantic import BaseModel

from rbx import console
from rbx.box.package import get_build_tests_path
from rbx.box.schema import TaskType, Testcase
from rbx.box.testcase_schema import TestcaseEntry

STDERR_PREFIX = '!'


class TestcasePattern(BaseModel):
    __test__ = False

    group_prefix: List[str]
    index: Optional[int] = None

    def group(self) -> str:
        return '/'.join(self.group_prefix)

    def match(self, group_entry: TestcaseEntry) -> bool:
        # TODO: support subgroups.
        entry_parts = tuple(group_entry.group.split('/'))
        if self.index is not None:
            if self.index != group_entry.index:
                return False
            if tuple(self.group_prefix) != entry_parts:
                return False
            return True

        if len(self.group_prefix) > len(entry_parts):
            return False

        return tuple(self.group_prefix) == entry_parts[: len(self.group_prefix)]

    def with_no_index(self) -> 'TestcasePattern':
        return self.model_copy(update={'index': None})

    def intersecting_group(self, group: str) -> bool:
        if self.with_no_index().match(TestcaseEntry(group=group, index=0)):
            # If the group is inside the pattern, then it is a match.
            return True
        if TestcasePattern.parse(group).match(
            TestcaseEntry(group=self.group(), index=0)
        ):
            # If the group is a prefix of the pattern, then it is a match.
            return True
        return False

    def __str__(self) -> str:
        prefix = '/'.join(self.group_prefix)
        if not prefix:
            return '*'
        if self.index is None:
            return f'{prefix}/'
        return f'{prefix}/{self.index}'

    @classmethod
    def parse(cls, spec: str) -> 'TestcasePattern':
        spec = spec.strip()
        if spec == '*':
            return cls(group_prefix=[], index=None)

        parts = spec.split('/')
        if len(parts) <= 1:
            return cls(group_prefix=parts, index=None)

        if parts[-1].isdigit():
            return cls(group_prefix=parts[:-1], index=int(parts[-1]))

        return cls(group_prefix=parts, index=None)


class TestcaseData(BaseModel):
    input: str
    output: str


class TestcaseInteractionEntry(BaseModel):
    """A single line of dialogue exchanged in an interactive testcase.

    An *entry* is the finest-grained unit of an interaction: exactly one line
    as it was parsed from the ``.interaction``/``.pio`` file, with its origin
    recorded in ``pipe``.

    This contrasts with an interaction *chunk* (see
    :class:`rbx.box.testcase_sample_utils.SampleInteractionChunk`): a chunk
    merges consecutive entries from the *same* participant into a single block,
    so a chunk represents one uninterrupted "turn" rather than one line. Chunks
    are derived from entries via :func:`merge_interaction_entries`.
    """

    __test__ = False

    # The text exchanged on this line (participant prefix already stripped).
    data: str
    # Which participant produced this line: 0 = interactor, 1 = solution.
    pipe: int


class TestcaseInteraction(BaseModel):
    """The full, unmerged dialogue of an interactive testcase.

    Holds every :class:`TestcaseInteractionEntry` in chronological order. This
    is the line-by-line source of truth; the merged, "chunked" view used for
    statement rendering is derived from ``entries`` via
    :func:`merge_interaction_entries`.
    """

    __test__ = False

    # All dialogue lines, in chronological order, one per exchanged line.
    entries: List[TestcaseInteractionEntry]
    # (interactor_prefix, solution_prefix) used when parsing the source file.
    prefixes: Tuple[str, str]


def clear_built_testcases():
    shutil.rmtree(str(get_build_tests_path()), ignore_errors=True)


def fill_output_for_defined_testcase(testcase: Testcase) -> Testcase:
    res = testcase.model_copy()
    if res.outputPath is not None:
        return res
    output_path = res.inputPath.with_suffix('.ans')
    if output_path.is_file():
        res.outputPath = output_path
    return res


class TestcaseInteractionParsingError(Exception):
    __test__ = False
    pass


def merge_interaction_entries(
    entries: List[TestcaseInteractionEntry],
) -> List[TestcaseInteractionEntry]:
    """Collapse a list of entries into "chunks".

    Consecutive entries produced by the same participant (same ``pipe``) are
    merged into a single entry, joining their ``data`` with newlines. The
    result is the chunked view of the dialogue: one entry per uninterrupted
    turn instead of one entry per line. Used to build
    :class:`rbx.box.testcase_sample_utils.SampleInteractionChunk` for statement
    rendering.

    The input list is not mutated; merged entries are copied.
    """
    merged_entries: List[TestcaseInteractionEntry] = []
    for entry in entries:
        if len(merged_entries) > 0 and merged_entries[-1].pipe == entry.pipe:
            merged_entries[-1].data += '\n' + entry.data
        else:
            merged_entries.append(entry.model_copy())
    return merged_entries


def parse_interaction(file: pathlib.Path) -> TestcaseInteraction:
    """Parse an interaction file into its unmerged :class:`TestcaseInteraction`.

    ``.interaction`` files use the predetermined prefixes ``<`` (interactor)
    and ``>`` (solution); any other suffix (e.g. ``.pio``) reads the two
    prefixes from the first two lines of the file. Lines starting with ``!``
    (the stderr prefix) become pipe 2 entries. Each remaining non-empty line
    becomes one :class:`TestcaseInteractionEntry` (no merging is done here --
    see :func:`merge_interaction_entries` for the chunked view).
    """
    entries = []
    with file.open('r') as f:
        if file.suffix == '.interaction':
            # Interaction files have a pretedetermined prefix.
            interactor_prefix = '<'
            solution_prefix = '>'
        else:
            try:
                interactor_prefix = f.readline().strip()
                solution_prefix = f.readline().strip()
            except Exception:
                raise TestcaseInteractionParsingError(
                    f'Failed to read interaction file {file}. Expected the first two lines to be the interactor and solution prefixes.'
                ) from None

        while line := f.readline().strip():
            if line.startswith(interactor_prefix):
                stripped = line[len(interactor_prefix) :].rstrip()
                entries.append(TestcaseInteractionEntry(data=stripped, pipe=0))
            elif line.startswith(solution_prefix):
                stripped = line[len(solution_prefix) :].rstrip()
                entries.append(TestcaseInteractionEntry(data=stripped, pipe=1))
            elif line.startswith(STDERR_PREFIX):
                stripped = line[len(STDERR_PREFIX) :].rstrip()
                entries.append(TestcaseInteractionEntry(data=stripped, pipe=2))
            else:
                raise TestcaseInteractionParsingError(
                    f'Invalid line in interaction file {file}. Expected the line to start with the interactor or solution prefix ({interactor_prefix} or {solution_prefix}).'
                ) from None

    return TestcaseInteraction(
        prefixes=(interactor_prefix, solution_prefix),
        entries=entries,
    )


def get_alternate_interaction_texts(
    interaction: TestcaseInteraction,
) -> Tuple[str, str]:
    interactor_entries = []
    solution_entries = []
    for entry in interaction.entries:
        if entry.pipe == 1:
            solution_entries.append(entry.data + '\n')
            interactor_entries.extend(['\n'] * (entry.data.count('\n') + 1))
        else:
            interactor_entries.append(entry.data + '\n')
            solution_entries.extend(['\n'] * (entry.data.count('\n') + 1))
    return ''.join(interactor_entries), ''.join(solution_entries)


def interaction_entry_style(pipe: int) -> str:
    if pipe == 0:
        return 'status'
    if pipe == 2:
        return 'error'
    return 'info'


def print_interaction(interaction: TestcaseInteraction):
    for entry in interaction.entries:
        text = rich.text.Text(entry.data)
        text.stylize(interaction_entry_style(entry.pipe))
        console.console.print(text)


def valid_interaction_suffixes() -> List[str]:
    return ['.interaction', '.pio']


def get_best_interaction_file(stdout_path: pathlib.Path) -> Optional[pathlib.Path]:
    for suffix in valid_interaction_suffixes():
        interaction_path = stdout_path.with_suffix(suffix)
        if interaction_path.is_file():
            return interaction_path
    return None


def get_all_interaction_files(stdout_path: pathlib.Path) -> List[pathlib.Path]:
    return [stdout_path.with_suffix(suffix) for suffix in valid_interaction_suffixes()]


def print_best_output(
    output_files: List[pathlib.Path],
    task_type: TaskType,
    empty_warning: bool = False,
    capture_pipes: bool = False,
):
    for output_file in output_files:
        if not output_file.is_file():
            continue
        if output_file.suffix in valid_interaction_suffixes():
            try:
                print_interaction(parse_interaction(output_file))
            except TestcaseInteractionParsingError:
                # Ignore parsing errors and proceed to next file.
                continue
        else:
            console.console.print(output_file.read_text())
        return
    if empty_warning:
        if task_type == TaskType.COMMUNICATION:
            console.console.print(
                '[warning]Solution produced no interaction.[/warning]'
            )
            if not capture_pipes:
                console.console.print(
                    '[warning]Use the [item]rbx -cp ...[/item] flag to capture the interaction.[/warning]'
                )
        else:
            console.console.print('[warning]Solution produced no output.[/warning]')
