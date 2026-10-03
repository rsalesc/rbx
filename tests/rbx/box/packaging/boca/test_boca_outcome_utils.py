import pytest

from rbx.box.packaging.boca.boca_outcome_utils import simplify_rbx_expected_outcome
from rbx.box.schema import ExpectedOutcome


@pytest.mark.parametrize(
    'outcome,expected',
    [
        (ExpectedOutcome.MEMORY_LIMIT_EXCEEDED, ExpectedOutcome.RUNTIME_ERROR),
        (ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED, ExpectedOutcome.RUNTIME_ERROR),
        (ExpectedOutcome.MLE_OR_RTE, ExpectedOutcome.RUNTIME_ERROR),
        # BOCA has no memory-limit verdict, so the MLE half becomes RTE.
        (ExpectedOutcome.TLE_OR_MLE, ExpectedOutcome.TLE_OR_RTE),
        (ExpectedOutcome.TLE_OR_RTE, ExpectedOutcome.TLE_OR_RTE),
        (ExpectedOutcome.TIME_LIMIT_EXCEEDED, ExpectedOutcome.TIME_LIMIT_EXCEEDED),
        (ExpectedOutcome.ACCEPTED, ExpectedOutcome.ACCEPTED),
    ],
)
def test_simplify_rbx_expected_outcome(outcome, expected):
    assert simplify_rbx_expected_outcome(outcome) == expected
