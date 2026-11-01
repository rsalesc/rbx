"""Judging a hand-set time limit against the evidence an estimate recorded."""

import pytest

from rbx.box import limits_info, timing_edit
from rbx.box.schema import (
    EstimationSolutionTiming,
    InferenceRole,
    LimitModifiers,
    LimitsProfile,
    TimingBound,
    TimingGroupOrigin,
    TimingGroupReport,
    TimingGroupUpperValidation,
    TimingMultipliers,
)

MULTIPLIERS = TimingMultipliers(
    acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100
)


def _report(**kwargs) -> TimingGroupReport:
    fields = dict(
        languages=['cpp'],
        timeLimit=1000,
        origin=TimingGroupOrigin.ESTIMATED,
        solutionCount=2,
        fastest=200,
        slowest=450,
        lowerBound=TimingBound(value=900, solution='sols/slowest.cpp'),
        upperBound=TimingBound(value=2000, solution='sols/slow.cpp'),
        upperValidation=TimingGroupUpperValidation(confirmed=['sols/tle.cpp']),
    )
    fields.update(kwargs)
    return TimingGroupReport(**fields)


def _profile(**kwargs) -> LimitsProfile:
    fields = dict(
        timeLimit=1000,
        multipliers=MULTIPLIERS,
        modifiers={'cpp': LimitModifiers(time=1000)},
        groups=[_report()],
    )
    fields.update(kwargs)
    return LimitsProfile(**fields)


def test_assess_at_the_estimate_is_ok():
    check = timing_edit.assess(_report(), MULTIPLIERS)
    assert check == timing_edit.GroupCheck(
        time_limit=1000,
        min_ms=900,
        min_solution='sols/slowest.cpp',
        max_ms=2000,
        max_solution='sols/slow.cpp',
        slowest_ms=450,
        confirmed=['sols/tle.cpp'],
    )
    assert check.ok


def test_assess_below_margin_and_below_slowest():
    thin = timing_edit.assess(_report(), MULTIPLIERS, 800)
    assert thin.below_min and not thin.rejects_own_solutions
    assert thin.estimated == 1000
    failing = timing_edit.assess(_report(), MULTIPLIERS, 400)
    assert failing.rejects_own_solutions


def test_assess_above_the_upper_bound():
    check = timing_edit.assess(_report(), MULTIPLIERS, 2100)
    assert check.above_max and check.breaks_upper


def test_raising_the_limit_leaves_confirmations_unverified():
    check = timing_edit.assess(_report(), MULTIPLIERS, 1200)
    assert check.confirmed == []
    assert check.unverified == ['sols/tle.cpp']
    assert not check.ok


def test_lowering_the_limit_keeps_confirmations():
    check = timing_edit.assess(_report(), MULTIPLIERS, 900)
    assert check.confirmed == ['sols/tle.cpp']
    assert check.ok


def test_a_violating_solution_stops_violating_when_the_limit_drops():
    # Finished in 1400 ms: within 1000 * 1.5, but not within 900 * 1.5 = 1350.
    report = _report(
        upperValidation=TimingGroupUpperValidation(
            violating=[TimingBound(value=1400, solution='sols/slow.cpp')]
        )
    )
    assert timing_edit.assess(report, MULTIPLIERS).violating
    assert timing_edit.assess(report, MULTIPLIERS, 900).violating == []


def test_formula_profiles_only_require_the_slowest_to_pass():
    check = timing_edit.assess(_report(), None, 500)
    assert check.min_ms == 450
    assert check.max_ms is None
    assert check.ok


def test_with_time_limit_moves_group_and_modifiers_and_keeps_evidence():
    edited = timing_edit.with_time_limit(_profile(), 0, 1500)
    group = edited.groups[0]
    assert group.timeLimit == 1500
    assert group.estimatedTimeLimit == 1000
    assert edited.modifiers['cpp'].time == 1500
    assert group.upperValidation == _report().upperValidation
    # A second edit keeps the limit the evidence was measured at.
    again = timing_edit.with_time_limit(edited, 0, 1700)
    assert again.groups[0].estimatedTimeLimit == 1000
    # And going back to it clears the mark.
    back = timing_edit.with_time_limit(again, 0, 1000)
    assert back.groups[0].estimatedTimeLimit is None
    assert back == _profile()


