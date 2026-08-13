import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.schema import ExpectedOutcome, InferenceRole, Solution


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
