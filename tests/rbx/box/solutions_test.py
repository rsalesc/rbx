import contextlib
import pathlib
import re
from typing import Dict, Iterator, List, NamedTuple, Optional, Set, Tuple
from unittest.mock import patch

import pytest
import rich.console
import rich.style
from rich.text import Text

from rbx import utils
from rbx.box import package
from rbx.box import solutions as solutions_module
from rbx.box.deferred import Deferred
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.sanitizers.issue_stack import IssueAccumulator, issue_stack_var
from rbx.box.schema import (
    ExpectedOutcome,
    ScoreType,
    Solution,
    Testcase,
)
from rbx.box.solutions import (
    AbortContext,
    EvaluationItem,
    FailedToCompileSolutionIssue,
    GroupOutcomeReport,
    GroupSkeleton,
    LiveRunReporter,
    RunSolutionResult,
    SolutionOutcomeStatus,
    SolutionReportSkeleton,
    SolutionSkeleton,
    TimingIssue,
    TraditionalRunReporter,
    _AbortGate,  # noqa: SLF001
    _gates_report,  # noqa: SLF001
    _print_timing,  # noqa: SLF001
    _render_detailed_group_table,  # noqa: SLF001
    convert_list_of_solution_evaluations_to_dict,
    fail_fast_abort_predicate,
    get_full_outcome_markup_verdict,
    get_matching_solutions,
    get_outcome_markup_verdict,
    get_outcome_style_verdict,
    get_solution_outcome_report,
    get_ui_friendly_outcome_style_verdict,
    is_fast,
    print_run_report,
    run_solutions,
)
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.limits import Limits
from rbx.grading.steps import (
    CompilationError,
    Evaluation,
    Outcome,
)

# The synthetic skeleton/evaluation builders live in conftest so that other run
# tests can share them; the fixtures come in automatically, these two do not.
from tests.rbx.box.conftest import make_evaluation, make_generation_entry

# The heaviest file in the suite: every test re-runs the same `box1` solutions
# in a fresh problem directory. Sharing the problem cache takes it from 84s to
# 42s. Compilation is a means here, never the assertion -- the two compilation
# tests in this file exercise `FailedToCompileSolutionIssue` messages built by
# hand, without compiling anything.
pytestmark = pytest.mark.shared_cache


class Box1Run(NamedTuple):
    """One solution of `problems/box1`, run over the whole testset."""

    skeleton: SolutionReportSkeleton
    solution: SolutionSkeleton
    evals: List[Evaluation]

    def report(self):
        return get_solution_outcome_report(
            self.solution, self.skeleton, self.evals, VerificationLevel.FULL
        )


@pytest.fixture
async def run_box1_solution(pkg_from_testdata: pathlib.Path):
    """Build `box1`'s testset once, then run one solution at a time.

    Every solution of this package is checked, but each in its own test: running
    them all in a single test made it by far the longest test in the suite, and
    `tracked_solutions` keeps each test's cost to the solution it is about.
    """
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    async def _run(path: str) -> Box1Run:
        result = await run_solutions(
            verification=VerificationLevel.FULL, tracked_solutions=[path]
        )
        res = await convert_list_of_solution_evaluations_to_dict(
            result.skeleton, result.items
        )
        return Box1Run(result.skeleton, result.skeleton.solutions[0], res[0]['gen1'])

    return _run


@pytest.mark.test_pkg('problems/box1')
async def test_accepted_solution_passes_every_testcase(run_box1_solution):
    run = await run_box1_solution('sol.cpp')

    assert all(chk.result.outcome == Outcome.ACCEPTED for chk in run.evals)

    report = run.report()
    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.ACCEPTED
    assert report.gotVerdicts == set()


@pytest.mark.test_pkg('problems/box1')
async def test_incorrect_solution_is_wrong_on_the_big_testcase(run_box1_solution):
    run = await run_box1_solution('wa.sol.cpp')

    # The 25 test is the one it gets wrong.
    assert run.evals[3].result.outcome == Outcome.WRONG_ANSWER

    # Expected to fail, and it does: that matches the expectation.
    report = run.report()
    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.INCORRECT


@pytest.mark.test_pkg('problems/box1')
async def test_runtime_error_solution_fails_every_testcase(run_box1_solution):
    run = await run_box1_solution('re.sol.cpp')

    assert all(chk.result.outcome == Outcome.RUNTIME_ERROR for chk in run.evals)

    report = run.report()
    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.RUNTIME_ERROR


@pytest.mark.test_pkg('problems/box1')
async def test_soft_tle_solution_warns_it_still_passed_in_double_tl(run_box1_solution):
    run = await run_box1_solution('tle.sol.cpp')

    # The 1e9 test times out, but only softly.
    assert run.evals[4].result.outcome == Outcome.TIME_LIMIT_EXCEEDED

    report = run.report()
    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.TIME_LIMIT_EXCEEDED
    assert report.runUnderDoubleTl is True
    assert (
        'still passed in double TL'
        in Text.from_markup(report.get_verdict_markup_with_warnings()).plain
    )


@pytest.mark.test_pkg('problems/box1')
async def test_soft_tle_solution_that_is_also_wrong_names_the_verdict(
    run_box1_solution,
):
    """A solution that is within double TL but is *also* wrong there: the warning
    must name the verdict instead of staying silent (#607)."""
    run = await run_box1_solution('tle-and-incorrect.sol.cpp')

    assert run.evals[4].result.no_tle_outcome == Outcome.WRONG_ANSWER

    report = run.report()
    assert report.status == SolutionOutcomeStatus.OK
    assert report.doubleTlVerdicts == {Outcome.WRONG_ANSWER}
    warning = Text.from_markup(report.get_verdict_markup_with_warnings()).plain
    assert warning.splitlines()[-1] == (
        'WARNING The solution still finished in double TL, '
        'but failed with WRONG_ANSWER.'
    )


@pytest.mark.test_pkg('problems/box1')
async def test_hard_tle_solution_has_no_outcome_within_double_tl(run_box1_solution):
    run = await run_box1_solution('hard-tle.sol.cpp')

    assert run.evals[4].result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    # It never finished, not even in double TL, so there is nothing to report.
    assert run.evals[4].result.no_tle_outcome is None


@pytest.mark.test_pkg('problems/box1')
async def test_output_limit_exceeded_solution_fails_every_testcase(run_box1_solution):
    run = await run_box1_solution('ole.cpp')

    assert all(chk.result.outcome == Outcome.OUTPUT_LIMIT_EXCEEDED for chk in run.evals)


# Unit tests with custom inputs


@contextlib.contextmanager
def fresh_issue_stack() -> Iterator[IssueAccumulator]:
    """Isolate the issue stack, so a test sees exactly the issues it caused."""
    accumulator = IssueAccumulator()
    token = issue_stack_var.set([accumulator])
    try:
        yield accumulator
    finally:
        issue_stack_var.reset(token)


# Reporter-level helpers. The reporters print the solution header by resolving
# `runs_dir` against the problem directory, which is the only thing they need a
# package for; `mock_problem_root` stands in for it.


@pytest.fixture
def mock_problem_root(tmp_path):
    with patch('rbx.box.package.find_problem', return_value=tmp_path):
        yield tmp_path


def make_reporter_skeleton(
    root: pathlib.Path,
    solution: Solution,
    entries_per_group: Dict[str, int],
    scores_per_group: Optional[Dict[str, int]] = None,
) -> SolutionReportSkeleton:
    inputs_dir = root / 'tests'
    inputs_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for group, count in entries_per_group.items():
        for index in range(count):
            input_path = inputs_dir / f'{group}_{index}.in'
            input_path.write_text('')
            entry = TestcaseEntry(group=group, index=index)
            entries.append(
                GenerationTestcaseEntry(
                    group_entry=entry,
                    subgroup_entry=entry,
                    metadata=GenerationMetadata(
                        copied_to=Testcase(inputPath=input_path)
                    ),
                )
            )
    groups = [
        GroupSkeleton(
            name=group,
            score=(scores_per_group or {}).get(group, 0),
            deps=[],
            testcases=[
                entry.metadata.copied_to
                for entry in entries
                if entry.group_entry.group == group
            ],
        )
        for group in entries_per_group
    ]
    return SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(**solution.model_dump(), runs_dir=root / 'runs' / '0')
        ],
        entries=entries,
        groups=groups,
        limits={'cpp': Limits(time=1000, memory=256, profile=None, isDoubleTL=False)},
        compiled_solutions={str(solution.path): 'digest'},
        verification=VerificationLevel.FULL,
    )


