# Command App Tabbed Commands Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance `rbxCommandApp` so each tab maintains a queue of commands with independent terminals, a dropdown to navigate command history, and an input box to queue new commands.

**Architecture:** Each tab tracks a list of sub-commands (initial argv + user-added). Each sub-command gets its own `CommandPane`. A `Select` dropdown switches between sub-command terminals. An `Input` widget at the bottom lets users type commands, with Enter queueing to the current tab and Shift+Enter queueing to all tabs. Each tab runs its queue sequentially. Toast notifications appear when commands are queued.

**Tech Stack:** Textual (Select, Input, CommandPane), Python asyncio for queuing

---

### Task 1: Add `prefix` field to `CommandEntry` and update `shell_command`

**Files:**
- Modify: `rbx/box/ui/command_app.py:30-45`

**Step 1: Add `prefix` field and update shell_command logic**

In the `CommandEntry` dataclass, add `prefix: Optional[str] = None`. Update `shell_command` to prepend the prefix to the command. Add a helper `make_shell_command(argv)` that builds a shell command from an argv list, applying the cwd and prefix of this entry.

```python
@dataclasses.dataclass
class CommandEntry:
    argv: List[str]
    name: Optional[str] = None
    cwd: Optional[str] = None
    prefix: Optional[str] = None

    @property
    def display_name(self) -> str:
        return self.name if self.name else ' '.join(self.argv)

    def make_shell_command(self, argv: List[str]) -> str:
        cmd = shlex.join(argv)
        if self.prefix is not None:
            cmd = f'{self.prefix} {cmd}'
        if self.cwd is not None:
            cmd = f'cd {shlex.quote(self.cwd)} && exec {cmd}'
        return cmd

    @property
    def shell_command(self) -> str:
        return self.make_shell_command(self.argv)
```

**Step 2: Verify nothing breaks**

Run: `uv run ruff check rbx/box/ui/command_app.py`

**Step 3: Commit**

```
feat(ui): add prefix field to CommandEntry
```

---

### Task 2: Introduce `TabState` to track per-tab sub-commands and queue

**Files:**
- Modify: `rbx/box/ui/command_app.py`

**Step 1: Create `SubCommand` dataclass and `TabState` class**

`SubCommand` holds a display name, the shell command string, a status, and a reference to its `CommandPane` widget id. `TabState` holds the parent `CommandEntry`, a list of `SubCommand`s, and manages the queue.

```python
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
        self._running_index: Optional[int] = -1

    def add_sub_command(self, name: str, argv: List[str]) -> SubCommand:
        shell_command = self.entry.make_shell_command(argv)
        pane_id = f'cmd-pane-{self.tab_index}-{self._next_sub_id}'
        sub = SubCommand(
            name=name,
            shell_command=shell_command,
            pane_id=pane_id,
        )
        self._next_sub_id += 1
        self.sub_commands.append(sub)
        return sub

    @property
    def is_idle(self) -> bool:
        return all(
            s.status in (CommandStatus.SUCCESS, CommandStatus.FAILED)
            for s in self.sub_commands
        )

    @property
    def current_sub_index(self) -> Optional[int]:
        """Index of the currently running sub-command, or None."""
        for i, s in enumerate(self.sub_commands):
            if s.status == CommandStatus.RUNNING:
                return i
        return None

    def next_pending(self) -> Optional[int]:
        for i, s in enumerate(self.sub_commands):
            if s.status == CommandStatus.PENDING:
                return i
        return None
```

**Step 2: Verify lint**

Run: `uv run ruff check rbx/box/ui/command_app.py`

**Step 3: Commit**

```
feat(ui): add TabState and SubCommand for per-tab command tracking
```

---

### Task 3: Rewrite `rbxCommandApp` compose to use Select dropdown + Input

**Files:**
- Modify: `rbx/box/ui/command_app.py`

**Step 1: Update imports and CSS**

Add `Select`, `Input` to textual imports. Update `DEFAULT_CSS` to style the new layout: the dropdown at the top of the right panel, input box at the bottom, command panes filling the middle.

```python
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Select
```

New CSS additions:

```css
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
```

**Step 2: Rewrite `compose()` method**

The new layout: left sidebar (tab list), right area with Select dropdown at top, CommandPane container in middle, Input at bottom.

```python
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
            yield Select(
                [],
                prompt='No commands yet',
                id='command-select',
                allow_blank=False,
            )
            with Vertical(id='command-pane-container'):
                pass  # CommandPanes added dynamically
            yield Input(
                placeholder='Type a command and press Enter...',
                id='command-input',
            )
```

**Step 3: Verify lint**

Run: `uv run ruff check rbx/box/ui/command_app.py`

**Step 4: Commit**

```
feat(ui): rewrite command app compose with Select dropdown and Input
```

---

### Task 4: Implement tab initialization and sub-command lifecycle

**Files:**
- Modify: `rbx/box/ui/command_app.py`

**Step 1: Rewrite `__init__` to create `TabState` objects**

