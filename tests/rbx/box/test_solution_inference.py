import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.schema import ExpectedOutcome, InferenceRole, Solution
from rbx.box.solutions import inference_role_of


def _solution(**kwargs) -> Solution:
    return Solution(path=pathlib.Path('sols/a.cpp'), **kwargs)


def test_inference_defaults_to_unset():
    assert _solution().inference is None


def test_inference_accepts_false_and_roles():
    assert _solution(inference=False).inference is False
    assert _solution(inference='lower').inference == InferenceRole.LOWER
    assert _solution(inference='upper').inference == InferenceRole.UPPER


def test_inference_rejects_true():
    with pytest.raises(ValidationError):
        _solution(inference=True)


def test_lower_role_rejects_a_slow_solution():
    with pytest.raises(ValidationError, match='lower'):
        _solution(outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED, inference='lower')


def test_lower_role_rejects_a_per_group_slow_solution():
    with pytest.raises(ValidationError, match='lower'):
        _solution(
            outcome=ExpectedOutcome.ACCEPTED,
            outcomePerGroup={'g1': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
            inference='lower',
        )


def test_default_roles_follow_the_expected_outcome():
    assert inference_role_of(_solution(outcome=ExpectedOutcome.ACCEPTED)) == (
        InferenceRole.LOWER
    )
    assert (
        inference_role_of(_solution(outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED))
        == InferenceRole.UPPER
    )
    assert inference_role_of(_solution(outcome=ExpectedOutcome.TLE_OR_RTE)) == (
        InferenceRole.UPPER
    )
    assert inference_role_of(_solution(outcome=ExpectedOutcome.ACCEPTED_OR_TLE)) is None
    assert inference_role_of(_solution(outcome=ExpectedOutcome.WRONG_ANSWER)) is None


def test_a_per_group_slow_expectation_bounds_from_above():
    assert (
        inference_role_of(
            _solution(
                outcome=ExpectedOutcome.ACCEPTED,
                outcomePerGroup={'g1': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
            )
        )
        == InferenceRole.UPPER
    )


def test_explicit_roles_win():
    assert (
        inference_role_of(_solution(outcome=ExpectedOutcome.ACCEPTED, inference=False))
        is None
    )
    assert (
        inference_role_of(
            _solution(outcome=ExpectedOutcome.ACCEPTED_OR_TLE, inference='upper')
        )
        == InferenceRole.UPPER
    )
