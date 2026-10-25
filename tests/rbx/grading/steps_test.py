from rbx.grading.steps import CheckerResult, Outcome


def test_skipped_is_less_severe_than_real_failures():
    assert (
        Outcome.worst_outcome(
            [Outcome.ACCEPTED, Outcome.TIME_LIMIT_EXCEEDED, Outcome.SKIPPED]
        )
        == Outcome.TIME_LIMIT_EXCEEDED
    )


def test_skipped_beats_accepted():
    assert Outcome.worst_outcome([Outcome.ACCEPTED, Outcome.SKIPPED]) == Outcome.SKIPPED


def test_skipped_is_not_slow_nor_limit_exceeded():
    assert not Outcome.SKIPPED.is_slow()
    assert not Outcome.SKIPPED.is_limit_exceeded()
    assert Outcome.SKIPPED.short_name() == 'SKIP'


def test_partially_correct_ranks_between_accepted_and_skipped():
    assert (
        Outcome.worst_outcome([Outcome.ACCEPTED, Outcome.PARTIALLY_CORRECT])
        == Outcome.PARTIALLY_CORRECT
    )
    assert (
        Outcome.worst_outcome([Outcome.PARTIALLY_CORRECT, Outcome.SKIPPED])
        == Outcome.SKIPPED
    )
    assert Outcome.PARTIALLY_CORRECT.short_name() == 'PC'


def test_checker_result_fraction():
    assert CheckerResult(outcome=Outcome.ACCEPTED).fraction() == 1.0
    assert CheckerResult(outcome=Outcome.WRONG_ANSWER).fraction() == 0.0
    assert CheckerResult(outcome=Outcome.SKIPPED).fraction() == 0.0
    assert (
        CheckerResult(outcome=Outcome.PARTIALLY_CORRECT, score=0.25).fraction() == 0.25
    )
    # A soft TLE keeps the checker's score, but the verdict decides: no credit.
    assert (
        CheckerResult(outcome=Outcome.TIME_LIMIT_EXCEEDED, score=0.25).fraction() == 0.0
    )
