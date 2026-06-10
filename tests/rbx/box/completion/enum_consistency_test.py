from rbx.box.completion import completers


def test_outcome_table_matches_expected_outcome_enum():
    from rbx.box.schema import ExpectedOutcome

    tokens = [v for v, _ in completers._OUTCOME_TABLE]  # noqa: SLF001
    # Every offered token parses to a valid ExpectedOutcome...
    parsed = {ExpectedOutcome(t) for t in tokens}
    # ...and every enum member is represented exactly once.
    assert parsed == set(ExpectedOutcome)
    assert len(tokens) == len(set(tokens)) == len(set(ExpectedOutcome))


def test_verification_table_matches_verification_level_enum():
    from rbx.box.environment import VerificationLevel

    table = dict(completers._VERIFICATION_TABLE)  # noqa: SLF001
    expected = {str(level.value): level.name for level in VerificationLevel}
    assert table == expected


def test_solution_prefixes_cover_registered_expanders():
    # If an expander is added/removed in remote.py, this fails so _SOLUTION_PREFIXES
    # (the @-prefixes the solutions completer offers) gets revisited.
    from rbx.box.remote import REGISTERED_EXPANDERS

    expander_names = {type(e).__name__ for e in REGISTERED_EXPANDERS}
    assert expander_names == {'MainExpander', 'BocaExpander'}

    prefixes = {p for p, _ in completers._SOLUTION_PREFIXES}  # noqa: SLF001
    assert prefixes == {'@main', '@boca/'}
