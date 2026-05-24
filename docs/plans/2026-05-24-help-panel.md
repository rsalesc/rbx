# Help Panel for `rbx ui` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the always-on footer keybinding bar with a slim footer (`? Help` + `q`) and a `?`-toggled side help panel listing all active keybindings, grouped with section headers.

**Architecture:** Add a small `HelpPanelMixin` (mirroring the existing `VimNavMixin`) that contributes an app-level `?` binding toggling Textual 8's built-in `HelpPanel`, with a `check_action` guard so `?` still types into focused `Input`/`TextArea` widgets. Mix it into `rbxBaseApp`. On the primary screens, flip feature bindings to `show=False` (they stay active and appear in the panel) and add `BINDING_GROUP_TITLE` for readable panel section headers.

**Tech Stack:** Textual 8.0.0 (`HelpPanel`, `App.action_show_help_panel`/`action_hide_help_panel`), pytest with Textual's `run_test()` pilot.

**Design doc:** `docs/plans/2026-05-24-help-panel-design.md`

**Conventions:** Single quotes; absolute imports only; commit via the `/commit` skill workflow (`.claude/skills/commit.md`) — conventional commits, append the `Co-Authored-By` trailer. Run tests with `uv run pytest`.

---

### Task 1: `HelpPanelMixin` — `?` toggles the help panel

**Files:**
- Create: `rbx/box/ui/help_panel.py`
- Create: `tests/rbx/box/ui/test_help_panel.py`

**Step 1: Write the failing tests**

```python
"""Tests for the ?-toggled help panel (rbx.box.ui.help_panel)."""

from textual.app import App, ComposeResult
from textual.widgets import HelpPanel, Input, OptionList

from rbx.box.ui.help_panel import HelpPanelMixin


class _PanelApp(HelpPanelMixin, App):
    def compose(self) -> ComposeResult:
        yield OptionList('a', 'b', 'c')

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()


async def test_question_mark_toggles_help_panel():
    app = _PanelApp()
    async with app.run_test() as pilot:
        assert not app.screen.query(HelpPanel)

        await pilot.press('question_mark')
        assert app.screen.query(HelpPanel)

        await pilot.press('question_mark')
        await pilot.pause()
        assert not app.screen.query(HelpPanel)


class _InputApp(HelpPanelMixin, App):
    def compose(self) -> ComposeResult:
        yield Input()

    def on_mount(self) -> None:
        self.query_one(Input).focus()


async def test_question_mark_types_into_focused_input():
    app = _InputApp()
    async with app.run_test() as pilot:
        await pilot.press('question_mark')
        assert app.query_one(Input).value == '?'
        assert not app.screen.query(HelpPanel)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rbx.box.ui.help_panel'`.

**Step 3: Write the implementation**

```python
from __future__ import annotations

from typing import Optional

from textual.binding import Binding
from textual.dom import DOMNode
from textual.widgets import HelpPanel, Input, TextArea


class HelpPanelMixin(DOMNode):
    """Adds a ``?`` binding that toggles Textual's built-in help panel.

    Lives at the app level (like ``VimNavMixin``) so the binding is available on
    every screen and shows up in the footer everywhere. The ``check_action``
    guard disables it while a text-editing widget is focused, so ``?`` still
    types literally into a focused ``Input``/``TextArea``.

    Subclasses ``DOMNode`` so Textual's ``_merge_bindings`` collects ``BINDINGS``
    when the mixin is combined with an ``App``.
    """

    BINDINGS = [
        Binding('question_mark', 'toggle_help_panel', 'Help', show=True),
    ]

    def check_action(
        self, action: str, parameters: tuple[object, ...]
    ) -> Optional[bool]:
        if action == 'toggle_help_panel':
            if isinstance(self.focused, (Input, TextArea)):
                # Returning None disables the binding and lets '?' type into
                # the focused text widget.
                return None
        return super().check_action(action, parameters)

    def action_toggle_help_panel(self) -> None:
        if self.screen.query(HelpPanel):
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py -v`
Expected: PASS (2 passed).

**Step 5: Commit**

