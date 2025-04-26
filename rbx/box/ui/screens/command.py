import asyncio
from typing import List

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header

from rbx.box.ui.captured_log import LogDisplay


class CommandScreen(Screen):
    BINDINGS = [('q', 'app.pop_screen', 'Back')]

    def __init__(self, command: List[str]):
        super().__init__()
        self.command = command

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield LogDisplay()

    async def _run_command(self):
        exitcode = await self.query_one(LogDisplay).capture(self.command)
        if exitcode != 0:
            self.query_one(LogDisplay).border_subtitle = f'Exit code: {exitcode}'
            return

        self.query_one(LogDisplay).border_subtitle = 'Finished'

    async def on_mount(self):
        self.query_one(LogDisplay).border_title = 'Command output'

        # Fire and forget.
        asyncio.create_task(self._run_command())
