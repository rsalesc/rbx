# Command Input Context Menu Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace direct Enter-to-submit in `rbxCommandApp` with a floating context menu that lets the user choose to run the command in the current tab, all tabs, or a selected subset of tabs.

**Architecture:** On Enter, a floating `Menu` widget (inspired by Toad's `Menu`) appears above the input with 3 options. "Run in this tab" is pre-highlighted so double-Enter preserves old quick workflow. "Run in selected tabs" opens a `TabSelectorModal` (using Textual's `SelectionList`). The Ctrl+O binding is removed.

**Tech Stack:** Textual 8.0 (ListView, SelectionList, ModalScreen), Python dataclasses

---

### Task 1: Create Menu widget

**Files:**
- Create: `rbx/box/ui/widgets/menu.py`

**Step 1: Create the Menu widget file**

This is a self-contained floating overlay menu inspired by `/private/tmp/toad/src/toad/widgets/menu.py`. Key differences from Toad: no `owner` parameter, no `_partition` (all items in order), simplified messages.

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import List, NamedTuple, Optional

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Label, ListItem, ListView


class MenuItem(NamedTuple):
    """An entry in a Menu."""

    description: str
    action: str
    key: Optional[str] = None


class _MenuOptionLabel(Label):
    ALLOW_SELECT = False


class MenuOption(ListItem):
    ALLOW_SELECT = False

    def __init__(
        self, action: str, description: str, key: Optional[str]
    ) -> None:
        self._action = action
        self._description = description
        self._key = key
        super().__init__()

    def compose(self) -> ComposeResult:
        yield _MenuOptionLabel(self._key or ' ', id='key')
        yield _MenuOptionLabel(self._description, id='description')


class Menu(ListView, can_focus=True):
    BINDINGS = [Binding('escape', 'dismiss', 'Dismiss')]

    DEFAULT_CSS = """
    Menu {
        width: auto;
        height: auto;
        max-width: 100%;
        overlay: screen;
        position: absolute;
        color: $foreground;
        background: $panel;
        border: round $accent;
        constrain: inside inside;
        padding: 0;

        & > MenuOption {
            layout: horizontal;
            width: 1fr;
            padding: 0 1;
            height: auto !important;
            overflow: auto;
            #description {
                color: $text 80%;
                width: 1fr;
            }
            #key {
                padding-right: 1;
                text-style: bold;
            }
        }

        &:blur {
            background-tint: transparent;
            & > ListItem.-highlight {
                color: $block-cursor-blurred-foreground;
                background: $block-cursor-blurred-background 30%;
                text-style: $block-cursor-blurred-text-style;
            }
        }

        &:focus {
            background-tint: transparent;
            & > ListItem.-highlight {
                color: $block-cursor-blurred-foreground;
                background: $block-cursor-blurred-background;
                text-style: $block-cursor-blurred-text-style;
            }
        }
    }
    """

    @dataclass
    class Selected(Message):
        menu: Menu
        action: str

    @dataclass
    class Dismissed(Message):
        menu: Menu

    def __init__(self, options: List[MenuItem], *args, **kwargs) -> None:
        self._options = options
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        self.extend(
            MenuOption(item.action, item.description, item.key)
            for item in self._options
        )

    async def _activate_index(self, index: int) -> None:
        action = self._options[index].action
        self.post_message(self.Selected(self, action))

    async def action_dismiss(self) -> None:
        self.post_message(self.Dismissed(self))

    async def on_blur(self) -> None:
        self.post_message(self.Dismissed(self))

    @on(events.Key)
    async def _on_key(self, event: events.Key) -> None:
        for index, option in enumerate(self._options):
            if option.key is not None and event.key == option.key:
                self.index = index
                event.stop()
                await self._activate_index(index)
                break

    @on(ListView.Selected)
    async def _on_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if event.index is not None:
            await self._activate_index(event.index)
