from rbx.box.packaging.cms import scoring
from rbx.box.schema import PointsScoring, ScoreType, TestcaseGroup
from rbx.box.scoring.dependencies import DependencyPolicy
from tests.rbx.box.packaging.cms._entries import build_entries


def test_group_min_follows_transitive_deps(testing_pkg, tmp_path):
    testing_pkg.yml.scoring = ScoreType.POINTS
    testing_pkg.yml.testcases = [
        TestcaseGroup(name='samples'),
        TestcaseGroup(name='small', score=20),
        TestcaseGroup(name='medium', score=30, deps=['small']),
        # Transitive: `big` needs `medium`, which needs `small`.
        TestcaseGroup(name='big', score=50, deps=['medium']),
        # No built tests: left out.
        TestcaseGroup(name='empty', score=0),
    ]
    testing_pkg.save()
    entries = build_entries(
        tmp_path, ['samples', 'small', 'small', 'medium', 'big', 'big']
    )

    # CMS names tests by their 0-based index.
    assert scoring.group_min_parameters(testing_pkg.yml, entries) == [
        [0, '^(000)$'],
        [20, '^(001|002)$'],
        [30, '^(003|001|002)$'],
        [50, '^(004|005|001|002|003)$'],
    ]


def test_group_min_follows_the_ladder_across_an_empty_group(testing_pkg, tmp_path):
    testing_pkg.yml.scoring = PointsScoring(dependencies=DependencyPolicy.LADDER)
    testing_pkg.yml.testcases = [
        TestcaseGroup(name='samples'),
        TestcaseGroup(name='small', score=20),
        # Built no tests: `big` must still chain down to `small` and `samples`.
        TestcaseGroup(name='medium', score=30),
        TestcaseGroup(name='big', score=50),
    ]
    testing_pkg.save()
    entries = build_entries(tmp_path, ['samples', 'small', 'big'])

    assert scoring.group_min_parameters(testing_pkg.yml, entries) == [
        [0, '^(000)$'],
        [20, '^(001|000)$'],
        [50, '^(002|000|001)$'],
    ]


def test_binary_problems_are_all_or_nothing(testing_pkg, tmp_path):
    entries = build_entries(tmp_path, ['main', 'main'])

    assert scoring.group_min_parameters(testing_pkg.yml, entries) == [[100, '.*']]


def test_sum_groups_are_one_subtask_per_test(testing_pkg, tmp_path):
    testing_pkg.yml.scoring = ScoreType.POINTS
    testing_pkg.yml.testcases = [
        TestcaseGroup(name='samples'),
        TestcaseGroup(name='small', score=40),
        # 10 points over 3 tests, each capped by `small`'s tests.
        TestcaseGroup(name='big', score=10, deps=['small'], aggregation='sum'),
    ]
    testing_pkg.save()
    entries = build_entries(tmp_path, ['samples', 'small', 'big', 'big', 'big'])

    assert scoring.group_min_parameters(testing_pkg.yml, entries) == [
        [0, '^(000)$'],
        [40, '^(001)$'],
        [3.33, '^(002|001)$'],
        [3.33, '^(003|001)$'],
        [3.34, '^(004|001)$'],
    ]