```python
def __init__(self, commands: List[CommandEntry], parallel: bool = False):
    super().__init__()
    self.commands = commands
    self.parallel = parallel
    self._tabs: List[TabState] = []
    self._active_tab: int = 0

    for i, cmd in enumerate(commands):
        tab = TabState(entry=cmd, tab_index=i)
        tab.add_sub_command(cmd.display_name, cmd.argv)
        self._tabs.append(tab)
```

**Step 2: Implement `on_mount` to wire up watchers and start execution**

- Set border title on the tab list.
- Mount the initial CommandPanes for each tab's first sub-command.
- Watch ListView index for tab switching.
- Start execution (parallel or sequential across tabs; within each tab, always sequential).

```python
async def on_mount(self):
    self.query_one('#command-list', ListView).border_title = 'Commands'

    # Mount initial command panes for each tab
    container = self.query_one('#command-pane-container')
    for tab in self._tabs:
        sub = tab.sub_commands[0]
        pane = CommandPane(id=sub.pane_id)
        await container.mount(pane)
        pane.display = False

    # Show first tab
    self._switch_to_tab(0)

    self.watch(
        self.query_one('#command-list', ListView),
        'index',
        self._on_tab_selected,
    )

    # Start execution
    if self.parallel:
        for tab in self._tabs:
            self._start_next_in_tab(tab)
    else:
        asyncio.create_task(self._run_tabs_sequential())
```

**Step 3: Implement `_switch_to_tab` and `_show_sub_command`**

`_switch_to_tab(index)` updates `_active_tab`, rebuilds the Select dropdown options for that tab, and shows the currently selected sub-command's pane. `_show_sub_command(tab, sub_index)` hides all panes and shows only the selected one.

```python
def _switch_to_tab(self, tab_index: int):
    self._active_tab = tab_index
    self._refresh_select()
    tab = self._tabs[tab_index]
    # Show the latest sub-command by default (or currently selected)
    select = self.query_one('#command-select', Select)
    if select.value is Select.BLANK:
        self._show_sub_command(len(tab.sub_commands) - 1)
    else:
        self._show_sub_command(select.value)
    # Update input placeholder with prefix
    input_widget = self.query_one('#command-input', Input)
    prefix = tab.entry.prefix
    if prefix:
        input_widget.placeholder = f'{prefix} <command>'
    else:
        input_widget.placeholder = 'Type a command and press Enter...'

def _refresh_select(self):
    tab = self._tabs[self._active_tab]
    select = self.query_one('#command-select', Select)
    options = [
        (f'{_STATUS_MARKUP[s.status]} {s.name}', i)
        for i, s in enumerate(tab.sub_commands)
    ]
    select.set_options(options)
    select.value = len(tab.sub_commands) - 1

def _show_sub_command(self, sub_index: int):
    """Show only the pane for the given sub-command index in the active tab."""
    container = self.query_one('#command-pane-container')
    for pane in container.query(CommandPane):
        pane.display = False
    tab = self._tabs[self._active_tab]
    if 0 <= sub_index < len(tab.sub_commands):
        pane_id = tab.sub_commands[sub_index].pane_id
        self.query_one(f'#{pane_id}', CommandPane).display = True
```

**Step 4: Implement `_start_next_in_tab`**

Finds the next pending sub-command in a tab and starts it.

```python
def _start_next_in_tab(self, tab: TabState):
    idx = tab.next_pending()
    if idx is None:
        return
    sub = tab.sub_commands[idx]
    sub.status = CommandStatus.RUNNING
    self._refresh_tab_sidebar(tab.tab_index)
    if self._active_tab == tab.tab_index:
        self._refresh_select()
    pane = self.query_one(f'#{sub.pane_id}', CommandPane)
    pane.border_title = sub.name
    pane.execute(sub.shell_command)
```

**Step 5: Implement command completion handler**

When a `CommandPane.CommandComplete` fires, find which tab/sub-command it belongs to, update status, and start the next queued command.

```python
def on_command_pane_command_complete(self, event: CommandPane.CommandComplete):
    for tab in self._tabs:
        for sub in tab.sub_commands:
            if sub.status != CommandStatus.RUNNING:
                continue
            pane = self.query_one(f'#{sub.pane_id}', CommandPane)
            if pane.return_code is None:
                continue
            if pane.return_code == 0:
                sub.status = CommandStatus.SUCCESS
                pane.border_subtitle = 'Done'
            else:
                sub.status = CommandStatus.FAILED
                pane.border_subtitle = f'Exit code: {pane.return_code}'
            self._refresh_tab_sidebar(tab.tab_index)
            if self._active_tab == tab.tab_index:
                self._refresh_select()
            # Start next queued command in this tab
            self._start_next_in_tab(tab)
            if not self.parallel:
                self._sequential_event.set()
            return
```

**Step 6: Implement sequential tab runner**

```python
async def _run_tabs_sequential(self):
    self._sequential_event = asyncio.Event()
    for tab in self._tabs:
        self._sequential_event.clear()
        self._start_next_in_tab(tab)
        await self._sequential_event.wait()
```

**Step 7: Implement tab sidebar helpers**

