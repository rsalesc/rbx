from rbx.box.packaging.cms import scoring
from rbx.box.schema import ScoreType, TestcaseGroup
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
        [50, '^(004|005|003|001|002)$'],
    ]


def test_binary_problems_are_all_or_nothing(testing_pkg, tmp_path):
    entries = build_entries(tmp_path, ['main', 'main'])

    assert scoring.group_min_parameters(testing_pkg.yml, entries) == [[100, '.*']]
