"""rbx ui surfaces YAML/config RbxExceptions without crashing the TUI.

A YAML syntax/validation error (RbxException) raised while rbx ui is running
used to fall through rbxBaseApp._handle_exception into Textual's default
handler, dumping a Rich traceback AND re-printing the diagnostic from the
top-level CLI handler. It now opens the dismissible ErrorModal and keeps the
app alive, falling back to a clean diagnostic-only exit if the modal cannot be
shown.
"""

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
