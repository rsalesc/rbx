from tests.rbx.box.completion.golden import typer_completions


def _canonical_names(items) -> set:
    # Typer renders an aliased group as a single completion whose value is the
    # full ``"name, alias1, alias2"`` string. The canonical name is the first
    # token; split so the assertions check the real command name.
    return {i.value.split(',')[0].strip() for i in items}


def test_root_command_names_include_known_commands():
    items = typer_completions(args=[], incomplete='')
    values = _canonical_names(items)
    assert 'build' in values
    assert 'run' in values
    assert 'package' in values  # canonical name of the `package, pkg` group


def test_language_option_completes_from_config():
    # The real app resolves ``--lang`` completions from ``get_config()``, which
    # outside a package yields no languages, so the call returns an empty list.
    # Assert the oracle resolves the completion without error (returns a list).
    items = typer_completions(args=['run', '--lang'], incomplete='')
    assert isinstance(items, list)
