"""Probe limits and the knowledge that lets the picker loop skip re-runs."""

import pytest

from rbx.box import timing_validation


@pytest.mark.parametrize(
    ('time_limit', 'ratio', 'expected'),
    [
        (1000, 1.5, 1500),
        # 1.1 is not exactly representable in binary floating point; the ratio the
        # setter typed is what must be used, as in `timing.compute_bounds`.
        (1000, 1.1, 1100),
        # Rounded up: a solution that finished at exactly the rounded-down value
        # would still be under the real bound.
        (333, 1.5, 500),
        (1, 1.5, 2),
        (1000, 2.0, 2000),
    ],
)
def test_probe_limit_is_the_bound_rounded_up_exactly(time_limit, ratio, expected):
    assert timing_validation.probe_limit(time_limit, ratio) == expected


def test_an_unmeasured_solution_must_run():
    knowledge = timing_validation.SlowKnowledge()
    assert knowledge.needs_run('sols/slow.cpp', 1500)


def test_a_solution_that_timed_out_covers_any_lower_probe():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 1500)
    assert not knowledge.needs_run('sols/slow.cpp', 1500)
    assert not knowledge.needs_run('sols/slow.cpp', 900)
    # A higher probe demands more than what is known.
    assert knowledge.needs_run('sols/slow.cpp', 1600)


def test_a_measured_solution_never_runs_again():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_time('sols/slow.cpp', 1200)
    assert not knowledge.needs_run('sols/slow.cpp', 99999)
    assert knowledge.measured_time('sols/slow.cpp') == 1200


def test_a_measurement_supersedes_an_earlier_timeout():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 900)
    knowledge.record_time('sols/slow.cpp', 1200)
    assert not knowledge.needs_run('sols/slow.cpp', 99999)
    assert knowledge.measured_time('sols/slow.cpp') == 1200


def test_a_timeout_never_weakens_what_is_known():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 1500)
    knowledge.record_timeout('sols/slow.cpp', 900)
    assert not knowledge.needs_run('sols/slow.cpp', 1500)


def test_a_confirmed_solution_reports_no_measurement():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 1500)
    assert knowledge.measured_time('sols/slow.cpp') is None


def test_a_solution_that_never_ran_is_neither_confirmed_nor_violating():
    knowledge = timing_validation.SlowKnowledge()
    assert knowledge.measured_time('sols/slow.cpp') is None
    assert not knowledge.is_confirmed('sols/slow.cpp')


def test_a_solution_that_timed_out_is_confirmed():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 1500)
    assert knowledge.is_confirmed('sols/slow.cpp')


def test_a_measured_solution_is_not_confirmed():
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_time('sols/slow.cpp', 1200)
    assert not knowledge.is_confirmed('sols/slow.cpp')
