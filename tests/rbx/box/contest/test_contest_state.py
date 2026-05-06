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