```python
def _make_tab_label(self, index: int) -> str:
    tab = self._tabs[index]
    # Tab status: show worst status of sub-commands
    if any(s.status == CommandStatus.FAILED for s in tab.sub_commands):
        icon = _STATUS_MARKUP[CommandStatus.FAILED]
    elif any(s.status == CommandStatus.RUNNING for s in tab.sub_commands):
        icon = _STATUS_MARKUP[CommandStatus.RUNNING]
    elif all(s.status == CommandStatus.SUCCESS for s in tab.sub_commands):
        icon = _STATUS_MARKUP[CommandStatus.SUCCESS]
    else:
        icon = _STATUS_MARKUP[CommandStatus.PENDING]
    return f'{icon} {tab.entry.display_name}'

def _refresh_tab_sidebar(self, tab_index: int):
    item = self.query_one(f'#cmd-item-{tab_index}', ListItem)
    label = item.query_one(Label)
    label.update(self._make_tab_label(tab_index))
```

**Step 8: Verify lint**

Run: `uv run ruff check rbx/box/ui/command_app.py`

**Step 9: Commit**

```
feat(ui): implement tab lifecycle and sub-command queue execution
```

---

### Task 5: Implement input handling (Enter and Shift+Enter)

**Files:**
- Modify: `rbx/box/ui/command_app.py`

**Step 1: Add `_queue_command` method**

This method adds a new sub-command to a tab, mounts a new CommandPane, and starts it if the tab is idle.

```python
async def _queue_command(self, tab: TabState, user_input: str):
    argv = shlex.split(user_input)
    name = user_input
    sub = tab.add_sub_command(name, argv)

    # Mount the new pane
    container = self.query_one('#command-pane-container')
    pane = CommandPane(id=sub.pane_id)
    await container.mount(pane)
    pane.display = False

    if tab.is_idle:
        self._start_next_in_tab(tab)
    else:
        self.notify(
            f'Command queued in {tab.entry.display_name}',
            title='Queued',
            timeout=3,
        )

    # Refresh UI if this is the active tab
    if self._active_tab == tab.tab_index:
        self._refresh_select()
        # Switch view to the new sub-command
        self._show_sub_command(len(tab.sub_commands) - 1)
```

**Step 2: Handle Enter key on Input (current tab only)**

```python
async def on_input_submitted(self, event: Input.Submitted):
    user_input = event.value.strip()
    if not user_input:
        return
    event.input.value = ''
    tab = self._tabs[self._active_tab]
    await self._queue_command(tab, user_input)
```

**Step 3: Handle Shift+Enter binding (all tabs)**

Add a binding for shift+enter and implement the handler.

```python
BINDINGS = [
    ('q', 'quit', 'Quit'),
    ('shift+enter', 'submit_all', 'Run in all tabs'),
]

async def action_submit_all(self):
    input_widget = self.query_one('#command-input', Input)
    user_input = input_widget.value.strip()
    if not user_input:
        return
    input_widget.value = ''
    for tab in self._tabs:
        await self._queue_command(tab, user_input)
```

**Step 4: Verify lint**

Run: `uv run ruff check rbx/box/ui/command_app.py`

**Step 5: Commit**

```
feat(ui): add input handling for Enter and Shift+Enter command queueing
```

---

### Task 6: Wire up Select dropdown and tab switching

**Files:**
- Modify: `rbx/box/ui/command_app.py`

**Step 1: Handle Select.Changed to switch visible pane**

```python
def on_select_changed(self, event: Select.Changed):
    if event.value is Select.BLANK:
        return
    self._show_sub_command(event.value)
```

**Step 2: Handle ListView index change for tab switching**

```python
def _on_tab_selected(self, index: Optional[int]):
    if index is None:
        return
    self._switch_to_tab(index)
```

**Step 3: Verify lint**

Run: `uv run ruff check rbx/box/ui/command_app.py`

**Step 4: Commit**

```
feat(ui): wire up Select dropdown and tab switching
```

---

### Task 7: Manual testing and polish

**Step 1: Test with the `__main__` block**

Update the `__main__` block to exercise multiple tabs, prefix, and cwd:

```python
if __name__ == '__main__':
    start_command_app([
        CommandEntry(argv=['ls', '-l'], name='list', prefix='env'),
        CommandEntry(argv=['echo', 'hello'], name='echo'),
    ])
```

Run: `uv run python -m rbx.box.ui.command_app`

Verify:
- Two tabs appear in sidebar
- Each tab has a dropdown showing its initial command with status icon
- Input box at the bottom accepts commands
- Enter queues in current tab, Shift+Enter in all tabs
- Toast notification appears when commands are queued
- Dropdown updates with new commands as they are added
- Selecting a dropdown entry switches the visible terminal

**Step 2: Verify existing callers still work**

Check `rbx/box/contest/main.py` — it only uses `CommandEntry(argv=..., name=..., cwd=...)` which is unchanged. The new `prefix` field defaults to `None`.

**Step 3: Final lint and format**

Run: `uv run ruff check rbx/box/ui/command_app.py && uv run ruff format rbx/box/ui/command_app.py`

**Step 4: Commit**

```
feat(ui): finalize command app with tabbed command queuing
```
