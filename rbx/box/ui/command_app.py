import asyncio
import dataclasses
import enum
import shlex
from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx.box.ui.captured_log import LogDisplay
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


class _SizeSafeLogDisplay(LogDisplay):
    """LogDisplay that handles capture when the widget is hidden (zero size)."""

    def _resize(self):
        if self.size.width <= 2:
            width = 80
            self.virtual_size = Size(width=width, height=self.virtual_size.height)
            self._screen.resize(self._max_lines, width)
            return
        super()._resize()


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
    #command-display-container LogDisplay {
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
                    yield _SizeSafeLogDisplay(id=f'cmd-display-{i}')

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
            self.query_one(f'#cmd-display-{i}', _SizeSafeLogDisplay).display = (
                i == index
            )

    def on_mount(self):
        self.query_one('#command-list', ListView).border_title = 'Commands'

        for i, cmd in enumerate(self.commands):
            display = self.query_one(f'#cmd-display-{i}', _SizeSafeLogDisplay)
            display.border_title = cmd.display_name

        self._show_display(0)

        self.watch(
            self.query_one('#command-list', ListView),
            'index',
            self._on_command_selected,
        )

        if self.parallel:
            for i in range(len(self.commands)):
                asyncio.create_task(self._run_command(i))
        else:
            asyncio.create_task(self._run_sequential())

    def _on_command_selected(self, index: Optional[int]):
        if index is None:
            return
        self._show_display(index)

    async def _run_command(self, index: int):
        self._statuses[index] = CommandStatus.RUNNING
        self._update_sidebar(index)

        display = self.query_one(f'#cmd-display-{index}', _SizeSafeLogDisplay)
        cmd = self.commands[index]
        argv = cmd.argv
        if cmd.cwd is not None:
            argv = [
                'sh',
                '-c',
                f'cd {shlex.quote(cmd.cwd)} && exec {shlex.join(cmd.argv)}',
            ]
        exitcode = await display.capture(argv)

        if exitcode == 0:
            self._statuses[index] = CommandStatus.SUCCESS
            display.border_subtitle = 'Done'
        else:
            self._statuses[index] = CommandStatus.FAILED
            display.border_subtitle = f'Exit code: {exitcode}'

        self._update_sidebar(index)

    async def _run_sequential(self):
        for i in range(len(self.commands)):
            await self._run_command(i)


def start_command_app(commands: List[CommandEntry], parallel: bool = False) -> None:
    app = rbxCommandApp(commands, parallel=parallel)
    app.run()


if __name__ == '__main__':
    start_command_app([CommandEntry(argv=['ls', '-l'])])
