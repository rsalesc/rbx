from rbx.grading.steps import Outcome


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
