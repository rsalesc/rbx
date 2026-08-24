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
    # ...and the two layers are published apart, so a client can say *which* of
    # them was missed instead of blaming the one that held.
    assert entry.pooledMatchesExpectation is True
    assert entry.failedGroups == ['small', 'big']
    assert entry.groups[0].expectedOutcome == ExpectedOutcome.TIME_LIMIT_EXCEEDED
    assert entry.groups[0].matchesExpectation is False


def test_a_missed_pooled_expectation_is_published_as_such(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """The other side of the pair: nothing per-group, the pooled layer missed."""
    solution = Solution(
        path=tmp_path / 'optimistic.cpp', outcome=ExpectedOutcome.ACCEPTED
    )
    skeleton = mock_skeleton([solution], entries_per_group={'small': 1, 'big': 1})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.WRONG_ANSWER),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.matchesExpectation is False
    assert entry.pooledMatchesExpectation is False
    assert entry.failedGroups == []


def test_an_expected_score_range_is_published(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """`status` alone says a score was wrong but never what was wanted."""
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        score=(40, 60),
    )
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'small': 1, 'big': 1},
        scores_per_group={'small': 40, 'big': 60},
    )
    evals = [
        make_evaluation(Outcome.WRONG_ANSWER),
        make_evaluation(Outcome.WRONG_ANSWER),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.status == 'UNEXPECTED_SCORE'
    assert entry.expectedScore == (40, 60)
    assert entry.score == 0
    # The verdicts were exactly what INCORRECT asked for; only the score was not.
    assert entry.pooledMatchesExpectation is True
    assert entry.failedGroups == []


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


def test_a_solution_that_only_fit_in_double_tl_says_so(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """The warning the console prints on a run that otherwise passed.

    `slow.cpp` declared TLE and got one, so `status` is OK and every
    expectation-shaped field reads clean. The only thing saying its slowness is
    borderline -- it fit inside 2x the 1000ms limit -- is this flag.
    """
    solution = Solution(
        path=tmp_path / 'slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution], entries_per_group={'small': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        # Soft TLE: over the limit, but under 2x it, and correct underneath.
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1500,
            no_tle_outcome=Outcome.ACCEPTED,
        ),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.status == 'OK'
    assert entry.matchesExpectation is True
    assert entry.runUnderDoubleTl is True
    assert entry.doubleTlVerdicts == []


def test_a_solution_that_fit_in_double_tl_but_wrongly_publishes_its_verdicts(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """The second, independent double-TL fact: slow *and* wrong underneath."""
    solution = Solution(
        path=tmp_path / 'slow-and-wrong.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
    )
    skeleton = mock_skeleton([solution], entries_per_group={'small': 2})
    evals = [
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1200,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1500,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.status == 'OK'
    assert entry.runUnderDoubleTl is False
    assert entry.doubleTlVerdicts == [Outcome.WRONG_ANSWER]


def test_double_tl_is_published_per_group_as_well(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """The console names the groups a warning came from; so does the report."""
    solution = Solution(
        path=tmp_path / 'slow.cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        outcomePerGroup={'*': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
    )
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'small': 1, 'big': 1},
        scores_per_group={'small': 40, 'big': 60},
    )
    evals = [
        # `small` timed out well past 2x the limit: decisively slow.
        make_evaluation(Outcome.TIME_LIMIT_EXCEEDED, time_ms=9000),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1500,
            no_tle_outcome=Outcome.ACCEPTED,
        ),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.groups[0].name == 'small'
    assert entry.groups[0].runUnderDoubleTl is False
    assert entry.groups[1].name == 'big'
    assert entry.groups[1].runUnderDoubleTl is True
    # The aggregate is a union over the pooled layer and every group, so one
    # borderline group is enough to raise it on the solution.
    assert entry.runUnderDoubleTl is True


def test_a_clean_run_publishes_no_double_tl_facts(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'small': 1})
    evals = [make_evaluation(Outcome.ACCEPTED, time_ms=100)]

    entry = build(solution, skeleton, evals)

    assert entry.runUnderDoubleTl is False
    assert entry.doubleTlVerdicts == []
    assert entry.groups[0].runUnderDoubleTl is False
    assert entry.groups[0].doubleTlVerdicts == []


def test_double_tl_verdicts_survive_yaml(tmp_path: pathlib.Path):
    """They are the only Outcome-valued *list* in the report."""
    report = run_report.RunReport(
        solutions=[
            run_report.RunSolutionReport(
                path='sols/slow.cpp',
                index=0,
                expectedOutcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
                status='OK',
                runUnderDoubleTl=True,
                doubleTlVerdicts=[Outcome.WRONG_ANSWER, Outcome.RUNTIME_ERROR],
            )
        ],
    )
    path = tmp_path / 'report.yml'
    run_report.write_report(path, report)

    reloaded = run_report.RunReport.model_validate(yaml.safe_load(path.read_text()))
    assert reloaded == report


def test_a_no_tle_verdict_no_expectation_accepts_is_surfaced(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """What a client needs to justify showing `no_tle_outcome` on a testcase row.

    The verdict itself is in the `.eval` and any client can read it. Whether it
    is worth showing needs `ExpectedOutcome.match`, so rbx answers instead.
    """
    solution = Solution(
        path=tmp_path / 'slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution], entries_per_group={'small': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=100),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1200,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.groups[0].unexpectedNoTleVerdicts == [Outcome.WRONG_ANSWER]


def test_a_no_tle_verdict_the_declaration_covers_is_not_surfaced(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """`incorrect` already says the solution answers wrongly.

    Surfacing the WA underneath would be telling the setter something they
    declared themselves.
    """
    solution = Solution(
        path=tmp_path / 'slow-and-wrong.cpp', outcome=ExpectedOutcome.INCORRECT
    )
    skeleton = mock_skeleton([solution], entries_per_group={'small': 1})
    evals = [
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1200,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        )
    ]

    entry = build(solution, skeleton, evals)

    assert entry.groups[0].unexpectedNoTleVerdicts == []


def test_an_accepted_no_tle_verdict_is_never_surfaced(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """A correct answer under a soft TLE is the good case, not an issue.

    It is already reported, once, as `runUnderDoubleTl` on the row above.
    """
    solution = Solution(
        path=tmp_path / 'slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution], entries_per_group={'small': 1})
    evals = [
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED, time_ms=1200, no_tle_outcome=Outcome.ACCEPTED
        )
    ]

    entry = build(solution, skeleton, evals)

    assert entry.groups[0].unexpectedNoTleVerdicts == []
    assert entry.runUnderDoubleTl is True


def test_either_layer_accepting_a_no_tle_verdict_keeps_it_quiet(
    tmp_path, mock_skeleton, mock_points_scoring
):
    """Both layers have to object, which is why the group's set is an
    intersection: `big` declares TLE and would object to the WA underneath, but
    the solution's pooled `incorrect` accepts it, and a setter who declared the
    solution wrong does not need telling twice.
    """
    solution = Solution(
        path=tmp_path / 'partial.cpp',
        outcome=ExpectedOutcome.INCORRECT,
        outcomePerGroup={
            'small': ExpectedOutcome.ACCEPTED,
            'big': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        },
    )
    skeleton = mock_skeleton(
        [solution],
        entries_per_group={'small': 1, 'big': 1},
        scores_per_group={'small': 40, 'big': 60},
    )
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1200,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.groups[1].name == 'big'
    assert entry.groups[1].unexpectedNoTleVerdicts == []


def test_a_group_that_hid_nothing_surfaces_nothing(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    """The pooled answer covers the whole solution, so it must be narrowed.

    `small` ran clean; only `big` hid a WA under a soft TLE. Without the
    intersection `small` inherits the pooled set and claims a verdict hidden in
    another group as its own, and a client reading the group row says one of its
    testcases hid something when none of them did.
    """
    solution = Solution(
        path=tmp_path / 'slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    skeleton = mock_skeleton([solution], entries_per_group={'small': 1, 'big': 1})
    evals = [
        make_evaluation(Outcome.ACCEPTED, time_ms=10),
        make_evaluation(
            Outcome.TIME_LIMIT_EXCEEDED,
            time_ms=1200,
            no_tle_outcome=Outcome.WRONG_ANSWER,
        ),
    ]

    entry = build(solution, skeleton, evals)

    assert entry.groups[0].name == 'small'
    assert entry.groups[0].unexpectedNoTleVerdicts == []
    assert entry.groups[1].name == 'big'
    assert entry.groups[1].unexpectedNoTleVerdicts == [Outcome.WRONG_ANSWER]


def test_an_ordinary_run_is_not_marked_sanitized(tmp_path, mock_skeleton):
    """The run-mode flags a client reads to know what kind of run it is showing.

    Absent by default, so a skeleton written by an rbx that predates them --
    and every ordinary run since -- reads as the ordinary run it was.
    """
    skeleton = mock_skeleton([])

    assert not skeleton.sanitized
    assert not skeleton.only_accepted


def test_a_solution_with_a_sanitizer_finding_says_so(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'main': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED, sanitizer_warnings=True),
    ]

    entry = build(solution, skeleton, evals)

    # The whole point: the run passed, and the warning is the only channel
    # saying otherwise.
    assert entry.matchesExpectation
    assert entry.outcome == Outcome.ACCEPTED
    assert entry.sanitizerWarnings


def test_a_clean_run_publishes_no_sanitizer_warning(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'main': 2})
    evals = [make_evaluation(Outcome.ACCEPTED), make_evaluation(Outcome.ACCEPTED)]

    entry = build(solution, skeleton, evals)

    assert not entry.sanitizerWarnings
    assert all(not group.sanitizerWarnings for group in entry.groups)


def test_a_sanitizer_finding_is_attributed_to_its_group(
    tmp_path, mock_skeleton, mock_binary_scoring
):
    solution = Solution(path=tmp_path / 'main.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'small': 2, 'big': 2})
    evals = [
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED),
        make_evaluation(Outcome.ACCEPTED, sanitizer_warnings=True),
        make_evaluation(Outcome.ACCEPTED),
    ]

    entry = build(solution, skeleton, evals)

    groups = {group.name: group for group in entry.groups}
    # Only the group that raised it, so the warning can say where to look
    # instead of sending the reader through every group.
    assert not groups['small'].sanitizerWarnings
    assert groups['big'].sanitizerWarnings
    assert entry.sanitizerWarnings
