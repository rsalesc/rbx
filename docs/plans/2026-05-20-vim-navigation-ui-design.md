# Vim-style (hjkl) navigation in `rbx ui`

**Date:** 2026-05-20
**Status:** Approved design — ready for implementation plan

## Problem

The Textual TUI launched by `rbx ui` only supports arrow-key navigation. Competitive
programming users overwhelmingly favor Vim, and want `h/j/k/l` to navigate menus,
lists, tables, and scrollable viewers.

## Decisions (locked)

- **Key scope:** `j`=down, `k`=up everywhere. `h`/`l` move left/right *only where
  horizontal movement exists* (DataTable cells, horizontally-scrollable viewers). In
  plain lists/menus, `h`/`l` are no-ops.
- **Implementation:** Centralized app-level remap dispatched onto the focused widget's
  existing actions, with a `check_action` guard that disables the keys when a text
  field is focused.
- **Motions:** `hjkl` only. No `gg`/`G`/`ctrl+d`/`ctrl+u`.

### Non-goals (YAGNI)

- No ranger-style `l`=select / `h`=back semantics.
- No `gg`/`G`/half-page motions.
- No footer hints (arrows remain the documented default; the Vim keys are hidden).
- No config toggle — the feature is purely additive and never shadows typing.

## Core idea

The navigable widgets already expose every action we need:

- `action_cursor_up/down/left/right` on `OptionList`, `ListView` (`Menu`), `DataTable`.
- `action_scroll_up/down/left/right` on `ScrollView`-based viewers (`LogDisplay`,
  `FileLog`, `CodeBox`).

So we do **not** rewrite or subclass any widget. We add a thin **app-level binding
layer** that maps `h/j/k/l` onto whatever the *focused* widget already supports, and
steps aside when a text field is focused.

## Component: `VimNavMixin`

New mixin (`rbx/box/ui/vim_nav.py`) inherited by `rbxBaseApp` in `main.py`. Since
`rbxBaseApp` is the parent of `rbxApp`, `rbxDifferApp`, and `rbxCommandApp`, this single
placement covers all three navigable apps. `rbxReviewApp` (a standalone y/n confirm
dialog) does not inherit `rbxBaseApp` and is intentionally excluded.

### 1. Bindings (hidden from footer)

```python
BINDINGS = [
    Binding('j', 'vim_move("down")',  'Down',  show=False),
    Binding('k', 'vim_move("up")',    'Up',    show=False),
    Binding('h', 'vim_move("left")',  'Left',  show=False),
    Binding('l', 'vim_move("right")', 'Right', show=False),
]
```

App-level bindings are the **last link in Textual's binding chain**, so any
widget/screen that already binds those letters wins (none currently do). The Vim keys
act purely as a fallback.

### 2. Dispatch — `action_vim_move(direction)`

Look at `self.focused`; for the direction, try the **cursor** action first, then fall
back to **scroll**:

| key | try first             | fall back to          |
|-----|-----------------------|-----------------------|
| j   | `action_cursor_down`  | `action_scroll_down`  |
| k   | `action_cursor_up`    | `action_scroll_up`    |
| h   | `action_cursor_left`  | `action_scroll_left`  |
| l   | `action_cursor_right` | `action_scroll_right` |

Resolve via `getattr(self.focused, name, None)` and invoke if present. This yields the
agreed semantics automatically, per widget type:

- `OptionList` / `ListView` (`Menu`): have `cursor_up/down` only → **j/k navigate; h/l
  no-op** (their `scroll_left/right` fallback does nothing without horizontal overflow).
- `DataTable`: has all four cursor actions → **full hjkl cell movement**.
- `LogDisplay` / `FileLog` / `CodeBox` (scroll views): no cursor actions → **hjkl all
  scroll**, horizontal included.

### 3. Text-input guard — `check_action`

When `self.focused` is an `Input` or `TextArea` (or `None`), return `None` for the
`vim_move` action so the keystroke passes straight through and types normally.
Textual's `Input` already consumes printable keys before app bindings resolve;
`check_action` makes this explicit, version-robust, and keeps the footer honest.

## Data flow

```
keypress
  -> focused-widget / screen bindings (none match hjkl)
  -> bubbles to app VimNavMixin binding
  -> check_action gate (skip -> pass through if text field / no focus)
  -> action_vim_move(direction)
  -> getattr(focused, 'action_cursor_*' or 'action_scroll_*')()
```

No synthetic key events, no per-call-site changes.

## Edge cases

- No focused widget, or focused widget supports neither action for the direction →
  no-op (guarded by `getattr(..., None)`).
- `rbxReviewApp` excluded — nothing to navigate.
- `Select` widget: collapsed → harmless no-op; expanded → its overlay `OptionList` is
  focused, so `j`/`k` navigate options as expected.
- If an action method returns an awaitable, schedule/await it (most cursor/scroll
  actions are synchronous; handle the coroutine case defensively).

## Testing (fast, Pilot-based — no docker/CLI)

Using Textual's `App.run_test()` / `Pilot`:

1. `OptionList` focused: `press('j')` advances `highlighted`, `press('k')` retreats;
   `press('h'/'l')` is a no-op.
2. `DataTable` focused: `h`/`l` move the column cursor, `j`/`k` move rows.
3. **`Input` focused: `press('j')` ⇒ `input.value == 'j'`** — the critical regression
   guard.
4. Scroll viewer with overflowing content: `j` increases `scroll_y`, `l` increases
   `scroll_x`.

Check `tests/rbx/box/ui/` for an existing Pilot harness and match its conventions.
