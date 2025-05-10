import pathlib

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from rbx.box.ui.widgets.diff_box import DiffBox


class DifferScreen(Screen):
    BINDINGS = [
        ('q', 'quit', 'Quit'),
    ]

    def __init__(self, path1: pathlib.Path, path2: pathlib.Path):
        super().__init__()
        self.path1 = path1
        self.path2 = path2

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Vertical():
            yield DiffBox()

    def on_mount(self):
        diff = self.query_one(DiffBox)
        diff.paths = (self.path1, self.path2)