def test_with_time_limit_records_a_lower_violation():
    edited = timing_edit.with_time_limit(_profile(), 0, 800)
    assert edited.groups[0].lowerViolation == TimingBound(
        value=900, solution='sols/slowest.cpp'
    )
    assert timing_edit.with_time_limit(edited, 0, 900).groups[0].lowerViolation is None


def test_with_time_limit_on_the_base():
    profile = _profile(baseEstimate=_report(languages=['cpp', 'java']))
    edited = timing_edit.with_time_limit(profile, None, 1200)
    assert edited.timeLimit == 1200
    assert edited.baseEstimate.timeLimit == 1200
    assert edited.baseEstimate.estimatedTimeLimit == 1000
    # The groups are left alone.
    assert edited.groups == profile.groups


def test_is_editable():
    assert timing_edit.is_editable(_profile())
    assert not timing_edit.is_editable(LimitsProfile(timeLimit=1000))
    assert not timing_edit.is_editable(LimitsProfile(inheritFromPackage=True))


def test_adjusted_checks_only_cover_hand_set_limits():
    assert timing_edit.adjusted_checks(_profile()) == []
    edited = timing_edit.with_time_limit(_profile(), 0, 1200)
    checks = timing_edit.adjusted_checks(edited)
    assert [check.time_limit for check in checks] == [1200]


def test_table_rows_judge_hand_set_limits_afresh():
    edited = timing_edit.with_time_limit(_profile(), 0, 1200)
    row = limits_info.build_limits_table_rows(edited)[1]
    assert row.time_limit_ms == 1200
    assert row.adjusted_from == 1000
    assert row.confirmed_upper == []
    assert row.unverified_upper == ['sols/tle.cpp']
    assert 'set by hand, estimated 1000 ms' in row.source


def test_table_rows_keep_recorded_data_at_the_estimate():
    row = limits_info.build_limits_table_rows(_profile())[1]
    assert row.adjusted_from is None
    assert row.confirmed_upper == ['sols/tle.cpp']
    assert row.unverified_upper == []


def _render(table) -> str:
    from rich.console import Console

    console = Console(width=200, record=True, file=None)
    console.print(table)
    return console.export_text()


def test_check_column_shows_only_when_asked_or_adjusted():
    plain = _render(limits_info.build_limits_table(_profile()))
    assert 'Check' not in plain
    asked = _render(limits_info.build_limits_table(_profile(), show_check=True))
    assert 'Check' in asked
    assert '900–2000 ms' in asked
    edited = timing_edit.with_time_limit(_profile(), 0, 1200)
    text = _render(limits_info.build_limits_table(edited))
    assert 'Check' in text
    assert '1 unverified' in text
    assert 'only confirmed too slow for the estimated limit' in text


def test_hand_set_captions_do_not_blame_a_derivation():
    edited = timing_edit.with_time_limit(_profile(), 0, 800)
    text = _render(limits_info.build_limits_table(edited))
    assert 'set by hand for its group, but without the margin' in text
    assert 'derived from another group' not in text


# --- per-solution timings -----------------------------------------------------


def _timing(path, language='cpp', role=InferenceRole.LOWER, **kwargs):
    return EstimationSolutionTiming(path=path, language=language, role=role, **kwargs)


def test_check_solution_lower():
    ac = _timing('sols/ac.cpp', time=450)
    ok = timing_edit.check_solution(ac, MULTIPLIERS, 1000)
    assert (ok.status, ok.min_ms) == (timing_edit.SolutionStatus.OK, 900)
    assert ok.ratio == pytest.approx(1000 / 450)
    thin = timing_edit.check_solution(ac, MULTIPLIERS, 800)
    assert thin.status == timing_edit.SolutionStatus.THIN
    fails = timing_edit.check_solution(ac, MULTIPLIERS, 400)
    assert fails.status == timing_edit.SolutionStatus.FAILS
    # A formula only asks that it passes.
    assert (
        timing_edit.check_solution(ac, None, 450).status
        == timing_edit.SolutionStatus.OK
    )


