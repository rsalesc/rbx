import asyncio
import dataclasses
import enum
import shlex
from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Select

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

_STATUS_ICON = {
    CommandStatus.PENDING: '○',
    CommandStatus.RUNNING: '●',
    CommandStatus.SUCCESS: '✓',
    CommandStatus.FAILED: '✗',
}


@dataclasses.dataclass
class CommandEntry:
    argv: List[str]
    name: Optional[str] = None
    cwd: Optional[str] = None
    prefix: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.name if self.name else ' '.join(self.argv)

    def make_raw_shell_command(self, cmd: str) -> str:
        if self.prefix is not None:
            cmd = f'{self.prefix} {cmd}'
        if self.cwd is not None:
            cmd = f'cd {shlex.quote(self.cwd)} && exec {cmd}'
        return cmd

    def make_shell_command(self, argv: List[str]) -> str:
        return self.make_raw_shell_command(shlex.join(argv))

    @property
    def shell_command(self) -> str:
        return self.make_shell_command(self.argv)


@dataclasses.dataclass
class SubCommand:
    name: str
    shell_command: str
    pane_id: str
    status: CommandStatus = CommandStatus.PENDING


class TabState:
    def __init__(self, entry: CommandEntry, tab_index: int):
        self.entry = entry
        self.tab_index = tab_index
        self.sub_commands: List[SubCommand] = []
        self._next_sub_id = 0

    def _append_sub_command(self, name: str, shell_command: str) -> SubCommand:
        pane_id = f'cmd-pane-{self.tab_index}-{self._next_sub_id}'
        sub = SubCommand(
            name=name,
            shell_command=shell_command,
            pane_id=pane_id,
        )
        self._next_sub_id += 1
        self.sub_commands.append(sub)
        return sub

    def add_sub_command(self, name: str, argv: List[str]) -> SubCommand:
        shell_command = self.entry.make_shell_command(argv)
        return self._append_sub_command(name, shell_command)

    def add_sub_command_raw(self, name: str, raw_command: str) -> SubCommand:
        shell_command = self.entry.make_raw_shell_command(raw_command)
        return self._append_sub_command(name, shell_command)

    @property
    def is_idle(self) -> bool:
        if not self.sub_commands:
            return True
        return all(
            s.status in (CommandStatus.SUCCESS, CommandStatus.FAILED)
            for s in self.sub_commands
        )

    def next_pending(self) -> Optional[int]:
        for i, s in enumerate(self.sub_commands):
            if s.status == CommandStatus.PENDING:
                return i
        return None

    @property
    def aggregate_status(self) -> CommandStatus:
        if not self.sub_commands:
            return CommandStatus.PENDING
        has_failed = False
        has_running = False
        has_pending = False
        for s in self.sub_commands:
            if s.status == CommandStatus.FAILED:
                has_failed = True
            elif s.status == CommandStatus.RUNNING:
                has_running = True
            elif s.status == CommandStatus.PENDING:
                has_pending = True
        if has_failed:
            return CommandStatus.FAILED
        if has_running:
            return CommandStatus.RUNNING
        if has_pending:
            return CommandStatus.PENDING
        return CommandStatus.SUCCESS


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
    #command-display-area {
        height: 1fr;
        width: 1fr;
    }
    #command-select {
        width: 1fr;
        margin: 0;
    }
    #command-pane-container {
        height: 1fr;
        width: 1fr;
    }
    #command-pane-container CommandPane {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    #command-input {
        dock: bottom;
    }
    """
    BINDINGS = [
        ('q', 'quit', 'Quit'),
        ('ctrl+o', 'submit_all', 'Run in all tabs'),
    ]

    def __init__(self, commands: List[CommandEntry], parallel: bool = False):
        super().__init__()
        self.commands = commands
        self.parallel = parallel
        self._tabs: List[TabState] = []
        self._active_tab: int = 0
        self._sequential_event: Optional[asyncio.Event] = None

        # Initialize tab states and add initial sub-commands.
        for i, cmd in enumerate(commands):
            tab = TabState(entry=cmd, tab_index=i)
            tab.add_sub_command(name=' '.join(cmd.argv), argv=cmd.argv)
            self._tabs.append(tab)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Horizontal(id='command-app'):
            with Vertical(id='command-list-container'):
                yield ListView(
                    *[
                        ListItem(
                            Label(self._make_tab_label(i), markup=True),
                            id=f'cmd-item-{i}',
                        )
                        for i in range(len(self.commands))
                    ],
                    id='command-list',
                )
            with Vertical(id='command-display-area'):
                yield Select[int](
                    self._get_select_options(0),
                    id='command-select',
                    allow_blank=False,
                )
                yield Vertical(id='command-pane-container')
                yield Input(
                    id='command-input',
                    placeholder=self._get_input_placeholder(0),
                )

    def _make_tab_label(self, index: int) -> str:
        tab = self._tabs[index]
        icon = _STATUS_MARKUP[tab.aggregate_status]
        name = tab.entry.display_name
        return f'{icon} {name}'

    def _update_sidebar(self, index: int):
        item = self.query_one(f'#cmd-item-{index}', ListItem)
        label = item.query_one(Label)
        label.update(self._make_tab_label(index))

    def _get_select_options(self, tab_index: int) -> List[Tuple[str, int]]:
        tab = self._tabs[tab_index]
        options = []
        for i, sub in enumerate(tab.sub_commands):
            icon = _STATUS_ICON[sub.status]
            options.append((f'{icon} {sub.name}', i))
        return options

    def _get_input_placeholder(self, tab_index: int) -> str:
        tab = self._tabs[tab_index]
        if tab.entry.prefix is not None:
            return f'{tab.entry.prefix} ...'
        return 'Enter command...'

    def _refresh_select(self):
        select = self.query_one('#command-select', Select)
        options = self._get_select_options(self._active_tab)
        current_value = select.value
        select.set_options(options)
        # Try to preserve selection; if it no longer exists, select last.
        if any(v == current_value for _, v in options):
            select.value = current_value
        elif options:
            select.value = options[-1][1]

    def _show_pane(self, pane_id: str):
        container = self.query_one('#command-pane-container', Vertical)
        for child in container.query(CommandPane):
            child.display = child.id == pane_id

    def _get_selected_pane_id(self) -> Optional[str]:
        select = self.query_one('#command-select', Select)
        if select.value is Select.BLANK:
            return None
        sub_index: int = select.value  # type: ignore[assignment]
        tab = self._tabs[self._active_tab]
        if 0 <= sub_index < len(tab.sub_commands):
            return tab.sub_commands[sub_index].pane_id
        return None

    def on_mount(self):
        self.query_one('#command-list', ListView).border_title = 'Commands'

        # Mount initial CommandPanes.
        container = self.query_one('#command-pane-container', Vertical)
        for tab in self._tabs:
            for sub in tab.sub_commands:
                pane = CommandPane(id=sub.pane_id)
                pane.border_title = sub.name
                container.mount(pane)

        # Show first tab's first pane.
        self._switch_tab(0)

        self.watch(
            self.query_one('#command-list', ListView),
            'index',
            self._on_tab_selected,
        )

        # Start initial commands.
        if self.parallel:
            for i in range(len(self._tabs)):
                self._start_next_in_tab(i)
        else:
            asyncio.create_task(self._run_initial_sequential())

    def _on_tab_selected(self, index: Optional[int]):
        if index is None:
            return
        self._switch_tab(index)

    def _switch_tab(self, index: int):
        self._active_tab = index
        self._refresh_select()

        # Select the latest sub-command by default.
        tab = self._tabs[index]
        select = self.query_one('#command-select', Select)
        if tab.sub_commands:
            select.value = len(tab.sub_commands) - 1
            self._show_pane(tab.sub_commands[-1].pane_id)
        else:
            # Hide all panes for this tab.
            container = self.query_one('#command-pane-container', Vertical)
            for child in container.query(CommandPane):
                child.display = False

        # Update input placeholder.
        input_widget = self.query_one('#command-input', Input)
        input_widget.placeholder = self._get_input_placeholder(index)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != 'command-select':
            return
        pane_id = self._get_selected_pane_id()
        if pane_id is not None:
            self._show_pane(pane_id)

    def _start_next_in_tab(self, tab_index: int):
        tab = self._tabs[tab_index]
        next_idx = tab.next_pending()
        if next_idx is None:
            return
        sub = tab.sub_commands[next_idx]
        sub.status = CommandStatus.RUNNING
        self._update_sidebar(tab_index)
        self._refresh_select_if_active(tab_index)

        pane = self.query_one(f'#{sub.pane_id}', CommandPane)
        pane.execute(sub.shell_command)

    def _refresh_select_if_active(self, tab_index: int):
        if tab_index == self._active_tab:
            self._refresh_select()

    def on_command_pane_command_complete(
        self, _event: CommandPane.CommandComplete
    ) -> None:
        # Find which sub-command completed.
        for tab_index, tab in enumerate(self._tabs):
            for sub in tab.sub_commands:
                if sub.status != CommandStatus.RUNNING:
                    continue
                try:
                    pane = self.query_one(f'#{sub.pane_id}', CommandPane)
                except NoMatches:
                    continue
                if pane.return_code is None:
                    continue
                return_code = pane.return_code
                if return_code == 0:
                    sub.status = CommandStatus.SUCCESS
                    pane.border_subtitle = 'Done'
                else:
                    sub.status = CommandStatus.FAILED
                    pane.border_subtitle = f'Exit code: {return_code}'

                self._update_sidebar(tab_index)
                self._refresh_select_if_active(tab_index)

                # Start next pending sub-command in this tab.
                self._start_next_in_tab(tab_index)

                # Signal sequential runner if applicable.
                if not self.parallel and self._sequential_event is not None:
                    self._sequential_event.set()
                return

    async def _run_initial_sequential(self):
        self._sequential_event = asyncio.Event()
        for i in range(len(self._tabs)):
            self._sequential_event.clear()
            self._start_next_in_tab(i)
            await self._sequential_event.wait()

    def _queue_command_in_tab(self, tab_index: int, raw_command: str) -> SubCommand:
        tab = self._tabs[tab_index]
        was_idle = tab.is_idle
        sub = tab.add_sub_command_raw(name=raw_command, raw_command=raw_command)

        # Mount the new pane.
        container = self.query_one('#command-pane-container', Vertical)
        pane = CommandPane(id=sub.pane_id)
        pane.border_title = sub.name
        pane.display = False
        container.mount(pane)

        self._update_sidebar(tab_index)
        self._refresh_select_if_active(tab_index)

        # If the tab was idle before we added, start immediately.
        if was_idle:
            self._start_next_in_tab(tab_index)
        return sub

    def _submit_command(self, raw_input: str):
        tab = self._tabs[self._active_tab]
        sub = self._queue_command_in_tab(self._active_tab, raw_input)

        # Switch to the newly added sub-command.
        self._refresh_select()
        select = self.query_one('#command-select', Select)
        select.value = len(tab.sub_commands) - 1
        self._show_pane(sub.pane_id)

        if sub.status == CommandStatus.PENDING:
            self.notify(f'Command queued in {tab.entry.display_name}')

    def _submit_command_all(self, raw_input: str):
        for i, tab in enumerate(self._tabs):
            sub = self._queue_command_in_tab(i, raw_input)
            if sub.status == CommandStatus.PENDING:
                self.notify(f'Command queued in {tab.entry.display_name}')

        # Switch to the active tab's latest sub-command.
        active_tab = self._tabs[self._active_tab]
        self._refresh_select()
        select = self.query_one('#command-select', Select)
        if active_tab.sub_commands:
            select.value = len(active_tab.sub_commands) - 1
            self._show_pane(active_tab.sub_commands[-1].pane_id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'command-input':
            return
        raw = event.value.strip()
        if not raw:
            return
        event.input.value = ''
        self._submit_command(raw)

    def action_submit_all(self) -> None:
        input_widget = self.query_one('#command-input', Input)
        raw = input_widget.value.strip()
        if not raw:
            return
        input_widget.value = ''
        self._submit_command_all(raw)


def start_command_app(commands: List[CommandEntry], parallel: bool = False) -> None:
    app = rbxCommandApp(commands, parallel=parallel)
    app.run()


if __name__ == '__main__':
    start_command_app([CommandEntry(argv=['ls', '-l'])])
