from typing import List, Optional, Tuple

import pytest

from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingGroupOrigin
from rbx.box.timing_groups import (
    GroupMeasurements,
    GroupTimings,
    GroupValidationError,
    ResolvedGroup,
    UpperTimings,
    build_partition,
    partition_from_assignment,
    resolve_groups,
    validate_partition,
)


def test_leftover_pool_for_unlisted_languages():
    groups = build_partition(
        env_groups=[LanguageGroup(languages=['c', 'cpp'])],
        all_languages=['c', 'cpp', 'python', 'go'],
    )
    # one explicit group + ONE leftover pool of all unlisted languages, in order
    assert [g.languages for g in groups] == [['c', 'cpp'], ['python', 'go']]
    assert groups[0].whenEmpty is None
    assert groups[1].whenEmpty is None


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


def test_build_partition_with_no_env_groups_makes_one_leftover_pool():
    groups = build_partition(env_groups=[], all_languages=['c', 'cpp', 'python'])
    assert [g.languages for g in groups] == [['c', 'cpp', 'python']]


def test_build_partition_no_leftover_when_all_grouped():
    groups = build_partition(
        env_groups=[LanguageGroup(languages=['c', 'cpp'])],
        all_languages=['c', 'cpp'],
    )
    assert [g.languages for g in groups] == [['c', 'cpp']]


def _eval(measured: GroupMeasurements):
    # simple deterministic formula for tests: max(fastest*3, slowest*2)
    assert measured.lower is not None
    return max(measured.lower.fastest * 3, measured.lower.slowest * 2)


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
    measured = {
        0: GroupMeasurements(
            lower=GroupTimings(fastest=100, slowest=200, solution_count=2)
        ),
        3: GroupMeasurements(
            lower=GroupTimings(fastest=500, slowest=500, solution_count=1)
        ),
    }
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=500, solution_count=3)
    )

    result = resolve_groups(groups, measured, base, _eval)

    assert result.base_time_limit == _eval(base)  # 1000
    by_lang = result.time_limit_per_language
    assert by_lang['cpp'] == _eval(measured[0])  # 400
    assert by_lang['c'] == 400
    assert by_lang['java'] == int(400 * 4.0)
    assert by_lang['kotlin'] == int(400 * 4.0)
    assert 'go' not in by_lang  # DEFAULTED -> uses base, no modifier
    assert by_lang['python'] == _eval(measured[3])  # 1500

    origins = {tuple(r.languages): r.origin for r in result.reports}
    assert origins[('c', 'cpp')] == TimingGroupOrigin.ESTIMATED
    assert origins[('java', 'kotlin')] == TimingGroupOrigin.MULTIPLIER
    assert origins[('go',)] == TimingGroupOrigin.DEFAULTED
    assert result.defaulted_languages == ['go']

    # The base (fallback) carries its own estimation provenance, pooled across
    # every solution.
    assert result.base_report.origin == TimingGroupOrigin.ESTIMATED
    assert result.base_report.timeLimit == result.base_time_limit
    assert result.base_report.fastest == 100
    assert result.base_report.slowest == 500
    assert result.base_report.solutionCount == 3


def test_multiplier_relative_to_base_when_relative_to_omitted():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['java'],
            whenEmpty=LanguageGroupFallback(multiplier=3.0),
        ),
    ]
    measured = {
        0: GroupMeasurements(
            lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
        )
    }
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
    )
    result = resolve_groups(groups, measured, base, _eval)
    assert result.time_limit_per_language['java'] == int(result.base_time_limit * 3.0)


def test_increment_added_on_top_of_multiplier():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['java'],
            whenEmpty=LanguageGroupFallback(
                relativeTo='cpp', multiplier=2.0, increment=500
            ),
        ),
    ]
    measured = {
        0: GroupMeasurements(
            lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
        )
    }
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
    )
    result = resolve_groups(groups, measured, base, _eval)
    cpp_tl = result.time_limit_per_language['cpp']
    assert result.time_limit_per_language['java'] == int(cpp_tl * 2.0 + 500)

    report = next(r for r in result.reports if r.languages == ['java'])
    assert report.multiplier == 2.0
    assert report.increment == 500