```bash
git add rbx/box/ui/help_panel.py tests/rbx/box/ui/test_help_panel.py
git commit -m "$(cat <<'EOF'
feat(ui): add help panel mixin toggled by '?'

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Wire `HelpPanelMixin` into `rbxBaseApp`

**Files:**
- Modify: `rbx/box/ui/main.py:26` (`rbxBaseApp` class definition + import)
- Test: `tests/rbx/box/ui/test_help_panel.py`

**Step 1: Add the failing test (real app)**

Append to `tests/rbx/box/ui/test_help_panel.py`:

```python
async def test_real_rbx_app_toggles_help_panel():
    from rbx.box.ui.main import rbxApp

    async with rbxApp().run_test() as pilot:
        assert not pilot.app.screen.query(HelpPanel)

        await pilot.press('question_mark')
        assert pilot.app.screen.query(HelpPanel)
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py::test_real_rbx_app_toggles_help_panel -v`
Expected: FAIL — no `HelpPanel` mounted (`?` not yet bound on `rbxApp`).

**Step 3: Wire the mixin in**

In `rbx/box/ui/main.py`, add the import alongside the existing vim_nav import:

```python
from rbx.box.ui.help_panel import HelpPanelMixin
from rbx.box.ui.vim_nav import VimNavMixin
```

Change the base app declaration (line 26) from:

```python
class rbxBaseApp(VimNavMixin, App):
```

to:

```python
class rbxBaseApp(VimNavMixin, HelpPanelMixin, App):
```

Both mixins subclass `DOMNode`, so Textual merges both `BINDINGS`; both `check_action` overrides run via `super()` chaining.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py -v`
Expected: PASS (3 passed).

**Step 5: Commit**

```bash
git add rbx/box/ui/main.py tests/rbx/box/ui/test_help_panel.py
git commit -m "$(cat <<'EOF'
feat(ui): enable '?' help panel on all rbx ui apps

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Slim the footer + section header on `TestExplorerScreen`

**Files:**
- Modify: `rbx/box/ui/screens/test_explorer.py:6,23-31`
- Test: `tests/rbx/box/ui/test_help_panel.py`

**Step 1: Add the failing test**

Add a reusable helper + test to `tests/rbx/box/ui/test_help_panel.py`:

```python
def _footer_visible_keys(app) -> set[str]:
    """Keys whose bindings are marked show=True on the active screen."""
    return {
        active.binding.key
        for active in app.screen.active_bindings.values()
        if active.binding.show
    }


async def test_test_explorer_footer_shows_only_help_and_quit():
    from rbx.box.ui.main import rbxApp
    from rbx.box.ui.screens.test_explorer import TestExplorerScreen

    async with rbxApp().run_test() as pilot:
        await pilot.app.push_screen(TestExplorerScreen())
        await pilot.pause()
        assert _footer_visible_keys(pilot.app) == {'question_mark', 'q'}
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py::test_test_explorer_footer_shows_only_help_and_quit -v`
Expected: FAIL — visible keys also include `m`, `1`, `2`, `3`, `v`.

**Step 3: Edit the screen**

In `rbx/box/ui/screens/test_explorer.py`, add the `Binding` import (line 6 region):

```python
from textual.binding import Binding
```

Replace the `BINDINGS` block (lines 23-31) and add a group title:

```python
class TestExplorerScreen(Screen):
    BINDING_GROUP_TITLE = 'Test Explorer'
    BINDINGS = [
        ('q', 'app.pop_screen', 'Quit'),
        Binding('m', 'toggle_metadata', 'Toggle metadata', show=False),
        Binding('1', 'show_output', 'Show output', show=False),
        Binding('2', 'show_stderr', 'Show stderr', show=False),
        Binding('3', 'show_log', 'Show log', show=False),
        Binding('v', 'open_visualizer', 'Open visualization', show=False),
    ]
