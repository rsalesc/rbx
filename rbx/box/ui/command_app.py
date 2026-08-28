import dataclasses
import datetime
import shlex
from time import monotonic
from typing import Dict, List, Optional, Tuple

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.selection import Selection
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Select

from rbx.box.setter_config import (
    ProblemLabelMode,
    get_setter_config,
    set_problem_label,
)
from rbx.box.ui import command_status, run_history
from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.command_status import CommandStatus
from rbx.box.ui.main import rbxBaseApp
from rbx.box.ui.screens.tab_selector import TabSelectorModal
from rbx.box.ui.task_queue import Task, TaskQueue
from rbx.box.ui.terminal_select import SelectableCommandPane
from rbx.box.ui.widgets.menu import Menu, MenuItem

_ESCAPE_TAP_DURATION = 0.4
_FOCUSED_SUBTITLE = '[b]esc×2[/b] exit  [b]ctrl+v[/b] select  [b]ctrl+y[/b] copy all'


class _AppCommandPane(SelectableCommandPane):
    """CommandPane that redirects focus to sidebar on blur (double-escape)."""

    def on_resize(self, event: events.Resize) -> None:
        super().on_resize(event)
        # All panes share the container's geometry, so whatever this one just
        # got is exactly what the hidden ones will get once shown. Tell them,
        # otherwise their commands keep rendering at the 80-column fallback.
        self.app.sync_hidden_pane_sizes(self)  # type: ignore[attr-defined]

    def blur(self):
        try:
            sidebar = self.screen.query_one('#command-list', ListView)
            self.screen.set_focus(sidebar)
        except Exception:
            super().blur()
        return self

    def on_blur(self) -> None:
        self.border_subtitle = '[b]tab[/b] to focus'

    def on_focus(self) -> None:
        self.border_subtitle = _FOCUSED_SUBTITLE

    def selection_updated(self, selection: Selection | None) -> None:
        super().selection_updated(selection)
        if self.in_select_mode:
            # The select mode owns the subtitle while it is on.
            return
        if self.has_focus and selection is not None:
            self.border_subtitle = '[b]ctrl+y[/b] copy selection'
        elif self.has_focus:
            self.border_subtitle = _FOCUSED_SUBTITLE


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
                '  [b]r[/b]           Retry this command\n'
                '  [b]R[/b]           Resume everything that did not succeed\n'
                '  [b]l[/b]           Cycle problem label (name/title/path)\n'
                '  [b]?[/b]           Show this help\n'
                '  [b]q[/b]           Quit',
                markup=True,
            )
            yield Label(
                '[b]Terminal[/b]\n'
                '  [b]esc\u00d72[/b]        Return to sidebar\n'
                '  [b]ctrl+y[/b]      Copy the selection, or all output\n'
                '  [b]ctrl+v[/b]      Enter select mode\n'
                '  (all other keys go to the running process)',
                markup=True,
            )
            yield Label(
                '[b]Select mode[/b] ([b]ctrl+v[/b])\n'
                '  [b]hjkl[/b] / arrows  Move the cursor\n'
                '  [b]0 ^ $ w b[/b]     Line start / first word / end / word\n'
                '  [b]gg G[/b]          Top / bottom  ([b]ctrl+d ctrl+u[/b] half page)\n'
                '  [b]v[/b] / [b]V[/b]           Select by character / by line\n'
                '  [b]y[/b]             Copy and exit ([b]y[/b] alone yanks the line)\n'
                '  [b]esc[/b]           Exit without copying',
                markup=True,
            )
            yield Label(
                '[b]Shell input[/b]\n'
                '  [b]enter[/b]        Submit command\n'
                '  [b]esc\u00d72[/b]        Cancel and return to sidebar',
                markup=True,
            )
            yield Label(
                '[b]Status[/b]\n'
                '  \u25cb queued   \u25cf running   \u2713 done   \u2717 failed\n'
                '  \u2298 skipped (an earlier command in the chain failed)',
                markup=True,
            )
            yield Label(
                '[b]esc[/b] or [b]?[/b] to close',
                id='help-hints',
            )


