import pytest

from rbx.box.scoring import partial
from rbx.box.scoring.dependencies import Aggregation

MIN = Aggregation.MIN
SUM = Aggregation.SUM


@pytest.mark.parametrize(
    'score,n,expected',
    [
        (10, 3, [3.33, 3.33, 3.34]),
        (33, 1, [33.0]),
        (60, 4, [15.0, 15.0, 15.0, 15.0]),
        (0, 2, [0.0, 0.0]),
        (10, 0, []),
    ],
)
def test_test_points_splits_evenly_and_sums_exactly(score, n, expected):
    points = partial.test_points(score, n)
    assert points == expected
    if n:
        assert round(sum(points), 2) == score


@pytest.mark.parametrize(
    'score,n,expected',
    [
        # Rounding each share to the cent would leave -0.45 for the last test.
        (7, 150, [0.04] * 50 + [0.05] * 100),
        # ... and -0.03 here.
        (10, 60, [0.16] * 20 + [0.17] * 40),
        (1, 300, [0.0] * 200 + [0.01] * 100),
    ],
)
def test_test_points_never_goes_negative(score, n, expected):
    assert partial.test_points(score, n) == expected


@pytest.mark.parametrize('score', [0, 1, 7, 10, 30, 100])
def test_test_points_shares_are_even_non_negative_and_exact(score):
    for n in range(1, 401):
        points = partial.test_points(score, n)
        assert len(points) == n
        assert all(p >= 0 for p in points)
        assert all(round(p, 2) == p for p in points)
        assert round(sum(points), 2) == score
        assert round(max(points) - min(points), 2) <= 0.01
        assert points == sorted(points)


def test_a_sum_group_never_pays_more_than_its_score():
    # WA only on the last test of a 150-test, 7-point group.
    assert _scores([('g', 7, SUM)], {'g': [1.0] * 149 + [0.0]}) == {'g': 6.95}


def _scores(groups, fractions, deps=None):
    deps = deps or {}

    def closure(name):
        seen = []
        stack = list(deps.get(name, []))
        while stack:
            dep = stack.pop()
            if dep not in seen:
                seen.append(dep)
                stack.extend(deps.get(dep, []))
        return seen

    return partial.group_scores(
        [partial.GroupSpec(name, score, agg) for name, score, agg in groups],
        fractions,
        closure,
    )


def test_binary_results_are_all_or_nothing():
    groups = [('a', 40, MIN), ('b', 60, MIN), ('c', 10, MIN)]
    fractions = {'a': [1.0, 1.0], 'b': [1.0, 0.0], 'c': [1.0]}
    assert _scores(groups, fractions, {'c': ['b']}) == {'a': 40, 'b': 0, 'c': 0}


def test_min_pays_the_lowest_test():
    # arvore4's group 6 on Polygon, complete-group with percent mode.
    assert _scores([('g', 33, MIN)], {'g': [1.0, 0.7405624, 0.8288]}) == {'g': 24.44}


def test_sum_pays_each_test_its_share():
    assert _scores([('g', 10, SUM)], {'g': [1.0, 0.4]}) == {'g': 7.0}


def test_polygon_probe():
    # Measured on Polygon (problem 614666, invocation 2637352) with percent mode.
    groups = [
        ('g1', 10, MIN),
        ('g2', 10, MIN),
        ('g3', 10, SUM),
        ('g4', 10, MIN),
        ('g5', 10, MIN),
        ('g6', 10, SUM),
        ('g7', 10, MIN),
        ('g8', 10, MIN),
        ('g9', 10, MIN),
        ('g10', 10, SUM),
    ]
    fractions = {
        'g1': [0.5, 1.0],
        'g2': [1.0, 1.0],
        'g3': [1.0, 0.8],
        'g4': [1.0, 0.0],
        'g5': [1.0],
        'g6': [1.0, 0.4],
        'g7': [1.0],
        'g8': [0.0],
        'g9': [1.0],
        'g10': [1.0, 1.0],
    }
    deps = {
        'g2': ['g1'],
        'g3': ['g1'],
        'g5': ['g4'],
        'g7': ['g6'],
        'g9': ['g8'],
        'g10': ['g8'],
    }
    assert _scores(groups, fractions, deps) == {
        'g1': 5,
        'g2': 5,
        'g3': 5,
        'g4': 0,
        'g5': 0,
        'g6': 7,
        'g7': 4,
        'g8': 0,
        'g9': 0,
        'g10': 0,
    }


def test_transitive_dependency_caps():
    groups = [('a', 10, MIN), ('b', 10, MIN), ('c', 10, SUM)]
    fractions = {'a': [0.3], 'b': [1.0], 'c': [1.0, 1.0]}
    assert _scores(groups, fractions, {'b': ['a'], 'c': ['b']}) == {
        'a': 3,
        'b': 3,
        'c': 3,
    }


def test_group_without_tests_scores_nothing():
    assert _scores([('g', 10, MIN)], {'g': []}) == {'g': 0}


def test_dependency_without_tests_does_not_cap():
    assert _scores([('a', 10, MIN), ('b', 10, MIN)], {'b': [1.0]}, {'b': ['a']}) == {
        'a': 0,
        'b': 10,
    }
