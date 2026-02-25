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
