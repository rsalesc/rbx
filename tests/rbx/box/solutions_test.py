import contextlib
import pathlib
from typing import Dict, Iterator, List, Optional, Tuple
from unittest.mock import patch

import pytest
import rich.console
import rich.style
from rich.text import Text

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
    convert_list_of_solution_evaluations_to_dict,
    get_full_outcome_markup_verdict,
    get_matching_solutions,
    get_outcome_style_verdict,
    get_solution_outcome_report,
    get_ui_friendly_outcome_style_verdict,
    is_fast,
    run_solutions,
)
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.limits import Limits
from rbx.grading.steps import (
    CheckerResult,
    CompilationError,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)


@pytest.mark.test_pkg('problems/box1')
async def test_solutions(pkg_from_testdata: pathlib.Path):
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    result = await run_solutions(verification=VerificationLevel.FULL)
    res = await convert_list_of_solution_evaluations_to_dict(
        result.skeleton, result.items
    )

    # First solution should pass all tests.
    assert all(chk.result.outcome == Outcome.ACCEPTED for chk in res[0]['gen1'])
    # 25 test should be WA for the second solution.
    assert res[1]['gen1'][3].result.outcome == Outcome.WRONG_ANSWER
    # Runtime error for third solution.
    assert all(chk.result.outcome == Outcome.RUNTIME_ERROR for chk in res[2]['gen1'])
    # 1e9 test should be TLE for the fourth solution (soft TLE)
    assert res[3]['gen1'][4].result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    # no TLE outcome should be WA (soft TLE)
    assert res[4]['gen1'][4].result.no_tle_outcome == Outcome.WRONG_ANSWER
    # hard TLE
    assert res[5]['gen1'][4].result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    assert res[5]['gen1'][4].result.no_tle_outcome is None
    # OLE
    assert all(
        chk.result.outcome == Outcome.OUTPUT_LIMIT_EXCEEDED for chk in res[6]['gen1']
    )


@pytest.mark.test_pkg('problems/box1')
async def test_get_solution_outcome_report(pkg_from_testdata: pathlib.Path):
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    result = await run_solutions(verification=VerificationLevel.FULL)
    res = await convert_list_of_solution_evaluations_to_dict(
        result.skeleton, result.items
    )

    # Test AC solution (expected AC, got AC)
    ac_solution = result.skeleton.solutions[0]
    ac_evals = res[0]['gen1']
    ac_report = get_solution_outcome_report(
        ac_solution, result.skeleton, ac_evals, VerificationLevel.FULL
    )
    assert ac_report.status == SolutionOutcomeStatus.OK
    assert ac_report.expectedOutcome == ExpectedOutcome.ACCEPTED
    assert ac_report.gotVerdicts == set()

    # Test WA solution (expected fail, got WA) - should pass since it matches expectation
    wa_solution = result.skeleton.solutions[1]
    wa_evals = res[1]['gen1']
    wa_report = get_solution_outcome_report(
        wa_solution, result.skeleton, wa_evals, VerificationLevel.FULL
    )
    assert wa_report.status == SolutionOutcomeStatus.OK
    assert wa_report.expectedOutcome == ExpectedOutcome.INCORRECT

    # Test RTE solution (expected RTE, got RTE)
    rte_solution = result.skeleton.solutions[2]
    rte_evals = res[2]['gen1']
    rte_report = get_solution_outcome_report(
        rte_solution, result.skeleton, rte_evals, VerificationLevel.FULL
    )
    assert rte_report.status == SolutionOutcomeStatus.OK
    assert rte_report.expectedOutcome == ExpectedOutcome.RUNTIME_ERROR

    # Test TLE solution with double TL warning
    tle_solution = result.skeleton.solutions[3]
    tle_evals = res[3]['gen1']
    tle_report = get_solution_outcome_report(
        tle_solution, result.skeleton, tle_evals, VerificationLevel.FULL
    )
    assert tle_report.status == SolutionOutcomeStatus.OK
    assert tle_report.expectedOutcome == ExpectedOutcome.TIME_LIMIT_EXCEEDED
    # Should have double TL warning for soft TLE
    assert tle_report.runUnderDoubleTl is True
    assert (
        'still passed in double TL'
        in Text.from_markup(tle_report.get_verdict_markup_with_warnings()).plain
    )

    # Solution that is within double TL but is *also* wrong there: the warning
    # must name the verdict instead of staying silent (#607).
    tle_incorrect_solution = result.skeleton.solutions[4]
    tle_incorrect_evals = res[4]['gen1']
    tle_incorrect_report = get_solution_outcome_report(
        tle_incorrect_solution,
        result.skeleton,
        tle_incorrect_evals,
        VerificationLevel.FULL,
    )
    assert tle_incorrect_report.status == SolutionOutcomeStatus.OK
    assert tle_incorrect_report.doubleTlVerdicts == {Outcome.WRONG_ANSWER}
    warning = Text.from_markup(
        tle_incorrect_report.get_verdict_markup_with_warnings()
    ).plain
    assert warning.splitlines()[-1] == (
        'WARNING The solution still finished in double TL, '
        'but failed with WRONG_ANSWER.'
    )


