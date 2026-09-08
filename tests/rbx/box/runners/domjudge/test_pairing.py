"""Pairing DOMjudge runs back onto rbx testcase entries.

DOMjudge gives a run an `ordinal` and no testcase name, so this is the one place
in the runner where a wrong answer is *silent*: a misattributed timing produces a
plausible number against the wrong testcase and corrupts the estimated limit
without any error. These pin the permutation, and the incremental delivery built
on top of it.
"""

import asyncio
from typing import List

import pytest

from rbx.box.runners.domjudge.runner import _Judging, _ordinals_for


class FakeEntry:
    """Only the bit `_ordinals_for` reads."""

    def __init__(self, sample: bool):
        self._sample = sample

    def is_sample(self) -> bool:
        return self._sample


def entries(*flags: bool) -> List[FakeEntry]:
    return [FakeEntry(flag) for flag in flags]


def test_samples_are_numbered_before_secrets():
    """The packager writes `data/sample/` and `data/secret/` with separate
    counters, and DOMjudge orders the sample directory first."""
    assert _ordinals_for(entries(True, False, False)) == [1, 2, 3]


def test_a_secret_group_before_a_sample_group_does_not_shift_the_pairing():
    """The case positional pairing gets wrong.

    Entry order here is secret, secret, sample -- but the package still holds one
    sample (ordinal 1) followed by two secrets (2, 3). Pairing by position would
    hand the sample's timing to the first secret.
    """
    assert _ordinals_for(entries(False, False, True)) == [2, 3, 1]


def test_interleaved_samples_keep_their_relative_order():
    """Samples take ordinals in the order they appear among the samples, not in
    the order they appear overall."""
    assert _ordinals_for(entries(False, True, False, True)) == [3, 1, 4, 2]


def test_every_entry_gets_a_distinct_ordinal():
    ordinals = _ordinals_for(entries(True, False, True, False, False))
    assert sorted(ordinals) == [1, 2, 3, 4, 5]


def test_no_entries_means_no_ordinals():
    assert _ordinals_for([]) == []


# -- incremental delivery ---------------------------------------------------------
#
# DOMjudge exposes only runs whose `endtime` is set, so `/runs` grows while
# judging proceeds. `_Judging` is what turns that growing list into per-testcase
# results, so a report ticks instead of sitting still for the whole submission.


def a_run(ordinal: int, run_time: float = 0.1, verdict: str = 'AC'):
    return {'ordinal': ordinal, 'run_time': run_time, 'judgement_type_id': verdict}


async def test_a_testcase_resolves_before_the_submission_finishes():
    """The whole point. Testcase 1's result is available while the judging is
    still running, rather than after every other testcase has been judged."""
    judging = _Judging(total=3)

    await judging.publish([a_run(1)])

    assert await judging.run_for(1) == a_run(1)


async def test_waiting_on_a_later_testcase_does_not_block_an_earlier_one():
    judging = _Judging(total=3)
    waiter = asyncio.ensure_future(judging.run_for(3))

    await judging.publish([a_run(1), a_run(2)])
    assert await judging.run_for(2) == a_run(2)

    assert not waiter.done()
    await judging.publish([a_run(1), a_run(2), a_run(3)])
    assert await waiter == a_run(3)


async def test_a_testcase_the_judging_never_reported_resolves_as_missing():
    """Lazy evaluation, or a judging that died part-way. "Not judged yet" and
    "never going to be" are the same thing until the judging ends, which is why
    this can only resolve once it does."""
    judging = _Judging(total=3)
    waiter = asyncio.ensure_future(judging.run_for(3))
    await judging.publish([a_run(1)])

    assert not waiter.done()

    await judging.finish({'id': '1', 'judgement_type_id': 'TLE'})

    assert await waiter is None


async def test_more_runs_than_testcases_pairs_nothing():
    """The remote problem holds testcases this run does not know about, so no
    ordinal means what it appears to and every testcase is left unpaired."""
    judging = _Judging(total=2)

    await judging.publish([a_run(1), a_run(2), a_run(3)])
    await judging.finish({'id': '1'})

    assert await judging.run_for(1) is None
    assert await judging.run_for(2) is None


async def test_a_run_without_an_ordinal_is_dropped_rather_than_guessed():
    judging = _Judging(total=1)

    await judging.publish([{'run_time': 0.1}])
    await judging.finish({'id': '1'})

    assert await judging.run_for(1) is None


async def test_a_failed_poll_raises_for_every_waiter_instead_of_hanging():
    """The deferreds block on the judging, not on the polling task, so a poll
    that blew up has to hand the reason over -- otherwise the error becomes a
    hang on a condition nobody will notify again."""
    judging = _Judging(total=2)
    waiter = asyncio.ensure_future(judging.run_for(2))

    await judging.fail(RuntimeError('the judge went away'))

    with pytest.raises(RuntimeError, match='the judge went away'):
        await waiter
    with pytest.raises(RuntimeError, match='the judge went away'):
        await judging.run_for(1)


async def test_progress_chips_count_what_has_been_judged():
    judging = _Judging(total=3)
    assert judging.chips() == ()

    await judging.publish([a_run(1), a_run(2)])

    assert [chip.text for chip in judging.chips()] == ['judged 2/3']


async def test_progress_says_nothing_when_the_runs_cannot_be_trusted():
    """A count over a mismatched run list would describe progress through a
    testset that is not the one being reported."""
    judging = _Judging(total=2)

    await judging.publish([a_run(1), a_run(2), a_run(3)])

    assert judging.chips() == ()
