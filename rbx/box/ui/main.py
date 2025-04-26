from typing import Type

from textual.app import App, ComposeResult
from textual.containers import Center
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList

from rbx.box.ui.screens.build import BuildScreen
from rbx.box.ui.screens.run import RunScreen
from rbx.box.ui.screens.test_explorer import TestExplorerScreen

SCREEN_OPTIONS = [
    ('Run solutions against define testsets.', RunScreen),
    ('Build tests.', BuildScreen),
    ('Explore tests.', TestExplorerScreen),
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


def start():
    app = rbxApp()
    app.run()