# Re-exported so existing importers of `command_app.CommandStatus` keep working;
# the enum itself lives beside the run history, which persists it.
_STATUS_MARKUP = command_status.STATUS_MARKUP
_STATUS_ICON = command_status.STATUS_ICON
_FINISHED_STATUSES = command_status.FINISHED_STATUSES


@dataclasses.dataclass
class CommandEntry:
    # One argv per command in the chain; they are queued in order in the tab.
    argvs: List[List[str]]
    name: Optional[str] = None
    cwd: Optional[str] = None
    prefix: Optional[str] = None
    placeholder_prefix: Optional[str] = None
    # Precomputed sidebar labels per ProblemLabelMode, so the UI can swap them
    # live without reloading problem packages. None for non-contest entries.
    labels: Optional[Dict[ProblemLabelMode, str]] = None

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        return ' '.join(self.argvs[0]) if self.argvs else ''

    def make_raw_shell_command(self, cmd: str) -> str:
        if self.prefix is not None:
            cmd = f'{self.prefix} {cmd}'
        if self.cwd is not None:
            cmd = f'cd {shlex.quote(self.cwd)} && exec {cmd}'
        return cmd

    def make_shell_command(self, argv: List[str]) -> str:
        return self.make_raw_shell_command(shlex.join(argv))

    @property
    def shell_commands(self) -> List[str]:
        return [self.make_shell_command(argv) for argv in self.argvs]


@dataclasses.dataclass
class SubCommand:
    name: str
    shell_command: str
    pane_id: str
    status: CommandStatus = CommandStatus.PENDING
    exit_code: Optional[int] = None
    task_id: Optional[int] = None
    # Seeded from the CLI as part of a `::` chain. Only chained commands are
    # skipped when an earlier one fails; commands queued interactively always
    # run, so a typo in one does not silently swallow the next.
    chained: bool = False


def _subtitle_for(sub: SubCommand) -> str:
    """What a pane's border says about a command that is no longer running."""
    if sub.status is CommandStatus.SUCCESS:
        return 'Done'
    if sub.status is CommandStatus.FAILED:
        return f'Exit code: {sub.exit_code}'
    if sub.status is CommandStatus.SKIPPED:
        return 'Skipped'
    if sub.status is CommandStatus.INTERRUPTED:
        return 'Interrupted'
    return ''


