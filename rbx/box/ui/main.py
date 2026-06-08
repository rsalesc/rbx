import pathlib
from typing import Type

import rich.text
import typer
from rich.segment import Segments
from textual.app import App, ComposeResult
from textual.containers import Center
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList

from rbx import console
from rbx.box import remote
from rbx.box.exception import RbxException
from rbx.box.ui.help_panel import HelpPanelMixin
from rbx.box.ui.screens.differ import DifferScreen
from rbx.box.ui.screens.error_modal import ErrorModal
from rbx.box.ui.screens.limits_editor import LimitsEditorScreen
from rbx.box.ui.screens.run_explorer import RunExplorerScreen
from rbx.box.ui.screens.test_explorer import TestExplorerScreen
from rbx.box.ui.vim_nav import VimNavMixin

SCREEN_OPTIONS = [
    ('Explore tests built by `rbx build`', TestExplorerScreen),
    ('Explore results of a past `rbx run`', RunExplorerScreen),
    ('Edit limits profiles (in development)', LimitsEditorScreen),
]


class rbxBaseApp(VimNavMixin, HelpPanelMixin, App):
    BINDING_GROUP_TITLE = 'Global'

    def run(self, *args, **kwargs):
        console.console.begin_capture()
        super().run(*args, **kwargs)

    def _handle_exception(self, error: Exception) -> None:
        if isinstance(error, typer.Exit):
            self._exit_renderables.clear()
            self._exit_renderables.append(Segments(console.console._buffer))  # noqa: SLF001
            self.exit(error.exit_code)
            return

        if isinstance(error, RbxException):
            # Recoverable user-config error (e.g. invalid problem/env YAML).
            # Keep the TUI alive and show it in a dismissible modal. Verified:
            # screen-entry crashes (a pushed screen's compose/on_mount) recover
            # here; the few action-body loads are guarded at the call site.
            if self.is_running:
                try:
                    # A crash during a pushed screen's compose/on_mount leaves
                    # that screen half-mounted on top of the stack; dismissing
                    # the modal would drop the user onto that wedged screen.
                    # Pop it first so they return to a working screen (e.g. the
                    # menu) and can navigate/quit. Only escaped/screen-entry
                    # errors reach here -- action/callback loads are caught at
                    # their call site -- so the top screen is the broken one.
                    if len(self.screen_stack) > 1:
                        try:
                            self.pop_screen()
                        except Exception:
                            pass
                    self.show_error(error)
                    return
                except Exception:
                    pass  # fall through to the clean exit below
            # Clean fallback: show ONLY the pretty diagnostic -- never a Python
            # traceback, and never re-raised (so the top-level CLI handler in
            # rbx/box/main.py cannot double-print it).
            self._exit_renderables.clear()
            self.exit(return_code=1, message=self._error_content(error))
            return

        # Default behavior (Rich traceback + return code 1)
        return super()._handle_exception(error)

    def _error_content(self, exc: RbxException) -> rich.text.Text:
        content = exc.from_ansi()
        if not content.plain.strip():
            content = rich.text.Text('An unexpected error occurred.')
        return content

    def show_error(self, exc: RbxException) -> None:
        """Surface an RbxException in a dismissible, scrollable modal.

        Preferred over a toast notification for errors that carry long,
        formatted output (e.g. a visualizer's compile/runtime failure, or an
        invalid problem/env YAML).
        """
        self.push_screen(ErrorModal(self._error_content(exc), title='Error'))


class rbxApp(rbxBaseApp):
    TITLE = 'rbx'
    CSS_PATH = 'css/app.tcss'
    BINDINGS = [('q', 'quit', 'Quit')]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Center(id='main'):
            yield OptionList(*(opt[0] for opt in SCREEN_OPTIONS))

    def on_mount(self):
        self.query_one(OptionList).border_title = 'Select a flow'

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        event.stop()
        self.show_screen(SCREEN_OPTIONS[event.option_index][1])

    def show_screen(self, screen_cls: Type[Screen]):
        self.push_screen(screen_cls())


class rbxDifferApp(rbxBaseApp):
    TITLE = 'rbx differ'
    CSS_PATH = 'css/app.tcss'
    BINDINGS = [('q', 'quit', 'Quit')]

    def __init__(self, path1: pathlib.Path, path2: pathlib.Path):
        super().__init__()
        self.path1 = path1
        self.path2 = path2

    def on_mount(self):
        self.push_screen(DifferScreen(self.path1, self.path2))


def start():
    app = rbxApp()
    app.run()


def start_differ(path1: pathlib.Path, path2: pathlib.Path):
    path1, path2 = remote.expand_files([str(path1), str(path2)])

    app = rbxDifferApp(path1, path2)
    app.run()
