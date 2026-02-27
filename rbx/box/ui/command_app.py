import dataclasses
import enum
import shlex
from time import monotonic
from typing import List, Optional, Tuple

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.selection import Selection
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Select

from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.main import rbxBaseApp
from rbx.box.ui.screens.tab_selector import TabSelectorModal
from rbx.box.ui.task_queue import Task, TaskQueue
from rbx.box.ui.widgets.menu import Menu, MenuItem

_ESCAPE_TAP_DURATION = 0.4


class _AppCommandPane(CommandPane):
    """CommandPane that redirects focus to sidebar on blur (double-escape)."""

    def blur(self):
        try:
            sidebar = self.screen.query_one('#command-list', ListView)
            self.screen.set_focus(sidebar)
        except Exception:
            super().blur()
        return self

    def on_blur(self) -> None:
        self.border_subtitle = '[b]tab[/b] to focus'

    def selection_updated(self, selection: Selection | None) -> None:
        super().selection_updated(selection)
        if self.has_focus and selection is not None:
            self.border_subtitle = '[b]ctrl+y[/b] copy selection'
        elif self.has_focus:
            self.border_subtitle = 'Tap [b]esc[/b] [i]twice[/i] to exit'

    async def on_key(self, event: events.Key) -> None:
        if event.key == 'ctrl+y':
            selected = self.screen.get_selected_text()
            if selected:
                self.app.copy_to_clipboard(selected)
                self.screen.clear_selection()
                self.border_subtitle = 'Tap [b]esc[/b] [i]twice[/i] to exit'
                event.stop()
                event.prevent_default()
                return
        await super().on_key(event)


