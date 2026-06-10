from rbx.box.completion import completers


def test_outcome_table_matches_expected_outcome_enum():
    from rbx.box.schema import ExpectedOutcome

    tokens = [v for v, _ in completers._OUTCOME_TABLE]  # noqa: SLF001
    # Every offered token parses to a valid ExpectedOutcome...
    parsed = {ExpectedOutcome(t) for t in tokens}
    # ...and every enum member is represented exactly once.
    assert parsed == set(ExpectedOutcome)
    assert len(tokens) == len(set(tokens)) == len(set(ExpectedOutcome))
