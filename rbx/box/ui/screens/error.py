from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header, Label


class ErrorScreen(Screen):
    BINDINGS = [('q', 'app.pop_screen', 'Quit')]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield Label(self.message)

    def on_mount(self):
        self.query_one(Label).border_title = 'Error'
