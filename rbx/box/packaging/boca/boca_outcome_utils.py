from rbx.box.schema import ExpectedOutcome


def simplify_rbx_expected_outcome(outcome: ExpectedOutcome) -> ExpectedOutcome:
    if outcome in [
        ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED,
        ExpectedOutcome.MEMORY_LIMIT_EXCEEDED,
        ExpectedOutcome.MLE_OR_RTE,
    ]:
        return ExpectedOutcome.RUNTIME_ERROR
    if outcome == ExpectedOutcome.TLE_OR_MLE:
        return ExpectedOutcome.TLE_OR_RTE
    return outcome