# Unit tests with custom inputs


@pytest.fixture
def mock_limits():
    """Create mock limits for testing."""
    return Limits(time=1000, memory=256, profile=None, isDoubleTL=False)


def make_generation_entry(
    group: str, index: int, tmp_path: pathlib.Path
) -> GenerationTestcaseEntry:
    """Create a minimal GenerationTestcaseEntry for testing."""
    entry = TestcaseEntry(group=group, index=index)
    return GenerationTestcaseEntry(
        group_entry=entry,
        subgroup_entry=entry,
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=tmp_path / f'{group}_{index}.in'),
        ),
    )


@pytest.fixture
def mock_skeleton(tmp_path, mock_limits):
    """Create a minimal skeleton for testing.

    Groups default to ``score=0``, so a POINTS-scoring test must pass
    ``scores_per_group`` or it will assert against ``maxScore == 0`` vacuously.
    """

    def _create_skeleton(
        solutions: List[Solution],
        num_entries: int = 5,
        entries_per_group: Optional[Dict[str, int]] = None,
        scores_per_group: Optional[Dict[str, int]] = None,
    ) -> SolutionReportSkeleton:
        if entries_per_group is None:
            entries_per_group = {'test': num_entries}
        entries = [
            make_generation_entry(group, i, tmp_path)
            for group, count in entries_per_group.items()
            for i in range(count)
        ]
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
                SolutionSkeleton(**sol.model_dump(), runs_dir=tmp_path / f'run_{i}')
                for i, sol in enumerate(solutions)
            ],
            entries=entries,
            groups=groups,
            limits={'cpp': mock_limits},
            compiled_solutions={
                str(sol.path): f'digest_{i}' for i, sol in enumerate(solutions)
            },
            verification=VerificationLevel.FULL,
        )

    return _create_skeleton


def make_evaluation(
    outcome: Outcome,
    time_ms: int = 100,
    memory_bytes: int = 1024,
    message: str = '',
    no_tle_outcome: Optional[Outcome] = None,
    sanitizer_warnings: bool = False,
    testcase_index: int = 0,
) -> Evaluation:
    """Helper to create evaluation objects."""
    return Evaluation(
        result=CheckerResult(
            outcome=outcome,
            message=message,
            no_tle_outcome=no_tle_outcome,
            sanitizer_warnings=sanitizer_warnings,
        ),
        log=TestcaseLog(
            time=time_ms / 1000.0,
            memory=memory_bytes,
        ),
        testcase=TestcaseIO(index=testcase_index),
    )


@pytest.fixture
def mock_binary_scoring():
    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.BINARY):
        yield


@pytest.fixture
def mock_points_scoring():
    # `outcomePerGroup` is only loadable under POINTS scoring (see
    # `Package.check_scoring_fields`), so every per-group test must run here and
    # not under `mock_binary_scoring`, which would be an impossible package.
    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        yield


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

    return RunSolutionResult(
        skeleton=skeleton,
        items=[
            EvaluationItem(
                solution=solution,
                testcase_entry=entry.group_entry,
                eval=resolved(
                    make_evaluation(
                        verdicts[entry.group_entry.key()],
                        testcase_index=entry.group_entry.index,
                    )
                ),
            )
            for solution in skeleton.solutions
            for entry in skeleton.entries
        ],
    )


async def drive_reporter(
    reporter: TraditionalRunReporter, skeleton: SolutionReportSkeleton
) -> bool:
    """Replay `print_run_report`'s loop over an already-computed run."""
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
        ok = reporter.finish_solution() and ok
    return ok


def recording_console() -> rich.console.Console:
    return rich.console.Console(
        record=True, force_terminal=False, color_system=None, width=120
    )


def rendered_lines(console: rich.console.Console) -> List[str]:
    """The recorded report, line by line. Keeps the buffer, so it can be re-read."""
    return [line.rstrip() for line in console.export_text(clear=False).splitlines()]


def rendered_group_lines(console: rich.console.Console) -> List[str]:
    """Only the group lines, which are what this feature marks."""
    return [line for line in rendered_lines(console) if line.startswith('group')]


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

    lines = rendered_lines(console)
    # group2 failed its tests, so it scores 0 of 60 -- while still meeting the
    # expectation that it fail, which the line says nothing about.
    assert 'group2 (1) 0/✗ (100 ms, 1 KiB) [0/60 pts]' in lines
    # `samples` has no score, so it gets no trailing mark at all.
    assert 'samples (1) (100 ms, 1 KiB)' in lines


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