```

**Step 2: Verify lint**

Run: `uv run ruff check rbx/box/ui/widgets/menu.py && uv run ruff format rbx/box/ui/widgets/menu.py`

**Step 3: Commit**

```
feat(ui): add Menu floating overlay widget
```

---

### Task 2: Create TabSelectorModal screen

**Files:**
- Create: `rbx/box/ui/screens/tab_selector.py`
- Modify: `rbx/box/ui/css/app.tcss` (add styling for the modal)

**Step 1: Create the TabSelectorModal file**

Uses `SelectionList` (already used in `rbx/box/ui/screens/run.py`). Returns `list[int]` of selected tab indices on dismiss, or `None` on cancel.

```python
from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, SelectionList
from textual.widgets.selection_list import Selection


class TabSelectorModal(ModalScreen[Optional[List[int]]]):
    BINDINGS = [
        ('escape', 'cancel', 'Cancel'),
        ('a', 'select_all', 'Select all'),
        ('n', 'deselect_all', 'Deselect all'),
    ]

    def __init__(self, tab_names: List[str]) -> None:
        super().__init__()
        self._tab_names = tab_names

    def compose(self) -> ComposeResult:
        with Container(id='tab-selector-dialog'):
            selection_list = SelectionList[int](
                *[
                    Selection(name, index, False)
                    for index, name in enumerate(self._tab_names)
                ],
                id='tab-selector-list',
            )
            selection_list.border_title = 'Select tabs'
            yield selection_list
            with Horizontal(id='tab-selector-buttons'):
                yield Button('Run', variant='primary', id='tab-selector-run')
                yield Button('Cancel', id='tab-selector-cancel')

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_all(self) -> None:
        self.query_one('#tab-selector-list', SelectionList).select_all()

    def action_deselect_all(self) -> None:
        self.query_one('#tab-selector-list', SelectionList).deselect_all()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'tab-selector-run':
            selected = list(
                self.query_one('#tab-selector-list', SelectionList).selected
            )
            self.dismiss(selected)
        elif event.button.id == 'tab-selector-cancel':
            self.dismiss(None)
```

**Step 2: Add CSS for the modal in `rbx/box/ui/css/app.tcss`**

Append after the existing `#selector-dialog` block (after line 126):

```css
#tab-selector-dialog {
        max-width: 60;
        height: auto;
        max-height: 20;
}

#tab-selector-buttons {
        height: auto;
        width: 100%;
}

#tab-selector-buttons Button {
        width: 1fr;
}
```

**Step 3: Verify lint**

Run: `uv run ruff check rbx/box/ui/screens/tab_selector.py && uv run ruff format rbx/box/ui/screens/tab_selector.py`

**Step 4: Commit**

```
feat(ui): add TabSelectorModal screen for selecting tabs
```

---

### Task 3: Wire Menu and TabSelectorModal into command_app.py

**Files:**
- Modify: `rbx/box/ui/command_app.py`

This is the main integration task. The changes are:

**Step 1: Update imports**

Add these imports at the top of `command_app.py`:

```python
from textual import on

from rbx.box.ui.screens.tab_selector import TabSelectorModal
from rbx.box.ui.widgets.menu import Menu, MenuItem
```

**Step 2: Remove Ctrl+O binding, add pending command state**

In `rbxCommandApp`:
- Remove `('ctrl+o', 'submit_all', 'Run in all tabs')` from `BINDINGS`
- Add `self._pending_command: Optional[str] = None` in `__init__`

The BINDINGS become:

```python
BINDINGS = [
    ('q', 'quit', 'Quit'),
]
```

And in `__init__`, after `self._sequential_event`:

```python
self._pending_command: Optional[str] = None
```

**Step 3: Replace `on_input_submitted` to show Menu instead of direct submit**

Replace the existing `on_input_submitted` method with:

```python
def _dismiss_menu(self) -> None:
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
```

**Step 4: Add Menu.Selected and Menu.Dismissed handlers**

