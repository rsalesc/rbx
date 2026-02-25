import asyncio
import dataclasses
import enum
import shlex
from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.main import rbxBaseApp


class CommandStatus(enum.Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'


_STATUS_MARKUP = {
    CommandStatus.PENDING: '[dim]○[/dim]',
    CommandStatus.RUNNING: '[yellow]●[/yellow]',
    CommandStatus.SUCCESS: '[green]✓[/green]',
    CommandStatus.FAILED: '[red]✗[/red]',
}


@dataclasses.dataclass
class CommandEntry:
    argv: List[str]
    name: Optional[str] = None
    cwd: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.name if self.name else ' '.join(self.argv)

    @property
    def shell_command(self) -> str:
        cmd = shlex.join(self.argv)
        if self.cwd is not None:
            cmd = f'cd {shlex.quote(self.cwd)} && exec {cmd}'
        return cmd


class rbxCommandApp(rbxBaseApp):
    TITLE = 'rbx'
    CSS_PATH = 'css/app.tcss'
    DEFAULT_CSS = """
    #command-app {
        height: 1fr;
    }
    #command-list-container {
        min-width: 20;
        max-width: 40;
        height: 1fr;
    }
    #command-list {
        width: 1fr;
    }
    #command-display-container {
        height: 1fr;
        width: 1fr;
    }
    #command-display-container CommandPane {
        height: 1fr;
    }
    """
    BINDINGS = [('q', 'quit', 'Quit')]

    def __init__(self, commands: List[CommandEntry], parallel: bool = False):
        super().__init__()
        self.commands = commands
        self.parallel = parallel
        self._statuses: List[CommandStatus] = [CommandStatus.PENDING] * len(commands)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Horizontal(id='command-app'):
            with Vertical(id='command-list-container'):
                yield ListView(
                    *[
                        ListItem(
                            Label(self._make_label(i), markup=True),
                            id=f'cmd-item-{i}',
                        )
                        for i in range(len(self.commands))
                    ],
                    id='command-list',
                )
            with Vertical(id='command-display-container'):
                for i in range(len(self.commands)):
                    yield CommandPane(id=f'cmd-display-{i}')

    def _make_label(self, index: int) -> str:
        icon = _STATUS_MARKUP[self._statuses[index]]
        name = self.commands[index].display_name
        return f'{icon} {name}'

    def _update_sidebar(self, index: int):
        item = self.query_one(f'#cmd-item-{index}', ListItem)
        label = item.query_one(Label)
        label.update(self._make_label(index))

    def _show_display(self, index: int):
        for i in range(len(self.commands)):
            self.query_one(f'#cmd-display-{i}', CommandPane).display = i == index

    def on_mount(self):
        self.query_one('#command-list', ListView).border_title = 'Commands'

        for i, cmd in enumerate(self.commands):
            pane = self.query_one(f'#cmd-display-{i}', CommandPane)
            pane.border_title = cmd.display_name

        self._show_display(0)

        self.watch(
            self.query_one('#command-list', ListView),
            'index',
            self._on_command_selected,
        )

        if self.parallel:
            for i in range(len(self.commands)):
                self._start_command(i)
        else:
            asyncio.create_task(self._run_sequential())

    def _on_command_selected(self, index: Optional[int]):
        if index is None:
            return
        self._show_display(index)

    def _start_command(self, index: int):
        self._statuses[index] = CommandStatus.RUNNING
        self._update_sidebar(index)

        pane = self.query_one(f'#cmd-display-{index}', CommandPane)
        pane.execute(self.commands[index].shell_command)

    def on_command_pane_command_complete(
        self, _event: CommandPane.CommandComplete
    ) -> None:
        for i in range(len(self.commands)):
            if self._statuses[i] != CommandStatus.RUNNING:
                continue
            pane = self.query_one(f'#cmd-display-{i}', CommandPane)
            if pane.return_code is None:
                continue
            return_code = pane.return_code
            if return_code == 0:
                self._statuses[i] = CommandStatus.SUCCESS
                pane.border_subtitle = 'Done'
            else:
                self._statuses[i] = CommandStatus.FAILED
                pane.border_subtitle = f'Exit code: {return_code}'
            self._update_sidebar(i)

            if not self.parallel:
                self._sequential_event.set()

    async def _run_sequential(self):
        self._sequential_event = asyncio.Event()
        for i in range(len(self.commands)):
            self._sequential_event.clear()
            self._start_command(i)
            await self._sequential_event.wait()


def start_command_app(commands: List[CommandEntry], parallel: bool = False) -> None:
    app = rbxCommandApp(commands, parallel=parallel)
    app.run()


if __name__ == '__main__':
    start_command_app([CommandEntry(argv=['ls', '-l'])])
