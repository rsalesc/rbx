"""Tests for the ?-toggled help panel (rbx.box.ui.help_panel)."""

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import HelpPanel, Input, OptionList

from rbx.box.ui.help_panel import HelpPanelMixin


def _footer_visible_keys(app) -> set[str]:
    """Keys whose bindings are marked show=True on the active screen."""
    return {
        active.binding.key
        for active in app.screen.active_bindings.values()
        if active.binding.show
    }


class _PanelApp(HelpPanelMixin, App):
    def compose(self) -> ComposeResult:
        yield OptionList('a', 'b', 'c')

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()


async def test_question_mark_toggles_help_panel():
    app = _PanelApp()
    async with app.run_test() as pilot:
        assert not app.screen.query(HelpPanel)

        await pilot.press('question_mark')
        assert app.screen.query(HelpPanel)

        await pilot.press('question_mark')
        await pilot.pause()
        assert not app.screen.query(HelpPanel)


class _InputApp(HelpPanelMixin, App):
    def compose(self) -> ComposeResult:
        yield Input()

    def on_mount(self) -> None:
        self.query_one(Input).focus()


async def test_question_mark_types_into_focused_input():
    app = _InputApp()
    async with app.run_test() as pilot:
        await pilot.press('question_mark')
        assert app.query_one(Input).value == '?'
        assert not app.screen.query(HelpPanel)


async def test_real_rbx_app_toggles_help_panel():
    from rbx.box.ui.main import rbxApp

    async with rbxApp().run_test() as pilot:
        assert not pilot.app.screen.query(HelpPanel)

        await pilot.press('question_mark')
        assert pilot.app.screen.query(HelpPanel)


async def test_test_explorer_footer_shows_only_help_and_quit():
    from rbx.box.ui.main import rbxApp
    from rbx.box.ui.screens.test_explorer import TestExplorerScreen

    async with rbxApp().run_test() as pilot:
        await pilot.app.push_screen(TestExplorerScreen())
        # The screen's on_mount needs a built problem package; outside one it
        # exits early, so we let the binding registration tick through instead
        # of pilot.pause() (which would wait on the unsettled mount). The footer
        # binding visibility we assert on is independent of on_mount completing.
        await asyncio.sleep(0.05)
        assert _footer_visible_keys(pilot.app) == {'question_mark', 'q'}
