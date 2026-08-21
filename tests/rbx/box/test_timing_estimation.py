from typing import Dict
from unittest import mock

import pytest

from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import (
    LimitsProfile,
    TimingBound,
    TimingGroupOrigin,
    TimingMultipliers,
)
from rbx.box.timing import (
    MissingLowerBoundError,
    _describe_strategy,  # noqa: SLF001
    build_timing_profile,
    default_assignment,
    describe_strategy_briefly,
    relevant_languages_for_estimation,
)
from rbx.box.timing_config import TimingStrategy
from rbx.box.timing_groups import (
    GroupMeasurements,
    TimingRangeError,
    partition_from_assignment,
    resolve_groups,
)


def _formula(formula: str) -> TimingStrategy:
    return TimingStrategy(formula=formula)


def _multipliers(**kwargs) -> TimingStrategy:
    # `inferenceTimeout` belongs to the strategy, not to the ratios.
    inference_timeout = kwargs.pop('inferenceTimeout', None)
    strategy_kwargs = (
        {} if inference_timeout is None else {'inferenceTimeout': inference_timeout}
    )
    return TimingStrategy(multipliers=TimingMultipliers(**kwargs), **strategy_kwargs)


def _measured_groups(profile_kwargs) -> Dict[int, GroupMeasurements]:
    """The per-group measurements ``build_timing_profile`` hands to the
    resolution layer, keyed by group index. This is where the dropped slow
    solutions are attributed to a group, before the reports carry them out."""
    with mock.patch(
        'rbx.box.timing_groups.resolve_groups', wraps=resolve_groups
    ) as spy:
        build_timing_profile(**profile_kwargs)
    return spy.call_args.args[1]


def test_build_timing_profile_groups_languages():
    timings = {
        'cpp': {'a.cpp': 100, 'b.cpp': 150},
        'python': {'p.py': 500},
    }
    profile = build_timing_profile(
        timing_per_solution_per_language=timings,
        strategy=_formula('max(fastest * 3, slowest * 2)'),
        env_groups=[
            LanguageGroup(languages=['c', 'cpp']),
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=4.0),
            ),
        ],
        all_languages=['c', 'cpp', 'java', 'kotlin', 'python'],
    )
    limits = profile.to_limits()
    assert limits.modifiers['java'].time == limits.modifiers['cpp'].time * 4
    assert limits.modifiers['c'].time == limits.modifiers['cpp'].time
    assert limits.groups is not None
    origins = {tuple(r.languages): r.origin for r in limits.groups}
    assert origins[('java', 'kotlin')] == TimingGroupOrigin.MULTIPLIER
    # The base estimate is pooled across every solution timing (100..500).
    assert limits.baseEstimate is not None
    assert limits.baseEstimate.origin == TimingGroupOrigin.ESTIMATED
    assert limits.baseEstimate.fastest == 100
    assert limits.baseEstimate.slowest == 500
    assert limits.baseEstimate.solutionCount == 3


def test_relevant_languages_includes_all_env_languages():
    result = relevant_languages_for_estimation(
        env_languages=['c', 'cpp', 'java', 'kotlin', 'python', 'go'],
        timing_languages=['python'],
    )
    # every env language is now in scope, ordered by env order
    assert result == ['c', 'cpp', 'java', 'kotlin', 'python', 'go']


def test_relevant_languages_appends_unknown_timing_langs():
    result = relevant_languages_for_estimation(
        env_languages=['cpp', 'python'],
        timing_languages=['python', 'rust'],  # rust not in env list
    )
    assert result == ['cpp', 'python', 'rust']


