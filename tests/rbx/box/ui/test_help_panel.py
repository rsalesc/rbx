"""Tests for the ?-toggled help panel (rbx.box.ui.help_panel)."""

from unittest import mock

from textual.app import App, ComposeResult
from textual.widgets import HelpPanel, Input, OptionList

from rbx.box.schema import TaskType
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
        await pilot.pause()
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


def _mounted_test_explorer():
    """Push a TestExplorerScreen whose on_mount completes without a package.

    ``TestExplorerScreen.on_mount`` calls ``find_problem_package_or_die()``
    (via ``_is_interactive`` and ``action_show_output``) and then
    ``extract_generation_testcases_from_groups()``. Outside a built package
    those raise/hang, so we mock both: the package mock reports a non-COMMUNICATION
    type (so ``_is_interactive()`` is False) and the extractor yields no testcases.
    """
    from rbx.box.ui.screens import test_explorer

    pkg = mock.Mock()
    pkg.type = TaskType.BATCH

    package_patch = mock.patch.object(
        test_explorer.package,
        'find_problem_package_or_die',
        return_value=pkg,
    )

    async def _no_testcases():
        return []

    extractor_patch = mock.patch.object(
        test_explorer,
        'extract_generation_testcases_from_groups',
        side_effect=_no_testcases,
    )
    return test_explorer.TestExplorerScreen, package_patch, extractor_patch


async def test_test_explorer_footer_shows_only_help_and_quit():
    from rbx.box.ui.main import rbxApp

    Screen, package_patch, extractor_patch = _mounted_test_explorer()

    with package_patch, extractor_patch:
        async with rbxApp().run_test() as pilot:
            screen = Screen()
            await pilot.app.push_screen(screen)
            # on_mount now completes cleanly under the mocks, so a plain pause
            # is enough to let the screen settle.
            await pilot.pause()
            assert pilot.app.screen is screen
            assert _footer_visible_keys(pilot.app) == {'question_mark', 'q'}


async def test_test_explorer_hidden_feature_keys_reach_panel_not_footer():
    """Behavioral: show=False feature keys stay in active_bindings (so the panel
    lists them) while being absent from the footer-visible subset.

    This proves the "footer slim, panel complete" contract -- the thing the
    static config-inspection tests below cannot verify.
    """
    from rbx.box.ui.main import rbxApp

    Screen, package_patch, extractor_patch = _mounted_test_explorer()
    feature_keys = {'m', '1', '2', '3', 'v'}

    with package_patch, extractor_patch:
        async with rbxApp().run_test() as pilot:
            screen = Screen()
            await pilot.app.push_screen(screen)
            await pilot.pause()
            assert pilot.app.screen is screen

            active_keys = {
                active.binding.key
                for active in pilot.app.screen.active_bindings.values()
            }
            # The panel renders active_bindings, so the hidden feature keys are
            # listed there ...
            assert feature_keys <= active_keys
            # ... but never in the slim footer subset.
            assert feature_keys.isdisjoint(_footer_visible_keys(pilot.app))


def test_run_test_explorer_feature_bindings_hidden():
    # Configuration guard, NOT a behavioral test: it only asserts that show=False
    # is set on the BINDINGS. These screens' on_mount loads run results from disk
    # and can't mount bare outside a built package, so the real "footer slim,
    # panel complete" behavior is covered by
    # test_test_explorer_hidden_feature_keys_reach_panel_not_footer above.
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
    # Configuration guard (asserts show=False on BINDINGS), not behavioral; same
    # rationale as test_run_test_explorer_feature_bindings_hidden above.
    from textual.binding import Binding

    from rbx.box.ui.screens.run_explorer import RunExplorerScreen

    shown = {
        b.key for b in RunExplorerScreen.BINDINGS if isinstance(b, Binding) and b.show
    }
    # 's' (compare) is hidden; no screen-level bindings stay visible.
    assert shown == set()
    assert RunExplorerScreen.BINDING_GROUP_TITLE == 'Run Explorer'


def test_limits_editor_feature_bindings_hidden():
    # Configuration guard (asserts show=False on BINDINGS), not behavioral; the
    # screen's on_mount loads from disk and can't mount bare. See
    # test_test_explorer_hidden_feature_keys_reach_panel_not_footer for the
    # behavioral coverage.
    from textual.binding import Binding

    from rbx.box.ui.screens.limits_editor import LimitsEditorScreen

    # Only 'q' stays visible; save/delete move to the panel.
    shown = {
        b.key for b in LimitsEditorScreen.BINDINGS if isinstance(b, Binding) and b.show
    }
    assert shown == {'q'}


def test_primary_screens_have_group_titles():
    from rbx.box.ui.screens.command import CommandScreen
    from rbx.box.ui.screens.differ import DifferScreen
    from rbx.box.ui.screens.run import RunScreen, SolutionReportScreen

    assert CommandScreen.BINDING_GROUP_TITLE == 'Command'
    assert DifferScreen.BINDING_GROUP_TITLE == 'Diff'
    assert RunScreen.BINDING_GROUP_TITLE == 'Run'
    assert SolutionReportScreen.BINDING_GROUP_TITLE == 'Solution Report'
