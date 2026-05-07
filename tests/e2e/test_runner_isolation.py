"""Verifies the e2e runner restores mutated contextvars between scenarios."""

from rbx.box.contest import contest_state
from tests.e2e.runner import _snapshot_e2e_contextvars


def test_snapshot_restores_selected_variant_id_var():
    assert contest_state.selected_variant_id_var.get() is None
    with _snapshot_e2e_contextvars():
        contest_state.selected_variant_id_var.set('div1')
        assert contest_state.selected_variant_id_var.get() == 'div1'
    assert contest_state.selected_variant_id_var.get() is None


def test_snapshot_restores_prior_value():
    contest_state.selected_variant_id_var.set('outer')
    try:
        with _snapshot_e2e_contextvars():
            contest_state.selected_variant_id_var.set('inner')
        assert contest_state.selected_variant_id_var.get() == 'outer'
    finally:
        contest_state.selected_variant_id_var.set(None)