def test_increment_relative_to_base_when_relative_to_omitted():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['java'],
            whenEmpty=LanguageGroupFallback(multiplier=1.0, increment=300),
        ),
    ]
    measured = {
        0: GroupMeasurements(
            lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
        )
    }
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
    )
    result = resolve_groups(groups, measured, base, _eval)
    # multiplier 1.0 against the base estimate, plus the increment.
    assert result.time_limit_per_language['java'] == int(
        result.base_time_limit * 1.0 + 300
    )


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
    measured = {
        0: GroupMeasurements(
            lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
        )
    }
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
    )
    result = resolve_groups(groups, measured, base, _eval)
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


def test_assignment_singleton_state_makes_singletons():
    groups = partition_from_assignment(
        assignment={'c': -1, 'cpp': -1, 'python': -1},
    )
    assert sorted(g.languages for g in groups) == [['c'], ['cpp'], ['python']]


def test_partition_from_assignment_three_states():
    # 1/2 = shared groups, -1 = singleton, 0 = unbucketed leftover pool
    groups = partition_from_assignment(
        assignment={
            'c': 1,
            'cpp': 1,
            'java': 2,
            'kotlin': 2,
            'python': -1,
            'go': 0,
            'rust': 0,
        },
    )
    langs = [g.languages for g in groups]
    assert ['c', 'cpp'] in langs
    assert ['java', 'kotlin'] in langs
    assert ['python'] in langs  # singleton -> own group
    assert ['go', 'rust'] in langs  # unbucketed -> ONE leftover pool
    # numbered groups first (sorted), then singletons, then the leftover pool
    assert langs[-1] == ['go', 'rust']


def test_partition_from_assignment_no_leftover_group_when_none_unbucketed():
    groups = partition_from_assignment(
        assignment={'cpp': 1, 'python': -1},
    )
    assert [g.languages for g in groups] == [['cpp'], ['python']]


def test_partition_applies_forced_relatives_by_group_key():
    groups = partition_from_assignment(
        {'cpp': 1, 'python': 2, 'go': 0, 'rust': -1},
        relatives={
            'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            's:rust': LanguageGroupFallback(relativeTo='cpp', multiplier=3.0),
            'leftover': LanguageGroupFallback(relativeTo='cpp', multiplier=4.0),
        },
    )
    by_lang = {g.languages[0]: g for g in groups}
    assert by_lang['python'].forced_relative.multiplier == 2.0
    assert by_lang['rust'].forced_relative.multiplier == 3.0
    assert by_lang['go'].forced_relative.multiplier == 4.0
    assert by_lang['cpp'].forced_relative is None


def test_partition_no_longer_derives_when_empty_from_env():
    # membership matches an env group, but partition_from_assignment must NOT
    # re-derive whenEmpty anymore (env-crossing dropped).
    groups = partition_from_assignment({'java': 1, 'kotlin': 1})
    assert groups[0].whenEmpty is None
    assert groups[0].forced_relative is None


def test_build_partition_marks_leftover():
    groups = build_partition(
        env_groups=[LanguageGroup(languages=['c', 'cpp'])],
        all_languages=['c', 'cpp', 'python', 'go'],
    )
    assert groups[0].is_leftover is False  # explicit env group
    assert groups[1].languages == ['python', 'go']
    assert groups[1].is_leftover is True  # the leftover pool


def test_partition_from_assignment_marks_leftover():
    groups = partition_from_assignment(
        assignment={'cpp': 1, 'python': -1, 'go': 0, 'rust': 0},
    )
    leftover = [g for g in groups if g.is_leftover]
    assert len(leftover) == 1
    assert leftover[0].languages == ['go', 'rust']
    non_leftover = [g for g in groups if not g.is_leftover]
    assert {tuple(g.languages) for g in non_leftover} == {('cpp',), ('python',)}


