import pytest

from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingGroupOrigin
from rbx.box.timing_groups import (
    GroupTimings,
    GroupValidationError,
    ResolvedGroup,
    build_partition,
    partition_from_assignment,
    resolve_groups,
    validate_partition,
)


def test_implicit_singletons_for_unlisted_languages():
    groups = build_partition(
        env_groups=[LanguageGroup(languages=['c', 'cpp'])],
        all_languages=['c', 'cpp', 'python'],
    )
    # one explicit group + one implicit singleton, order preserved
    assert [g.languages for g in groups] == [['c', 'cpp'], ['python']]
    assert groups[0].whenEmpty is None


def test_partition_preserves_when_empty():
    groups = build_partition(
        env_groups=[
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            )
        ],
        all_languages=['java', 'kotlin'],
    )
    assert groups[0].whenEmpty.multiplier == 2.0


def test_build_partition_with_no_env_groups_makes_all_singletons():
    groups = build_partition(env_groups=[], all_languages=['c', 'cpp', 'python'])
    assert [g.languages for g in groups] == [['c'], ['cpp'], ['python']]


def _eval(fastest, slowest):
    # simple deterministic formula for tests: max(fastest*3, slowest*2)
    return max(fastest * 3, slowest * 2)


def test_resolves_estimated_and_multiplier_and_default_groups():
    groups = [
        ResolvedGroup(languages=['c', 'cpp']),
        ResolvedGroup(
            languages=['java', 'kotlin'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=4.0),
        ),
        ResolvedGroup(languages=['go']),  # empty, no whenEmpty -> DEFAULTED
        ResolvedGroup(languages=['python']),
    ]
    pooled = {
        0: GroupTimings(fastest=100, slowest=200, solution_count=2),
        3: GroupTimings(fastest=500, slowest=500, solution_count=1),
    }
    base = GroupTimings(fastest=100, slowest=500, solution_count=3)

    result = resolve_groups(groups, pooled, base, _eval)

    assert result.base_time_limit == _eval(100, 500)  # 1000
    by_lang = result.time_limit_per_language
    assert by_lang['cpp'] == _eval(100, 200)  # 400
    assert by_lang['c'] == 400
    assert by_lang['java'] == int(400 * 4.0)
    assert by_lang['kotlin'] == int(400 * 4.0)
    assert 'go' not in by_lang  # DEFAULTED -> uses base, no modifier
    assert by_lang['python'] == _eval(500, 500)  # 1500

    origins = {tuple(r.languages): r.origin for r in result.reports}
    assert origins[('c', 'cpp')] == TimingGroupOrigin.ESTIMATED
    assert origins[('java', 'kotlin')] == TimingGroupOrigin.MULTIPLIER
    assert origins[('go',)] == TimingGroupOrigin.DEFAULTED
    assert result.defaulted_languages == ['go']


def test_multiplier_relative_to_base_when_relative_to_omitted():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['java'],
            whenEmpty=LanguageGroupFallback(multiplier=3.0),
        ),
    ]
    pooled = {0: GroupTimings(fastest=100, slowest=100, solution_count=1)}
    base = GroupTimings(fastest=100, slowest=100, solution_count=1)
    result = resolve_groups(groups, pooled, base, _eval)
    assert result.time_limit_per_language['java'] == int(result.base_time_limit * 3.0)


def test_multiplier_chain_through_another_empty_group():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['java'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        ),
        ResolvedGroup(
            languages=['dart'],
            whenEmpty=LanguageGroupFallback(relativeTo='java', multiplier=2.0),
        ),
    ]
    pooled = {0: GroupTimings(fastest=100, slowest=100, solution_count=1)}
    base = GroupTimings(fastest=100, slowest=100, solution_count=1)
    result = resolve_groups(groups, pooled, base, _eval)
    cpp_tl = result.time_limit_per_language['cpp']
    assert result.time_limit_per_language['java'] == cpp_tl * 2
    assert result.time_limit_per_language['dart'] == cpp_tl * 2 * 2


def test_relative_to_unknown_language_errors():
    groups = build_partition(
        env_groups=[
            LanguageGroup(
                languages=['java'],
                whenEmpty=LanguageGroupFallback(relativeTo='rust', multiplier=2.0),
            )
        ],
        all_languages=['java'],
    )
    with pytest.raises(GroupValidationError, match='rust'):
        validate_partition(groups)


def test_relative_to_same_group_errors():
    groups = build_partition(
        env_groups=[
            LanguageGroup(
                languages=['java', 'kotlin'],
                whenEmpty=LanguageGroupFallback(relativeTo='kotlin', multiplier=2.0),
            )
        ],
        all_languages=['java', 'kotlin'],
    )
    with pytest.raises(GroupValidationError, match='same group'):
        validate_partition(groups)


def test_cyclic_when_empty_errors():
    groups = build_partition(
        env_groups=[
            LanguageGroup(
                languages=['a'],
                whenEmpty=LanguageGroupFallback(relativeTo='b', multiplier=2.0),
            ),
            LanguageGroup(
                languages=['b'],
                whenEmpty=LanguageGroupFallback(relativeTo='a', multiplier=2.0),
            ),
        ],
        all_languages=['a', 'b'],
    )
    with pytest.raises(GroupValidationError, match='cycle'):
        validate_partition(groups)


def test_valid_partition_passes():
    groups = build_partition(
        env_groups=[
            LanguageGroup(languages=['cpp']),
            LanguageGroup(
                languages=['java'],
                whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            ),
        ],
        all_languages=['cpp', 'java'],
    )
    validate_partition(groups)  # no raise


def test_assignment_zero_makes_singletons():
    env_groups = [LanguageGroup(languages=['c', 'cpp'])]
    groups = partition_from_assignment(
        assignment={'c': 0, 'cpp': 0, 'python': 0},
        env_groups=env_groups,
    )
    assert sorted(g.languages for g in groups) == [['c'], ['cpp'], ['python']]


def test_identical_membership_preserves_when_empty():
    env_groups = [
        LanguageGroup(
            languages=['java', 'kotlin'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        )
    ]
    groups = partition_from_assignment(
        assignment={'java': 1, 'kotlin': 1, 'cpp': 2},
        env_groups=env_groups,
    )
    jvm = next(g for g in groups if set(g.languages) == {'java', 'kotlin'})
    assert jvm.whenEmpty is not None and jvm.whenEmpty.multiplier == 2.0


def test_changed_membership_drops_when_empty():
    env_groups = [
        LanguageGroup(
            languages=['java', 'kotlin'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        )
    ]
    groups = partition_from_assignment(
        assignment={'java': 1, 'kotlin': 1, 'scala': 1},
        env_groups=env_groups,
    )
    jvm = next(g for g in groups if 'java' in g.languages)
    assert jvm.whenEmpty is None
