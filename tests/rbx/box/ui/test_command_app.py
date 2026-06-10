"""Tests for the rbx on / rbx each command app (rbx.box.ui.command_app)."""

import pytest
from textual.widgets import Label, ListItem

from rbx.box import setter_config
from rbx.box.setter_config import ProblemLabelMode
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp


@pytest.fixture(autouse=True)
def _reset_label_mode():
    # `mock_app_path` is session-scoped, so the persisted setter config is shared
    # across tests; pin it to the default before each test for isolation.
    cfg = setter_config.get_setter_config()
    cfg.ui.problem_label = ProblemLabelMode.NAME
    setter_config.save_setter_config(cfg)
    yield


def _labeled_entry() -> CommandEntry:
    return CommandEntry(
        # Empty argv => no sub-command is enqueued, so no subprocess is spawned.
        argv=[],
        name='A. two-sum',
        labels={
            ProblemLabelMode.NAME: 'A. two-sum',
            ProblemLabelMode.TITLE: 'A. Two Sum',
            ProblemLabelMode.PATH: 'A. probs/a',
        },
    )


def _sidebar_text(app, index: int) -> str:
    label = app.query_one(f'#cmd-item-{index}', ListItem).query_one(Label)
    return str(label.render())


def _persisted_mode() -> ProblemLabelMode:
    return setter_config.get_setter_config().ui.problem_label


async def test_sidebar_uses_configured_label_mode():
    app = rbxCommandApp([_labeled_entry()])
    async with app.run_test() as pilot:
        await pilot.pause()
        # Default mode is `name`.
        assert 'A. two-sum' in _sidebar_text(app, 0)


async def test_l_cycles_and_persists_problem_label():
    app = rbxCommandApp([_labeled_entry()])
    async with app.run_test() as pilot:
        # shift+tab deterministically focuses the sidebar (public key path).
        await pilot.press('shift+tab')
        await pilot.pause()

        await pilot.press('l')
        await pilot.pause()
        assert _persisted_mode() is ProblemLabelMode.TITLE
        assert 'A. Two Sum' in _sidebar_text(app, 0)

        await pilot.press('l')
        await pilot.pause()
        assert _persisted_mode() is ProblemLabelMode.PATH
        assert 'A. probs/a' in _sidebar_text(app, 0)

        # Wraps back to name.
        await pilot.press('l')
        await pilot.pause()
        assert _persisted_mode() is ProblemLabelMode.NAME
        assert 'A. two-sum' in _sidebar_text(app, 0)


async def test_l_is_inert_without_labels():
    app = rbxCommandApp([CommandEntry(argv=[], name='echo')])
    async with app.run_test() as pilot:
        await pilot.press('shift+tab')
        await pilot.pause()

        await pilot.press('l')
        await pilot.pause()
        # No labels => the key falls through; the persisted config is unchanged.
        assert _persisted_mode() is ProblemLabelMode.NAME