def test_resolve_propagates_is_leftover():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(languages=['go', 'java'], is_leftover=True),
    ]
    measured = {
        0: GroupMeasurements(
            lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
        )
    }
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=100, solution_count=1)
    )
    result = resolve_groups(groups, measured, base, _eval)
    by_leftover = {tuple(r.languages): r.isLeftover for r in result.reports}
    assert by_leftover[('cpp',)] is False
    assert by_leftover[('go', 'java')] is True


def _eval_slowest(measured: GroupMeasurements):
    # simple deterministic formula for tests: just the slowest
    assert measured.lower is not None
    return measured.lower.slowest


def test_forced_relative_wins_over_pooled_timings():
    # group 0 has solutions; group 1 forced relative to group 0
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['python'],
            forced_relative=LanguageGroupFallback(
                relativeTo='cpp', multiplier=2.0, increment=100
            ),
        ),
    ]
    measured = {
        0: GroupMeasurements(
            lower=GroupTimings(fastest=100, slowest=200, solution_count=1)
        ),
        1: GroupMeasurements(
            lower=GroupTimings(fastest=500, slowest=900, solution_count=1)
        ),
    }
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=900, solution_count=2)
    )
    result = resolve_groups(groups, measured, base, _eval_slowest)
    # group 1 ignores its own timings (would be 900) -> 2.0*200 + 100 = 500
    assert result.reports[1].timeLimit == 500
    assert result.reports[1].origin == TimingGroupOrigin.MULTIPLIER
    assert result.reports[1].relativeToLanguage == 'cpp'
    # solution count of the overridden group is preserved for display
    assert result.reports[1].solutionCount == 1


def test_forced_relative_validates_self_reference():
    groups = [
        ResolvedGroup(
            languages=['cpp'],
            forced_relative=LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
        )
    ]
    with pytest.raises(GroupValidationError):
        validate_partition(groups)


def test_forced_relative_to_base_estimate():
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['python'],
            forced_relative=LanguageGroupFallback(relativeTo=None, multiplier=3.0),
        ),
    ]
    measured = {
        0: GroupMeasurements(
            lower=GroupTimings(fastest=100, slowest=200, solution_count=1)
        )
    }
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=200, solution_count=1)
    )
    result = resolve_groups(groups, measured, base, _eval_slowest)
    # base_tl = _eval_slowest(base) = 200; forced -> 3.0*200 = 600
    assert result.reports[1].timeLimit == 600


class _RecordingDerive:
    """A derive_fn stub that records every (time_limit, measurements) it gets."""

    def __init__(self, returns: Optional[int] = None):
        self.calls: List[Tuple[int, GroupMeasurements]] = []
        self.returns = returns

    def __call__(self, tl: int, measured: GroupMeasurements) -> int:
        self.calls.append((tl, measured))
        return self.returns if self.returns is not None else tl


def _slow_only(fastest_slow: int) -> GroupMeasurements:
    """A group with slow solutions but no accepted ones."""
    return GroupMeasurements(
        upper=UpperTimings(
            fastest_slow=fastest_slow, fastest_slow_solution='sols/slow.py'
        )
    )


def test_when_empty_group_with_only_slow_solutions_is_upper_checked():
    # 'python' has a slow solution but no accepted one, so it has no lower
    # timings and derives its limit from 'cpp' -- its upper bound must still
    # reach derive_fn.
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['python'],
            whenEmpty=LanguageGroupFallback(relativeTo='cpp', multiplier=3.0),
        ),
    ]
    cpp = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=200, solution_count=1)
    )
    py = _slow_only(400)
    derive = _RecordingDerive()

    result = resolve_groups(groups, {0: cpp, 1: py}, cpp, _eval_slowest, derive)

    assert derive.calls == [(600, py)]  # 3.0 * cpp's 200
    assert result.reports[1].timeLimit == 600
    assert result.reports[1].origin == TimingGroupOrigin.MULTIPLIER


