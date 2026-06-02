from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingGroupOrigin
from rbx.box.timing import build_timing_profile, relevant_languages_for_estimation


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
