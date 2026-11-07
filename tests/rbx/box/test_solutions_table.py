"""The per-solution table `rbx time` prints right before the limits table."""

from typing import List

import pytest
from rich.console import Console

from rbx.box import limits_info
from rbx.box.schema import (
    EstimationSolutionTiming,
    InferenceRole,
    LimitModifiers,
    LimitsProfile,
)


def _rows(profile: LimitsProfile) -> List[List[str]]:
    out = Console(width=200, record=True, file=None)
    limits_info.render_solutions_table(profile, title='Solution times', target=out)
    lines = out.export_text().splitlines()
    return [
        [cell.strip() for cell in line.strip('│').split('│')]
        for line in lines
        if line.startswith('│')
    ]


def _timing(path, role, time=None, survived=None, language='cpp'):
    return EstimationSolutionTiming(
        path=path, language=language, role=role, time=time, survivedAt=survived
    )


def test_one_row_per_solution_with_its_verdict_at_the_limit():
    profile = LimitsProfile(
        timeLimit=1000,
        solutions=[
            _timing('sols/ac.cpp', InferenceRole.LOWER, time=400),
            _timing('sols/tle.cpp', InferenceRole.UPPER, time=2500),
            _timing('sols/fits.cpp', InferenceRole.UPPER, time=900),
            _timing('sols/never.cpp', InferenceRole.UPPER, survived=3000),
            _timing('sols/skipped.cpp', InferenceRole.UPPER),
        ],
    )

    assert _rows(profile) == [
        ['sols/ac.cpp', 'accepted', '400 ms', 'AC'],
        ['sols/tle.cpp', 'too slow', '2500 ms', 'TLE'],
        ['sols/fits.cpp', 'too slow', '900 ms', 'AC'],
        ['sols/never.cpp', 'too slow', '>3000 ms', 'TLE'],
        ['sols/skipped.cpp', 'too slow', '-', 'not run'],
    ]


def test_the_verdict_uses_the_solutions_own_language_limit():
    profile = LimitsProfile(
        timeLimit=1000,
        modifiers={'py': LimitModifiers(time=3000)},
        solutions=[
            _timing('sols/ac.cpp', InferenceRole.LOWER, time=400),
            _timing('sols/ac.py', InferenceRole.LOWER, time=2000, language='py'),
        ],
    )

    assert [row[-1] for row in _rows(profile)] == ['AC', 'AC']


def test_a_timeout_below_the_limit_says_nothing_about_it():
    profile = LimitsProfile(
        timeLimit=1000,
        solutions=[_timing('sols/slow.cpp', InferenceRole.UPPER, survived=500)],
    )

    assert _rows(profile) == [['sols/slow.cpp', 'too slow', '>500 ms', 'unknown']]


@pytest.mark.parametrize('solutions', [None, []])
def test_no_table_when_the_profile_recorded_no_solution(solutions):
    profile = LimitsProfile(timeLimit=1000, solutions=solutions)

    assert limits_info.build_solutions_table(profile) is None
    assert _rows(profile) == []


def test_cells_shared_with_the_moj_calibration_report():
    assert limits_info.solution_role_cell(InferenceRole.LOWER) == 'accepted'
    assert limits_info.solution_role_cell(InferenceRole.UPPER) == 'too slow'
    assert limits_info.solution_time_cell(None) == '-'
    assert limits_info.solution_time_cell(120) == '120 ms'
    assert limits_info.solution_time_cell(120, timed_out=True) == '>120 ms'
