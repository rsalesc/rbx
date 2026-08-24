import pytest

from rbx.box.contest import contest_state


@pytest.fixture
def unregister_probe_commands():
    """Take probe commands back off the real Typer apps after the test.

    These tests exercise the root callbacks, so they have to hang a throwaway
    command off the genuine `cli.app` / contest `app` rather than a copy. Typer
    exposes no removal API, but `registered_commands` is a plain list, so
    restoring the snapshot un-registers whatever the decorator appended.

    Leaving them registered leaks the probes into every later consumer of the
    app in the same process. The completion drift test is the one that notices:
    it serializes the live CLI and compares it against the committed spec, so a
    leaked `probe-contest-*` shows up as spurious drift whenever these tests
    happen to run first.
    """
    from rbx.box import cli
    from rbx.box.contest import main as contest_main

    snapshots = [
        (app, list(app.registered_commands)) for app in (cli.app, contest_main.app)
    ]
    yield
    for app, commands in snapshots:
        app.registered_commands[:] = commands


def test_variant_id_pattern_accepts_typical_ids():
    assert contest_state.is_valid_variant_id('div1')
    assert contest_state.is_valid_variant_id('warmup')
    assert contest_state.is_valid_variant_id('A1')
    assert contest_state.is_valid_variant_id('ioi-2024_main')


def test_variant_id_pattern_rejects_invalid():
    assert not contest_state.is_valid_variant_id('')
    assert not contest_state.is_valid_variant_id('1div')
    assert not contest_state.is_valid_variant_id('div 1')
    assert not contest_state.is_valid_variant_id('div.1')


def test_selection_default_is_none():
    assert contest_state.get_selected_variant_id() is None


def test_set_selected_variant_id_round_trip():
    token = contest_state.selected_variant_id_var.set('div1')
    try:
        assert contest_state.get_selected_variant_id() == 'div1'
    finally:
        contest_state.selected_variant_id_var.reset(token)
    assert contest_state.get_selected_variant_id() is None


def test_resolve_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('RBX_CONTEST', 'envdiv')
    assert contest_state.resolve_explicit_selection() == 'envdiv'


def test_resolve_prefers_var_over_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('RBX_CONTEST', 'envdiv')
    token = contest_state.selected_variant_id_var.set('flagdiv')
    try:
        assert contest_state.resolve_explicit_selection() == 'flagdiv'
    finally:
        contest_state.selected_variant_id_var.reset(token)


def test_apply_cli_selection_sets_var():
    contest_state.apply_cli_selection('div1')
    assert contest_state.get_selected_variant_id() == 'div1'


def test_apply_cli_selection_rejects_invalid(capsys):
    import typer

    with pytest.raises(typer.Exit):
        contest_state.apply_cli_selection('bad id')
    out = capsys.readouterr().out
    assert 'Invalid contest id' in out


def test_apply_cli_selection_noop_on_none():
    contest_state.apply_cli_selection(None)
    assert contest_state.get_selected_variant_id() is None


def test_root_callback_sets_contextvar_from_flag(unregister_probe_commands):
    """Smoke: invoking the root callback with -C sets the contextvar."""
    from typer.testing import CliRunner

    from rbx.box import cli
    from rbx.box.contest.contest_state import selected_variant_id_var

    captured = {}

    @cli.app.command('probe-contest-rcv')
    def probe():
        captured['value'] = selected_variant_id_var.get()

    runner = CliRunner()
    result = runner.invoke(cli.app, ['-C', 'div1', 'probe-contest-rcv'])
    assert result.exit_code == 0, result.output
    assert captured['value'] == 'div1'


def test_root_callback_rejects_invalid_id(unregister_probe_commands):
    from typer.testing import CliRunner

    from rbx.box import cli

    @cli.app.command('probe-contest-invalid')
    def probe():
        pass

    runner = CliRunner()
    result = runner.invoke(cli.app, ['-C', 'has space', 'probe-contest-invalid'])
    assert result.exit_code != 0
    assert 'Invalid contest id' in result.output


def test_contest_subapp_callback_sets_contextvar_from_flag(unregister_probe_commands):
    from typer.testing import CliRunner

    from rbx.box.contest import main as contest_main
    from rbx.box.contest.contest_state import selected_variant_id_var

    captured = {}

    @contest_main.app.command('probe-contest-cv')
    def probe():
        captured['value'] = selected_variant_id_var.get()

    runner = CliRunner()
    result = runner.invoke(contest_main.app, ['-C', 'div2', 'probe-contest-cv'])
    assert result.exit_code == 0, result.output
    assert captured['value'] == 'div2'


def test_root_callback_resolves_from_env(
    monkeypatch: pytest.MonkeyPatch, unregister_probe_commands
):
    """RBX_CONTEST env var alone (no -C flag) populates the contextvar."""
    from typer.testing import CliRunner

    from rbx.box import cli
    from rbx.box.contest.contest_state import selected_variant_id_var

    monkeypatch.setenv('RBX_CONTEST', 'envdiv')

    captured = {}

    @cli.app.command('probe-contest-env')
    def probe():
        captured['value'] = selected_variant_id_var.get()

    runner = CliRunner()
    result = runner.invoke(cli.app, ['probe-contest-env'])
    assert result.exit_code == 0, result.output
    assert captured['value'] == 'envdiv'
