"""A group whose limit is derived from elsewhere is still checked against its own
accepted solutions, and the table says so when the check fails."""

import re
from typing import Dict, List, Optional

import pytest
from prompt_toolkit.formatted_text import ANSI, to_formatted_text

from rbx.box import limits_info
from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingGroupOrigin, TimingMultipliers
from rbx.box.timing import build_preview_renderer, build_timing_profile
from rbx.box.timing_config import TimingStrategy


def _multipliers(
    ac_to_time_limit: float = 2.0,
    time_resolution: int = 100,
) -> TimingStrategy:
    return TimingStrategy(
        multipliers=TimingMultipliers(
            acToTimeLimit=ac_to_time_limit,
            timeLimitToTle=1.5,
            timeResolution=time_resolution,
        )
    )


def _profile(
    strategy: TimingStrategy,
    timings: Dict[str, Dict[str, int]],
    repartition: Optional[Dict[str, int]] = None,
    relatives: Optional[Dict[str, LanguageGroupFallback]] = None,
    env_groups: Optional[List[LanguageGroup]] = None,
    skipped_upper: Optional[Dict[str, List[str]]] = None,
):
    return build_timing_profile(
        timing_per_solution_per_language=timings,
        strategy=strategy,
        env_groups=env_groups or [],
        all_languages=sorted(timings),
        repartition=repartition,
        relatives=relatives,
        skipped_upper_per_language=skipped_upper,
    )


def _group(profile, language: str):
    assert profile.groups is not None
    return next(g for g in profile.groups if language in g.languages)


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _table_text(profile, width: int = 100) -> str:
    """The table as plain text, with styling and rich's own word wrapping
    normalized away -- a caption assertion is about the wording, not about where
    a 100-column render happens to break the line."""
    from rbx import console

    rendered = console.capture_ansi(
        limits_info.build_limits_table(profile.to_limits()), width=width
    )
    return ' '.join(_ANSI.sub('', rendered).split())


