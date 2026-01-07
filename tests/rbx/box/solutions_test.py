import pathlib
from typing import List, Optional
from unittest.mock import patch

import pytest

from rbx.box.environment import VerificationLevel
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.schema import (
    ExpectedOutcome,
    ScoreType,
    Solution,
    Testcase,
)
from rbx.box.solutions import (
    GroupSkeleton,
    SolutionOutcomeStatus,
    SolutionReportSkeleton,
    SolutionSkeleton,
    convert_list_of_solution_evaluations_to_dict,
    get_matching_solutions,
    get_solution_outcome_report,
    run_solutions,
)
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.box.testcase_utils import TestcaseEntry
from rbx.grading.limits import Limits
from rbx.grading.steps import (
    CheckerResult,
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

    result = run_solutions(verification=VerificationLevel.FULL)
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

    result = run_solutions(verification=VerificationLevel.FULL)
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
    assert tle_report.runUnderDoubleTl is True or len(tle_report.doubleTlVerdicts) > 0


# Unit tests with custom inputs


@pytest.fixture
def mock_limits():
    """Create mock limits for testing."""
    return Limits(time=1000, memory=256, profile=None, isDoubleTL=False)


@pytest.fixture
def mock_skeleton(tmp_path, mock_limits):
    """Create a minimal skeleton for testing."""

    def _create_skeleton(
        solutions: List[Solution],
        num_entries: int = 5,
    ) -> SolutionReportSkeleton:
        return SolutionReportSkeleton(
            solutions=[
                SolutionSkeleton(**sol.model_dump(), runs_dir=tmp_path / f'run_{i}')
                for i, sol in enumerate(solutions)
            ],
            entries=[TestcaseEntry(group='test', index=i) for i in range(num_entries)],
            groups=[],
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


def test_solution_outcome_report_ac_expects_ac(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_wa_expects_ac(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_wa_expects_incorrect(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_ac_expects_incorrect(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_rte_expects_rte(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_tle_with_double_tl(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_tle_with_soft_tle_and_wa(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_sanitizer_warnings(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_subset_mode(tmp_path, mock_skeleton):
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


def test_solution_outcome_report_mixed_outcomes(tmp_path, mock_skeleton):
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
        testcases=[Testcase(inputPath=tmp_path / 'g1_1.in')],
    )
    g2 = GroupSkeleton(
        name='g2',
        score=70,
        testcases=[Testcase(inputPath=tmp_path / 'g2_1.in')],
    )

    skeleton = SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(**solution.model_dump(), runs_dir=tmp_path / 'run')
        ],
        entries=[
            TestcaseEntry(group='g1', index=0),
            TestcaseEntry(group='g2', index=0),
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