def test_unrepresented_languages_inherit_leftover_pool():
    # cpp has solutions and is unbucketed; go/java are unbucketed with no
    # solutions -> they share cpp's pooled estimate via the leftover pool.
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'a.cpp': 100, 'b.cpp': 150}},
        strategy=_formula('max(fastest * 3, slowest * 2)'),
        env_groups=[],
        all_languages=['cpp', 'go', 'java'],
    )
    limits = profile.to_limits()
    # one leftover pool: cpp's estimate applies to all members
    assert limits.modifiers['cpp'].time == limits.modifiers['go'].time
    assert limits.modifiers['go'].time == limits.modifiers['java'].time
    assert profile.groups is not None
    origins = {tuple(sorted(r.languages)): r.origin for r in profile.groups}
    assert origins[('cpp', 'go', 'java')] == TimingGroupOrigin.ESTIMATED


def test_empty_leftover_pool_defaults_to_base():
    # No solutions for any leftover language other than the represented one in
    # its own group; the leftover pool is empty -> DEFAULTED to base, no modifier.
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'a.cpp': 100, 'b.cpp': 150}},
        strategy=_formula('max(fastest * 3, slowest * 2)'),
        env_groups=[LanguageGroup(languages=['cpp'])],
        all_languages=['cpp', 'go', 'java'],
    )
    limits = profile.to_limits()
    # leftover pool (go, java) has no solutions -> DEFAULTED, no modifiers
    assert 'go' not in limits.modifiers
    assert 'java' not in limits.modifiers
    assert profile.groups is not None
    defaulted = {
        tuple(sorted(r.languages)): r
        for r in profile.groups
        if r.origin == TimingGroupOrigin.DEFAULTED
    }
    assert ('go', 'java') in defaulted


def test_default_assignment_round_trip_reproduces_env_grouping():
    # The picker's prepopulated default, fed straight into the partition builder,
    # must reproduce the env grouping (membership) and pool every ungrouped
    # language into one leftover pool. (whenEmpty is no longer re-derived here;
    # env-crossing was dropped from partition_from_assignment.)
    env_groups = [
        LanguageGroup(languages=['c', 'cpp']),
        LanguageGroup(
            languages=['java', 'kotlin'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        ),
    ]
    all_languages = ['c', 'cpp', 'java', 'kotlin', 'python', 'go']

    default = default_assignment(all_languages, env_groups)
    assert default == {
        'c': 1,
        'cpp': 1,
        'java': 2,
        'kotlin': 2,
        'python': 0,
        'go': 0,
    }

    groups = partition_from_assignment(default)
    jk = next(g for g in groups if set(g.languages) == {'java', 'kotlin'})
    assert jk.whenEmpty is None
    assert jk.forced_relative is None
    # python + go are unbucketed -> a single leftover pool
    assert ['python', 'go'] in [g.languages for g in groups]


def test_default_relatives_seeds_only_empty_groups():
    from rbx.box.environment import LanguageGroup, LanguageGroupFallback
    from rbx.box.timing import default_relatives

    env_groups = [
        LanguageGroup(languages=['cpp']),  # has solutions
        LanguageGroup(
            languages=['py'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        ),  # empty -> seed
        LanguageGroup(
            languages=['go'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=3.0),
        ),  # has solutions -> do NOT seed
    ]
    langs_with_solutions = {'cpp', 'go'}
    seeded = default_relatives(env_groups, langs_with_solutions)
    assert set(seeded) == {'g2'}  # only the empty py group (env group #2)
    assert seeded['g2'].multiplier == 2.0


def test_default_relatives_skips_groups_without_when_empty():
    from rbx.box.environment import LanguageGroup
    from rbx.box.timing import default_relatives

    env_groups = [LanguageGroup(languages=['py'])]  # empty but no whenEmpty
    assert default_relatives(env_groups, set()) == {}


def test_build_profile_with_multipliers_uses_both_bounds():
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
        strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 6000}},
        env_groups=[],
        all_languages=['cpp'],
    )
    assert profile.timeLimit == 800
    assert profile.formula is None
    assert profile.multipliers is not None
    assert profile.to_limits().multipliers == profile.multipliers


def test_build_profile_with_multipliers_rejects_an_empty_range():
    with pytest.raises(TimingRangeError):
        build_timing_profile(
            timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
            strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 900}},
            env_groups=[],
            all_languages=['cpp'],
        )


