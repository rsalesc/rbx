import shlex
from typing import List

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header

from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane


class CommandScreen(Screen):
    BINDINGS = [('q', 'app.pop_screen', 'Back')]

    def __init__(self, command: List[str]):
        super().__init__()
        self.command = command

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield CommandPane()

    def on_mount(self):
        pane = self.query_one(CommandPane)
        pane.border_title = 'Command output'
        pane.execute(shlex.join(self.command))

    def on_command_pane_command_complete(
        self, event: CommandPane.CommandComplete
    ) -> None:
        pane = self.query_one(CommandPane)
        if event.return_code != 0:
            pane.border_subtitle = f'Exit code: {event.return_code}'
        else:
            pane.border_subtitle = 'Finished'