```

(`q` stays a plain tuple so it remains `show=True`.)

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/ui/screens/test_explorer.py tests/rbx/box/ui/test_help_panel.py
git commit -m "$(cat <<'EOF'
feat(ui): slim test explorer footer to help + quit

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Slim footer + titles on `RunTestExplorerScreen` and `RunExplorerScreen`

**Files:**
- Modify: `rbx/box/ui/screens/run_test_explorer.py:8,30-41`
- Modify: `rbx/box/ui/screens/run_explorer.py:6,16-17`
- Test: `tests/rbx/box/ui/test_help_panel.py`

**Step 1: Add the failing test**

A direct binding-attribute assertion (no running app needed):

```python
def test_run_test_explorer_feature_bindings_hidden():
    from textual.binding import Binding
    from rbx.box.ui.screens.run_test_explorer import RunTestExplorerScreen

    shown = {
        b.key for b in RunTestExplorerScreen.BINDINGS
        if isinstance(b, Binding) and b.show
    }
    tuple_keys = {
        b[0] for b in RunTestExplorerScreen.BINDINGS if isinstance(b, tuple)
    }
    # Only 'q' (a plain tuple) stays visible; all Binding() entries are hidden.
    assert shown == set()
    assert tuple_keys == {'q'}
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py::test_run_test_explorer_feature_bindings_hidden -v`
Expected: FAIL — bindings are still plain `show=True` tuples.

**Step 3: Edit the screens**

`run_test_explorer.py` — add `from textual.binding import Binding`, then replace the `BINDINGS` block (lines 30-41):

```python
class RunTestExplorerScreen(Screen):
    BINDING_GROUP_TITLE = 'Run Test Explorer'
    BINDINGS = [
        ('q', 'app.pop_screen', 'Quit'),
        Binding('1', 'show_output', 'Show output', show=False),
        Binding('2', 'show_stderr', 'Show stderr', show=False),
        Binding('3', 'show_log', 'Show log', show=False),
        Binding('m', 'toggle_metadata', 'Toggle metadata', show=False),
        Binding('s', 'toggle_side_by_side', 'Toggle sxs', show=False),
        Binding('g', 'toggle_test_metadata', 'Toggle test metadata', show=False),
        Binding('v', 'open_visualizer', 'Open visualization', show=False),
        Binding(
            'V', 'open_output_visualizer', 'Open output visualization', show=False
        ),
    ]
```

`run_explorer.py` — add `from textual.binding import Binding`, then replace line 16-17:

```python
class RunExplorerScreen(Screen):
    BINDING_GROUP_TITLE = 'Run Explorer'
    BINDINGS = [Binding('s', 'compare_with', 'Compare with', show=False)]
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/ui/screens/run_test_explorer.py rbx/box/ui/screens/run_explorer.py tests/rbx/box/ui/test_help_panel.py
git commit -m "$(cat <<'EOF'
feat(ui): slim run explorer footers to help + quit

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Section titles on remaining primary screens + hide limits-editor feature keys

**Files:**
- Modify: `rbx/box/ui/screens/run.py:37-40,107-108` (`SolutionReportScreen`, `RunScreen`)
- Modify: `rbx/box/ui/screens/command.py:11-12` (`CommandScreen`; `BuildScreen` inherits)
- Modify: `rbx/box/ui/screens/differ.py:11-12` (`DifferScreen`)
- Modify: `rbx/box/ui/screens/limits_editor.py:45-49` (`LimitsEditorScreen`)
- Test: `tests/rbx/box/ui/test_help_panel.py`

**Step 1: Add the failing test**

```python
async def test_limits_editor_feature_bindings_hidden():
    from textual.binding import Binding
    from rbx.box.ui.screens.limits_editor import LimitsEditorScreen

    shown = {b.key for b in LimitsEditorScreen.BINDINGS if b.show}
    # Only 'q' stays visible; save/delete move to the panel.
    assert shown == {'q'}


def test_primary_screens_have_group_titles():
    from rbx.box.ui.screens.command import CommandScreen
    from rbx.box.ui.screens.differ import DifferScreen
    from rbx.box.ui.screens.run import RunScreen, SolutionReportScreen

    for screen_cls in (CommandScreen, DifferScreen, RunScreen, SolutionReportScreen):
        assert getattr(screen_cls, 'BINDING_GROUP_TITLE', None)
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py -k "group_titles or limits_editor" -v`
Expected: FAIL — no `BINDING_GROUP_TITLE`; `ctrl+s`/`d` still shown.

