"""rbx ui surfaces YAML/config RbxExceptions without crashing the TUI.

A YAML syntax/validation error (RbxException) raised while rbx ui is running
used to fall through rbxBaseApp._handle_exception into Textual's default
handler, dumping a Rich traceback AND re-printing the diagnostic from the
top-level CLI handler. It now opens the dismissible ErrorModal and keeps the
app alive, falling back to a clean diagnostic-only exit if the modal cannot be
shown.
"""

from unittest import mock

import rich.text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, RichLog

from rbx.box.exception import RbxException
from rbx.box.ui.main import rbxApp
from rbx.box.ui.screens.error_modal import ErrorModal


def _exc(text: str) -> RbxException:
    """Build an RbxException carrying ``text`` as its rendered diagnostic."""
    exc = RbxException()
    exc.print(text)
    return exc


def _rich_log_text(modal: ErrorModal) -> str:
    rich_log = modal.query_one(RichLog)
    return '\n'.join(strip.text for strip in rich_log.lines)


class _CrashOnMountScreen(Screen):
    """Mirrors a real screen that loads invalid YAML during on_mount."""

    def compose(self) -> ComposeResult:
        yield Label('loading')

    def on_mount(self) -> None:
        raise _exc('env.rbx.yml: 1 validation error\nlanguages: extra inputs')


async def test_yaml_error_on_screen_entry_opens_modal_and_keeps_app_alive():
    async with rbxApp().run_test() as pilot:
        app = pilot.app
        await app.push_screen(_CrashOnMountScreen())
        await pilot.pause()

        assert app.is_running
        assert isinstance(app.screen, ErrorModal)
        assert 'extra inputs' in _rich_log_text(app.screen)


async def test_broken_screen_is_popped_so_user_can_dismiss_and_quit():
    """After a screen-entry crash, the half-mounted screen is removed.

    Otherwise dismissing the modal drops the user onto the wedged screen and
    they cannot navigate or quit.
    """
    async with rbxApp().run_test() as pilot:
        app = pilot.app
        await app.push_screen(_CrashOnMountScreen())
        await pilot.pause()

        # The modal sits on a working screen, not the broken one.
        assert isinstance(app.screen, ErrorModal)
        assert not any(isinstance(s, _CrashOnMountScreen) for s in app.screen_stack)

        # Dismissing returns to a working screen, app still alive.
        await pilot.press('escape')
        await pilot.pause()
        assert app.is_running
        assert not isinstance(app.screen, ErrorModal)

        # And the user can actually quit from there.
        await pilot.press('q')
        await pilot.pause()
        assert not app.is_running


async def test_clean_fallback_shows_diagnostic_without_traceback():
    async with rbxApp().run_test() as pilot:
        app = pilot.app

        # Force the modal path to fail so the clean-exit fallback runs.
        def _boom(_exc):
            raise RuntimeError('cannot push modal')

        app.show_error = _boom  # type: ignore[method-assign]

        app._handle_exception(_exc('problem.rbx.yml: bad value at line 12'))  # noqa: SLF001
        await pilot.pause()

        # The sole exit renderable is the pretty diagnostic as plain rich Text,
        # NOT a Rich Traceback / Segments dump.
        assert app._exit_renderables  # noqa: SLF001
        rendered = app._exit_renderables[-1]  # noqa: SLF001
        assert isinstance(rendered, rich.text.Text)
        assert 'bad value at line 12' in rendered.plain
        # App is exiting with code 1 rather than crashing.
        assert app._return_code == 1  # noqa: SLF001


async def test_limits_editor_profile_load_error_opens_modal():
    """A non-mount config load (limits editor) is caught at the call site.

    LimitsEditorScreen loads the package in a profile-selection callback, not
    at mount, so it cannot rely on the _handle_exception safety net. It catches
    the RbxException and routes it to the same ErrorModal.
    """
    from rbx.box.schema import LimitsProfile
    from rbx.box.ui.screens import limits_editor

    with (
        mock.patch.object(
            limits_editor.limits_info,
            'get_available_profile_names',
            return_value=[],
        ),
        mock.patch.object(
            limits_editor.package,
            'find_problem_package_or_die',
            side_effect=_exc('problem.rbx.yml: invalid limits'),
        ),
    ):
        async with rbxApp().run_test() as pilot:
            app = pilot.app
            screen = limits_editor.LimitsEditorScreen()
            await app.push_screen(screen)
            await pilot.pause()

            # Rendering a profile detail form triggers the package load.
            await screen._load_profile_detail_from(LimitsProfile())  # noqa: SLF001
            await pilot.pause()

            assert app.is_running
            assert isinstance(app.screen, ErrorModal)
            assert 'invalid limits' in _rich_log_text(app.screen)