def make_run_result(
    skeleton: SolutionReportSkeleton,
    verdicts: Dict[Tuple[str, int], Outcome],
) -> RunSolutionResult:
    """Present fixed verdicts as an already-computed run."""

    def resolved(evaluation: Evaluation) -> Deferred[Evaluation]:
        async def fn() -> Evaluation:
            return evaluation

        return Deferred(fn)

    def make(outcome: Outcome, index: int) -> Evaluation:
        # A skipped testcase never entered the sandbox, so it carries no time
        # and no memory -- exactly what the runner records for one.
        unmeasured = outcome == Outcome.SKIPPED
        return make_evaluation(
            outcome,
            time_ms=None if unmeasured else 100,
            memory_bytes=None if unmeasured else 1024,
            testcase_index=index,
        )

    return RunSolutionResult(
        skeleton=skeleton,
        items=[
            EvaluationItem(
                solution=solution,
                testcase_entry=entry.group_entry,
                eval=resolved(
                    make(
                        verdicts[entry.group_entry.key()],
                        entry.group_entry.index,
                    )
                ),
            )
            for solution in skeleton.solutions
            for entry in skeleton.entries
        ],
    )


async def drive_reporter(
    reporter: TraditionalRunReporter,
    skeleton: SolutionReportSkeleton,
    gating_solutions: Optional[Set[str]] = None,
) -> bool:
    """Replay `print_run_report`'s loop over an already-computed run.

    Kept structurally identical to the real loop, gate included: a solution
    outside ``gating_solutions`` is still run and reported but cannot fail the
    verdict (time limit inference relies on that for the solutions it expects to
    hit the cap).
    """
    ok = True
    for solution in skeleton.solutions:
        reporter.start_solution(solution)
        for group in skeleton.groups:
            reporter.start_group(group)
            for entry in skeleton.get_entries_for_group(group.name):
                reporter.start_testcase(entry)
                deferred = reporter.get_current_evaluation()
                reporter.finish_testcase(
                    await deferred() if deferred is not None else None
                )
            reporter.finish_group()
        cur_ok = reporter.finish_solution()
        if _gates_report(solution, gating_solutions):
            ok = ok and cur_ok
    return ok


def recording_console() -> rich.console.Console:
    return rich.console.Console(
        record=True, force_terminal=False, color_system=None, width=120
    )


def rendered_lines(console: rich.console.Console) -> List[str]:
    """The recorded report, line by line. Keeps the buffer, so it can be re-read."""
    return [line.rstrip() for line in console.export_text(clear=False).splitlines()]


def rendered_group_lines(console: rich.console.Console) -> List[str]:
    """Only the group lines, which are what this feature marks.

    Accepts either indent: `LiveRunReporter` draws a solution as one block and
    indents its group lines two spaces under the header, while the per-group
    fallback does not. What every caller here asserts on is the content of the
    line, never where it starts.

    Deliberately *not* `line.strip().startswith(...)`. A solution that misses
    expectations in more than one group continues its failure message on further
    lines, indented to clear the `FAILED ` label -- and those name a group too,
    so stripping first would pull `group3: expected ..., got: ...` in as if it
    were a group line.
    """
    return [
        line.strip()
        for line in rendered_lines(console)
        if line.startswith('group') or line.startswith('  group')
    ]


def test_get_solution_limits_display_time_recovers_declared_tl(tmp_path, mock_skeleton):
    """The timing report's no-eval fallback reads the declared TL via
    display_time(), so it no longer needs to re-resolve the profile from disk
    even when the enforced TL is nulled (#351)."""
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution])
    # Enforced TL stripped (no limit applied for this run) but the declared TL
    # is still known.
    skeleton.limits['cpp'] = Limits(time=None, configuredTime=2000)

    limits = skeleton.get_solution_limits(solution)

    assert limits.time is None
    assert limits.display_time() == 2000
    assert not hasattr(skeleton, 'get_solution_limits_from_disk')


def test_solution_outcome_report_ac_expects_ac(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test AC solution that expects AC - should pass."""
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution])
    evals = [make_evaluation(Outcome.ACCEPTED) for _ in range(5)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.ACCEPTED
    assert report.gotVerdicts == set()
    assert report.runUnderDoubleTl is False
    assert report.sanitizerWarnings is False


def test_solution_outcome_report_wa_expects_ac(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test WA solution that expects AC - should fail."""
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution])
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER, message='Expected 5, got 3'),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    assert report.expectedOutcome == ExpectedOutcome.ACCEPTED
    assert Outcome.WRONG_ANSWER in report.gotVerdicts
    assert report.message is not None
    assert report.message[1] == 'Expected 5, got 3'


