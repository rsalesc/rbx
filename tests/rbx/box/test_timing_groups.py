from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.timing_groups import build_partition


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
