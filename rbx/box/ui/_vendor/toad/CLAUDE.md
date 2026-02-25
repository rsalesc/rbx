# Vendored Toad Library (`rbx/box/ui/_vendor/toad/`)

Vendored from [batrachian-toad v0.6.0](https://github.com/batrachianai/toad) (AGPL-3.0). See `README.md` for vendoring details and modifications.

## What It Does

Full ANSI terminal emulator widget for Textual. Parses escape sequences, manages terminal state (cursor, colors, scrollback/alternate buffers), and renders output as Textual `Strip` objects. Includes PTY-based subprocess execution.

## Usage in rbx

`CommandPane` is used by `CommandScreen` (`rbx/box/ui/screens/command.py`) to run shell commands (`rbx build`, `rbx run`, etc.) and display live terminal output in the TUI. This replaces the older pyte-based `LogDisplay` in `captured_log.py`.

## Module Structure

### `ansi/` -- ANSI State Machine

| File | Purpose |
|------|---------|
| `_ansi.py` | **`TerminalState`** -- Core state machine. Manages cursor, buffers (scrollback + alternate), DEC charsets. `write(text)` processes ANSI input; `key_event_to_stdin(event)` converts Textual keys to escape sequences. |
| `_stream_parser.py` | Generic tokenizer framework. `Pattern[T]` base class with generator-based matching. `StreamRead` variants: `Read`, `ReadUntil`, `ReadRegex`, `ReadPatterns`. `FEPattern` detects CSI/OSC/DCS/DEC sequences. |
| `_ansi_colors.py` | 256-color ANSI palette mapped to Textual `Color` objects (16 basic + 216 RGB cube + 24 grayscale). |
| `_sgr_styles.py` | SGR parameter → Textual `Style` mapping (bold, italic, underline, colors, resets). |
| `_keys.py` | ~250 key mappings: F-keys, arrows, navigation, Ctrl combos → ANSI escape sequences. |
| `_control_codes.py` | ANSI control code name constants. |

### `widgets/` -- Textual Widgets

| File | Purpose |
|------|---------|
| `terminal.py` | **`Terminal(ScrollView)`** -- Base widget. Wraps `TerminalState`, renders lines via LRU-cached `Strip` objects. Handles scrollback, alternate screen, cursor rendering, double-tap ESC to blur. Messages: `Finalized`, `AlternateScreenChanged`, `LongRunning`. |
| `command_pane.py` | **`CommandPane(Terminal)`** -- Adds PTY subprocess execution. `execute(command)` forks via `pty.openpty()`, sets up async I/O with `shell_read()`. Forces color env vars. Message: `CommandComplete(return_code)`. |

### Root Files

| File | Purpose |
|------|---------|
| `dec.py` | DEC character set tables (14 national variants, ~1000 lines of Unicode mappings). |
| `shell_read.py` | `shell_read()` -- Async buffered reader for PTY output. Batches reads at ~1/100s with max 1/60s latency. |

## Data Flow

```
CommandPane.execute(cmd)
  → pty.openpty() + subprocess
  → shell_read() batches PTY output
  → Terminal.write(text)
    → TerminalState.write() tokenizes ANSI sequences
    → Updates scrollback/alternate buffers
  → Terminal._update_from_state() invalidates render regions
  → Terminal.render_line(y) → cached Strip objects
  → Textual renders to screen
  → CommandPane.CommandComplete on process exit
```

## Editing Guidelines

- **Do not modify** unless necessary -- this is vendored third-party code.
- If changes are needed, document them in `README.md` under "Modifications from upstream".
- Keep Python 3.10 compatibility (no PEP 695 type syntax).
- Import paths must use `rbx.box.ui._vendor.toad.*`, not `toad.*`.
