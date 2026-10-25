import pytest

from rbx.box import checkers
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.steps import Outcome, RunLog


def _checker_log(exitcode: int) -> RunLog:
    return RunLog(
        exitcode=exitcode,
        exitstatus=SandboxBase.EXIT_OK
        if exitcode == 0
        else SandboxBase.EXIT_NONZERO_RETURN,
    )


@pytest.mark.parametrize(
    'stderr,outcome,score,message',
    [
        ('points 82.5 ok, 7 ops\n', Outcome.PARTIALLY_CORRECT, 0.825, 'ok, 7 ops'),
        ('points 100\n', Outcome.ACCEPTED, 1.0, ''),
        ('points 0 too many ops\n', Outcome.WRONG_ANSWER, 0.0, 'too many ops'),
        # testlib prints a multi-line message after the points as-is.
        (
            'debug\npoints 50 first\nsecond\n',
            Outcome.PARTIALLY_CORRECT,
            0.5,
            'first\nsecond',
        ),
    ],
)
def test_process_checker_points(stderr, outcome, score, message):
    result = checkers.process_checker_run_log(_checker_log(7), stderr)
    assert (result.outcome, result.score, result.message) == (
        outcome,
        score,
        message,
    )


@pytest.mark.parametrize(
    'stderr', ['points 150\n', 'points -3\n', 'points abc\n', 'no points here\n']
)
def test_process_checker_points_out_of_range_fails(stderr):
    result = checkers.process_checker_run_log(_checker_log(7), stderr)
    assert result.outcome == Outcome.JUDGE_FAILED
    assert result.score is None


@pytest.mark.parametrize('exitcode', [0, 1, 7, 50])
def test_process_checker_refuses_pc(exitcode):
    # `_pc(k)` exits with k, so `_pc(1)` would otherwise read as a WA.
    result = checkers.process_checker_run_log(
        _checker_log(exitcode), 'partially correct (1) half\n'
    )
    assert result.outcome == Outcome.JUDGE_FAILED
    assert 'quitp' in result.message


@pytest.mark.parametrize(
    'exitcode,outcome',
    [
        (0, Outcome.ACCEPTED),
        (1, Outcome.WRONG_ANSWER),
        (2, Outcome.WRONG_ANSWER),
        (3, Outcome.JUDGE_FAILED),
        (4, Outcome.JUDGE_FAILED),
    ],
)
def test_process_checker_exit_codes_unchanged(exitcode, outcome):
    result = checkers.process_checker_run_log(_checker_log(exitcode), 'msg\n')
    assert (result.outcome, result.score) == (outcome, None)
