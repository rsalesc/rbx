import pytest

from rbx.box.scoring.dependencies import (
    DependencyPolicy,
    FlatteningError,
    GroupDependencies,
    flatten,
    resolve_edges,
)

GROUPS = [('samples', []), ('small', []), ('medium', []), ('big', ['small'])]


def test_manual_keeps_only_the_declared_deps():
    assert resolve_edges(GROUPS, DependencyPolicy.MANUAL) == {
        'samples': [],
        'small': [],
        'medium': [],
        'big': ['small'],
    }


def test_samples_makes_every_group_depend_on_samples():
    assert resolve_edges(GROUPS, DependencyPolicy.SAMPLES) == {
        'samples': [],
        'small': ['samples'],
        'medium': ['samples'],
        'big': ['samples', 'small'],
    }


def test_samples_adds_nothing_without_a_samples_group():
    groups = [('small', []), ('big', [])]
    assert resolve_edges(groups, DependencyPolicy.SAMPLES) == {
        'small': [],
        'big': [],
    }


def test_ladder_chains_each_group_to_the_previous_one_starting_at_samples():
    assert resolve_edges(GROUPS, DependencyPolicy.LADDER) == {
        'samples': [],
        'small': ['samples'],
        'medium': ['small'],
        # The declared dep is kept beside the policy's.
        'big': ['medium', 'small'],
    }


def test_a_declared_dep_the_policy_already_adds_is_not_repeated():
    groups = [('samples', []), ('small', ['samples'])]
    assert resolve_edges(groups, DependencyPolicy.SAMPLES)['small'] == ['samples']


def _ladder() -> GroupDependencies:
    return GroupDependencies(resolve_edges(GROUPS, DependencyPolicy.LADDER))


def test_closure_is_transitive_and_in_declaration_order():
    deps = _ladder()
    assert deps.closure('big') == ['samples', 'small', 'medium']
    assert deps.closure('samples') == []


def test_dependents_is_the_reverse_closure():
    deps = _ladder()
    assert deps.dependents('samples') == ['small', 'medium', 'big']
    assert deps.dependents('big') == []


def test_closure_of_a_diamond_lists_each_group_once():
    deps = GroupDependencies(
        {'a': [], 'b': ['a'], 'c': ['a'], 'd': ['b', 'c']},
    )
    assert deps.closure('d') == ['a', 'b', 'c']


def test_over_keeps_what_a_dropped_group_chained_together():
    # `medium` built no tests: `big` must still depend on `small` and `samples`.
    deps = _ladder().over(['samples', 'small', 'big'])
    assert deps.direct('big') == ['samples', 'small']
    assert deps.direct('medium') == []
    assert deps.dependents('samples') == ['small', 'big']


def test_flatten_appends_the_tests_of_every_dependency():
    flattened = flatten(
        _ladder(),
        {'samples': ['s1'], 'small': ['a1', 'a2'], 'big': ['b1']},
    )
    assert flattened == {
        'samples': ['s1'],
        'small': ['a1', 'a2', 's1'],
        # `medium` has no tests, so it contributes nothing and is left out.
        'big': ['b1', 's1', 'a1', 'a2'],
    }


def test_flatten_refuses_an_aggregation_duplication_cannot_reproduce():
    with pytest.raises(FlatteningError):
        flatten(_ladder(), {'samples': ['s1']}, aggregation='sum')  # type: ignore