def test_solution_outcome_report_wa_expects_incorrect(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test WA solution that expects incorrect - should pass."""
    solution = Solution(path=tmp_path / 'wa.cpp', outcome=ExpectedOutcome.INCORRECT)
    skeleton = mock_skeleton([solution])
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.INCORRECT


def test_solution_outcome_report_ac_expects_incorrect(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test AC solution that expects incorrect - should fail."""
    solution = Solution(path=tmp_path / 'wa.cpp', outcome=ExpectedOutcome.INCORRECT)
    skeleton = mock_skeleton([solution])
    evals = [make_evaluation(Outcome.ACCEPTED) for _ in range(5)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    assert report.expectedOutcome == ExpectedOutcome.INCORRECT
    assert Outcome.ACCEPTED in report.gotVerdicts


def test_solution_outcome_report_rte_expects_rte(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test RTE solution that expects RTE - should pass."""
    solution = Solution(
        path=tmp_path / 'rte.cpp', outcome=ExpectedOutcome.RUNTIME_ERROR
    )
    skeleton = mock_skeleton([solution])
    evals = [make_evaluation(Outcome.RUNTIME_ERROR) for _ in range(5)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.RUNTIME_ERROR


def test_solution_outcome_report_tle_with_double_tl(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test TLE solution that runs under double TL - should show warning."""
    solution = Solution(
        path=tmp_path / 'tle.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution])
    # Soft TLE (has no_tle_outcome)
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED, time_ms=1500, no_tle_outcome=Outcome.ACCEPTED
        ),
        make_evaluation(Outcome.ACCEPTED, time_ms=200),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.TIME_LIMIT_EXCEEDED
    # Should detect it runs under double TL
    assert report.runUnderDoubleTl is True


def test_solution_outcome_report_tle_with_soft_tle_and_wa(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test TLE solution with soft TLE that also has WA in double TL."""
    solution = Solution(
        path=tmp_path / 'tle.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution])
    evals = [
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1500,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED, time_ms=1600, no_tle_outcome=Outcome.ACCEPTED
        ),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.expectedOutcome == ExpectedOutcome.TIME_LIMIT_EXCEEDED
    # Should show double TL verdicts
    assert len(report.doubleTlVerdicts) > 0
    assert Outcome.WRONG_ANSWER in report.doubleTlVerdicts
    # ...and must actually say so: this warning used to be computed and then
    # dropped, since a report can never have both double TL flags set at the
    # pooled layer alone (#607).
    assert report.runUnderDoubleTl is False
    assert report.get_verdict_markup_with_warnings() == (
        '[success]OK[/success] \n'
        '[warning]WARNING[/warning] The solution still finished in double TL, '
        'but failed with [item]WRONG_ANSWER[/item].'
    )


def test_double_tl_warning_lists_every_verdict_in_a_stable_order(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Several soft-TLE verdicts are all named, sorted so the line does not
    change between runs."""
    solution = Solution(
        path=tmp_path / 'tle.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution])
    evals = [
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1500,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1600,
            no_tle_outcome=Outcome.RUNTIME_ERROR,
        ),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.doubleTlVerdicts == {Outcome.WRONG_ANSWER, Outcome.RUNTIME_ERROR}
    warning = Text.from_markup(report.get_verdict_markup_with_warnings()).plain
    assert warning.splitlines()[-1] == (
        'WARNING The solution still finished in double TL, '
        'but failed with RUNTIME_ERROR WRONG_ANSWER.'
    )


def test_solution_outcome_report_sanitizer_warnings(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test solution with sanitizer warnings."""
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution])
    evals = [
        make_evaluation(Outcome.ACCEPTED, sanitizer_warnings=False),
        make_evaluation(Outcome.ACCEPTED, sanitizer_warnings=True),
        make_evaluation(Outcome.ACCEPTED, sanitizer_warnings=False),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.sanitizerWarnings is True


def test_solution_outcome_report_subset_mode(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test subset mode shows all verdicts."""
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution])
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL, subset=True
    )

    assert report.status == SolutionOutcomeStatus.OK
    # In subset mode, should show got verdicts even when passing
    assert Outcome.ACCEPTED in report.gotVerdicts
    assert report.expectedOutcome == ExpectedOutcome.ACCEPTED


def test_solution_outcome_report_mixed_outcomes(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """Test solution with multiple different outcomes."""
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution])
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.RUNTIME_ERROR),
        make_evaluation(Outcome.TIME_LIMIT_EXCEEDED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    # Should report the unmatched verdicts
    assert Outcome.WRONG_ANSWER in report.gotVerdicts
    assert Outcome.RUNTIME_ERROR in report.gotVerdicts
    assert Outcome.TIME_LIMIT_EXCEEDED in report.gotVerdicts


def test_no_outcome_per_group_leaves_the_report_untouched(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """A solution that declares no `outcomePerGroup` must be checked exactly as
    before: no group is inspected, and `status` is the pooled status alone."""
    solution = Solution(path=tmp_path / 'wa.cpp', outcome=ExpectedOutcome.INCORRECT)
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 2, 'group2': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.perGroup == {}
    assert report.failedGroups == []
    # group2 is fully accepted, which a per-group INCORRECT would have failed.
    assert report.pooledStatus == SolutionOutcomeStatus.OK
    assert report.status == report.pooledStatus


def test_pooled_outcome_fails_while_every_group_passes(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """The mirror case: relaxing a group's expectation without relaxing the
    pooled one still fails, and it fails on the pooled layer."""
    solution = Solution(
        path=tmp_path / 'sol.cpp',
        outcome=ExpectedOutcome.ACCEPTED,
        outcomePerGroup={'group1': ExpectedOutcome.INCORRECT},
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 2, 'group2': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.pooledStatus == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    assert report.failedGroups == []
    assert report.perGroup['group1'].status == SolutionOutcomeStatus.OK
    assert report.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS


def test_per_group_double_tl_is_reported_and_merged(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """Double TL is detected per group and merged into the aggregate, keeping
    "passed within 2x TL" distinguishable from "had other soft-TLE verdicts"."""
    solution = Solution(
        path=tmp_path / 'tle.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        outcomePerGroup={
            'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
            'group3': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        },
    )
    skeleton = mock_skeleton(
        [solution], entries_per_group={'group1': 1, 'group2': 2, 'group3': 2}
    )
    evals = [
        # group1 alone pushes the pooled max time past 2x TL, so the pooled layer
        # flags nothing and everything below comes from the per-group reports.
        make_evaluation(Outcome.ACCEPTED, time_ms=2500),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        # Soft TLE that is otherwise accepted: group2 passed within 2x TL.
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED, time_ms=1500, no_tle_outcome=Outcome.ACCEPTED
        ),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        # Soft TLE that is a WA without the TL: group3 has other verdicts.
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1500,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.perGroup['group2'].runUnderDoubleTl is True
    assert report.perGroup['group2'].doubleTlVerdicts == set()
    assert report.perGroup['group3'].runUnderDoubleTl is False
    assert report.perGroup['group3'].doubleTlVerdicts == {Outcome.WRONG_ANSWER}
    # The aggregate is the union, even though the pooled layer flagged neither.
    assert report.runUnderDoubleTl is True
    assert report.doubleTlVerdicts == {Outcome.WRONG_ANSWER}


def test_double_tl_warning_attributes_each_fact_to_its_own_group(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """The two facts come from different groups, so each is its own sentence
    naming its own group: group2 is what passed within 2x TL, group3 is what
    failed."""
    solution = Solution(
        path=tmp_path / 'tle.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        outcomePerGroup={
            'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
            'group3': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        },
    )
    skeleton = mock_skeleton(
        [solution], entries_per_group={'group1': 1, 'group2': 2, 'group3': 2}
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=2500),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        # group2 passed within 2x TL.
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED, time_ms=1500, no_tle_outcome=Outcome.ACCEPTED
        ),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        # group3 was a WA without the TL.
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1500,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    warning = Text.from_markup(report.get_verdict_markup_with_warnings()).plain
    assert warning.splitlines()[-2:] == [
        'WARNING The solution still passed in double TL on group2.',
        'WARNING The solution still finished in double TL, '
        'but failed with WRONG_ANSWER on group3.',
    ]


def test_double_tl_warning_comma_joins_the_groups_it_names(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """Several groups are listed with separators, not space-joined into one
    unreadable run of names."""
    solution = Solution(
        path=tmp_path / 'tle.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        outcomePerGroup={'*': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton(
        [solution], entries_per_group={'group1': 1, 'group2': 1, 'group3': 1}
    )
    # Every group times out, but within 2x TL.
    evals = [
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED, time_ms=1500, no_tle_outcome=Outcome.ACCEPTED
        )
        for _ in range(3)
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    warning = Text.from_markup(report.get_verdict_markup_with_warnings()).plain
    assert warning.splitlines()[-1] == (
        'WARNING The solution still passed in double TL on group1, group2, group3.'
    )


def test_double_tl_warning_is_unchanged_without_outcome_per_group(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """A solution with no `outcomePerGroup` has no group to attribute the
    warning to, so the sentence must stay exactly as it always was."""
    solution = Solution(
        path=tmp_path / 'tle.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED, time_ms=1500, no_tle_outcome=Outcome.ACCEPTED
        ),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.perGroup == {}
    assert report.runUnderDoubleTl is True
    assert report.get_verdict_markup_with_warnings() == (
        '[success]OK[/success] \n'
        '[warning]WARNING[/warning] The solution still passed in double TL.'
    )


def test_per_group_outcome_fails_while_pooled_outcome_passes(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """group2 is expected to TLE but is fully accepted: the solution fails even
    though the pooled INCORRECT expectation is satisfied by group1's WA."""
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 2, 'group2': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    assert report.pooledStatus == SolutionOutcomeStatus.OK
    assert report.failedGroups == ['group2']
    assert set(report.perGroup) == {'group2'}
    assert report.perGroup['group2'] == GroupOutcomeReport(
        expectedOutcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        gotVerdicts={Outcome.ACCEPTED},
        status=SolutionOutcomeStatus.UNEXPECTED_VERDICTS,
        runUnderDoubleTl=False,
        doubleTlVerdicts=set(),
        unexpectedNoTleVerdicts=set(),
    )


def test_per_group_outcome_all_satisfied(tmp_path, mock_skeleton, mock_points_scoring):
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'group2': ExpectedOutcome.WRONG_ANSWER,
        },
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 2, 'group2': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.ACCEPTED),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.failedGroups == []
    # The wildcard covers group1 too.
    assert {name: group.expectedOutcome for name, group in report.perGroup.items()} == {
        'group1': ExpectedOutcome.ACCEPTED,
        'group2': ExpectedOutcome.WRONG_ANSWER,
    }


def test_wildcard_expectation_is_checked_per_group(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """'*': wa demands a WA in EVERY group; group1 being clean is a failure."""
    solution = Solution(
        path=tmp_path / 'wa.cpp',
        outcome=ExpectedOutcome.WRONG_ANSWER,
        outcomePerGroup={'*': ExpectedOutcome.WRONG_ANSWER},
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 2, 'group2': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.WRONG_ANSWER),
    ]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    assert report.failedGroups == ['group1']


def test_groups_without_evaluations_are_not_checked(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """Mid-run, later groups have no evals yet. A bad expectation on them must
    not fail the report, or the live reporters would flash spurious failures."""
    solution = Solution(
        path=tmp_path / 'tle.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 2, 'group2': 2})
    # Only group1 has run.
    evals = [make_evaluation(Outcome.ACCEPTED), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert 'group2' not in report.perGroup
    assert report.failedGroups == []


def test_groups_outside_the_testset_are_not_checked(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """`rbx irun` evaluates a synthetic `interactive` group that is not part of
    the testset, and builds its skeleton with no groups at all. A `'*'` default
    must not bind to it: the wildcard expands over declared groups only, which is
    also the only set `check_outcome_per_group_names` accepts as explicit keys."""
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'big': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        },
    )
    skeleton = mock_skeleton([solution], entries_per_group={'interactive': 1})
    # Mirror `_get_interactive_skeleton`, which declares no groups.
    skeleton.groups = []
    evals = [make_evaluation(Outcome.WRONG_ANSWER)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL, subset=True
    )

    assert report.perGroup == {}
    assert report.failedGroups == []
    assert report.status == SolutionOutcomeStatus.OK


def test_verdict_markup_attributes_failure_to_the_group(
    tmp_path, mock_skeleton, mock_points_scoring
):
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'group1': 1, 'group2': 1},
        scores_per_group={'group1': 40, 'group2': 60},
    )
    evals = [make_evaluation(Outcome.WRONG_ANSWER), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )
    markup = report.get_verdict_markup()

    assert 'FAILED' in markup
    assert 'group2' in markup
    assert 'TIME_LIMIT_EXCEEDED' in markup
    assert 'ACCEPTED' in markup
    # The pooled layer passed, so it must not be reported as the culprit.
    assert 'Expected: INCORRECT' not in markup
    # Rendering also asserts the markup is well-formed. POINTS scoring leads with
    # the score line, and the group attribution lines up underneath it.
    assert Text.from_markup(markup).plain == (
        'FAILED Got [60/100 pts]\n'
        '       group2: expected TIME_LIMIT_EXCEEDED, got: ACCEPTED'
    )


def test_verdict_markup_lists_every_failed_group(
    tmp_path, mock_skeleton, mock_points_scoring
):
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'group2': ExpectedOutcome.WRONG_ANSWER,
        },
    )
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'group1': 1, 'group2': 1},
        scores_per_group={'group1': 40, 'group2': 60},
    )
    # group1 was supposed to be clean, group2 was supposed to fail.
    evals = [make_evaluation(Outcome.WRONG_ANSWER), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )
    markup = report.get_verdict_markup()

    # FAILED is said once; the remaining lines line up underneath it.
    assert markup.count('FAILED') == 1
    assert 'group1' in markup and 'group2' in markup
    assert Text.from_markup(markup).plain == (
        'FAILED Got [60/100 pts]\n'
        '       group1: expected ACCEPTED, got: WRONG_ANSWER\n'
        '       group2: expected WRONG_ANSWER, got: ACCEPTED'
    )


def test_verdict_markup_hides_group_lines_when_incomplete(
    tmp_path, mock_skeleton, mock_points_scoring
):
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 1, 'group2': 1})
    evals = [make_evaluation(Outcome.WRONG_ANSWER), make_evaluation(Outcome.ACCEPTED)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert 'group2' not in report.get_verdict_markup(incomplete=True)


def test_passing_subset_group_reports_all_of_its_verdicts(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """In `subset` mode a *passing* group reports all of its verdicts rather than
    an empty set, so pass/fail must be read off `status`, never off
    `gotVerdicts`."""
    solution = Solution(
        path=tmp_path / 'wa.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'group1': ExpectedOutcome.WRONG_ANSWER},
    )
    skeleton = mock_skeleton([solution], entries_per_group={'group1': 2})
    evals = [make_evaluation(Outcome.ACCEPTED), make_evaluation(Outcome.WRONG_ANSWER)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL, subset=True
    )

    assert report.perGroup['group1'].status == SolutionOutcomeStatus.OK
    assert report.perGroup['group1'].gotVerdicts == {
        Outcome.ACCEPTED,
        Outcome.WRONG_ANSWER,
    }
    # ...and the group is not reported as a failure despite those verdicts.
    assert report.failedGroups == []
    assert 'group1' not in report.get_verdict_markup()


async def test_reporter_leaves_group_lines_alone_and_names_failures_once(
    mock_problem_root, mock_binary_scoring
):
    """End-to-end through a reporter: group lines carry no expectation marker --
    stating each expectation both inline and in the summary said everything
    twice -- and the summary says FAILED once, aligning the rest under it."""
    solution = Solution(
        path=pathlib.Path('partial.cpp'),
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'group2': ExpectedOutcome.WRONG_ANSWER,
            'group3': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        },
    )
    skeleton = make_reporter_skeleton(
        mock_problem_root, solution, {'group1': 2, 'group2': 1, 'group3': 1}
    )
    result = make_run_result(
        skeleton,
        {
            # Covered by '*': accepted, but wrong on one test.
            ('group1', 0): Outcome.ACCEPTED,
            ('group1', 1): Outcome.WRONG_ANSWER,
            # Expected to be wrong, and wrong.
            ('group2', 0): Outcome.WRONG_ANSWER,
            # Expected to time out, but accepted.
            ('group3', 0): Outcome.ACCEPTED,
        },
    )
    console = recording_console()

    with fresh_issue_stack():
        ok = await drive_reporter(
            LiveRunReporter(result, VerificationLevel.FULL, console), skeleton
        )

    assert not ok
    # No expectation markers here: the group lines are exactly what a package
    # without `outcomePerGroup` renders. Accepted verdicts are left out of the
    # line, as the live reporter always does, so group3 shows none at all.
    assert rendered_group_lines(console) == [
        'group1 (2) 1/✗ (100 ms, 1 KiB)',
        'group2 (1) 0/✗ (100 ms, 1 KiB)',
        'group3 (1) (100 ms, 1 KiB)',
    ]
    # The summary names every group that missed its expectation, and only those,
    # saying FAILED once and aligning the rest under it.
    lines = rendered_lines(console)
    assert 'FAILED group1: expected ACCEPTED, got: WRONG_ANSWER' in lines
    assert '       group3: expected TIME_LIMIT_EXCEEDED, got: ACCEPTED' in lines
    assert not any('group2:' in line for line in lines)


async def test_reporter_group_lines_carry_only_the_score(
    mock_problem_root,
):
    """The group line's only trailing mark is its POINTS score. A per-group
    expectation adds nothing there, whether the group is scored or not."""
    solution = Solution(
        path=pathlib.Path('partial.cpp'),
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'group2': ExpectedOutcome.WRONG_ANSWER},
    )
    skeleton = make_reporter_skeleton(
        mock_problem_root,
        solution,
        {'samples': 1, 'group2': 1},
        scores_per_group={'group2': 60},
    )
    result = make_run_result(
        skeleton,
        {('samples', 0): Outcome.ACCEPTED, ('group2', 0): Outcome.WRONG_ANSWER},
    )
    console = recording_console()

    with (
        fresh_issue_stack(),
        patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS),
    ):
        await drive_reporter(
            LiveRunReporter(result, VerificationLevel.FULL, console), skeleton
        )

    # Stripped: the live reporter indents group lines under the solution header,
    # and where the line starts is not what this test is about.
    lines = [line.strip() for line in rendered_lines(console)]
    # group2 failed its tests, so it scores 0 of 60 -- while still meeting the
    # expectation that it fail, which the line says nothing about.
    assert 'group2 (1) 0/✗ (100 ms, 1 KiB) [0/60 pts]' in lines
    # `samples` has no score, so it gets no trailing mark at all.
    assert 'samples (1) (100 ms, 1 KiB)' in lines