class TabState:
    def __init__(self, entry: CommandEntry, tab_index: int):
        self.entry = entry
        self.tab_index = tab_index
        self.sub_commands: List[SubCommand] = []
        self._next_sub_id = 0

    def _append_sub_command(
        self, name: str, shell_command: str, chained: bool = False
    ) -> SubCommand:
        pane_id = f'cmd-pane-{self.tab_index}-{self._next_sub_id}'
        sub = SubCommand(
            name=name,
            shell_command=shell_command,
            pane_id=pane_id,
            chained=chained,
        )
        self._next_sub_id += 1
        self.sub_commands.append(sub)
        return sub

    def add_sub_command(
        self, name: str, argv: List[str], chained: bool = False
    ) -> SubCommand:
        shell_command = self.entry.make_shell_command(argv)
        return self._append_sub_command(name, shell_command, chained=chained)

    def add_sub_command_raw(self, name: str, raw_command: str) -> SubCommand:
        shell_command = self.entry.make_raw_shell_command(raw_command)
        return self._append_sub_command(name, shell_command)

    def add_recorded_sub_command(
        self, record: run_history.SubCommandRecord
    ) -> SubCommand:
        """Re-create a sub-command from history.

        The stored `shell_command` is used verbatim: it already had the tab's
        `cwd`/`prefix` folded into it when it first ran, and re-deriving it
        would risk resuming something subtly different from what was recorded.
        """
        sub = self._append_sub_command(
            record.name, record.shell_command, chained=record.chained
        )
        sub.status = command_status.on_load(record.status)
        sub.exit_code = record.exit_code
        return sub

    @property
    def active_sub_command_index(self) -> Optional[int]:
        """The sub-command worth showing when this tab is opened.

        The one that is running, or the next one up if the tab is between
        commands. Falls back to the last one once the whole queue is done --
        with nothing left to watch, its output is what you came to read.
        """
        if not self.sub_commands:
            return None
        for status in (CommandStatus.RUNNING, CommandStatus.PENDING):
            for i, sub_command in enumerate(self.sub_commands):
                if sub_command.status is status:
                    return i
        return len(self.sub_commands) - 1

    @property
    def is_idle(self) -> bool:
        if not self.sub_commands:
            return True
        return all(s.status in _FINISHED_STATUSES for s in self.sub_commands)

    @property
    def aggregate_status(self) -> CommandStatus:
        if not self.sub_commands:
            return CommandStatus.PENDING
        statuses = {s.status for s in self.sub_commands}
        for status in command_status.AGGREGATE_PRECEDENCE:
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
        /* Reserve the scrollbar column up front. Textual only posts `Resize`
           when the widget's own size changes, so a scrollbar appearing once
           the output overflows silently narrows the content region by one
           column -- the emulator and the pty keep the old width until some
           unrelated relayout corrects them, and everything printed until then
           is re-folded one column short (a trailing character per line spills
           onto a line of its own). */
        scrollbar-gutter: stable;
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
        # rbxCommandApp intercepts '?' in on_key to open the legacy HelpModal
        # instead of the inherited side panel, so hide the inherited footer
        # entry (unification tracked in issue #483).
        Binding('question_mark', 'toggle_help_panel', 'Help', show=False),
        ('q', 'quit', 'Quit'),
    ]

    def __init__(
        self,
        commands: List[CommandEntry],
        parallel: bool = False,
        keep_going: bool = False,
        run_handle: Optional[run_history.RunHandle] = None,
        restored: bool = False,
    ):
        super().__init__()
        self.commands = commands
        self.parallel = parallel
        self.keep_going = keep_going
        self._run_handle = run_handle
        self._restored = restored
        self._tabs: List[TabState] = []
        self._active_tab: int = 0
        self._label_mode: ProblemLabelMode = get_setter_config().ui.problem_label
        self._task_queue = TaskQueue(
            num_terminals=len(commands),
            parallel=parallel,
            on_task_ready=lambda t: self.post_message(self.TaskReady(t)),
        )
        self._pending_command: Optional[str] = None
        self._pending_menu: Optional[str] = None
        self._pane_size: Tuple[int, int] = (0, 0)

        # Initialize tab states and add initial sub-commands.
        for i, cmd in enumerate(commands):
            tab = TabState(entry=cmd, tab_index=i)
            if restored and run_handle is not None:
                for record in run_handle.manifest.tabs[i].sub_commands:
                    tab.add_recorded_sub_command(record)
            else:
                chained = len(cmd.argvs) > 1
                for argv in cmd.argvs:
                    if not argv:
                        continue
                    tab.add_sub_command(name=' '.join(argv), argv=argv, chained=chained)
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
                    self._get_select_options(0) or [('—', -1)],
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

    def _entry_label(self, entry: CommandEntry) -> str:
        if entry.labels:
            return entry.labels.get(self._label_mode) or entry.display_name
        return entry.display_name

    def _make_tab_label(self, index: int) -> str:
        tab = self._tabs[index]
        icon = _STATUS_MARKUP[tab.aggregate_status]
        name = self._entry_label(tab.entry)
        return f'{icon} {name}'

    def _update_sidebar(self, index: int):
        item = self.query_one(f'#cmd-item-{index}', ListItem)
        label = item.query_one(Label)
        label.update(self._make_tab_label(index))

    def _has_labels(self) -> bool:
        return any(t.entry.labels for t in self._tabs)

    def _sidebar_subtitle(self) -> str:
        if self._has_labels():
            return f'[b]l[/b] label: {self._label_mode.value}  [b]?[/b] help'
        return _SIDEBAR_SUBTITLE

    def _update_sidebar_subtitle(self) -> None:
        sidebar = self.query_one('#command-list', ListView)
        sidebar.border_subtitle = self._sidebar_subtitle()

    def _cycle_problem_label(self) -> None:
        modes = list(ProblemLabelMode)
        nxt = modes[(modes.index(self._label_mode) + 1) % len(modes)]
        self._label_mode = nxt
        set_problem_label(nxt)
        for i in range(len(self._tabs)):
            self._update_sidebar(i)
        self._update_sidebar_subtitle()

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
        select.set_options(options or [('—', -1)])
        # Try to preserve selection; if it no longer exists, select last.
        if any(v == current_value for _, v in options):
            select.value = current_value
        elif options:
            select.value = options[-1][1]

    def _pane_dimensions(self) -> Tuple[int, int]:
        """Size a hidden pane should pretend to have."""
        return self._pane_size

    def sync_hidden_pane_sizes(self, source: CommandPane) -> None:
        """Propagate a laid-out pane's geometry to the hidden ones.

        Only one pane is displayed at a time, and a hidden widget has a
        zero-sized region -- so a hidden pane never learns the terminal size and
        its command runs on a 0x0 pty, which every size-aware program (rich,
        included) reads as the 80-column fallback. Switching to that tab then
        shows output hard-wrapped at 80 inside a much wider pane.
        """
        width, height = source.scrollable_content_region.size
        if width <= 0 or height <= 0 or (width, height) == self._pane_size:
            return
        self._pane_size = (width, height)
        for pane in self.query(_AppCommandPane):
            if pane is not source:
                pane.refresh_terminal_size()

    def _make_pane(self, pane_id: str) -> '_AppCommandPane':
        return _AppCommandPane(
            id=pane_id, get_fallback_dimensions=self._pane_dimensions
        )

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
        sidebar.border_subtitle = self._sidebar_subtitle()

        select = self.query_one('#command-select', Select)
        select.border_subtitle = _SELECT_SUBTITLE

        # Mount initial CommandPanes.
        container = self.query_one('#command-pane-container', Vertical)
        for tab in self._tabs:
            for sub in tab.sub_commands:
                pane = self._make_pane(sub.pane_id)
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

        if self._restored:
            # Nothing runs on open: the panes are filled from disk and the run
            # sits idle until the user retries, resumes, or types a command.
            self._restore_subtitles()
            self.run_worker(self._restore_panes(), exclusive=False)
        else:
            # Enqueue initial commands.
            for i, tab in enumerate(self._tabs):
                for sub in tab.sub_commands:
                    task = self._task_queue.enqueue(sub.shell_command, terminal_id=i)
                    sub.task_id = task.task_id

        self._persist()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """Mirror the live tabs into the manifest and write it out.

        Called on every status change, so history on disk is complete up to the
        last finished command at all times -- whatever happens to the process
        next.
        """
        if self._run_handle is None:
            return
        self._run_handle.manifest.tabs = [
            run_history.TabRecord(
                name=tab.entry.display_name,
                cwd=tab.entry.cwd,
                prefix=tab.entry.prefix,
                placeholder_prefix=tab.entry.placeholder_prefix,
                labels=(
                    {mode.value: label for mode, label in tab.entry.labels.items()}
                    if tab.entry.labels
                    else None
                ),
                sub_commands=[
                    run_history.SubCommandRecord(
                        name=sub.name,
                        shell_command=sub.shell_command,
                        status=sub.status,
                        exit_code=sub.exit_code,
                        chained=sub.chained,
                    )
                    for sub in tab.sub_commands
                ],
            )
            for tab in self._tabs
        ]
        try:
            self._run_handle.save()
        except OSError:
            # History is a convenience; never take the session down for it.
            pass

    def _dump_pane(self, tab_index: int, sub_index: int, sub: SubCommand) -> None:
        if self._run_handle is None:
            return
        try:
            pane = self.query_one(f'#{sub.pane_id}', CommandPane)
        except NoMatches:
            return
        try:
            dumped = run_history.dump_buffer(pane.state.scrollback_buffer)
        except Exception:
            return
        if not dumped:
            return
        try:
            self._run_handle.write_pane(tab_index, sub_index, dumped)
        except OSError:
            pass

    def _dump_all_panes(self) -> None:
        for tab_index, tab in enumerate(self._tabs):
            for sub_index, sub in enumerate(tab.sub_commands):
                self._dump_pane(tab_index, sub_index, sub)

    def on_unmount(self) -> None:
        """Keep whatever was on screen when the app goes away.

        A command still running here never reported an exit code; it is
        persisted as RUNNING and reloads as INTERRUPTED.
        """
        self._dump_all_panes()
        self._persist()

    def _restore_subtitles(self) -> None:
        for tab in self._tabs:
            for sub in tab.sub_commands:
                try:
                    pane = self.query_one(f'#{sub.pane_id}', CommandPane)
                except NoMatches:
                    continue
                pane.border_subtitle = _subtitle_for(sub)

    async def _restore_panes(self) -> None:
        for tab_index, tab in enumerate(self._tabs):
            for sub_index, sub in enumerate(tab.sub_commands):
                if self._run_handle is None:
                    return
                dumped = self._run_handle.read_pane(tab_index, sub_index)
                if not dumped:
                    continue
                try:
                    pane = self.query_one(f'#{sub.pane_id}', CommandPane)
                except NoMatches:
                    continue
                await pane.write(run_history.to_terminal_input(dumped))

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
        self._follow_running_sub_command(task.terminal_id, sub)
        pane = self.query_one(f'#{sub.pane_id}', CommandPane)
        pane.execute(task.command)

    def _follow_running_sub_command(self, tab_index: int, started: SubCommand) -> None:
        """Move the view onto a command that just started.

        Only when the view is parked on a command that already finished --
        typically the previous link of the same chain. A pending selection is
        someone looking ahead on purpose, so it is left alone.
        """
        if tab_index != self._active_tab:
            return
        tab = self._tabs[tab_index]
        select = self.query_one('#command-select', Select)
        if select.value is Select.BLANK:
            return
        current: int = select.value  # type: ignore[assignment]
        if not 0 <= current < len(tab.sub_commands):
            return
        if tab.sub_commands[current].status not in _FINISHED_STATUSES:
            return
        select.value = tab.sub_commands.index(started)
        self._show_pane(started.pane_id)

    def _on_tab_selected(self, index: Optional[int]):
        if index is None:
            return
        self._switch_tab(index)

    def _switch_tab(self, index: int):
        self._active_tab = index
        self._refresh_select()

        # Land on the command that is actually executing, not on the tail of
        # the queue -- with a chain, the last one has not started yet.
        tab = self._tabs[index]
        select = self.query_one('#command-select', Select)
        active = tab.active_sub_command_index
        if active is not None:
            select.value = active
            self._show_pane(tab.sub_commands[active].pane_id)
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

        if event.character == 'r':
            event.stop()
            event.prevent_default()
            self.run_worker(self._retry_current(), exclusive=False)
            return

        if event.character == 'R':
            event.stop()
            event.prevent_default()
            self._open_resume_menu()
            return

        if event.character == 'l' and self._has_labels():
            event.stop()
            event.prevent_default()
            self._cycle_problem_label()
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

                sub.exit_code = pane.return_code
                if pane.return_code == 0:
                    sub.status = CommandStatus.SUCCESS
                else:
                    sub.status = CommandStatus.FAILED
                pane.border_subtitle = _subtitle_for(sub)

                if sub.status == CommandStatus.FAILED:
                    self._skip_rest_of_chain(tab_index, sub)

                self._update_sidebar(tab_index)
                self._refresh_select_if_active(tab_index)
                # Dump before releasing the terminal: the next command in the
                # queue may start the moment `notify_complete` returns.
                self._dump_pane(tab_index, tab.sub_commands.index(sub), sub)
                self._persist()
                if sub.task_id is not None:
                    self._task_queue.notify_complete(sub.task_id)
                return

    def _skip_rest_of_chain(self, tab_index: int, failed: SubCommand) -> None:
        """Cancel the rest of a failed CLI chain in this tab.

        Runs before `notify_complete` releases the terminal, otherwise the
        queue would drain the next command before it is cancelled. Commands
        queued interactively are left alone -- they keep going by design.
        """
        if self.keep_going or not failed.chained:
            return
        tab = self._tabs[tab_index]
        for later in tab.sub_commands[tab.sub_commands.index(failed) + 1 :]:
            if later.status != CommandStatus.PENDING or not later.chained:
                continue
            if later.task_id is None or not self._task_queue.cancel(later.task_id):
                continue
            later.status = CommandStatus.SKIPPED
            later.task_id = None
            try:
                pane = self.query_one(f'#{later.pane_id}', CommandPane)
            except NoMatches:
                continue
            pane.border_subtitle = 'Skipped'

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
        pane = self._make_pane(sub.pane_id)
        pane.border_title = sub.name
        pane.display = False
        container.mount(pane)

        self._update_sidebar(tab_index)
        self._refresh_select_if_active(tab_index)

        task = self._task_queue.enqueue(sub.shell_command, terminal_id=tab_index)
        sub.task_id = task.task_id
        self._persist()
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
        queued = 0
        for i in range(len(self._tabs)):
            sub = self._queue_command_in_tab(i, raw_input)
            if sub.status == CommandStatus.PENDING:
                queued += 1
        self._show_latest_sub_command()
        if queued > 0:
            self.notify(f'Command queued in {queued} tab(s)')

    # ------------------------------------------------------------------
    # Retry and resume
    # ------------------------------------------------------------------

    def _resumable_in_tab(self, tab_index: int) -> List[Tuple[int, SubCommand]]:
        return [
            (i, sub)
            for i, sub in enumerate(self._tabs[tab_index].sub_commands)
            if command_status.is_resumable(sub.status)
        ]

    def _resumable_count(self, tab_indices: List[int]) -> int:
        return sum(len(self._resumable_in_tab(i)) for i in tab_indices)

    async def _reset_pane(
        self, tab_index: int, sub_index: int, sub: SubCommand
    ) -> None:
        """Give a command a clean slate to run in again.

        `CommandPane.execute` appends to the terminal state rather than
        clearing it, so re-running in place would stack the new attempt under
        the old one. Swapping in a fresh pane under the same id is the only way
        to get an empty terminal, and the stored output goes with it -- only
        the latest attempt is kept.
        """
        container = self.query_one('#command-pane-container', Vertical)
        displayed = False
        try:
            old = self.query_one(f'#{sub.pane_id}', CommandPane)
        except NoMatches:
            old = None
        if old is not None:
            displayed = old.display
            # Awaited: mounting the replacement before the old widget is gone
            # would collide on the duplicate id.
            await old.remove()

        pane = self._make_pane(sub.pane_id)
        pane.border_title = sub.name
        pane.display = displayed
        await container.mount(pane)

        if self._run_handle is not None:
            self._run_handle.clear_pane(tab_index, sub_index)
        sub.status = CommandStatus.PENDING
        sub.exit_code = None

    def _enqueue_sub(self, tab_index: int, sub: SubCommand) -> None:
        task = self._task_queue.enqueue(sub.shell_command, terminal_id=tab_index)
        sub.task_id = task.task_id

    async def _resume_tabs(self, tab_indices: List[int]) -> None:
        targets: List[Tuple[int, int, SubCommand]] = []
        for tab_index in tab_indices:
            for sub_index, sub in self._resumable_in_tab(tab_index):
                targets.append((tab_index, sub_index, sub))
        if not targets:
            self.notify('Nothing to resume')
            return

        # Every pane is reset before anything is enqueued, so the whole batch is
        # PENDING by the time the first command can finish. Otherwise a fast
        # failure could complete while later links of its chain were not yet
        # queued, and `_skip_rest_of_chain` would have nothing to cancel.
        for tab_index, sub_index, sub in targets:
            await self._reset_pane(tab_index, sub_index, sub)
        for tab_index, _, sub in targets:
            self._enqueue_sub(tab_index, sub)

        for tab_index in sorted({t for t, _, _ in targets}):
            self._update_sidebar(tab_index)
        self._refresh_select_if_active(self._active_tab)
        self._persist()
        self.notify(f'Resumed {len(targets)} command(s)')

    async def _retry_current(self) -> None:
        tab = self._tabs[self._active_tab]
        select = self.query_one('#command-select', Select)
        if select.value is Select.BLANK:
            return
        sub_index: int = select.value  # type: ignore[assignment]
        if not 0 <= sub_index < len(tab.sub_commands):
            return
        sub = tab.sub_commands[sub_index]
        if sub.status in (CommandStatus.PENDING, CommandStatus.RUNNING):
            self.notify('Command is already queued')
            return
        await self._reset_pane(self._active_tab, sub_index, sub)
        self._enqueue_sub(self._active_tab, sub)
        self._update_sidebar(self._active_tab)
        self._refresh_select_if_active(self._active_tab)
        self._persist()
        self.notify(f'Retrying {sub.name}')

    def _start_resume(self, tab_indices: List[int]) -> None:
        self.run_worker(self._resume_tabs(tab_indices), exclusive=False)

    def _open_resume_menu(self) -> None:
        total = self._resumable_count(list(range(len(self._tabs))))
        if total == 0:
            self.notify('Nothing to resume')
            return
        self._dismiss_menu()
        self._pending_menu = 'resume'
        here = self._resumable_count([self._active_tab])
        menu = Menu(
            [
                MenuItem(f'Resume this tab ({here} commands)', 'resume_this_tab', '1'),
                MenuItem(f'Resume all tabs ({total} commands)', 'resume_all_tabs', '2'),
                MenuItem('Resume selected tabs', 'resume_selected_tabs', '3'),
            ],
        )
        input_container = self.query_one('#command-input-container', Horizontal)
        input_container.mount(menu)
        menu.focus()

    def _on_resume_tabs_selected(self, indices: Optional[List[int]]) -> None:
        if indices:
            self._start_resume(indices)
        self._focus_sidebar()

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
        self._pending_menu = 'run'
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
        self._pending_menu = None
        event.menu.remove()

        if event.action.startswith('resume_'):
            if event.action == 'resume_selected_tabs':
                self.push_screen(
                    TabSelectorModal(
                        [self._make_tab_label(i) for i in range(len(self._tabs))]
                    ),
                    callback=self._on_resume_tabs_selected,
                )
                return
            tab_indices = (
                [self._active_tab]
                if event.action == 'resume_this_tab'
                else list(range(len(self._tabs)))
            )
            self._start_resume(tab_indices)
            self._focus_sidebar()
            return

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
        self._pending_menu = None
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
        queued = 0
        for i in tab_indices:
            if 0 <= i < len(self._tabs):
                sub = self._queue_command_in_tab(i, raw_input)
                if sub.status == CommandStatus.PENDING:
                    queued += 1
        if self._active_tab in tab_indices:
            self._show_latest_sub_command()
        if queued > 0:
            self.notify(f'Command queued in {queued} tab(s)')


def _create_run_handle() -> Optional[run_history.RunHandle]:
    """Start recording this run, if we are inside a contest.

    Never fatal: a session that cannot write history is still a working session.
    """
    try:
        from rbx.box.contest import contest_state

        store = run_history.get_contest_run_store()
        if store is None:
            return None
        store.prune()
        now = datetime.datetime.now()
        return store.create_run(
            run_history.RunManifest(
                run_id=run_history.new_run_id(now),
                started_at=now,
                updated_at=now,
                contest_id=contest_state.resolve_explicit_selection(),
            )
        )
    except Exception:
        return None


def start_command_app(
    commands: List[CommandEntry],
    parallel: bool = False,
    keep_going: bool = False,
) -> None:
    app = rbxCommandApp(
        commands,
        parallel=parallel,
        keep_going=keep_going,
        run_handle=_create_run_handle(),
    )
    app.run()


if __name__ == '__main__':
    start_command_app(
        [
            CommandEntry(argvs=[['echo', 'hello']], name='echo1'),
            CommandEntry(argvs=[['echo', 'world']], name='echo2'),
            CommandEntry(argvs=[['echo', 'foo']], name='echo3'),
        ]
    )
