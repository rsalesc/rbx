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
        screen = TestExplorerScreen()
        await pilot.app.push_screen(screen)
        # TestExplorerScreen.on_mount calls find_problem_package_or_die(),
        # which raises typer.Exit outside a built package, so pilot.pause()
        # would hang on the unsettled mount. Poll until the screen is active
        # instead -- binding visibility is registered at mount, independent
        # of on_mount completing.
        for _ in range(100):
            if pilot.app.screen is screen:
                break
            await asyncio.sleep(0.005)
        assert pilot.app.screen is screen
        assert _footer_visible_keys(pilot.app) == {'question_mark', 'q'}


def test_run_test_explorer_feature_bindings_hidden():
    # Static inspection: these screens' on_mount loads run results from disk and
    # can't mount bare outside a built package, so we assert on BINDINGS directly.
    # (The app-level ?/q footer merge is covered by the test_explorer test above.)
    from textual.binding import Binding

    from rbx.box.ui.screens.run_test_explorer import RunTestExplorerScreen

    shown = {
        b.key
        for b in RunTestExplorerScreen.BINDINGS
        if isinstance(b, Binding) and b.show
    }
    tuple_keys = {b[0] for b in RunTestExplorerScreen.BINDINGS if isinstance(b, tuple)}
    # Only 'q' (a plain tuple) stays visible; all Binding() entries are hidden.
    assert shown == set()
    assert tuple_keys == {'q'}


def test_run_explorer_feature_bindings_hidden():
    # Same static-inspection rationale as above.
    from textual.binding import Binding

    from rbx.box.ui.screens.run_explorer import RunExplorerScreen

    shown = {
        b.key for b in RunExplorerScreen.BINDINGS if isinstance(b, Binding) and b.show
    }
    # 's' (compare) is hidden; no screen-level bindings stay visible.
    assert shown == set()
    assert RunExplorerScreen.BINDING_GROUP_TITLE == 'Run Explorer'