def test_check_solution_upper():
    slow = _timing('sols/slow.cpp', role=InferenceRole.UPPER, time=1600)
    ok = timing_edit.check_solution(slow, MULTIPLIERS, 1000)
    assert (ok.status, ok.max_ms) == (timing_edit.SolutionStatus.OK, 1066)
    passes = timing_edit.check_solution(slow, MULTIPLIERS, 1100)
    assert passes.status == timing_edit.SolutionStatus.PASSES

    survived = _timing('sols/tle.cpp', role=InferenceRole.UPPER, survivedAt=1500)
    assert (
        timing_edit.check_solution(survived, MULTIPLIERS, 1000).status
        == timing_edit.SolutionStatus.OK
    )
    assert (
        timing_edit.check_solution(survived, MULTIPLIERS, 1100).status
        == timing_edit.SolutionStatus.UNVERIFIED
    )

    never = _timing('sols/brute.cpp', role=InferenceRole.UPPER)
    assert (
        timing_edit.check_solution(never, MULTIPLIERS, 1000).status
        == timing_edit.SolutionStatus.UNCHECKED
    )
    # Without timeLimitToTle nothing bounds the limit from above.
    assert (
        timing_edit.check_solution(slow, None, 1000).status
        == timing_edit.SolutionStatus.UNCHECKED
    )


def test_check_solutions_lists_the_closest_to_the_limit_first():
    checks = timing_edit.check_solutions(
        [
            _timing('a.cpp', time=100),
            _timing('b.cpp', time=300),
            _timing('never.cpp', role=InferenceRole.UPPER),
            _timing('tle.cpp', role=InferenceRole.UPPER, survivedAt=5000),
            _timing('slow.cpp', role=InferenceRole.UPPER, time=2000),
        ],
        MULTIPLIERS,
        1000,
    )
    assert [check.path for check in checks] == [
        'b.cpp',
        'a.cpp',
        'slow.cpp',
        'tle.cpp',
        'never.cpp',
    ]


def test_group_solutions():
    timings = [_timing('a.cpp'), _timing('B.java', language='java', time=1)]
    profile = _profile(solutions=timings, baseEstimate=_report())
    assert timing_edit.group_solutions(_profile(), _report()) is None
    assert timing_edit.group_solutions(profile, profile.groups[0]) == [timings[0]]
    assert timing_edit.group_solutions(profile, profile.baseEstimate) == timings
    assert timing_edit.group_solutions(profile, None) == timings


def test_assess_confirms_against_the_limit_actually_survived():
    # Seen running at 3000 ms: with timeLimitToTle 1.5 it stays confirmed for any
    # limit up to 2000 ms, far above the 1000 ms it was estimated at.
    solutions = [
        _timing('sols/tle.cpp', role=InferenceRole.UPPER, survivedAt=3000),
    ]
    check = timing_edit.assess(_report(), MULTIPLIERS, 1800, solutions=solutions)
    assert check.confirmed == ['sols/tle.cpp']
    assert check.unverified == []
    check = timing_edit.assess(_report(), MULTIPLIERS, 2100, solutions=solutions)
    assert check.unverified == ['sols/tle.cpp']
    # Without the timing it falls back to the estimated limit.
    assert timing_edit.assess(_report(), MULTIPLIERS, 1800).unverified == [
        'sols/tle.cpp'
    ]


def test_profile_yaml_puts_one_line_per_solution_last_and_round_trips():
    import yaml

    profile = _profile(
        solutions=[
            _timing('sols/ac.cpp', time=450),
            _timing('sols/tle.cpp', role=InferenceRole.UPPER, survivedAt=3000),
        ]
    )
    text = limits_info.profile_to_yaml(profile)
    tail = text[text.index(limits_info.SOLUTIONS_HEADER) :]
    assert tail.splitlines()[2:] == [
        'solutions:',
        '- {path: sols/ac.cpp, language: cpp, role: lower, time: 450}',
        '- {path: sols/tle.cpp, language: cpp, role: upper, survivedAt: 3000}',
    ]
    assert LimitsProfile.model_validate(yaml.safe_load(text)) == profile
    # Nothing changes for a profile without timings.
    assert 'solutions' not in limits_info.profile_to_yaml(_profile())
