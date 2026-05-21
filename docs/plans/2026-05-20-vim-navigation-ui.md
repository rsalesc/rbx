# Vim-style (hjkl) Navigation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Vim-style `h/j/k/l` navigation to the `rbx ui` Textual TUI without breaking text entry.

**Architecture:** A single `VimNavMixin` mixed into `rbxBaseApp` registers app-level `h/j/k/l` bindings. Each binding dispatches to the *focused* widget's existing `cursor_*`/`scroll_*` action (cursor first, scroll fallback). A `check_action` guard disables the keys when an `Input`/`TextArea` is focused so typing still works. No widget is subclassed and no call site changes.

**Tech Stack:** Python, Textual 8.0, pytest + pytest-asyncio (`asyncio_mode = auto`), Textual `App.run_test()` / `Pilot` for tests.

**Design doc:** `docs/plans/2026-05-20-vim-navigation-ui-design.md`

**Conventions:** Single quotes (ruff-enforced), absolute imports only. Run tests with `uv run pytest`. Commit with the project's conventional-commits format (see `.claude/skills/commit.md`), appending `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

### Task 1: `VimNavMixin` — j/k cursor movement on a list

**Files:**
- Create: `rbx/box/ui/vim_nav.py`
- Test: `tests/rbx/box/ui/test_vim_nav.py`

**Step 1: Write the failing test**

Create `tests/rbx/box/ui/test_vim_nav.py`:

```python
"""Tests for Vim-style hjkl navigation in the Textual TUI (rbx.box.ui.vim_nav)."""

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from rbx.box.ui.vim_nav import VimNavMixin


class _ListApp(VimNavMixin, App):
    def compose(self) -> ComposeResult:
        yield OptionList('a', 'b', 'c')

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()


async def test_j_moves_down_and_k_moves_up():
    app = _ListApp()
    async with app.run_test() as pilot:
        option_list = app.query_one(OptionList)
        start = option_list.highlighted or 0

        await pilot.press('j')
        assert option_list.highlighted == start + 1

        await pilot.press('j')
        assert option_list.highlighted == start + 2

        await pilot.press('k')
        assert option_list.highlighted == start + 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py::test_j_moves_down_and_k_moves_up -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rbx.box.ui.vim_nav'`.

**Step 3: Write minimal implementation**

Create `rbx/box/ui/vim_nav.py`:

```python
from __future__ import annotations

import inspect
from typing import Optional

from textual.binding import Binding
from textual.widgets import Input, TextArea

# Maps a logical direction to (cursor action, scroll fallback action).
_DIRECTION_ACTIONS = {
    'down': ('cursor_down', 'scroll_down'),
    'up': ('cursor_up', 'scroll_up'),
    'left': ('cursor_left', 'scroll_left'),
    'right': ('cursor_right', 'scroll_right'),
}


class VimNavMixin:
    """Adds Vim-style hjkl navigation as an app-level fallback.

    Maps h/j/k/l onto the focused widget's existing ``cursor_*`` actions, falling
    back to ``scroll_*``. The bindings live at the app level (the last link in
    Textual's binding chain), so any widget that binds these letters wins. They are
    disabled while a text-editing widget is focused, so typing is never hijacked.
    """

    BINDINGS = [
        Binding('j', 'vim_move("down")', 'Down', show=False),
        Binding('k', 'vim_move("up")', 'Up', show=False),
        Binding('h', 'vim_move("left")', 'Left', show=False),
        Binding('l', 'vim_move("right")', 'Right', show=False),
    ]

    def check_action(self, action: str, parameters: tuple) -> Optional[bool]:
        if action == 'vim_move':
            focused = self.focused
            if focused is None or isinstance(focused, (Input, TextArea)):
                # Returning None disables the binding and lets the key fall through
                # (e.g. so it types into a focused Input).
                return None
        return super().check_action(action, parameters)

    async def action_vim_move(self, direction: str) -> None:
        focused = self.focused
        if focused is None:
            return
        cursor_action, scroll_action = _DIRECTION_ACTIONS[direction]
        method = getattr(focused, f'action_{cursor_action}', None)
        if method is None:
            method = getattr(focused, f'action_{scroll_action}', None)
        if method is None:
            return
        result = method()
        if inspect.isawaitable(result):
            await result
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py::test_j_moves_down_and_k_moves_up -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/ui/vim_nav.py tests/rbx/box/ui/test_vim_nav.py
git commit -m "$(cat <<'EOF'
feat(ui): add VimNavMixin for hjkl list navigation

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `h`/`l` are no-ops on a plain list

This pins the agreed semantics: horizontal keys do nothing where there is no horizontal movement.

**Files:**
- Test: `tests/rbx/box/ui/test_vim_nav.py` (add to existing file)

**Step 1: Write the failing test**

Append to `tests/rbx/box/ui/test_vim_nav.py`:

```python
async def test_h_and_l_are_noops_on_plain_list():
    app = _ListApp()
    async with app.run_test() as pilot:
        option_list = app.query_one(OptionList)
        await pilot.press('j')  # move off the first row first
        before = option_list.highlighted

        await pilot.press('l')
        assert option_list.highlighted == before

        await pilot.press('h')
        assert option_list.highlighted == before
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py::test_h_and_l_are_noops_on_plain_list -v`
Expected: PASS (OptionList has no `action_cursor_left/right`; its `scroll_left/right` fallback is a no-op with no horizontal overflow). This is a behavior-locking test for code already written in Task 1.

**Step 3: Commit**

```bash
git add tests/rbx/box/ui/test_vim_nav.py
git commit -m "$(cat <<'EOF'
test(ui): lock h/l no-op behavior on plain lists

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Text input is never hijacked (critical regression guard)