def test_slow_measurements_are_pooled_per_group():
    # cpp and python sit in different groups; each group is capped by its own
    # fastest slow solution, and the binding one is named in the error.
    with pytest.raises(TimingRangeError) as exc:
        build_timing_profile(
            timing_per_solution_per_language={
                'cpp': {'sols/ac.cpp': 100},
                'python': {'sols/ac.py': 400},
            },
            strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            slow_timing_per_solution_per_language={
                'cpp': {'sols/tle.cpp': 5000},
                'python': {'sols/tle.py': 900},
            },
            env_groups=[],
            all_languages=['cpp', 'python'],
            repartition={'cpp': 1, 'python': 2},
        )
    # python's group is the unsatisfiable one: 400*2 = 800 > floor(900/1.5) = 600.
    assert 'sols/tle.py' in str(exc.value)
    assert 'sols/ac.py' in str(exc.value)


def test_slowest_and_fastest_slow_solutions_are_recorded():
    # Two accepted and two slow solutions in one group: the slowest accepted
    # drives the lower bound and the fastest slow one drives the cap.
    with pytest.raises(TimingRangeError) as exc:
        build_timing_profile(
            timing_per_solution_per_language={
                'cpp': {'sols/fast.cpp': 100, 'sols/slow_ac.cpp': 400}
            },
            strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            slow_timing_per_solution_per_language={
                'cpp': {'sols/tle.cpp': 900, 'sols/hopeless.cpp': 9000}
            },
            env_groups=[],
            all_languages=['cpp'],
        )
    message = str(exc.value)
    assert 'sols/slow_ac.cpp' in message
    assert 'sols/tle.cpp' in message
    assert 'sols/hopeless.cpp' not in message


def test_confirmed_slow_solutions_do_not_bound_the_limit():
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
        strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 6000}},
        confirmed_upper_per_language={'cpp': ['sols/hopeless.cpp']},
        env_groups=[],
        all_languages=['cpp'],
    )
    assert profile.timeLimit == 800


def test_a_group_whose_slow_solutions_were_all_confirmed_keeps_them_listed():
    # The group bounds nothing from above, but the outcome still has to be
    # attributable to it -- reconstructing that later from the per-language map
    # would duplicate the pooling this layer exists to do.
    profile_kwargs = dict(
        timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
        strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        slow_timing_per_solution_per_language={},
        confirmed_upper_per_language={'cpp': ['sols/hopeless.cpp']},
        env_groups=[],
        all_languages=['cpp'],
    )
    profile = build_timing_profile(**profile_kwargs)
    assert profile.timeLimit == 800
    upper = _measured_groups(profile_kwargs)[0].upper
    assert upper is not None
    assert upper.fastest_slow is None
    assert upper.confirmed_upper == ['sols/hopeless.cpp']


def test_a_language_with_only_confirmed_slow_solutions_still_forms_a_group():
    # python has no measurement at all, only a confirmed slow solution: its group
    # must not be skipped, or the outcome would be lost.
    measured = _measured_groups(
        dict(
            timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
            strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            confirmed_upper_per_language={'python': ['sols/hopeless.py']},
            env_groups=[],
            all_languages=['cpp', 'python'],
            repartition={'cpp': 1, 'python': 2},
        )
    )
    python_upper = measured[1].upper
    assert python_upper is not None
    assert python_upper.confirmed_upper == ['sols/hopeless.py']


def test_the_upper_bound_pools_every_language_of_a_single_group():
    # cpp and python share ONE group: the group is capped by the fastest slow
    # solution of either language, not by each language on its own.
    with pytest.raises(TimingRangeError) as exc:
        build_timing_profile(
            timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
            strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            slow_timing_per_solution_per_language={
                'cpp': {'sols/tle.cpp': 5000},
                'python': {'sols/tle.py': 900},
            },
            env_groups=[],
            all_languages=['cpp', 'python'],
            repartition={'cpp': 1, 'python': 1},
        )
    # 400*2 = 800 > floor(900/1.5) = 600: the python solution binds the cpp
    # measurement because they sit in the same group.
    assert 'sols/tle.py' in str(exc.value)


