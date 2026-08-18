import pathlib

import pytest
import yaml

from rbx.box import run_report
from rbx.box.environment import VerificationLevel
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.box.solutions import get_solution_outcome_report
from rbx.grading.steps import Outcome
from tests.rbx.box.conftest import make_evaluation


def build(solution, skeleton, evals):
    """The projection under test, fed by the real outcome report."""
    report = get_solution_outcome_report(
        solution, skeleton, evals, VerificationLevel.FULL
    )
    return run_report.build_solution_report(0, skeleton, report)


def test_report_round_trips_through_yaml(tmp_path: pathlib.Path):
    report = run_report.RunReport(
        version=run_report.REPORT_VERSION,
        solutions=[
            run_report.RunSolutionReport(
                path='sols/main.cpp',
                index=0,
                expectedOutcome=ExpectedOutcome.ACCEPTED,
                outcome=Outcome.ACCEPTED,
                status='OK',
                matchesExpectation=True,
                score=100,
                maxScore=100,
                maxTime=0.008,
                maxMemory=10485760,
            )
        ],
    )
    path = tmp_path / 'report.yml'
    run_report.write_report(path, report)

    reloaded = run_report.RunReport.model_validate(yaml.safe_load(path.read_text()))
    assert reloaded == report


def test_projects_the_verdict_and_the_score_rbx_decided(
    tmp_path, mock_skeleton, mock_points_scoring
):
    solution = Solution(
        path=tmp_path / 'partial.cpp', outcome=ExpectedOutcome.INCORRECT
    )
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'small': 2, 'big': 2},
        scores_per_group={'small': 40, 'big': 60},
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=19),
        make_evaluation(Outcome.ACCEPTED, time_ms=8),
        make_evaluation(Outcome.WRONG_ANSWER, time_ms=7),
        make_evaluation(Outcome.WRONG_ANSWER, time_ms=7),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.path == str(tmp_path / 'partial.cpp')
    assert entry.index == 0
    assert entry.outcome == Outcome.WRONG_ANSWER
    assert entry.score == 40
    assert entry.maxScore == 100
    # Max across the whole solution, not per group and not a sum.
    assert entry.maxTime == pytest.approx(0.019)

    assert [group.name for group in entry.groups] == ['small', 'big']
    assert entry.groups[0].outcome == Outcome.ACCEPTED
    assert entry.groups[0].score == 40
    assert entry.groups[0].maxScore == 40
    assert entry.groups[0].maxTime == pytest.approx(0.019)
    assert entry.groups[1].outcome == Outcome.WRONG_ANSWER
    assert entry.groups[1].score == 0
    assert entry.groups[1].maxScore == 60
    assert entry.groups[1].maxTime == pytest.approx(0.007)


def test_score_honours_group_dependencies(tmp_path, mock_skeleton, mock_points_scoring):
    """The reason this projection exists rather than a client-side one.

    `big` passes on its own, but depends on `small`, which failed. rbx zeroes
    it; a naive "did this group pass?" would award all 60 points.
    """
    solution = Solution(
        path=tmp_path / 'partial.cpp', outcome=ExpectedOutcome.INCORRECT
    )
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'small': 1, 'big': 1},
        scores_per_group={'small': 40, 'big': 60},
    )
    for group in skeleton.groups:
        if group.name == 'big':
            group.deps = ['small']
    evals = [
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.ACCEPTED),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.groups[1].outcome == Outcome.ACCEPTED
    assert entry.groups[1].score == 0
    assert entry.score == 0


def test_group_with_no_evaluations_has_no_outcome(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'small': 1, 'big': 1})
    # Only the first group ran -- an interrupted or in-flight run.
    evals = [make_evaluation(Outcome.ACCEPTED)]

    entry = build(solution, skeleton, evals)

    assert entry.groups[0].outcome == Outcome.ACCEPTED
    assert entry.groups[1].outcome is None
    assert entry.groups[1].maxTime is None
    assert entry.groups[1].maxMemory is None


def test_unmeasured_evaluations_leave_time_and_memory_absent(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'small': 1})
    evals = [
        make_evaluation(Outcome.COMPILATION_ERROR, time_ms=None, memory_bytes=None)
    ]

    entry = build(solution, skeleton, evals)

    assert entry.maxTime is None
    assert entry.maxMemory is None


def test_per_group_expectations_are_carried_through(
    tmp_path, mock_skeleton, mock_points_scoring
):
    solution = Solution(
        path=tmp_path / 'mislabeled.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={'*': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'small': 1, 'big': 1},
        scores_per_group={'small': 40, 'big': 60},
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
    ]

    entry = build(solution, skeleton, evals)

    # The pooled `incorrect` holds -- it does fail somewhere -- so only the
    # per-group layer catches this solution.
    assert entry.matchesExpectation is False
    assert entry.failedGroups == ['small', 'big']
    assert entry.groups[0].expectedOutcome == ExpectedOutcome.TIME_LIMIT_EXCEEDED
    assert entry.groups[0].matchesExpectation is False


def test_every_outcome_survives_the_published_report():
    """A new Outcome must be a deliberate choice, not a silent XX in a client."""
    for outcome in Outcome:
        entry = run_report.RunGroupReport(name='g', outcome=outcome)
        reloaded = run_report.RunGroupReport.model_validate(
            yaml.safe_load(yaml.safe_dump(entry.model_dump(mode='json')))
        )
        assert reloaded.outcome is outcome


def test_every_expected_outcome_survives_the_published_report():
    for expected in ExpectedOutcome:
        entry = run_report.RunSolutionReport(
            path='s.cpp', index=0, expectedOutcome=expected, status='OK'
        )
        reloaded = run_report.RunSolutionReport.model_validate(
            yaml.safe_load(yaml.safe_dump(entry.model_dump(mode='json')))
        )
        assert reloaded.expectedOutcome == expected