**Files:**
- Test: `tests/rbx/box/ui/test_vim_nav.py` (add)

**Step 1: Write the failing test**

Add the import `from textual.widgets import Input` (extend the existing import line to `from textual.widgets import Input, OptionList`) and append:

```python
class _InputApp(VimNavMixin, App):
    def compose(self) -> ComposeResult:
        yield Input()

    def on_mount(self) -> None:
        self.query_one(Input).focus()


async def test_typing_hjkl_into_input_is_not_hijacked():
    app = _InputApp()
    async with app.run_test() as pilot:
        await pilot.press('h', 'j', 'k', 'l')
        assert app.query_one(Input).value == 'hjkl'
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py::test_typing_hjkl_into_input_is_not_hijacked -v`
Expected: PASS — `check_action` returns `None` while the `Input` is focused, so the keys reach the Input and type normally.

> If this FAILS with `value` empty or missing characters, the binding is shadowing the Input. Confirm the `check_action` `isinstance(focused, (Input, TextArea))` branch is reached (add a temporary `print`/`textual.log`). Do NOT "fix" it by removing the bindings — debug the guard.

**Step 3: Commit**

```bash
git add tests/rbx/box/ui/test_vim_nav.py
git commit -m "$(cat <<'EOF'
test(ui): guard text input against hjkl hijacking

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Full hjkl on `DataTable` (cell cursor)

**Files:**
- Test: `tests/rbx/box/ui/test_vim_nav.py` (add)

**Step 1: Write the failing test**

Extend the import to include `DataTable` (`from textual.widgets import DataTable, Input, OptionList`) and append:

```python
class _TableApp(VimNavMixin, App):
    def compose(self) -> ComposeResult:
        yield DataTable()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = 'cell'
        table.add_columns('x', 'y')
        table.add_rows([('1', '2'), ('3', '4')])
        table.focus()


async def test_datatable_hjkl_moves_cell_cursor():
    app = _TableApp()
    async with app.run_test() as pilot:
        table = app.query_one(DataTable)
        assert table.cursor_coordinate == (0, 0)

        await pilot.press('l')
        assert table.cursor_coordinate == (0, 1)

        await pilot.press('h')
        assert table.cursor_coordinate == (0, 0)

        await pilot.press('j')
        assert table.cursor_coordinate == (1, 0)

        await pilot.press('k')
        assert table.cursor_coordinate == (0, 0)
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py::test_datatable_hjkl_moves_cell_cursor -v`
Expected: PASS — `DataTable` defines all four `action_cursor_*` methods, so hjkl maps to full cell movement.

**Step 3: Commit**

```bash
git add tests/rbx/box/ui/test_vim_nav.py
git commit -m "$(cat <<'EOF'
test(ui): verify hjkl moves DataTable cell cursor

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `j`/`l` scroll a scroll container

**Files:**
- Test: `tests/rbx/box/ui/test_vim_nav.py` (add)

**Step 1: Write the failing test**

Add imports `from textual.containers import VerticalScroll` and `from textual.widgets import Static` (alongside the existing widget import), then append:

```python
class _ScrollApp(VimNavMixin, App):
    def compose(self) -> ComposeResult:
        with VerticalScroll():
            # Content larger than the test viewport in both dimensions.
            wide_line = 'x' * 200
            yield Static('\n'.join(wide_line for _ in range(200)))

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).focus()


async def test_j_and_l_scroll_a_scroll_container():
    app = _ScrollApp()
    async with app.run_test(size=(20, 10)) as pilot:
        container = app.query_one(VerticalScroll)
        assert container.scroll_offset == (0, 0)

        for _ in range(5):
            await pilot.press('j')
        await pilot.pause()
        assert container.scroll_offset.y > 0

        for _ in range(5):
            await pilot.press('l')
        await pilot.pause()
        assert container.scroll_offset.x > 0
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py::test_j_and_l_scroll_a_scroll_container -v`
Expected: PASS — `VerticalScroll` has no `cursor_*` actions, so hjkl falls back to `scroll_*`.