async def test_a_solution_outside_the_gate_cannot_fail_the_report(
    mock_problem_root, mock_binary_scoring
):
    """`print_run_report`'s `gating_solutions`: time limit inference runs
    solutions it *expects* to fail (they are capped on purpose), and their
    verdicts must not decide the run's outcome."""
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 1})

    async def _drive(gating_solutions):
        result = make_run_result(skeleton, {('group1', 0): Outcome.WRONG_ANSWER})
        with fresh_issue_stack():
            return await drive_reporter(
                LiveRunReporter(result, VerificationLevel.FULL, recording_console()),
                skeleton,
                gating_solutions=gating_solutions,
            )

    assert not await _drive(None)  # ungated: the failure decides
    assert not await _drive({'sol.cpp'})  # gated on itself: still decides
    assert await _drive(set())  # gated away: the same failure is tolerated


async def test_partial_reports_do_not_add_timing_issues(
    mock_problem_root, mock_binary_scoring
):
    """A partial report is computed at every scored group's end purely to render
    it. The timing heuristic reads too-fast/too-slow off the evals it is handed,
    so an all-accepted group that finishes before the slow group has started
    looks too fast in isolation, and used to collect a bogus `rbx time` warning
    that way even though the final report was clean."""
    solution = Solution(
        path=pathlib.Path('sol.cpp'),
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        outcomePerGroup={'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = make_reporter_skeleton(
        mock_problem_root,
        solution,
        {'group1': 2, 'group2': 1},
        scores_per_group={'group1': 40, 'group2': 60},
    )
    result = make_run_result(
        skeleton,
        {
            ('group1', 0): Outcome.ACCEPTED,
            ('group1', 1): Outcome.ACCEPTED,
            ('group2', 0): Outcome.TIME_LIMIT_EXCEEDED,
        },
    )

    with (
        fresh_issue_stack() as issues,
        patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS),
    ):
        await drive_reporter(
            LiveRunReporter(result, VerificationLevel.FULL, recording_console()),
            skeleton,
        )

    # Exactly one: the report at solution end, which is the one entitled to speak
    # about the run. Both group ends also built a report, to render their score.
    assert len([i for i in issues.issues if isinstance(i, TimingIssue)]) == 1

    # The very evals the group-1 partial report saw. As a rendering-only report
    # they raise nothing; as a final one they still do, so `report_issues` is the
    # only difference between the two calls.
    partial_evals = [make_evaluation(Outcome.ACCEPTED) for _ in range(2)]
    with fresh_issue_stack() as issues:
        get_solution_outcome_report(
            solution,
            skeleton,
            partial_evals,
            VerificationLevel.FULL,
            report_issues=False,
        )

    assert [issue for issue in issues.issues if isinstance(issue, TimingIssue)] == []

    with fresh_issue_stack() as issues:
        get_solution_outcome_report(
            solution, skeleton, partial_evals, VerificationLevel.FULL
        )

    assert any(isinstance(issue, TimingIssue) for issue in issues.issues)


def test_report_evals_are_not_clobbered_by_the_per_group_loop(tmp_path, mock_skeleton):
    """Regression: the POINTS loop used to rebind `evals`, so the report's
    Time/Memory line only saw the last group's evaluations."""
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'group1': 2, 'group2': 2},
        scores_per_group={'group1': 50, 'group2': 50},
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=900),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
    ]

    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution, skeleton, evals, VerificationLevel.FULL
        )

    # The report must carry every eval, not just the last group's -- the first
    # one, deliberately the slowest, is what the Time line reports.
    assert report.evals == evals
    assert report.evals[0].log is not None
    assert report.evals[0].log.time == 0.9
    assert report.gotScore == 100


