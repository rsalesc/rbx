"""Tests for the ?-toggled help panel (rbx.box.ui.help_panel)."""

from textual.app import App, ComposeResult
from textual.widgets import HelpPanel, Input, OptionList

from rbx.box.ui.help_panel import HelpPanelMixin


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
