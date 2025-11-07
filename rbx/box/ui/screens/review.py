import pathlib

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from rbx.box.ui.widgets.code_box import CodeBox


class ReviewScreen(Screen):
    BINDINGS = [
        ('y', 'confirm', 'Confirm'),
        ('n', 'exit', 'Exit'),
    ]

    def __init__(self, path: pathlib.Path):
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Vertical():
            yield CodeBox()

    def on_mount(self):
        box = self.query_one(CodeBox)
        box.path = self.path

    def action_confirm(self):
        # Signal confirmation and exit the app
        self.app.confirmed = True  # type: ignore[attr-defined]
        self.app.exit()

    def action_exit(self):
        # Signal not confirmed and exit the app
        self.app.confirmed = False  # type: ignore[attr-defined]
        self.app.exit()
