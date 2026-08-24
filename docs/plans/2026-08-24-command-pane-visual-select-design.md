# Command pane: copy-all and keyboard visual selection (#717)

Status: implemented 2026-08-24 (`rbx/box/ui/terminal_select.py`).

## Problem

The command pane in `rbx contest on` / `rbx contest each` (`rbxCommandApp`,
`rbx/box/ui/command_app.py`) can only copy what the mouse has selected. Two things
are missing:

1. There is no way to copy the whole output of a command in one keystroke.
2. Mouse selection breaks down exactly where it is most needed. Output that overflows
   the pane cannot be dragged past the edge of the scroll region, and a logical line
   folded across several rows comes back with the fold breaks baked in.

## What the current code gives us

Grounding, because it decides most of the design:

- `_AppCommandPane.on_key` (`command_app.py:60`) already intercepts `ctrl+y` **ahead of**
  `Terminal.on_key`. That matters: while a command is running, `Terminal.on_key` forwards
  every key to the pty, so any new binding has to be stolen the same way.
- `Terminal.get_selection` extracts from `state.buffer.lines` — the *unfolded logical*
  lines. So a selection covering a wrapped line yields the line as the program wrote it,
  with no fold breaks. Copy-all gets that property for free.
- Textual's `Screen.selections` is a plain writable `dict[Widget, Selection]`, and
  `Terminal._render_line` already highlights from `self.text_selection`. A keyboard mode
  can therefore drive the **existing** rendering and `Screen.get_selected_text()` without
  touching the vendored renderer.
- `Selection` offsets are logical `(line_no, column-in-unfolded-content)`, while the
  viewport scrolls in *folded* rows. `buffer.folded_lines[y] -> (line_no, line_offset,
  offset, line, updates)` is the bridge, and `_render_line` shows how the alternate
  screen is offset by `scrollback_buffer.height`.
- `Terminal.allow_select` is already `False` while a non-finalized alternate screen is
  active (a full-screen child TUI owns the display).

The vendored `toad` tree stays untouched, per `_vendor/toad/CLAUDE.md`.

## Decisions

| Question | Decision |
|---|---|
| Selection UX | Vim-style visual mode, in place in the pane |
| Enter visual mode | `ctrl+v` |
| Copy the whole content | `ctrl+y` with no active selection |
| Vendored changes | None |

`ctrl+y` becomes contextual: with a selection it copies the selection (today's
behaviour, unchanged); with none it copies the entire buffer. That steals no additional
key from the running child process, and the border subtitle always says which of the two
the next `ctrl+y` will do.

## Design

### Where the code lives

A new `rbx/box/ui/terminal_select.py` holds `TerminalSelectMixin`, mixed in *ahead of*
`CommandPane` in the MRO so its `on_key` runs first:

```python
class SelectableCommandPane(TerminalSelectMixin, CommandPane): ...
```

`_AppCommandPane` subclasses `SelectableCommandPane` and drops its bespoke `ctrl+y`
branch (the mixin owns it). `screens/command.py` yields `SelectableCommandPane()` instead
of `CommandPane()`, so `rbx ui`'s build/run screens get the same behaviour from a
one-line change.

### Copy-all

On `ctrl+y` with `screen.selections.get(self)` empty:

```python
text, _ = self.get_selection(Selection(None, None))
```

`Selection(None, None)` means "from the start of the first line to the end of the last",
so this is the whole active buffer as logical lines. Two clean-ups before copying, since
terminal buffers pad to the terminal width: `rstrip()` each line, then drop trailing
empty lines. Copy-all has no on-screen effect, so it confirms with a toast
(`Copied N lines`) rather than only a subtitle change.

### Visual mode

State on the mixin, all in **logical** coordinates:

- `_cursor: Offset | None` — `(x=column, y=logical line)`; `None` means mode is off
- `_anchor: Offset | None` — set by `v` / `V`, `None` while only moving
- `_linewise: bool`
- `_desired_x: int` — vim's sticky column across short lines

`ctrl+v` enters, but only when `self.allow_select`; otherwise it is forwarded to the
process, so a full-screen child TUI keeps the key. Entry puts the cursor at the logical
position of the top-left visible cell — you scrolled there to look at something. The pane
gains a `-selecting` CSS class (accent border) so the mode is unmistakable, and the
border subtitle switches to `v select · y copy · esc exit`.

Bindings inside the mode, none of which reach the process:

| Keys | Action |
|---|---|
| `h j k l`, arrows | move the cursor (no line wrap; `j`/`k` keep `_desired_x`) |
| `0 ^ $` | line start / first non-blank / line end |
| `w b` | word motions (`\w+|\S`) |
| `gg G` | first / last logical line |
| `ctrl+d ctrl+u`, page keys | half / full viewport, measured in folded rows |
| `v` | start or drop a charwise selection at the cursor |
| `V` | linewise selection |
| `y`, `ctrl+y`, `enter` | copy and leave the mode |
| `esc`, `ctrl+v` | leave without copying |
| anything else | ignored |

