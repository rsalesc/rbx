# Help Panel for `rbx ui` (issue #482)

**Date:** 2026-05-24
**Status:** Approved design, ready for implementation planning

## Problem

Every screen in the Textual TUI yields a `Footer()` that renders all visible
`BINDINGS` along the bottom bar. On the busier screens (e.g.
`RunTestExplorerScreen` has 9 bindings) this bar is cluttered and crowds out the
content.

## Goal

Replace the always-on keybinding bar with:

1. A **slim footer** showing only `? Help` and `q` (quit/back).
2. A **`?`-toggled side help panel** that lists *all* active keybindings,
   grouped with readable section headers.

We use Textual 8's **built-in `HelpPanel` / `KeyPanel`** as-is. Confirmed
available in the pinned `textual==8.0.0`, along with `App.action_show_help_panel`
and `App.action_hide_help_panel`. The built-in `KeyPanel` already reads
`screen.active_bindings`, groups by namespace, prints each namespace's
`BINDING_GROUP_TITLE` as a section header, and collapses bindings that share an
`action` into a single multi-key row. No custom panel is needed; the
description-level merging and arbitrary-extra-content ideas from the issue are
deliberately out of scope (YAGNI).

## Design

### 1. App-level toggle binding (the core)

In the shared base where vim navigation already lives (`VimNavMixin` /
`rbxBaseApp` in `rbx/box/ui/main.py`):

- Add `Binding('question_mark', 'toggle_help_panel', 'Help', show=True)`.
- Implement `action_toggle_help_panel()`: if a `HelpPanel` is currently mounted
  on the active screen, call `action_hide_help_panel()`, otherwise
  `action_show_help_panel()`.

Defining it at the base means it appears in every screen's footer automatically
and works on all three apps (`rbxApp`, `rbxDifferApp`, `rbxCommandApp`) — the
same sharing mechanism vim nav uses.

### 2. Slim the footer

Flip the per-screen *feature* bindings (`1/2/3`, `m`, `s`, `g`, `v`, `V`,
`ctrl+s`, `d`, …) to `show=False`. They remain active and still appear in the
help panel, but leave the footer. Each screen's `q` (quit/back) stays
`show=True`. Resulting footer: `? Help` + `q`.

### 3. Section headers

Set `BINDING_GROUP_TITLE` on the primary screen classes so the panel renders a
readable header per section (e.g. "Test Explorer", "Run Test Explorer"). Cheap
and a clear readability win.

### 4. Scope

Apply to the primary navigational screens:
`TestExplorerScreen`, `RunExplorerScreen`, `RunTestExplorerScreen`, `RunScreen`,
`SolutionReportScreen`, `CommandScreen`/`BuildScreen`, `DifferScreen`, and the
menu apps.

Leave transient modals untouched (`SelectorScreen`, `RichLogModal`,
`TabSelectorModal`, `ConfirmDiscardScreen`, `ReviewScreen`, `ErrorScreen`) — a
side panel over a small modal is awkward and low-value; their footers are
already minimal.

## Edge cases

- **`?` while an `Input`/`TextArea` is focused** (RunScreen filter, limits
  editor): `?` is a typable character. `check_action` must disable
  `toggle_help_panel` when focus is an `Input`/`TextArea`, exactly mirroring
  vim_nav's existing guard. This is the one must-not-miss detail.
- The hidden vim `j/k/h/l` bindings (`show=False`) **will** appear in the panel
  — desirable, it makes the panel the complete reference.
- The panel is per-screen; pushing a new screen drops it. Acceptable — it is
  contextual to the screen.

## Testing

Pilot-based, mirroring `tests/rbx/box/ui/test_vim_nav.py` (which already drives
app-level bindings, including against the real `rbxApp`). New file
`tests/rbx/box/ui/test_help_panel.py`:

- Press `?` → assert a `HelpPanel` is mounted on the screen; press `?` again →
  assert it is removed.
- `?` typed into a focused `Input` inserts `?` and opens no panel.
- Footer exposes only `?` and `q` (assert via binding `show` flags / rendered
  footer).
- Exercise against the real `rbxApp` menu, like
  `test_main_menu_app_supports_vim_nav`.

## Files touched

- `rbx/box/ui/vim_nav.py` and/or `rbx/box/ui/main.py` — binding, action,
  `check_action` guard.
- Per-screen files under `rbx/box/ui/screens/` — flip `show` flags, add
  `BINDING_GROUP_TITLE`.
- New `tests/rbx/box/ui/test_help_panel.py`.