**Step 3: Edit the screens**

`run.py` — add `BINDING_GROUP_TITLE = 'Solution Report'` to `SolutionReportScreen` (above its `BINDINGS`, line 40) and `BINDING_GROUP_TITLE = 'Run'` to `RunScreen` (above line 108). Leave their single `q` tuple visible.

`command.py` — add `BINDING_GROUP_TITLE = 'Command'` to `CommandScreen` (above line 12).

`differ.py` — add `BINDING_GROUP_TITLE = 'Diff'` to `DifferScreen` (above its `BINDINGS`).

`limits_editor.py` — already imports `Binding`. Add title and hide feature keys; keep `q` visible (lines 45-49):

```python
class LimitsEditorScreen(Screen):
    BINDING_GROUP_TITLE = 'Limits Editor'
    BINDINGS = [
        Binding('q', 'quit_screen', 'Quit'),
        Binding('ctrl+s', 'save', 'Save', show=False),
        Binding('d', 'delete_profile', 'Delete profile', show=False),
    ]
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_help_panel.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/ui/screens/run.py rbx/box/ui/screens/command.py rbx/box/ui/screens/differ.py rbx/box/ui/screens/limits_editor.py tests/rbx/box/ui/test_help_panel.py
git commit -m "$(cat <<'EOF'
feat(ui): add help-panel titles and slim limits editor footer

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Manual smoke check + docs

**Files:**
- Modify: `rbx/box/ui/CLAUDE.md` (Keybindings section)

**Step 1: Full UI test suite**

Run: `uv run pytest tests/rbx/box/ui -v`
Expected: PASS (existing vim_nav + run_ui + task_queue + new help_panel tests).

**Step 2: Lint/format**

Run: `uv run ruff check rbx/box/ui tests/rbx/box/ui && uv run ruff format --check rbx/box/ui tests/rbx/box/ui`
Expected: clean (run `ruff format` then `ruff check --fix` if not).

**Step 3: Manual smoke (optional but recommended)**

In a problem package: `uv run rbx ui`, confirm the footer shows only `? Help` and `q`, press `?` to open the panel (sections titled per screen, all keys listed), press `?` again to close, and confirm typing in the limits-editor inputs still accepts `?`.

**Step 4: Update the Keybindings section of `rbx/box/ui/CLAUDE.md`**

Add a short paragraph describing `HelpPanelMixin` (in `help_panel.py`, mixed into `rbxBaseApp` alongside `VimNavMixin`): `?` toggles Textual's built-in `HelpPanel`; feature bindings on primary screens use `show=False` so the footer stays slim while the panel lists everything; screens set `BINDING_GROUP_TITLE` for panel section headers; `check_action` lets `?` type into focused inputs.

**Step 5: Commit**

```bash
git add rbx/box/ui/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(ui): document help panel keybinding pattern

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Notes / gotchas

- **Plain tuple vs `Binding`:** a 3-tuple `(key, action, desc)` defaults to `show=True`. To hide, convert to `Binding(..., show=False)`. Keep `q` as a tuple to leave it visible.
- **Both mixins are `DOMNode`s:** Textual's `_merge_bindings` only collects `BINDINGS` from `DOMNode` subclasses in the MRO, and `check_action` chains via `super()`. `class rbxBaseApp(VimNavMixin, HelpPanelMixin, App)` is correct; do not drop `App` from the end.
- **Modals untouched:** `SelectorScreen`, `RichLogModal`, `TabSelectorModal`, `ConfirmDiscardScreen`, `ReviewScreen`, `ErrorScreen` keep their current minimal footers (per design).
- **Panel shows hidden bindings:** the vim `h/j/k/l` (`show=False`) will appear in the panel — intended; the panel is the full reference.
- **Pre-existing local failures:** unrelated C++ checker/validator/sandbox/docker tests fail on this machine; do not treat them as regressions.
