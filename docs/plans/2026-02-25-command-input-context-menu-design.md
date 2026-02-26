# Command Input Context Menu Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the direct Enter-to-submit behavior in `rbxCommandApp` with a floating context menu that lets the user choose where to run the command: current tab, all tabs, or a custom selection of tabs.

## Current Behavior

- **Enter** in input box: submits command to the active tab
- **Ctrl+O**: submits command to all tabs

## New Behavior

- **Enter** in input box: shows a floating context menu above the input with 3 options:
  1. **Run in this tab** (pre-highlighted, so Enter+Enter = old behavior)
  2. **Run in all tabs**
  3. **Run in selected tabs** (opens a modal to pick tabs)
- **Ctrl+O binding removed** (functionality moved to menu option 2)
- **Escape** or blur dismisses the menu without running

## New Components

### 1. Menu Widget (`rbx/box/ui/widgets/menu.py`)

A floating overlay `ListView`, inspired by Toad's `Menu` widget.

**Data model:**
```python
class MenuItem(NamedTuple):
    description: str       # Display text (supports Textual markup)
    action: str            # Action identifier
    key: str | None = None # Optional single-char keyboard shortcut
```

**Widget:**
- `Menu(ListView)` — takes `list[MenuItem]`, renders as absolute-positioned overlay
- CSS: `position: absolute`, `overlay: screen`, `dock: bottom` (anchored above input)
- First item pre-highlighted
- **Messages:** `Menu.Selected(action: str)`, `Menu.Dismissed`
- **Dismiss on:** Escape key, blur
- **Select on:** Enter (highlighted item), single-char key shortcut, mouse click

### 2. Tab Selector Modal (`rbx/box/ui/screens/tab_selector.py`)

A Textual `ModalScreen` for choosing which tabs to run in.

- Displays a vertical list of tab names, each with a checkbox/toggle
- All unchecked by default
- Keyboard shortcuts: `a` = select all, `n` = deselect all
- **Enter** confirms selection, **Escape** cancels
- Returns `list[int]` of selected tab indices via screen dismiss callback

### 3. Changes to `command_app.py`

- `on_input_submitted`: store raw command, mount `Menu` with 3 options above input
- Remove `ctrl+o` binding and `action_submit_all` method
- Handle `Menu.Selected`:
  - `"run_this_tab"` -> `_submit_command(raw)`
  - `"run_all_tabs"` -> `_submit_command_all(raw)`
  - `"run_selected_tabs"` -> push `TabSelectorModal`, on callback call new `_submit_command_selected(raw, indices)`
- Handle `Menu.Dismissed`: remove menu, refocus input
- New `_submit_command_selected(raw, indices)`: like `_submit_command_all` but only for given tab indices

## UX Flow

```
User types "make test" + Enter
  -> Menu appears above input:
       [1] Run in this tab     (highlighted)
       [2] Run in all tabs
       [3] Run in selected tabs
  -> User presses Enter (or "1")
       -> command runs in current tab, menu dismissed
  -> User presses "2"
       -> command runs in all tabs, menu dismissed
  -> User presses "3"
       -> Modal appears with tab checkboxes
       -> User toggles tabs, presses Enter
       -> command runs in selected tabs, modal + menu dismissed
  -> User presses Escape
       -> Menu dismissed, command text restored to input
```

## File Structure

```
rbx/box/ui/
  widgets/
    menu.py              # Menu + MenuItem (NEW)
  screens/
    tab_selector.py      # TabSelectorModal (NEW)
  command_app.py         # Modified wiring
```