```python
@on(Menu.Selected)
def _on_menu_selected(self, event: Menu.Selected) -> None:
    event.stop()
    raw = self._pending_command
    self._pending_command = None
    event.menu.remove()

    if raw is None:
        return

    if event.action == 'run_this_tab':
        self._submit_command(raw)
    elif event.action == 'run_all_tabs':
        self._submit_command_all(raw)
    elif event.action == 'run_selected_tabs':
        tab_names = [tab.entry.display_name for tab in self._tabs]
        self.push_screen(
            TabSelectorModal(tab_names),
            callback=lambda indices: self._on_tabs_selected(raw, indices),
        )

@on(Menu.Dismissed)
def _on_menu_dismissed(self, event: Menu.Dismissed) -> None:
    event.stop()
    raw = self._pending_command
    self._pending_command = None
    event.menu.remove()

    # Restore command text to input.
    if raw is not None:
        input_widget = self.query_one('#command-input', Input)
        input_widget.value = raw
    input_widget = self.query_one('#command-input', Input)
    input_widget.focus()
```

**Step 5: Add `_on_tabs_selected` and `_submit_command_selected` methods**

```python
def _on_tabs_selected(
    self, raw: str, indices: Optional[List[int]]
) -> None:
    if indices is None or not indices:
        return
    self._submit_command_selected(raw, indices)

def _submit_command_selected(self, raw_input: str, tab_indices: List[int]) -> None:
    for i in tab_indices:
        tab = self._tabs[i]
        sub = self._queue_command_in_tab(i, raw_input)
        if sub.status == CommandStatus.PENDING:
            self.notify(f'Command queued in {tab.entry.display_name}')

    # Switch to the active tab's latest sub-command if it was selected.
    if self._active_tab in tab_indices:
        active_tab = self._tabs[self._active_tab]
        self._refresh_select()
        select = self.query_one('#command-select', Select)
        if active_tab.sub_commands:
            select.value = len(active_tab.sub_commands) - 1
            self._show_pane(active_tab.sub_commands[-1].pane_id)
```

**Step 6: Remove `action_submit_all` method**

Delete the entire `action_submit_all` method (lines 502-508 in current file).

**Step 7: Verify lint**

Run: `uv run ruff check rbx/box/ui/command_app.py && uv run ruff format rbx/box/ui/command_app.py`

**Step 8: Commit**

```
feat(ui): wire context menu into command input submission
```

---

### Task 4: Manual testing and polish

**Step 1: Test with the `__main__` block**

Run: `uv run python -m rbx.box.ui.command_app`

Verify:
- Type a command and press Enter -> Menu appears above input with 3 options
- "Run in this tab" is highlighted by default
- Press Enter again -> runs in current tab, menu disappears
- Type command + Enter + "2" -> runs in all tabs (only tab in this test, but no crash)
- Type command + Enter + "3" -> modal appears with tab checkboxes
- In modal: `a` selects all, `n` deselects all
- In modal: Enter confirms, Escape cancels
- Press Escape on menu -> menu dismissed, command text restored to input
- Blur (click elsewhere) -> menu dismissed

**Step 2: Test with multiple tabs**

Update `__main__` block:

```python
if __name__ == '__main__':
    start_command_app([
        CommandEntry(argv=['echo', 'hello'], name='echo1'),
        CommandEntry(argv=['echo', 'world'], name='echo2'),
        CommandEntry(argv=['echo', 'foo'], name='echo3'),
    ])
```

Verify:
- "Run in selected tabs" -> modal shows all 3 tab names
- Toggle individual tabs, confirm -> command only queued in selected tabs
- "Run in all tabs" -> command queued in all 3

**Step 3: Verify no regressions**

Run: `uv run ruff check rbx/box/ui/ && uv run ruff format --check rbx/box/ui/`

**Step 4: Commit**

```
feat(ui): finalize command input context menu
```
