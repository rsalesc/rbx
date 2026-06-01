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


def test_relevant_languages_includes_relative_to_target():
    # 'cpp' is referenced by java's whenEmpty but has no solution and is in no
    # group of its own; it must still be pulled into scope.
    result = relevant_languages_for_estimation(
        env_languages=['c', 'cpp', 'java', 'kotlin', 'python', 'go'],
        timing_languages=['python'],
        env_groups=[
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            ),
        ],
    )
    assert 'cpp' in result  # relativeTo target pulled in
    assert 'python' in result  # has solution
    assert 'java' in result and 'kotlin' in result  # grouped
    assert 'go' not in result  # irrelevant, excluded
    # ordering follows env_languages
    assert result == [
        name
        for name in ['c', 'cpp', 'java', 'kotlin', 'python', 'go']
        if name in result
    ]


def test_relevant_languages_orders_by_env_then_appends_unknown_timing_langs():
    result = relevant_languages_for_estimation(
        env_languages=['cpp', 'python'],
        timing_languages=['python', 'rust'],  # rust not in env list
        env_groups=[],
    )
    assert result == ['python', 'rust']