def test_formula_mode_ignores_slow_measurements():
    # The formula bounds from below only, so passing slow measurements (or drops)
    # to it must change nothing at all.
    kwargs = dict(
        timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
        strategy=_formula('slowest * 2'),
        env_groups=[],
        all_languages=['cpp'],
    )
    plain = build_timing_profile(**kwargs)
    with_slow = build_timing_profile(
        **kwargs,
        slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 500}},
        confirmed_upper_per_language={'cpp': ['sols/hopeless.cpp']},
    )
    assert with_slow == plain
    assert with_slow.timeLimit == 800


def test_multipliers_bound_a_group_that_derives_its_limit():
    # The python group has no accepted solution of its own, so it derives its
    # limit from cpp -- but its own slow solution still caps it.
    with pytest.raises(TimingRangeError):
        build_timing_profile(
            timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
            strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            slow_timing_per_solution_per_language={'python': {'sols/tle.py': 900}},
            env_groups=[],
            all_languages=['cpp', 'python'],
            repartition={'cpp': 1, 'python': 2},
            relatives={
                'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=1.0),
            },
        )


def test_no_lower_bound_measurements_raise_a_setter_facing_error():
    with pytest.raises(MissingLowerBoundError) as exc:
        build_timing_profile(
            timing_per_solution_per_language={},
            strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 6000}},
            env_groups=[],
            all_languages=['cpp'],
        )
    assert 'inference' in str(exc.value)


def test_strategy_is_described_as_a_formula_or_as_ratios():
    formula_described = _describe_strategy(_formula('slowest * 2'))
    assert 'Using formula: slowest * 2' in formula_described
    # The cap applies to a formula estimate too, so it is spelled out there.
    assert 'capped at 10000 ms (inferenceTimeout)' in formula_described
    described = _describe_strategy(
        _multipliers(
            acToTimeLimit=2.0,
            timeLimitToTle=1.5,
            timeResolution=100,
            inferenceTimeout=8000,
        )
    )
    # Every number in effect is spelled out as the relation it imposes, with the
    # YAML key it comes from in parentheses.
    assert '2.0x the slowest accepted solution (acToTimeLimit)' in described
    assert '1.5x the limit, checked afterwards (timeLimitToTle)' in described
    assert 'capped at 8000 ms (inferenceTimeout)' in described
    assert 'multiple of 100 ms (timeResolution)' in described


def test_the_brief_description_fits_one_menu_line():
    # The `rbx time` menu offers the strategy in effect as a single choice, so
    # the block `_describe_strategy` prints cannot be reused there.
    assert (
        describe_strategy_briefly(_formula('slowest * 2'))
        == 'based on the formula slowest * 2'
    )
    brief = describe_strategy_briefly(
        _multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    )
    assert '\n' not in brief
    assert 'acToTimeLimit 2.0' in brief
    assert 'timeLimitToTle 1.5' in brief
    assert '100 ms' in brief


def test_the_brief_description_says_when_nothing_bounds_from_above():
    brief = describe_strategy_briefly(_multipliers(acToTimeLimit=2.0))
    assert '\n' not in brief
    assert 'no upper bound' in brief


def test_an_unbounded_estimate_says_the_slow_solutions_were_never_checked():
    # The most important fact about a run without timeLimitToTle is what it did
    # NOT do, so it is stated rather than left to the absence of a number.
    described = _describe_strategy(_multipliers(acToTimeLimit=2.0))
    assert 'NOT bounded from above' in described
    assert 'were not run' in described


def test_no_lower_bound_measurements_raise_in_formula_mode_too():
    with pytest.raises(MissingLowerBoundError):
        build_timing_profile(
            timing_per_solution_per_language={},
            strategy=_formula('slowest * 2'),
            env_groups=[],
            all_languages=['cpp'],
        )


