# Vendored: Toad Terminal Widgets

This directory contains vendored code from [Toad](https://github.com/batrachianai/toad)
(batrachian-toad v0.6.0), a unified terminal AI experience by Batrachian AI.

## License

The vendored code is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.
See the original project for full license terms: https://github.com/batrachianai/toad/blob/main/LICENSE

## What is vendored

Only the files required for the `CommandPane` terminal widget are included:

- `ansi/` -- ANSI terminal state machine and stream parser
- `dec.py` -- DEC character set mappings
- `shell_read.py` -- Buffered async shell output reader
- `widgets/terminal.py` -- Base `Terminal` Textual widget
- `widgets/command_pane.py` -- `CommandPane` widget for running shell commands

## Modifications from upstream

- Import paths changed from `toad.*` to `rbx.box.ui._vendor.toad.*`
- PEP 695 type parameter syntax converted to `TypeVar`/`Generic` for Python 3.10 compatibility
- Removed Toad-specific `Conversation` widget reference from `terminal.py`
- Removed unused `MenuItem` import from `terminal.py`
- `terminal.py`: `update_size()` now recomputes the scrollable extents (extracted as
  `_update_virtual_size()`, shared with `_update_from_state()`). Upstream only sets
  `virtual_size` on a write, so a resize that reflows the buffer with nothing written
  afterwards -- a command that already finished -- leaves the extents describing the old
  fold count and an anchored terminal scrolls past the end of its own output.
- `ansi/_ansi.py`, `widgets/terminal.py`: the cursor is positioned in **cells**, while lines
  are stored as **characters** -- and a CJK ideograph or an emoji is one character and two
  cells wide. Upstream uses `cursor_offset` directly as an index, so any program that
  positions the cursor by column on a line holding wide characters (a `\r` redraw, a
  progress bar, `ESC[nG`) lands at the wrong place: the gap gets padded with spaces that
  were never printed, or a character that was printed gets eaten. `cell_to_index`,
  `cell_span` and `index_to_cell` convert between the two spaces, and `Buffer.cursor`,
  `Buffer.update_cursor`, `TerminalState.get_cursor_position` (replacing
  `get_cursor_line_offset`), content writes, `ECH`/`DCH`, `_reflow` and the cursor
  rendering all go through them. `cursor_offset` is now documented as a cell column.
- `command_pane.py`: `CommandPane` takes an optional `get_fallback_dimensions` callable,
  used when its own region is zero-sized (a hidden pane), and exposes
  `refresh_terminal_size()` so an owner can re-apply the size to a pane that gets no
  `Resize` of its own. `_size_changed()` no longer bails before the process starts (it
  just skips the ioctl), and `_execute()` sizes the pty *before* forking, so a program
  reading its width on the first write does not see the 0x0 a fresh pty starts with.