> If `scroll_offset` does not change: scrolling is animated/throttled. The `await pilot.pause()` after the presses should settle it; if still flaky, assert after a single larger movement or compare `>=`/use `pilot.pause()` between presses. The container must be focusable and actually overflow — keep `size=(20, 10)` small relative to content.

**Step 3: Commit**

```bash
git add tests/rbx/box/ui/test_vim_nav.py
git commit -m "$(cat <<'EOF'
test(ui): verify j/l scroll a scroll container via fallback

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Wire `VimNavMixin` into the real apps + integration test

**Files:**
- Modify: `rbx/box/ui/main.py:25` (`rbxBaseApp` class definition + import)
- Test: `tests/rbx/box/ui/test_vim_nav.py` (add)

**Step 1: Write the failing test**

Append an integration test exercising the actual main-menu app:

```python
async def test_main_menu_app_supports_vim_nav():
    from rbx.box.ui.main import rbxApp

    async with rbxApp().run_test() as pilot:
        option_list = pilot.app.query_one(OptionList)
        start = option_list.highlighted or 0

        await pilot.press('j')
        assert option_list.highlighted == start + 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py::test_main_menu_app_supports_vim_nav -v`
Expected: FAIL — `rbxApp` does not yet inherit `VimNavMixin`, so `j` does nothing and `highlighted` stays at `start`.

**Step 3: Wire the mixin into `rbxBaseApp`**

In `rbx/box/ui/main.py`, add the import near the other `rbx.box.ui` imports:

```python
from rbx.box.ui.vim_nav import VimNavMixin
```

Change the base app declaration (currently `class rbxBaseApp(App):`) to:

```python
class rbxBaseApp(VimNavMixin, App):
```

The mixin MUST come before `App` in the MRO so its `BINDINGS` merge in and its `check_action` overrides the default. No other changes are needed — `rbxApp`, `rbxDifferApp`, and `rbxCommandApp` all inherit from `rbxBaseApp`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py::test_main_menu_app_supports_vim_nav -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/ui/main.py tests/rbx/box/ui/test_vim_nav.py
git commit -m "$(cat <<'EOF'
feat(ui): enable vim hjkl navigation across rbx ui apps

Mix VimNavMixin into rbxBaseApp so the main menu, differ, and command
apps all gain hjkl navigation.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Document the feature

**Files:**
- Modify: `rbx/box/ui/CLAUDE.md`

**Step 1: Add a short section**

Add a brief subsection (e.g. under a new "Keybindings" heading) to `rbx/box/ui/CLAUDE.md` describing Vim navigation:

```markdown
## Keybindings

- Vim navigation lives in `vim_nav.py` (`VimNavMixin`, mixed into `rbxBaseApp`).
  App-level `h/j/k/l` bindings dispatch to the focused widget's existing
  `cursor_*` action (falling back to `scroll_*`): `j`/`k` move down/up everywhere;
  `h`/`l` move left/right only where horizontal movement exists (DataTable cells,
  scroll viewers). `check_action` disables them while an `Input`/`TextArea` is
  focused, so typing is never hijacked.
```

**Step 2: Commit**

```bash
git add rbx/box/ui/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(ui): document vim hjkl navigation

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Full verification

**Step 1: Run the full Vim-nav test file**

Run: `uv run pytest tests/rbx/box/ui/test_vim_nav.py -v`
Expected: all tests PASS.

**Step 2: Run the broader UI test suite for regressions**

Run: `uv run pytest tests/rbx/box/ui -v`
Expected: PASS (no regressions in `test_run_ui.py` / `test_task_queue.py`).

**Step 3: Lint and format**

Run: `uv run ruff check rbx/box/ui/vim_nav.py rbx/box/ui/main.py tests/rbx/box/ui/test_vim_nav.py && uv run ruff format --check rbx/box/ui/vim_nav.py rbx/box/ui/main.py tests/rbx/box/ui/test_vim_nav.py`
Expected: no errors. If `ruff format --check` reports changes, run `uv run ruff format <files>` and commit with `style(ui): format vim nav code`.

**Step 4: Manual smoke test (optional, requires a problem package)**

In a problem directory: `uv run rbx ui`, then use `j`/`k` to move through the main menu, `Enter` to open a flow, and confirm `h`/`l` move columns in the run report `DataTable`. Confirm typing into the limits-editor inputs still works.

---

## Notes for the implementer

- **MRO matters:** `VimNavMixin` must be listed *before* `App`. Textual merges `BINDINGS` across the MRO and resolves `check_action`/`action_vim_move` on the app instance.
- **Why app-level, not per-widget:** app bindings are the last fallback in Textual's binding chain, so they never shadow a widget/screen binding and require zero call-site changes.
- **Don't widen scope:** no `gg`/`G`/`ctrl+d`, no ranger-style `l`=select/`h`=back, no footer hints, no config toggle (see design doc non-goals).
```
