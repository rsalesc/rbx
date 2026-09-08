"""Pairing DOMjudge runs back onto rbx testcase entries.

DOMjudge gives a run an `ordinal` and no testcase name, so this is the one place
in the runner where a wrong answer is *silent*: a misattributed timing produces a
plausible number against the wrong testcase and corrupts the estimated limit
without any error. These pin the permutation and the guards around it.
"""

from typing import List

import pytest

from rbx.box.runners.domjudge.runner import _ordinals_for, _runs_by_ordinal


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


# -- the guards -------------------------------------------------------------------


def run(ordinal: int, run_time: float = 0.1, verdict: str = 'AC'):
    return {'ordinal': ordinal, 'run_time': run_time, 'judgement_type_id': verdict}


def test_runs_are_indexed_by_their_own_ordinal():
    indexed = _runs_by_ordinal([run(2), run(1)], total=2)
    assert set(indexed) == {1, 2}
    assert indexed[1]['ordinal'] == 1


def test_a_short_run_list_still_pairs_what_arrived():
    """Lazy evaluation, or a judging that failed part-way, reports a prefix.

    The ordinals are explicit, so what did arrive is trustworthy; the caller
    renders the missing ones as SKIPPED rather than as a measurement.
    """
    indexed = _runs_by_ordinal([run(1)], total=3)
    assert set(indexed) == {1}


def test_more_runs_than_testcases_pairs_nothing():
    """The uploaded problem holds testcases this run does not know about, so no
    ordinal can be trusted to mean what rbx thinks it means."""
    assert _runs_by_ordinal([run(1), run(2), run(3)], total=2) == {}


@pytest.mark.parametrize('missing', [{'run_time': 0.1}, {'ordinal': None}])
def test_a_run_without_an_ordinal_is_dropped_rather_than_guessed(missing):
    assert _runs_by_ordinal([missing], total=1) == {}