# The grouping that started this: java is forced relative to cpp, so its own
# 900 ms solution never bounds the 200 ms limit it ends up with.
_REJECTING = dict(
    timings={'cpp': {'sol.cpp': 100}, 'java': {'sol.java': 900}},
    repartition={'cpp': 1, 'java': 2},
    relatives={'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=1.0)},
)


def test_derived_limit_records_the_bound_its_own_solutions_need():
    profile = _profile(_multipliers(), **_REJECTING)

    java = _group(profile, 'java')
    assert java.origin == TimingGroupOrigin.MULTIPLIER
    assert java.timeLimit == 200
    # 900 ms of accepted solution at acToTimeLimit 2.0 needs 1800 ms.
    assert java.lowerViolation is not None
    assert java.lowerViolation.value == 1800
    assert java.lowerViolation.solution == 'sol.java'


def test_estimated_group_never_violates_its_own_bound():
    profile = _profile(_multipliers(), **_REJECTING)

    # cpp is estimated from its own solutions, so the bound holds by construction.
    assert _group(profile, 'cpp').lowerViolation is None
    assert profile.baseEstimate is not None
    assert profile.baseEstimate.lowerViolation is None


def test_no_violation_when_the_derived_limit_clears_the_bound():
    profile = _profile(
        _multipliers(),
        timings={'cpp': {'sol.cpp': 100}, 'java': {'sol.java': 900}},
        repartition={'cpp': 1, 'java': 2},
        relatives={'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=10.0)},
    )

    java = _group(profile, 'java')
    assert java.timeLimit == 2000
    assert java.lowerViolation is None


def test_violation_is_flagged_when_only_the_margin_is_missing():
    # java takes 150 ms and gets 200 ms: it passes, but acToTimeLimit 2.0 wants 300.
    profile = _profile(
        _multipliers(),
        timings={'cpp': {'sol.cpp': 100}, 'java': {'sol.java': 150}},
        repartition={'cpp': 1, 'java': 2},
        relatives={'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=1.0)},
    )

    java = _group(profile, 'java')
    assert java.timeLimit == 200
    assert java.lowerViolation is not None
    assert java.lowerViolation.value == 300


def test_when_empty_group_with_no_solutions_has_nothing_to_violate():
    profile = _profile(
        _multipliers(),
        timings={'cpp': {'sol.cpp': 100}, 'java': {}},
        env_groups=[
            LanguageGroup(
                languages=['java'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=1.0),
            )
        ],
    )

    assert _group(profile, 'java').lowerViolation is None


def test_formula_mode_derived_group_is_checked():
    # Formula mode used to pass derive_fn=None, leaving a derived group
    # unchecked from both sides.
    profile = _profile(
        TimingStrategy(formula='fastest * 2'),
        **_REJECTING,
    )

    java = _group(profile, 'java')
    assert java.timeLimit == 200
    # With no acToTimeLimit to apply, the bound is the raw measurement: a
    # solution taking 900 ms needs a limit of at least 900 ms.
    assert java.lowerViolation is not None
    assert java.lowerViolation.value == 900
    assert java.lowerViolation.solution == 'sol.java'


def test_formula_mode_estimated_group_is_left_alone():
    profile = _profile(
        TimingStrategy(formula='slowest * 3'),
        timings={'cpp': {'sol.cpp': 100}, 'java': {'sol.java': 900}},
        repartition={'cpp': 1, 'java': 2},
    )

    assert _group(profile, 'java').lowerViolation is None
    assert _group(profile, 'java').timeLimit == 2700


def test_formula_mode_derive_reports_no_bounds_it_cannot_know():
    profile = _profile(TimingStrategy(formula='fastest * 2'), **_REJECTING)

    java = _group(profile, 'java')
    # A formula bounds nothing, so the derived row must not claim bounds.
    assert java.lowerBound is None
    assert java.upperBound is None


@pytest.mark.parametrize(
    'strategy', [_multipliers(), TimingStrategy(formula='fastest * 2')]
)
def test_derived_limit_is_not_moved_by_the_check(strategy: TimingStrategy):
    profile = _profile(strategy, **_REJECTING)

    # The check warns; it never silently repairs the limit under the setter.
    assert _group(profile, 'java').timeLimit == 200
    assert profile.timeLimitPerLanguage['java'] == 200


class TestTable:
    def test_rejecting_group_is_named_in_the_caption(self):
        text = _table_text(_profile(_multipliers(), **_REJECTING))

        assert 'sol.java is accepted, but does not pass at the time limit' in text
        assert 'needs ≥ 1800 ms' in text
        assert 'sol.java takes 900 ms' in text

    def test_missing_margin_gets_its_own_caption(self):
        profile = _profile(
            _multipliers(),
            timings={'cpp': {'sol.cpp': 100}, 'java': {'sol.java': 150}},
            repartition={'cpp': 1, 'java': 2},
            relatives={'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=1.0)},
        )
        text = _table_text(profile)

        assert 'without the margin acToTimeLimit asks for' in text
        assert 'does not pass at the time limit' not in text

    def test_healthy_grouping_says_nothing(self):
        profile = _profile(
            _multipliers(),
            timings={'cpp': {'sol.cpp': 100}, 'java': {'sol.java': 900}},
            repartition={'cpp': 1, 'java': 2},
        )
        text = _table_text(profile)

        assert 'does not pass at the time limit' not in text
        assert 'without the margin' not in text
        assert '⚠' not in text

    def test_several_violating_groups_are_all_named(self):
        profile = _profile(
            _multipliers(),
            timings={
                'cpp': {'sol.cpp': 100},
                'java': {'sol.java': 900},
                'python': {'sol.py': 800},
            },
            repartition={'cpp': 1, 'java': 2, 'python': 3},
            relatives={
                'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=1.0),
                'g3': LanguageGroupFallback(relativeTo='cpp', multiplier=1.0),
            },
        )
        text = _table_text(profile)

        assert 'Each of' in text
        assert 'sol.java' in text and 'sol.py' in text


def test_formula_mode_does_not_start_reporting_on_slow_solutions():
    """Checking the lower bound must not make formula mode emit an upper record.

    A formula computes no bounds, so its estimated groups say nothing about the
    slow solutions; a derived one gaining an `upperValidation` its siblings never
    get would make the profile look like only some groups were validated.
    """
    profile = _profile(
        TimingStrategy(formula='fastest * 2'),
        timings={'cpp': {'sol.cpp': 100}, 'java': {'sol.java': 900}},
        repartition={'cpp': 1, 'java': 2},
        relatives={'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=1.0)},
        skipped_upper={'java': ['slow.java']},
    )

    assert _group(profile, 'java').upperValidation is None
    assert _group(profile, 'cpp').upperValidation is None
    # The lower-bound check still fired.
    assert _group(profile, 'java').lowerViolation is not None


def test_multiplier_mode_still_reports_on_slow_solutions():
    profile = _profile(
        _multipliers(),
        timings={'cpp': {'sol.cpp': 100}, 'java': {'sol.java': 900}},
        repartition={'cpp': 1, 'java': 2},
        relatives={'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=1.0)},
        skipped_upper={'java': ['slow.java']},
    )

    validation = _group(profile, 'java').upperValidation
    assert validation is not None
    assert validation.skipped == ['slow.java']


def test_preview_surfaces_the_violation_instead_of_hiding_the_table():
    """The picker must keep rendering the table -- the setter is choosing the
    grouping and needs to see which row the warning is about."""
    render = build_preview_renderer(
        timing_per_solution_per_language=_REJECTING['timings'],
        strategy=_multipliers(),
        env_groups=[],
        all_languages=['cpp', 'java'],
        width=100,
    )
    ansi: ANSI = render(_REJECTING['repartition'], _REJECTING['relatives'])
    text = ''.join(t for _, t in to_formatted_text(ansi))

    assert 'Time Limit' in text  # the table itself, not an inline error
    assert 'cpp' in text and 'java' in text
    assert 'does not pass at the time limit' in text
