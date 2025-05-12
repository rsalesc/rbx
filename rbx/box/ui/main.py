import pathlib
from typing import Type

from textual.app import App, ComposeResult
from textual.containers import Center
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList

from rbx.box import remote
from rbx.box.ui.screens.differ import DifferScreen
from rbx.box.ui.screens.run_explorer import RunExplorerScreen
from rbx.box.ui.screens.test_explorer import TestExplorerScreen

SCREEN_OPTIONS = [
    ('Explore tests built by `rbx build`.', TestExplorerScreen),
    ('Explore results of a past `rbx run`.', RunExplorerScreen),
]


class rbxApp(App):
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
        self.show_screen(SCREEN_OPTIONS[event.option_index][1])

    def show_screen(self, screen_cls: Type[Screen]):
        self.push_screen(screen_cls())


class rbxDifferApp(App):
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
    path1, path2 = remote.expand_files([path1, path2])

    app = rbxDifferApp(path1, path2)
    app.run()