Selection is published by assigning `screen.selections = {self: selection}`:

- **No anchor yet** — a one-cell `Selection(cursor, cursor + (1, 0))`. The existing
  highlight then *is* the cursor, which the pane otherwise has no way to draw once the
  command is finalized and the pty cursor is hidden.
- **Charwise** — the ordered pair of anchor and cursor, with the end column `+1`, because
  `Selection.extract` slices with an exclusive end and the cell under the cursor is part
  of the selection in vim.
- **Linewise** — `Selection(Offset(0, top), Offset(len(lines[bottom]), bottom))`.

### Coordinate mapping and why it is logical-first

Folded row → logical is a direct index into `buffer.folded_lines`, plus the
alternate-screen offset. Logical → folded row is a `bisect` over the same list, which is
ordered by `line_no`.

Anchoring the mode's state in logical coordinates is the load-bearing choice. Scrollback
only ever appends, so a command that keeps printing while you are selecting cannot shift
the indices under you, and a **resize reflows every folded row while leaving logical
coordinates intact**. The alternative — tracking viewport rows — breaks under both.

Two consequences to implement deliberately:

- After each motion, map the cursor to its folded row and `scroll_to(..., animate=False)`
  if it left the viewport. This is the whole point of the feature: reaching content the
  mouse cannot drag to.
- While the mode is on, suppress the pane's follow-the-output scrolling, or a chatty
  command yanks the view away from the cursor.

### Discoverability

`HelpModal` in `command_app.py` grows its Terminal section:

```
ctrl+v      Enter select mode (hjkl move, v/V select, y copy)
ctrl+y      Copy selection, or all output when nothing is selected
```

The unification with `RbxHelpPanel` tracked in #483 is left alone.

### Known edges

- **Tabs.** `_render_line` applies `content.expand_tabs(8)` before mapping a selection
  span, while `get_selection` does not. On a line containing tabs the highlight and the
  copied text can disagree by the tab expansion. rbx command output effectively never
  contains tabs; expanding tabs in the column arithmetic is the fix if it ever bites.
- **Alternate screen.** `get_selection` reads `state.buffer` (the active one) whereas
  `_render_line` composes scrollback + alternate. They agree in the normal case, and the
  mode refuses to start in the alternate case, so the divergence is unreachable — but it
  is why `ctrl+v` gates on `allow_select` rather than on `is_finalized`.
- **Render cache.** A one-cell cursor selection sets `cache_key = None` for that line
  only, so the cost of drawing the cursor is one uncached line per frame.

## Testing

New `tests/rbx/box/ui/test_command_pane_select.py`, driven by `app.run_test()` + pilot in
the style of `test_command_pane.py`, asserting on `app._clipboard` and
`screen.selections`:

1. `ctrl+y` with nothing selected copies the whole buffer, rstripped and without trailing
   blank lines.
2. `ctrl+y` with a selection still copies only the selection.
3. `ctrl+v` enters the mode and keys stop reaching the process (run `cat`, press `j`,
   assert nothing is echoed).
4. Motions move the one-cell cursor selection.
5. `v` then `G` then `y` copies from the cursor to the end of the output.
6. `V` over a line longer than the pane width copies the **unwrapped** logical line — the
   regression this feature exists for.
7. A motion past the viewport changes `scroll_offset`.
8. `esc` leaves the mode without copying and restores key forwarding.
9. `ctrl+v` is forwarded to the process while the alternate screen is active.

## Out of scope

Search in output, extending a mouse selection with the keyboard, block/rectangular
selection, copying with ANSI styling preserved, "copy the last command's output block",
and persisting a selection across pane switches.

## As built

Four deltas from the design above, all found while implementing:

- **`y` with no anchor yanks the cursor line**, `yy`-style, instead of copying nothing.
  Pressing `ctrl+v` then `y` doing nothing at all read as a broken key.
- **Auto-scroll passes `immediate=True`.** Textual's `scroll_to` otherwise defers the
  scroll until after the next refresh, which leaves the cursor drawn off-screen for a
  frame -- and never scrolls at all under `run_test`.
- **`ctrl+c` also exits the mode**, alongside `esc` and `ctrl+v`. It cannot reach the
  child process from inside the mode anyway, so swallowing it silently would be worse
  than treating it as "get me out".
- **`can_select()` gates on the alternate screen, not on `is_finalized`.**
  `Terminal.finalize()` turns out never to be called anywhere in rbx, so `allow_select`
  reduces to that one condition.

The tab-expansion edge under "Known edges" is unchanged and still unaddressed.