def test_get_matching_solutions(tmp_path):
    """Test get_matching_solutions with various filters."""
    # Create mock solutions
    s1 = Solution(
        path=tmp_path / 's1.cpp',
        outcome=ExpectedOutcome.ACCEPTED,
        tags=['implementation', 'easy'],
    )
    s2 = Solution(
        path=tmp_path / 's2.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        tags=['brute-force', 'slow'],
    )
    s3 = Solution(
        path=tmp_path / 's3.cpp',
        outcome=ExpectedOutcome.WRONG_ANSWER,
        tags=['implementation', 'buggy'],
    )
    s4 = Solution(
        path=tmp_path / 's4.cpp',
        outcome=ExpectedOutcome.ACCEPTED,
        tags=[],
    )

    with patch(
        'rbx.box.solutions.package.get_solutions', return_value=[s1, s2, s3, s4]
    ):
        # Test no filters
        assert len(get_matching_solutions()) == 4

        # Test filter by expected_outcome
        assert get_matching_solutions(expected_outcome=ExpectedOutcome.ACCEPTED) == [
            s1,
            s4,
        ]
        assert get_matching_solutions(
            expected_outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
        ) == [s2]

        # Test filter by tags
        assert get_matching_solutions(tags=['implementation']) == [s1, s3]
        assert get_matching_solutions(tags=['easy']) == [s1]
        assert get_matching_solutions(tags=['brute-force']) == [s2]

        # Test filter by multiple tags (subset check)
        # s1 has implementation and easy.
        assert get_matching_solutions(tags=['implementation', 'easy']) == [s1]
        # order shouldn't matter
        assert get_matching_solutions(tags=['easy', 'implementation']) == [s1]

        # Test non-matching tags
        assert get_matching_solutions(tags=['nonexistent']) == []
        # s1 has implementation but not slow
        assert get_matching_solutions(tags=['implementation', 'slow']) == []

        # Test filter by both outcome and tags
        assert get_matching_solutions(
            expected_outcome=ExpectedOutcome.ACCEPTED, tags=['implementation']
        ) == [s1]

        # s3 is WA and matches implementation
        assert get_matching_solutions(
            expected_outcome=ExpectedOutcome.WRONG_ANSWER, tags=['implementation']
        ) == [s3]

        # s4 is AC but empty tags, shouldn't match if we ask for implementation
        assert get_matching_solutions(
            expected_outcome=ExpectedOutcome.ACCEPTED, tags=['implementation']
        ) == [s1]


def test_is_fast_considers_per_group_expectations(tmp_path):
    """A solution expected to be slow on a single group is not a fast solution."""
    fast = Solution(path=tmp_path / 'ac.cpp', outcome=ExpectedOutcome.ACCEPTED)
    slow_group = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            '*': ExpectedOutcome.ACCEPTED,
            'group3': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        },
    )
    slow_pooled = Solution(
        path=tmp_path / 'slow.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
    )

    assert is_fast(fast)
    # Expected to time out on group3, so it is not a fast solution.
    assert not is_fast(slow_group)
    # Unchanged: a pooled slow expectation still makes it not fast.
    assert not is_fast(slow_pooled)


def test_solution_outcome_report_points_scoring(tmp_path, mock_limits, mock_skeleton):
    """Test solution reporting with POINTS scoring."""
    # Setup solution with expected score range
    solution = Solution(
        path=tmp_path / 'sol.cpp',
        outcome=ExpectedOutcome.ACCEPTED,
        score=100,  # Expects exactly 100 points
    )

    # Create groups with scores
    g1 = GroupSkeleton(
        name='g1',
        score=30,
        deps=[],
        testcases=[Testcase(inputPath=tmp_path / 'g1_1.in')],
    )
    g2 = GroupSkeleton(
        name='g2',
        score=70,
        deps=[],
        testcases=[Testcase(inputPath=tmp_path / 'g2_1.in')],
    )

    skeleton = SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(**solution.model_dump(), runs_dir=tmp_path / 'run')
        ],
        entries=[
            make_generation_entry('g1', 0, tmp_path),
            make_generation_entry('g2', 0, tmp_path),
        ],
        groups=[g1, g2],
        limits={'cpp': mock_limits},
        compiled_solutions={str(solution.path): 'digest'},
        verification=VerificationLevel.FULL,
    )

    # 1. Test perfect score (30 + 70 = 100)
    evals_perfect = [
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g1
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g2
    ]

    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution, skeleton, evals_perfect, VerificationLevel.FULL
        )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.gotScore == 100
    assert report.maxScore == 100

    # 2. Test partial score (30 + 0 = 30) - Expected 100, got 30 -> UNEXPECTED_SCORE
    evals_partial = [
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g1
        make_evaluation(Outcome.WRONG_ANSWER, testcase_index=0),  # g2
    ]

    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution, skeleton, evals_partial, VerificationLevel.FULL
        )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_SCORE
    assert report.gotScore == 30

    # 3. Test unexpected score range
    # Solution expects 0..50
    solution_range = Solution(
        path=tmp_path / 'range.cpp',
        outcome=ExpectedOutcome.ANY,
        score=(0, 50),
    )

    # Got 100 (Unlikely for a solution expecting low score, but logic should hold)
    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution_range, skeleton, evals_perfect, VerificationLevel.FULL
        )

    assert report.status == SolutionOutcomeStatus.UNEXPECTED_SCORE
    assert report.gotScore == 100

    # Got 30 (Into range)
    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution_range, skeleton, evals_partial, VerificationLevel.FULL
        )

    assert report.status == SolutionOutcomeStatus.OK
    assert report.gotScore == 30


def test_solution_outcome_report_points_scoring_with_dependencies(
    tmp_path, mock_limits, mock_skeleton
):
    """Test solution reporting with POINTS scoring and dependencies."""
    solution = Solution(
        path=tmp_path / 'sol.cpp',
        outcome=ExpectedOutcome.ACCEPTED,
        score=100,
    )

    # Create groups with dependencies
    # g1 (30)
    # g2 (30) -> deps: g1
    # g3 (40) -> deps: g2
    g1 = GroupSkeleton(
        name='g1',
        score=30,
        deps=[],
        testcases=[Testcase(inputPath=tmp_path / 'g1_1.in')],
    )
    g2 = GroupSkeleton(
        name='g2',
        score=30,
        deps=['g1'],
        testcases=[Testcase(inputPath=tmp_path / 'g2_1.in')],
    )
    g3 = GroupSkeleton(
        name='g3',
        score=40,
        deps=['g2'],
        testcases=[Testcase(inputPath=tmp_path / 'g3_1.in')],
    )

    skeleton = SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(**solution.model_dump(), runs_dir=tmp_path / 'run')
        ],
        entries=[
            make_generation_entry('g1', 0, tmp_path),
            make_generation_entry('g2', 0, tmp_path),
            make_generation_entry('g3', 0, tmp_path),
        ],
        groups=[g1, g2, g3],
        limits={'cpp': mock_limits},
        compiled_solutions={str(solution.path): 'digest'},
        verification=VerificationLevel.FULL,
    )

    # 1. All pass -> Score 100
    evals_all_pass = [
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g1
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g2
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g3
    ]

    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution, skeleton, evals_all_pass, VerificationLevel.FULL
        )
    assert report.gotScore == 100

    # 2. g1 fails -> Score 0 (g2 and g3 check deps and fail efficiently or just don't count)
    evals_g1_fail = [
        make_evaluation(Outcome.WRONG_ANSWER, testcase_index=0),  # g1
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g2
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g3
    ]

    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution, skeleton, evals_g1_fail, VerificationLevel.FULL
        )
    assert report.gotScore == 0

    # 3. g1 passes, g2 fails -> Score 30 (g3 blocked)
    evals_g2_fail = [
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g1
        make_evaluation(Outcome.WRONG_ANSWER, testcase_index=0),  # g2
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g3
    ]

    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution, skeleton, evals_g2_fail, VerificationLevel.FULL
        )
    assert report.gotScore == 30

    # 4. g1 passes, g2 passes, g3 fails -> Score 60
    evals_g3_fail = [
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g1
        make_evaluation(Outcome.ACCEPTED, testcase_index=0),  # g2
        make_evaluation(Outcome.WRONG_ANSWER, testcase_index=0),  # g3
    ]

    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        report = get_solution_outcome_report(
            solution, skeleton, evals_g3_fail, VerificationLevel.FULL
        )
    assert report.gotScore == 60


