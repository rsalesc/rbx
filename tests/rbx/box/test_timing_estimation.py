from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingGroupOrigin
from rbx.box.timing import (
    build_timing_profile,
    default_assignment,
    relevant_languages_for_estimation,
)
from rbx.box.timing_groups import partition_from_assignment


def test_build_timing_profile_groups_languages():
    timings = {
        'cpp': {'a.cpp': 100, 'b.cpp': 150},
        'python': {'p.py': 500},
    }
    profile = build_timing_profile(
        timing_per_solution_per_language=timings,
        formula='max(fastest * 3, slowest * 2)',
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
        formula='max(fastest * 3, slowest * 2)',
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
        formula='max(fastest * 3, slowest * 2)',
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
