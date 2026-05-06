import pytest

from rbx.box.contest import contest_state


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


def test_root_callback_sets_contextvar_from_flag():
    """Smoke: invoking the root callback with -C sets the contextvar."""
    from typer.testing import CliRunner

    from rbx.box import cli
    from rbx.box.contest.contest_state import selected_variant_id_var

    captured = {}

    @cli.app.command('probe-contest-rcv')
    def probe():
        captured['value'] = selected_variant_id_var.get()

    try:
        runner = CliRunner()
        result = runner.invoke(cli.app, ['-C', 'div1', 'probe-contest-rcv'])
        assert result.exit_code == 0, result.output
        assert captured['value'] == 'div1'
    finally:
        # Best-effort cleanup of the registered command. Typer doesn't expose a
        # public removal API, so leak is fine for a unit test.
        pass


def test_root_callback_rejects_invalid_id():
    from typer.testing import CliRunner

    from rbx.box import cli

    @cli.app.command('probe-contest-invalid')
    def probe():
        pass

    runner = CliRunner()
    result = runner.invoke(cli.app, ['-C', 'has space', 'probe-contest-invalid'])
    assert result.exit_code != 0
    assert 'Invalid contest id' in result.output


def test_contest_subapp_callback_sets_contextvar_from_flag():
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


def test_root_callback_resolves_from_env(monkeypatch: pytest.MonkeyPatch):
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