class ShellInput(Input):
    """Input that captures Tab/Shift+Tab and supports double-Escape to exit."""

    class Escaped(Message):
        """Posted when the user double-taps Escape to exit the input."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._escaping = False
        self._escape_time: float = 0.0
        self._escape_timer = None

    def _reset_escaping(self) -> None:
        self._escaping = False

    def on_focus(self) -> None:
        self.border_subtitle = _INPUT_FOCUSED_SUBTITLE

    def on_blur(self) -> None:
        self.border_subtitle = _INPUT_BLURRED_SUBTITLE

    def _cancel_escape_timer(self) -> None:
        if self._escape_timer is not None:
            self._escape_timer.stop()
            self._escape_timer = None

    def on_key(self, event: events.Key) -> None:
        if event.key in ('tab', 'shift+tab'):
            event.stop()
            event.prevent_default()
            return
        if event.key == 'escape':
            event.stop()
            event.prevent_default()
            self._cancel_escape_timer()
            if (
                self._escaping
                and monotonic() < self._escape_time + _ESCAPE_TAP_DURATION
            ):
                self._escaping = False
                self.post_message(self.Escaped())
            else:
                self._escaping = True
                self._escape_time = monotonic()
                self._escape_timer = self.set_timer(
                    _ESCAPE_TAP_DURATION, self._reset_escaping
                )


_SIDEBAR_SUBTITLE = '[b]?[/b] help'
_INPUT_FOCUSED_SUBTITLE = '[b]enter[/b] run  [b]esc\u00d72[/b] cancel'
_INPUT_BLURRED_SUBTITLE = '[b]![/b] to focus'
_SELECT_SUBTITLE = '[b]\u25c2\u25b8[/b] sub-cmd'


class HelpModal(ModalScreen[None]):
    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('question_mark', 'app.pop_screen', 'Close'),
    ]

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    #help-dialog {
        max-width: 60;
        height: auto;
        padding: 1 2;
        border: solid $accent;
        background: $surface;
    }
    #help-dialog Label {
        width: 1fr;
        margin-bottom: 1;
    }
    #help-title {
        text-style: bold;
        text-align: center;
    }
    #help-hints {
        text-align: center;
        color: $text 60%;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id='help-dialog'):
            yield Label('Keyboard Shortcuts', id='help-title')
            yield Label(
                '[b]Sidebar (command list)[/b]\n'
                '  [b]tab[/b]         Focus terminal\n'
                '  [b]![/b]           Open shell input\n'
                '  [b]\u2190 / \u2192[/b]       Previous / next sub-command\n'
                '  [b]?[/b]           Show this help\n'
                '  [b]q[/b]           Quit',
                markup=True,
            )
            yield Label(
                '[b]Terminal[/b]\n'
                '  [b]esc\u00d72[/b]        Return to sidebar\n'
                '  [b]ctrl+y[/b]      Copy selected text\n'
                '  (all other keys go to the running process)',
                markup=True,
            )
            yield Label(
                '[b]Shell input[/b]\n'
                '  [b]enter[/b]        Submit command\n'
                '  [b]esc\u00d72[/b]        Cancel and return to sidebar',
                markup=True,
            )
            yield Label(
                '[b]esc[/b] or [b]?[/b] to close',
                id='help-hints',
            )


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
    placeholder_prefix: Optional[str] = None

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
    task_id: Optional[int] = None


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

    @property
    def aggregate_status(self) -> CommandStatus:
        if not self.sub_commands:
            return CommandStatus.PENDING
        statuses = {s.status for s in self.sub_commands}
        for status in (
            CommandStatus.FAILED,
            CommandStatus.RUNNING,
            CommandStatus.PENDING,
        ):
            if status in statuses:
                return status
        return CommandStatus.SUCCESS


class rbxCommandApp(rbxBaseApp):
    class TaskReady(Message):
        def __init__(self, task: Task):
            self.task = task
            super().__init__()

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
    #command-list:focus {
        border: solid dodgerblue;
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
        scrollbar-size-vertical: 1;
    }
    #command-pane-container CommandPane:focus {
        border: solid dodgerblue;
    }
    #command-input-container {
        dock: bottom;
        height: auto;
    }
    #command-input-prefix {
        width: auto;
        height: 3;
        content-align: left middle;
        padding: 0 1;
        color: $accent;
    }
    #command-input {
        width: 1fr;
    }
    #command-input:focus {
        border: tall dodgerblue;
    }
    """
    BINDINGS = [
        ('q', 'quit', 'Quit'),
    ]

    def __init__(self, commands: List[CommandEntry], parallel: bool = False):
        super().__init__()
        self.commands = commands
        self.parallel = parallel
        self._tabs: List[TabState] = []
        self._active_tab: int = 0
        self._task_queue = TaskQueue(
            num_terminals=len(commands),
            parallel=parallel,
            on_task_ready=lambda t: self.post_message(self.TaskReady(t)),
        )
        self._pending_command: Optional[str] = None

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
                with Horizontal(id='command-input-container'):
                    yield Label(
                        self._get_input_prefix_text(0),
                        id='command-input-prefix',
                    )
                    yield ShellInput(
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
        return [
            (f'{_STATUS_ICON[sub.status]} {sub.name}', i)
            for i, sub in enumerate(self._tabs[tab_index].sub_commands)
        ]

    def _get_input_prefix_text(self, tab_index: int) -> str:
        return self._tabs[tab_index].entry.prefix or ''

    def _update_input_prefix(self, tab_index: int):
        prefix_label = self.query_one('#command-input-prefix', Label)
        tab = self._tabs[tab_index]
        if tab.entry.prefix is not None:
            prefix_label.update(tab.entry.prefix)
            prefix_label.display = True
        else:
            prefix_label.update('')
            prefix_label.display = False

    def _get_input_placeholder(self, tab_index: int) -> str:
        tab = self._tabs[tab_index]
        if tab.entry.placeholder_prefix is not None:
            return f'{tab.entry.placeholder_prefix} <command>'
        return 'Type a command and press Enter...'

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
        sidebar = self.query_one('#command-list', ListView)
        sidebar.border_title = 'Commands'
        sidebar.border_subtitle = _SIDEBAR_SUBTITLE

        select = self.query_one('#command-select', Select)
        select.border_subtitle = _SELECT_SUBTITLE

        # Mount initial CommandPanes.
        container = self.query_one('#command-pane-container', Vertical)
        for tab in self._tabs:
            for sub in tab.sub_commands:
                pane = _AppCommandPane(id=sub.pane_id)
                pane.border_title = sub.name
                container.mount(pane)

        # Show first tab's first pane.
        self._switch_tab(0)

        self.watch(
            self.query_one('#command-list', ListView),
            'index',
            self._on_tab_selected,
        )

        # Redirect to sidebar when focus becomes None (e.g. modal dismiss).
        self.watch(self.screen, 'focused', self._on_focused_changed)

        # Initial focus on the sidebar.
        self._focus_sidebar()

        # Enqueue initial commands.
        for i, tab in enumerate(self._tabs):
            for sub in tab.sub_commands:
                task = self._task_queue.enqueue(sub.shell_command, terminal_id=i)
                sub.task_id = task.task_id

    def on_rbx_command_app_task_ready(self, event: TaskReady) -> None:
        task = event.task
        tab = self._tabs[task.terminal_id]
        # Find the sub-command linked to this task.
        sub = next((s for s in tab.sub_commands if s.task_id == task.task_id), None)
        if sub is None:
            return
        sub.status = CommandStatus.RUNNING
        self._update_sidebar(task.terminal_id)
        self._refresh_select_if_active(task.terminal_id)
        pane = self.query_one(f'#{sub.pane_id}', CommandPane)
        pane.execute(task.command)

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

        # Update input prefix and placeholder.
        self._update_input_prefix(index)
        input_widget = self.query_one('#command-input', Input)
        input_widget.placeholder = self._get_input_placeholder(index)

    def _focus_sidebar(self) -> None:
        self.query_one('#command-list', ListView).focus()

    def _focus_terminal(self) -> None:
        pane_id = self._get_selected_pane_id()
        if pane_id is not None:
            try:
                self.query_one(f'#{pane_id}', CommandPane).focus()
            except NoMatches:
                pass

    def _select_prev_sub_command(self) -> None:
        select = self.query_one('#command-select', Select)
        if select.value is Select.BLANK:
            return
        current: int = select.value  # type: ignore[assignment]
        if current > 0:
            select.value = current - 1

    def _select_next_sub_command(self) -> None:
        select = self.query_one('#command-select', Select)
        if select.value is Select.BLANK:
            return
        current: int = select.value  # type: ignore[assignment]
        tab = self._tabs[self._active_tab]
        if current < len(tab.sub_commands) - 1:
            select.value = current + 1

    def _on_focused_changed(self, focused: Optional[Widget]) -> None:
        if focused is None:
            self._focus_sidebar()

    def on_key(self, event: events.Key) -> None:
        focused = self.screen.focused
        sidebar = self.query_one('#command-list', ListView)

        # Tab / Shift+Tab: cycle between sidebar and terminal only.
        if event.key in ('tab', 'shift+tab'):
            event.stop()
            event.prevent_default()
            if not isinstance(focused, Menu):
                if event.key == 'tab':
                    self._focus_terminal()
                else:
                    self._focus_sidebar()
            return

        # The following shortcuts only apply when the sidebar is focused.
        if focused is not sidebar:
            return

        if event.character == '!':
            event.stop()
            event.prevent_default()
            self.query_one('#command-input', ShellInput).focus()
            return

        if event.key == 'left':
            event.stop()
            event.prevent_default()
            self._select_prev_sub_command()
            return

        if event.key == 'right':
            event.stop()
            event.prevent_default()
            self._select_next_sub_command()
            return

        if event.character == '?':
            event.stop()
            event.prevent_default()
            self.push_screen(HelpModal())
            return

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != 'command-select':
            return
        pane_id = self._get_selected_pane_id()
        if pane_id is not None:
            self._show_pane(pane_id)

    def _refresh_select_if_active(self, tab_index: int):
        if tab_index == self._active_tab:
            self._refresh_select()

    def on_command_pane_command_complete(
        self, _event: CommandPane.CommandComplete
    ) -> None:
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

                if pane.return_code == 0:
                    sub.status = CommandStatus.SUCCESS
                    pane.border_subtitle = 'Done'
                else:
                    sub.status = CommandStatus.FAILED
                    pane.border_subtitle = f'Exit code: {pane.return_code}'

                self._update_sidebar(tab_index)
                self._refresh_select_if_active(tab_index)
                if sub.task_id is not None:
                    self._task_queue.notify_complete(sub.task_id)
                return

    def _queue_command_in_tab(self, tab_index: int, raw_command: str) -> SubCommand:
        tab = self._tabs[tab_index]
        display_name = (
            f'{tab.entry.prefix} {raw_command}'
            if tab.entry.prefix is not None
            else raw_command
        )
        sub = tab.add_sub_command_raw(name=display_name, raw_command=raw_command)

        # Mount the new pane.
        container = self.query_one('#command-pane-container', Vertical)
        pane = _AppCommandPane(id=sub.pane_id)
        pane.border_title = sub.name
        pane.display = False
        container.mount(pane)

        self._update_sidebar(tab_index)
        self._refresh_select_if_active(tab_index)

        task = self._task_queue.enqueue(sub.shell_command, terminal_id=tab_index)
        sub.task_id = task.task_id
        return sub

    def _show_latest_sub_command(self) -> None:
        """Refresh the select widget and show the latest sub-command pane."""
        tab = self._tabs[self._active_tab]
        self._refresh_select()
        if tab.sub_commands:
            select = self.query_one('#command-select', Select)
            select.value = len(tab.sub_commands) - 1
            self._show_pane(tab.sub_commands[-1].pane_id)

    def _submit_command(self, raw_input: str):
        sub = self._queue_command_in_tab(self._active_tab, raw_input)
        self._show_latest_sub_command()
        if sub.status == CommandStatus.PENDING:
            self.notify(
                f'Command queued in {self._tabs[self._active_tab].entry.display_name}'
            )

    def _submit_command_all(self, raw_input: str):
        for i, tab in enumerate(self._tabs):
            sub = self._queue_command_in_tab(i, raw_input)
            if sub.status == CommandStatus.PENDING:
                self.notify(f'Command queued in {tab.entry.display_name}')
        self._show_latest_sub_command()

    def _dismiss_menu(self) -> None:
        self._pending_command = None
        for menu in self.query(Menu):
            menu.remove()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'command-input':
            return
        raw = event.value.strip()
        if not raw:
            return
        event.input.value = ''

        # Dismiss any existing menu first.
        self._dismiss_menu()

        self._pending_command = raw
        menu = Menu(
            [
                MenuItem('Run in this tab', 'run_this_tab', '1'),
                MenuItem('Run in all tabs', 'run_all_tabs', '2'),
                MenuItem('Run in selected tabs', 'run_selected_tabs', '3'),
            ],
        )
        input_container = self.query_one('#command-input-container', Horizontal)
        input_container.mount(menu)
        menu.focus()

    @on(Menu.OptionSelected)
    def _on_menu_selected(self, event: Menu.OptionSelected) -> None:
        event.stop()
        raw = self._pending_command
        self._pending_command = None
        event.menu.remove()

        if raw is not None and event.action == 'run_selected_tabs':
            tab_names = [tab.entry.display_name for tab in self._tabs]
            self.push_screen(
                TabSelectorModal(tab_names),
                callback=lambda indices: self._on_tabs_selected(raw, indices),
            )
            return

        if raw is not None:
            if event.action == 'run_this_tab':
                self._submit_command(raw)
            elif event.action == 'run_all_tabs':
                self._submit_command_all(raw)
        self._focus_sidebar()

    @on(Menu.Dismissed)
    def _on_menu_dismissed(self, event: Menu.Dismissed) -> None:
        event.stop()
        self._pending_command = None
        event.menu.remove()

        # Clear input and return to sidebar.
        self.query_one('#command-input', ShellInput).value = ''
        self._focus_sidebar()

    @on(ShellInput.Escaped)
    def _on_shell_input_escaped(self, event: ShellInput.Escaped) -> None:
        event.stop()
        self.query_one('#command-input', ShellInput).value = ''
        self._focus_sidebar()

    def _on_tabs_selected(self, raw: str, indices: Optional[List[int]]) -> None:
        if indices:
            self._submit_command_selected(raw, indices)
        self._focus_sidebar()

    def _submit_command_selected(self, raw_input: str, tab_indices: List[int]) -> None:
        for i in tab_indices:
            if 0 <= i < len(self._tabs):
                sub = self._queue_command_in_tab(i, raw_input)
                if sub.status == CommandStatus.PENDING:
                    self.notify(f'Command queued in {self._tabs[i].entry.display_name}')
        if self._active_tab in tab_indices:
            self._show_latest_sub_command()


def start_command_app(commands: List[CommandEntry], parallel: bool = False) -> None:
    app = rbxCommandApp(commands, parallel=parallel)
    app.run()


if __name__ == '__main__':
    start_command_app(
        [
            CommandEntry(argv=['echo', 'hello'], name='echo1'),
            CommandEntry(argv=['echo', 'world'], name='echo2'),
            CommandEntry(argv=['echo', 'foo'], name='echo3'),
        ]
    )