def test_the_profile_records_the_bounds_and_the_solutions_that_set_them():
    profile = build_timing_profile(
        timing_per_solution_per_language={
            'cpp': {'sols/fast.cpp': 100, 'sols/slow_ac.cpp': 630}
        },
        strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 6100}},
        confirmed_upper_per_language={'cpp': ['sols/hopeless.cpp']},
        env_groups=[],
        all_languages=['cpp'],
    )
    assert profile.groups is not None
    (group,) = profile.groups
    # 630 * 2.0 = 1260, rounded up to 1300 by the 100 ms resolution.
    assert group.timeLimit == 1300
    assert group.lowerBound == TimingBound(value=1260, solution='sols/slow_ac.cpp')
    # floor(6100 / 1.5) = 4066: the LARGEST limit the slow solution still allows.
    assert group.upperBound == TimingBound(value=4066, solution='sols/tle.cpp')
    assert group.upperValidation is not None
    assert group.upperValidation.confirmed == ['sols/hopeless.cpp']


def test_a_group_with_no_upper_bound_records_only_its_drops():
    # Every slow solution of the group hit the cap: it bounds nothing from
    # above, and the serialized report must still say so.
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
        strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        confirmed_upper_per_language={'cpp': ['sols/hopeless.cpp']},
        env_groups=[],
        all_languages=['cpp'],
    )
    assert profile.groups is not None
    (group,) = profile.groups
    assert group.upperBound is None
    assert group.upperValidation is not None
    assert group.upperValidation.confirmed == ['sols/hopeless.cpp']


def test_formula_mode_records_no_bounds():
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'sols/ac.cpp': 400}},
        strategy=_formula('slowest * 2'),
        env_groups=[],
        all_languages=['cpp'],
    )
    assert profile.groups is not None
    (group,) = profile.groups
    assert group.lowerBound is None
    assert group.upperBound is None
    assert group.upperValidation is None


def test_the_recorded_bounds_are_computed_exactly_once_per_group():
    # A second computation at the serialization layer is where the recorded
    # provenance would silently drift from the limit it explains.
    from rbx.box import timing

    with mock.patch(
        'rbx.box.timing.compute_bounds', wraps=timing.compute_bounds
    ) as spy:
        build_timing_profile(
            timing_per_solution_per_language={
                'cpp': {'sols/ac.cpp': 400},
                'python': {'sols/ac.py': 400},
            },
            strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
            env_groups=[],
            all_languages=['cpp', 'python'],
            repartition={'cpp': 1, 'python': 2},
        )
    # The pooled base estimate plus the two groups, and nothing more.
    assert spy.call_count == 3


def test_the_base_estimate_records_its_own_bounds():
    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'sols/slow_ac.cpp': 630}},
        strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 6100}},
        env_groups=[],
        all_languages=['cpp'],
    )
    assert profile.baseEstimate is not None
    assert profile.baseEstimate.lowerBound == TimingBound(
        value=1260, solution='sols/slow_ac.cpp'
    )
    assert profile.baseEstimate.upperBound == TimingBound(
        value=4066, solution='sols/tle.cpp'
    )


def test_the_limits_profile_round_trips_the_multipliers_and_the_bounds():
    import yaml

    from rbx import utils

    profile = build_timing_profile(
        timing_per_solution_per_language={'cpp': {'sols/slow_ac.cpp': 630}},
        strategy=_multipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        slow_timing_per_solution_per_language={'cpp': {'sols/tle.cpp': 6100}},
        confirmed_upper_per_language={'cpp': ['sols/hopeless.cpp']},
        env_groups=[],
        all_languages=['cpp'],
    )
    limits = profile.to_limits()
    reloaded = LimitsProfile(**yaml.safe_load(utils.model_to_yaml(limits)))
    assert reloaded == limits
    assert reloaded.multipliers is not None
    assert reloaded.multipliers.acToTimeLimit == 2.0
    assert reloaded.groups is not None
    assert reloaded.groups[0].upperBound == TimingBound(
        value=4066, solution='sols/tle.cpp'
    )
