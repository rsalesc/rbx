import pathlib
from typing import List, Optional

import pytest

from rbx.box.environment import VerificationLevel
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.box.solutions import (
    SolutionReportSkeleton,
    SolutionSkeleton,
    convert_list_of_solution_evaluations_to_dict,
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
    assert ac_report.ok is True
    assert ac_report.expectedOutcome == ExpectedOutcome.ACCEPTED
    assert ac_report.gotVerdicts == set()

    # Test WA solution (expected fail, got WA) - should pass since it matches expectation
    wa_solution = result.skeleton.solutions[1]
    wa_evals = res[1]['gen1']
    wa_report = get_solution_outcome_report(
        wa_solution, result.skeleton, wa_evals, VerificationLevel.FULL
    )
    assert wa_report.ok is True
    assert wa_report.expectedOutcome == ExpectedOutcome.INCORRECT

    # Test RTE solution (expected RTE, got RTE)
    rte_solution = result.skeleton.solutions[2]
    rte_evals = res[2]['gen1']
    rte_report = get_solution_outcome_report(
        rte_solution, result.skeleton, rte_evals, VerificationLevel.FULL
    )
    assert rte_report.ok is True
    assert rte_report.expectedOutcome == ExpectedOutcome.RUNTIME_ERROR

    # Test TLE solution with double TL warning
    tle_solution = result.skeleton.solutions[3]
    tle_evals = res[3]['gen1']
    tle_report = get_solution_outcome_report(
        tle_solution, result.skeleton, tle_evals, VerificationLevel.FULL
    )
    assert tle_report.ok is True
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

    assert report.ok is True
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

    assert report.ok is False
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

    assert report.ok is True
    assert report.expectedOutcome == ExpectedOutcome.INCORRECT


def test_solution_outcome_report_ac_expects_incorrect(tmp_path, mock_skeleton):
    """Test AC solution that expects incorrect - should fail."""
    solution = Solution(path=tmp_path / 'wa.cpp', outcome=ExpectedOutcome.INCORRECT)
    skeleton = mock_skeleton([solution])
    evals = [make_evaluation(Outcome.ACCEPTED) for _ in range(5)]

    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )

    assert report.ok is False
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

    assert report.ok is True
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

    assert report.ok is True
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

    assert report.ok is True
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

    assert report.ok is True
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

    assert report.ok is True
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

    assert report.ok is False
    # Should report the unmatched verdicts
    assert Outcome.WRONG_ANSWER in report.gotVerdicts
    assert Outcome.RUNTIME_ERROR in report.gotVerdicts
    assert Outcome.TIME_LIMIT_EXCEEDED in report.gotVerdicts