def test_forced_relative_group_with_only_slow_solutions_is_upper_checked():
    # Same as above through the user-configured forced-relative path.
    groups = [
        ResolvedGroup(languages=['cpp']),
        ResolvedGroup(
            languages=['python'],
            forced_relative=LanguageGroupFallback(relativeTo='cpp', multiplier=3.0),
        ),
    ]
    cpp = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=200, solution_count=1)
    )
    py = _slow_only(400)
    derive = _RecordingDerive(returns=500)

    result = resolve_groups(groups, {0: cpp, 1: py}, cpp, _eval_slowest, derive)

    assert derive.calls == [(600, py)]  # 3.0 * cpp's 200
    # a forced relative reports as MULTIPLIER, so derive_fn may move it
    assert result.reports[1].timeLimit == 500
    assert result.time_limit_per_language['python'] == 500


def test_defaulted_group_with_only_slow_solutions_is_upper_checked():
    # 'python' has neither accepted solutions nor a whenEmpty, so it inherits
    # the base limit -- its upper bound must still reach derive_fn.
    groups = [ResolvedGroup(languages=['cpp']), ResolvedGroup(languages=['python'])]
    cpp = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=200, solution_count=1)
    )
    py = _slow_only(400)
    derive = _RecordingDerive()

    result = resolve_groups(groups, {0: cpp, 1: py}, cpp, _eval_slowest, derive)

    assert derive.calls == [(200, py)]  # base_tl
    assert result.reports[1].origin == TimingGroupOrigin.DEFAULTED
    assert result.defaulted_languages == ['python']
    assert 'python' not in result.time_limit_per_language


def test_defaulted_group_ignores_the_derived_limit():
    # A DEFAULTED group states it fell back to the base limit, so derive_fn is
    # a check-only hook there: its return value must not move the group.
    groups = [ResolvedGroup(languages=['cpp']), ResolvedGroup(languages=['python'])]
    cpp = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=200, solution_count=1)
    )
    derive = _RecordingDerive(returns=999)

    result = resolve_groups(groups, {0: cpp}, cpp, _eval_slowest, derive)

    assert result.reports[1].timeLimit == result.base_time_limit == 200
    assert result.defaulted_languages == ['python']
    assert 'python' not in result.time_limit_per_language


def test_defaulted_group_propagates_derive_errors():
    groups = [ResolvedGroup(languages=['cpp']), ResolvedGroup(languages=['python'])]
    cpp = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=200, solution_count=1)
    )

    def _raising(tl: int, measured: GroupMeasurements) -> int:
        raise ValueError('slow solution would pass')

    with pytest.raises(ValueError, match='slow solution would pass'):
        resolve_groups(
            groups, {0: cpp, 1: _slow_only(150)}, cpp, _eval_slowest, _raising
        )


def test_estimated_groups_receive_their_own_measurements():
    recorded: List[GroupMeasurements] = []

    def _eval_recording(measured: GroupMeasurements) -> int:
        recorded.append(measured)
        assert measured.lower is not None
        return measured.lower.slowest

    groups = [ResolvedGroup(languages=['cpp']), ResolvedGroup(languages=['python'])]
    cpp = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=200, solution_count=1),
        upper=UpperTimings(fastest_slow=500),
    )
    py = GroupMeasurements(
        lower=GroupTimings(fastest=500, slowest=900, solution_count=1)
    )
    base = GroupMeasurements(
        lower=GroupTimings(fastest=100, slowest=900, solution_count=2),
        upper=UpperTimings(fastest_slow=500, dropped_upper=['sols/timeout.py']),
    )

    resolve_groups(groups, {0: cpp, 1: py}, base, _eval_recording)

    assert recorded == [base, cpp, py]
