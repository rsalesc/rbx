"""Tests for the ErrorModal and rbxBaseApp.show_error helper (issue #380).

Visualizer actions used to surface RbxExceptions as transient, plain-text toast
notifications (``notify(e.plain(), severity='error')``), which truncated and
auto-dismissed long compiler/runtime output. They now open a dismissible,
scrollable ErrorModal that preserves the formatted message.
"""

from unittest import mock

from textual.widgets import Label, RichLog

from rbx.box.exception import RbxException
from rbx.box.ui.main import rbxApp
from rbx.box.ui.screens.error_modal import ErrorModal


def _exc(text: str) -> RbxException:
    """Build an RbxException carrying ``text`` as captured console output."""
    exc = RbxException()
    exc.print(text)
    return exc


async def test_error_modal_shows_close_hint():
    async with rbxApp().run_test() as pilot:
        app = pilot.app
        app.show_error(_exc('boom'))
        await pilot.pause()

        assert isinstance(app.screen, ErrorModal)
        hint = str(app.screen.query_one('#error-hints', Label).content).lower()
        # The user is told how to dismiss the modal.
        assert 'close' in hint
        assert 'q' in hint and 'esc' in hint


def _rich_log_text(modal: ErrorModal) -> str:
    rich_log = modal.query_one(RichLog)
    return '\n'.join(strip.text for strip in rich_log.lines)


async def test_show_error_opens_error_modal_with_message():
    async with rbxApp().run_test() as pilot:
        app = pilot.app
        assert not isinstance(app.screen, ErrorModal)

        app.show_error(_exc('visualizer failed to compile'))
        await pilot.pause()

        assert isinstance(app.screen, ErrorModal)
        assert 'visualizer failed to compile' in _rich_log_text(app.screen)


async def test_error_modal_dismissed_with_q():
    async with rbxApp().run_test() as pilot:
        app = pilot.app
        app.show_error(_exc('boom'))
        await pilot.pause()
        assert isinstance(app.screen, ErrorModal)

        await pilot.press('q')
        await pilot.pause()
        assert not isinstance(app.screen, ErrorModal)


async def test_error_modal_dismissed_with_escape():
    async with rbxApp().run_test() as pilot:
        app = pilot.app
        app.show_error(_exc('boom'))
        await pilot.pause()
        assert isinstance(app.screen, ErrorModal)

        await pilot.press('escape')
        await pilot.pause()
        assert not isinstance(app.screen, ErrorModal)


async def test_show_error_falls_back_when_message_empty():
    async with rbxApp().run_test() as pilot:
        app = pilot.app

        app.show_error(RbxException())  # no captured output
        await pilot.pause()

        assert isinstance(app.screen, ErrorModal)
        assert _rich_log_text(app.screen).strip()  # not blank


async def test_visualizer_error_routes_to_error_modal():
    """The real visualizer action surfaces an RbxException via the modal.

    Mounts the TestExplorerScreen (mocking package discovery and testcase
    extraction, mirroring the help-panel tests), points the input FileLog at a
    dummy path, and makes the visualizer raise. The except-block must open an
    ErrorModal rather than a toast notification.
    """
    import pathlib

    from rbx.box.schema import TaskType
    from rbx.box.ui.screens import test_explorer
    from rbx.box.ui.widgets.file_log import FileLog

    pkg = mock.Mock()
    pkg.type = TaskType.BATCH

    async def _no_testcases():
        return []

    async def _raise(*args, **kwargs):
        exc = RbxException()
        exc.print('visualizer crashed at runtime')
        raise exc

    with (
        mock.patch.object(
            test_explorer.package,
            'find_problem_package_or_die',
            return_value=pkg,
        ),
        mock.patch.object(
            test_explorer,
            'extract_generation_testcases_from_groups',
            side_effect=_no_testcases,
        ),
        mock.patch.object(
            test_explorer.visualizers,
            'run_ui_input_visualizer_for_testcase',
            side_effect=_raise,
        ),
    ):
        async with rbxApp().run_test() as pilot:
            screen = test_explorer.TestExplorerScreen()
            await pilot.app.push_screen(screen)
            await pilot.pause()

            screen.query_one('#test-input', FileLog).path = (
                pathlib.Path.cwd() / 'dummy.in'
            )
            await screen.action_open_visualizer()
            await pilot.pause()

            assert isinstance(pilot.app.screen, ErrorModal)
            assert 'visualizer crashed at runtime' in _rich_log_text(pilot.app.screen)
