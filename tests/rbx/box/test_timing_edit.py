"""Judging a hand-set time limit against the evidence an estimate recorded."""

from rbx.box import limits_info, timing_edit
from rbx.box.schema import (
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