def test_failed_to_compile_issue_includes_not_found_reason():
    sol = Solution(
        path=pathlib.Path('sols/wa.py'), outcome=ExpectedOutcome.WRONG_ANSWER
    )
    exc = CompilationError()
    exc.not_found_executable = 'python3'
    issue = FailedToCompileSolutionIssue(sol, exception=exc)

    msg = issue.get_detailed_message()
    assert 'python3' in msg
    assert 'sols/wa.py' in msg


def test_failed_to_compile_issue_generic_message_without_reason():
    sol = Solution(
        path=pathlib.Path('sols/wa.py'), outcome=ExpectedOutcome.WRONG_ANSWER
    )
    issue = FailedToCompileSolutionIssue(sol)

    msg = issue.get_detailed_message()
    assert 'could not be compiled and was skipped' in msg
    assert 'sols/wa.py' in msg


@pytest.mark.parametrize('outcome', list(Outcome))
def test_outcome_styles_are_valid_rich_styles(outcome: Outcome):
    # Rich has no plain 'orange' color, and an invalid style blows up at render
    # time (e.g. in the UI's test list), so every outcome must map to a
    # parseable style.
    rich.style.Style.parse(get_outcome_style_verdict(outcome))
    rich.style.Style.parse(get_ui_friendly_outcome_style_verdict(outcome))
    Text.from_markup(get_full_outcome_markup_verdict(outcome)).render(
        rich.console.Console()
    )


def test_skipped_outcome_does_not_fall_through_to_the_unknown_verdict_style():
    # The palette itself may change; what matters is that SKIPPED is spelled
    # out rather than landing on the catch-all used for unrecognized verdicts.
    assert get_outcome_style_verdict(Outcome.SKIPPED) != 'magenta'
    assert '✗' not in get_outcome_markup_verdict(Outcome.SKIPPED)


def _group(name: str, deps: List[str]) -> GroupSkeleton:
    return GroupSkeleton(name=name, score=100, deps=deps, testcases=[])


def test_binary_scoring_aborts_the_whole_testset():
    groups = [_group('a', []), _group('b', []), _group('c', [])]
    gate = _AbortGate(groups=groups, scoring=ScoreType.BINARY)
    gate.trip('a')
    assert all(gate.is_skipped(group.name) for group in groups)


def test_points_scoring_aborts_the_group_and_its_dependents():
    # c depends on b, b depends on a; d is independent.
    groups = [
        _group('a', []),
        _group('b', ['a']),
        _group('c', ['b']),
        _group('d', []),
    ]
    gate = _AbortGate(groups=groups, scoring=ScoreType.POINTS)
    gate.trip('a')
    assert gate.is_skipped('a')
    assert gate.is_skipped('b')
    assert gate.is_skipped('c')  # indirect dependency
    assert not gate.is_skipped('d')


def test_gate_is_not_skipped_before_tripping():
    groups = [_group('a', [])]
    gate = _AbortGate(groups=groups, scoring=ScoreType.POINTS)
    assert not gate.is_skipped('a')


@pytest.mark.test_pkg('problems/box1')
async def test_abort_skips_every_later_testcase_of_that_solution(
    pkg_from_testdata: pathlib.Path,
):
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    real_run = solutions_module.run_solution_on_testcase
    with patch.object(
        solutions_module, 'run_solution_on_testcase', wraps=real_run
    ) as spy:
        result = await run_solutions(
            verification=VerificationLevel.FULL,
            tracked_solutions=['sol.cpp', 'wa.sol.cpp'],
            abort_on=lambda ctx: ctx.evaluation.result.outcome != Outcome.ACCEPTED,
        )
        res = await convert_list_of_solution_evaluations_to_dict(
            result.skeleton, result.items
        )
        runs = spy.call_count

    accepted_outcomes = [ev.result.outcome for ev in res[0]['gen1']]
    aborted_outcomes = [ev.result.outcome for ev in res[1]['gen1']]

    # The accepted solution never trips the gate.
    assert Outcome.SKIPPED not in accepted_outcomes
    assert accepted_outcomes == [Outcome.ACCEPTED] * len(accepted_outcomes)

    # Everything after the first bad verdict is skipped, and nothing is missing:
    # a skipped slot still holds a real evaluation, keeping the positions aligned.
    assert Outcome.SKIPPED in aborted_outcomes
    first_skip = aborted_outcomes.index(Outcome.SKIPPED)
    assert first_skip > 0
    assert aborted_outcomes[first_skip - 1] != Outcome.ACCEPTED
    assert all(outcome == Outcome.SKIPPED for outcome in aborted_outcomes[first_skip:])
    assert len(aborted_outcomes) == len(accepted_outcomes)

    # The sandbox is never entered for a skipped testcase.
    assert runs == len(accepted_outcomes) + first_skip


@pytest.mark.test_pkg('problems/abort-groups')
async def test_abort_skips_dependent_groups_but_not_independent_ones(
    pkg_from_testdata: pathlib.Path,
):
    # `abort-groups` is points-scored with `small` <- `mid` <- `late` and a
    # fourth group depending on nothing, so this crosses group boundaries: it is
    # what tells a per-solution gate apart from a per-group one.
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        abort_on=lambda ctx: ctx.evaluation.result.outcome != Outcome.ACCEPTED,
    )
    res = await convert_list_of_solution_evaluations_to_dict(
        result.skeleton, result.items
    )

    def outcomes(solution_index: int, group: str) -> List[Outcome]:
        return [ev.result.outcome for ev in res[solution_index][group]]

    groups = ['small', 'mid', 'late', 'independent']

    # The main solution passes everything and never trips the gate.
    for group in groups:
        assert outcomes(0, group) == [Outcome.ACCEPTED] * len(res[0][group])

    # `wa.sol.cpp` is wrong on the very first testcase of `small`.
    assert outcomes(1, 'small') == [
        Outcome.WRONG_ANSWER,
        Outcome.SKIPPED,
        Outcome.SKIPPED,
    ]
    # The direct dependent is skipped whole, even though it is a later group.
    assert outcomes(1, 'mid') == [Outcome.SKIPPED, Outcome.SKIPPED]
    # And so is the indirect one.
    assert outcomes(1, 'late') == [Outcome.SKIPPED, Outcome.SKIPPED]
    # But a group that depends on nothing can still score, so it still runs.
    assert outcomes(1, 'independent') == [Outcome.ACCEPTED, Outcome.ACCEPTED]

    # The gate belongs to one solution: the next one is judged from scratch.
    for group in groups:
        assert outcomes(2, group) == [Outcome.ACCEPTED] * len(res[2][group])


def _fail_fast_context(
    outcome: Outcome,
    expected_outcome: ExpectedOutcome = ExpectedOutcome.ACCEPTED,
) -> AbortContext:
    return AbortContext(
        solution=Solution(path=pathlib.Path('sol.cpp'), outcome=expected_outcome),
        group=_group('group1', []),
        entry=TestcaseEntry(group='group1', index=0),
        expected_outcome=expected_outcome,
        group_expected_outcome=None,
        evaluation=make_evaluation(outcome),
    )


def test_fail_fast_trips_on_every_verdict_but_accepted():
    assert not fail_fast_abort_predicate(_fail_fast_context(Outcome.ACCEPTED))

    for outcome in Outcome:
        if outcome == Outcome.ACCEPTED:
            continue
        assert fail_fast_abort_predicate(_fail_fast_context(outcome)), outcome


def test_fail_fast_trips_even_on_the_verdict_the_solution_declared():
    """The coarseness is the point, and the reason the command warns about the
    flag: a solution declared `wa` is *supposed* to fail somewhere, so its
    remaining testcases are not doomed at all -- they are dropped anyway."""
    context = _fail_fast_context(
        Outcome.WRONG_ANSWER, expected_outcome=ExpectedOutcome.WRONG_ANSWER
    )
    assert context.expected_outcome.match(context.evaluation.result.outcome)
    assert fail_fast_abort_predicate(context)


