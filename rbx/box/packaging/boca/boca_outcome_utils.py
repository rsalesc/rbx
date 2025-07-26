from rbx.box.schema import ExpectedOutcome


def simplify_rbx_expected_outcome(outcome: ExpectedOutcome) -> ExpectedOutcome:
    if outcome in [
        ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED,
        ExpectedOutcome.MEMORY_LIMIT_EXCEEDED,
    ]:
        return ExpectedOutcome.RUNTIME_ERROR
    return outcome