def test_double_tl_is_not_claimed_off_a_truncated_run(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """A run that stopped early only measures a prefix of the testset, and a
    testcase that never ran could well be the one that does not fit in double
    TL.

    Two things suppress the claim today -- the explicit skipped check, and
    SKIPPED landing among the other bad verdicts -- so this pins the behavior
    rather than either mechanism.
    """
    solution = Solution(
        path=tmp_path / 'tle.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution])
    soft_tle = make_evaluation(
        Outcome.TIME_LIMIT_EXCEEDED, time_ms=1500, no_tle_outcome=Outcome.ACCEPTED
    )
    skipped = make_evaluation(Outcome.SKIPPED, time_ms=None, memory_bytes=None)

    complete = get_solution_outcome_report(
        solution,
        skeleton,
        [soft_tle, make_evaluation(Outcome.ACCEPTED, time_ms=200)],
        VerificationLevel.FULL,
    )
    assert complete.runUnderDoubleTl is True

    truncated = get_solution_outcome_report(
        solution, skeleton, [soft_tle, skipped], VerificationLevel.FULL
    )
    assert truncated.runUnderDoubleTl is False
    assert 'double TL' not in truncated.get_verdict_markup_with_warnings()


def test_double_tl_verdicts_are_not_claimed_off_a_truncated_run(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(
        path=tmp_path / 'tle.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution])
    soft_tle_with_wa = make_evaluation(
        Outcome.TIME_LIMIT_EXCEEDED, time_ms=1500, no_tle_outcome=Outcome.WRONG_ANSWER
    )

    complete = get_solution_outcome_report(
        solution, skeleton, [soft_tle_with_wa], VerificationLevel.FULL
    )
    assert complete.doubleTlVerdicts == {Outcome.WRONG_ANSWER}

    truncated = get_solution_outcome_report(
        solution,
        skeleton,
        [soft_tle_with_wa, make_evaluation(Outcome.SKIPPED, time_ms=None)],
        VerificationLevel.FULL,
    )
    assert truncated.doubleTlVerdicts == set()


def test_timing_issues_are_not_raised_off_a_truncated_run(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """A solution expected to be slow that fails early for another reason never
    reaches the testcase that would have timed out, so it looks 'too fast' only
    because the rest never ran. Blaming the limits for that is misleading --
    same rule as the partial reports, which is why they pass
    ``report_issues=False``."""
    solution = Solution(
        path=tmp_path / 'tle.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution])
    wrong_answer = make_evaluation(Outcome.WRONG_ANSWER)

    # Ran to the end and never timed out: the limits really may be untuned.
    with fresh_issue_stack() as issues:
        get_solution_outcome_report(
            solution, skeleton, [wrong_answer], VerificationLevel.FULL
        )
    assert any(isinstance(issue, TimingIssue) for issue in issues.issues)

    # Same verdicts, but the run stopped: the missing TLE says nothing.
    with fresh_issue_stack() as issues:
        get_solution_outcome_report(
            solution,
            skeleton,
            [wrong_answer, make_evaluation(Outcome.SKIPPED, time_ms=None)],
            VerificationLevel.FULL,
        )
    assert [issue for issue in issues.issues if isinstance(issue, TimingIssue)] == []


async def test_plain_report_drops_the_timing_summary_when_timing_is_off(
    mock_problem_root, mock_skeleton, mock_binary_scoring
):
    """`rbx run --ff` turns `timing` off, since every line of that summary is an
    extreme over the solutions and a solution that stopped early is only timed
    on the testcases that ran. Only the detailed report used to honor the flag,
    so the plain one kept printing the summary."""
    solutions = [
        Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED),
        Solution(path=pathlib.Path('other.cpp'), outcome=ExpectedOutcome.ACCEPTED),
    ]
    skeleton = mock_skeleton(solutions, entries_per_group={'group1': 1})
    result = make_run_result(skeleton, {('group1', 0): Outcome.ACCEPTED})

    console = recording_console()
    await print_run_report(result, console, VerificationLevel.FULL, timing=True)
    assert 'Timing summary' in console.export_text(clear=False)

    console = recording_console()
    await print_run_report(result, console, VerificationLevel.FULL, timing=False)
    assert 'Timing summary' not in console.export_text(clear=False)


@pytest.mark.test_pkg('problems/abort-groups')
async def test_skipped_testcase_writes_a_readable_eval_artifact(
    pkg_from_testdata: pathlib.Path,
):
    # The run explorer reads evaluations off disk, and its only signal that a
    # testcase has not run is a missing `.eval`. A skipped test must leave one
    # behind, at the very path the skeleton points the TUI at.
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        abort_on=lambda ctx: ctx.evaluation.result.outcome != Outcome.ACCEPTED,
    )
    await convert_list_of_solution_evaluations_to_dict(result.skeleton, result.items)

    skeleton = result.skeleton
    solution = skeleton.find_solution_skeleton(
        next(sol for sol in package.get_solutions() if sol.path.name == 'wa.sol.cpp')
    )
    assert solution is not None

    skipped_entries = [
        entry.group_entry
        for entry in skeleton.entries
        if entry.group_entry.group in ('mid', 'late')
    ]
    assert skipped_entries

    for entry in skipped_entries:
        path = skeleton.get_solution_entry_prefix(solution, entry).with_suffix('.eval')
        assert path.is_file()
        evaluation = utils.model_from_yaml(Evaluation, path.read_text())
        assert evaluation.result.outcome == Outcome.SKIPPED
        assert evaluation.log.eval_absolute_path == path.absolute()
        # The artifact drops its `None` fields, so the round trip must not turn
        # a testcase that never ran into one that ran instantly.
        assert evaluation.log.time is None
        assert evaluation.log.memory is None

    # And the skipped artifacts land where the real ones do: a testcase that
    # actually ran is readable from the same skeleton-derived path.
    ran_entry = next(
        entry.group_entry
        for entry in skeleton.entries
        if entry.group_entry.group == 'independent'
    )
    ran_path = skeleton.get_solution_entry_prefix(solution, ran_entry).with_suffix(
        '.eval'
    )
    assert ran_path.is_file()
    assert (
        utils.model_from_yaml(Evaluation, ran_path.read_text()).result.outcome
        == Outcome.ACCEPTED
    )


async def test_timing_summary_ignores_skipped_testcases(
    mock_problem_root, mock_binary_scoring
):
    """A skipped testcase never ran, so it measures nothing. The exclusion rests
    on the verdict, not on the absent time a skipped evaluation happens to
    record today."""
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 2})

    def resolved(evaluation: Evaluation) -> Deferred[Evaluation]:
        async def fn() -> Evaluation:
            return evaluation

        return Deferred(fn)

    evaluations = {
        str(skeleton.solutions[0].path): {
            'group1': [
                resolved(make_evaluation(Outcome.ACCEPTED, time_ms=400)),
                resolved(make_evaluation(Outcome.SKIPPED, time_ms=9999)),
            ]
        }
    }
    console = recording_console()
    await _print_timing(console, skeleton, evaluations)

    text = ' '.join(console.export_text(clear=False).split())
    assert '400 ms' in text
    assert '9999 ms' not in text


async def test_detailed_table_marks_a_skipped_testcase_instead_of_pending(
    mock_problem_root, mock_binary_scoring
):
    """A skipped testcase carries a real evaluation, so the detailed table shows
    its verdict. Had the skipped slots been left empty, the cell would read
    '...' -- exactly what a testcase that has not been awaited yet renders."""
    solution = Solution(path=pathlib.Path('wa.cpp'), outcome=ExpectedOutcome.INCORRECT)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 2})
    result = make_run_result(
        skeleton,
        {('group1', 0): Outcome.WRONG_ANSWER, ('group1', 1): Outcome.SKIPPED},
    )
    console = recording_console()
    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)

    await _render_detailed_group_table(
        skeleton.groups[0],
        skeleton,
        reporter.structured_evaluations,
        console,
        verification=VerificationLevel.FULL,
    )

    text = console.export_text(clear=False)
    assert '#1 ⊘' in ' '.join(text.split())
    assert '...' not in text


async def test_live_reporter_counts_a_skipped_testcase_as_evaluated(
    mock_problem_root, mock_binary_scoring
):
    """The live line marks a skipped testcase and moves on. A slot left empty
    would have frozen the line at `1/..`, which is how a testcase that is still
    running renders."""
    solution = Solution(path=pathlib.Path('wa.cpp'), outcome=ExpectedOutcome.INCORRECT)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 3})
    result = make_run_result(
        skeleton,
        {
            ('group1', 0): Outcome.ACCEPTED,
            ('group1', 1): Outcome.WRONG_ANSWER,
            ('group1', 2): Outcome.SKIPPED,
        },
    )
    console = recording_console()
    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)

    with fresh_issue_stack():
        await drive_reporter(reporter, skeleton)

    assert reporter.post_evaluated == 3
    (group_line,) = rendered_group_lines(console)
    assert '/..' not in group_line
    assert group_line.startswith('group1 (3) 1/✗ 2/⊘ ')


async def test_fully_skipped_group_reports_no_time_instead_of_zero(
    mock_problem_root, mock_binary_scoring
):
    """Nothing ran, so there is nothing to report. A `0 ms` here would read as
    'instant' -- the most flattering number available -- for a group that was
    never even attempted."""
    solution = Solution(
        path=pathlib.Path('slow.cpp'), outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 2})
    result = make_run_result(
        skeleton,
        {('group1', 0): Outcome.SKIPPED, ('group1', 1): Outcome.SKIPPED},
    )
    console = recording_console()
    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)

    with fresh_issue_stack():
        await drive_reporter(reporter, skeleton)

    (group_line,) = rendered_group_lines(console)
    assert '0 ms' not in group_line
    assert '0 B' not in group_line
    assert group_line.endswith('(-, -)')


async def test_partially_skipped_group_still_reports_the_measured_maximum(
    mock_problem_root, mock_binary_scoring
):
    """Dropping the unmeasured testcases must not drop the measured ones."""
    solution = Solution(path=pathlib.Path('wa.cpp'), outcome=ExpectedOutcome.INCORRECT)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 2})
    result = make_run_result(
        skeleton,
        {('group1', 0): Outcome.WRONG_ANSWER, ('group1', 1): Outcome.SKIPPED},
    )
    console = recording_console()
    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)

    with fresh_issue_stack():
        await drive_reporter(reporter, skeleton)

    (group_line,) = rendered_group_lines(console)
    assert group_line.endswith('(100 ms, 1 KiB)')


async def test_detailed_table_does_not_time_a_fully_skipped_group(
    mock_problem_root, mock_binary_scoring
):
    """The summary row of the detailed table reads the same helpers."""
    solution = Solution(
        path=pathlib.Path('slow.cpp'), outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 2})
    result = make_run_result(
        skeleton,
        {('group1', 0): Outcome.SKIPPED, ('group1', 1): Outcome.SKIPPED},
    )
    console = recording_console()
    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)

    await _render_detailed_group_table(
        skeleton.groups[0],
        skeleton,
        reporter.structured_evaluations,
        console,
        verification=VerificationLevel.FULL,
    )

    text = ' '.join(console.export_text(clear=False).split())
    assert '0 ms' not in text
    assert '0 B' not in text


# -- the solution block ------------------------------------------------------


def terminal_console(height: int = 40, width: int = 120) -> rich.console.Console:
    """A console that claims to be a terminal, so the reporter animates.

    `height` is what the block's guard measures itself against; rich reports the
    size it is given rather than probing anything, which is what makes the guard
    testable at all.
    """
    return rich.console.Console(
        record=True,
        force_terminal=True,
        color_system=None,
        width=width,
        height=height,
    )


async def test_live_reporter_draws_the_solution_as_one_block(
    mock_problem_root, mock_binary_scoring
):
    """The header and the group lines finalize together, header first.

    That ordering is the whole point of moving the Live up to the solution: a
    header printed before the first group is already in scrollback by the time
    anything worth putting on it is known.
    """
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    skeleton = make_reporter_skeleton(
        mock_problem_root, solution, {'samples': 1, 'group1': 2}
    )
    result = make_run_result(
        skeleton,
        {
            ('samples', 0): Outcome.ACCEPTED,
            ('group1', 0): Outcome.ACCEPTED,
            ('group1', 1): Outcome.ACCEPTED,
        },
    )
    console = recording_console()

    with fresh_issue_stack():
        await drive_reporter(
            LiveRunReporter(result, VerificationLevel.FULL, console), skeleton
        )

    lines = [line.strip() for line in rendered_lines(console)]
    header = next(i for i, line in enumerate(lines) if line.startswith('sol.cpp'))
    samples = next(i for i, line in enumerate(lines) if line.startswith('samples ('))
    group1 = next(i for i, line in enumerate(lines) if line.startswith('group1 ('))
    assert header < samples < group1


async def test_live_reporter_indents_group_lines_under_the_header(
    mock_problem_root, mock_binary_scoring
):
    """Group lines are indented so the block reads as one thing."""
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 1})
    result = make_run_result(skeleton, {('group1', 0): Outcome.ACCEPTED})
    console = recording_console()

    with fresh_issue_stack():
        await drive_reporter(
            LiveRunReporter(result, VerificationLevel.FULL, console), skeleton
        )

    raw = rendered_lines(console)
    assert any(line.startswith('  group1 (1)') for line in raw)
    # The header itself is not indented -- it is what the group lines hang from.
    assert any(line.startswith('sol.cpp') for line in raw)


async def test_live_reporter_omits_the_clock_on_a_non_terminal(
    mock_problem_root, mock_binary_scoring
):
    """No wall clock in a recorded report.

    `--share` reports, e2e goldens and asciinema casts are all non-terminal
    consoles. An elapsed time in any of them is a diff on every single run, which
    is how a golden stops being a golden.
    """
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 1})
    result = make_run_result(skeleton, {('group1', 0): Outcome.ACCEPTED})
    console = recording_console()

    with fresh_issue_stack():
        await drive_reporter(
            LiveRunReporter(result, VerificationLevel.FULL, console), skeleton
        )

    header = next(
        line for line in rendered_lines(console) if line.startswith('sol.cpp')
    )
    assert '·' not in header


async def test_live_reporter_ticks_a_clock_on_a_terminal(
    mock_problem_root, mock_binary_scoring
):
    """On a terminal the header carries how long the solution has been running."""
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 1})
    result = make_run_result(skeleton, {('group1', 0): Outcome.ACCEPTED})
    console = terminal_console()

    with fresh_issue_stack():
        await drive_reporter(
            LiveRunReporter(result, VerificationLevel.FULL, console), skeleton
        )

    text = console.export_text(clear=False)
    assert re.search(r'sol\.cpp.*·\s*\d+(\.\d)?s', text)


async def test_live_reporter_falls_back_when_the_block_would_not_fit(
    mock_problem_root, mock_binary_scoring
):
    """More groups than the terminal has rows drops back to a Live per group.

    A live region taller than the terminal is redrawn by moving the cursor up
    over its own output, so it flickers or tears. The fallback is what shipped
    before the block existed, so the degradation is a familiar one -- and the
    give-away is that the header no longer sits above the group lines in one
    finalized frame.
    """
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    groups = {f'group{i}': 1 for i in range(10)}
    skeleton = make_reporter_skeleton(mock_problem_root, solution, groups)
    result = make_run_result(skeleton, {(name, 0): Outcome.ACCEPTED for name in groups})
    # 10 groups + chrome does not fit in 8 rows.
    console = terminal_console(height=8)

    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)
    with fresh_issue_stack():
        await drive_reporter(reporter, skeleton)

    assert reporter._block is False  # noqa: SLF001
    # Still a complete report: falling back changes the framing, never the
    # content. Compared as a set, because a terminal console records every
    # animation frame and so repeats each line many times over.
    assert {line.split()[0] for line in rendered_group_lines(console)} == {
        f'group{i}' for i in range(10)
    }


async def test_live_reporter_keeps_the_block_when_it_fits(
    mock_problem_root, mock_binary_scoring
):
    """The same package on a tall enough terminal is drawn as one block."""
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    groups = {f'group{i}': 1 for i in range(10)}
    skeleton = make_reporter_skeleton(mock_problem_root, solution, groups)
    result = make_run_result(skeleton, {(name, 0): Outcome.ACCEPTED for name in groups})
    console = terminal_console(height=40)

    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)
    with fresh_issue_stack():
        await drive_reporter(reporter, skeleton)

    assert reporter._block is True  # noqa: SLF001
    assert {line.split()[0] for line in rendered_group_lines(console)} == {
        f'group{i}' for i in range(10)
    }


async def test_live_reporter_stops_its_live_when_an_evaluation_raises(
    mock_problem_root, mock_binary_scoring
):
    """A deferred that raises must not leave the display live.

    A remote judge that never answers raises out of the awaited deferred and
    unwinds straight through the reporter. A `rich.live.Live` left started keeps
    the cursor hidden and overwrites the first lines of whatever is printed next
    -- which on this path is the traceback saying what went wrong.
    """
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 1})

    async def boom() -> Evaluation:
        raise RuntimeError('the judge never answered')

    items = [
        EvaluationItem(
            solution=solution,
            testcase_entry=TestcaseEntry(group='group1', index=0),
            eval=Deferred(boom),
        )
    ]
    result = RunSolutionResult(skeleton=skeleton, items=items)
    console = terminal_console()

    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)
    with fresh_issue_stack():
        with pytest.raises(RuntimeError, match='never answered'):
            await drive_reporter(reporter, skeleton)
        reporter.close()

    assert reporter.live is None
    assert console.is_terminal and not console._live_stack  # noqa: SLF001


async def test_reporter_close_is_idempotent(mock_problem_root, mock_binary_scoring):
    """`close` runs from a `finally`, so it also runs after a clean report."""
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    skeleton = make_reporter_skeleton(mock_problem_root, solution, {'group1': 1})
    result = make_run_result(skeleton, {('group1', 0): Outcome.ACCEPTED})
    console = terminal_console()

    reporter = LiveRunReporter(result, VerificationLevel.FULL, console)
    with fresh_issue_stack():
        await drive_reporter(reporter, skeleton)

    reporter.close()
    reporter.close()
    assert reporter.live is None


def test_elapsed_reads_one_decimal_below_ten_seconds():
    """A ticker reading `0s` on every frame looks exactly as frozen as none."""
    elapsed = utils.Elapsed()
    with patch('rbx.utils.time.monotonic', return_value=elapsed._started + 3.25):  # noqa: SLF001
        assert str(elapsed) == '3.2s'
    with patch('rbx.utils.time.monotonic', return_value=elapsed._started + 41.9):  # noqa: SLF001
        assert str(elapsed) == '41s'
