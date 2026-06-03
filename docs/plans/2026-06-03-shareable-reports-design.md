# Design: Shareable run & time reports (#388)

## Problem

It is currently difficult to share a run report (`rbx run`) or a time report
(`rbx time`) with another person. Both are rendered with [Rich] to the terminal
and there is no export/share path. Issue #388 asks for an easy way to produce a
shareable artifact (image, HTML, table — "anything shareable").

## Decisions

- **Formats:** PNG image + plain text.
- **Delivery:** copy to the system clipboard.
- **Platforms (image clipboard):** macOS + Linux. Text clipboard is
  cross-platform. Windows / unsupported environments degrade gracefully.
- **PNG generation:** shell out to a runtime-detected SVG→PNG converter
  (`rsvg-convert` → ImageMagick `magick`/`convert` → macOS `qlmanage`). No new
  Python dependency.
- **CLI surface:** a `--share[=FORMAT]` flag on the two commands that already
  produce these reports — `rbx run` and `rbx time`. `FORMAT ∈ {png, text}`,
  default `png`.

## UX

```
rbx run … --share         # capture report → PNG → clipboard
rbx run … --share=text    # capture report → text → clipboard
rbx time … --share        # same, for the estimation report
```

1. The command runs exactly as today; the live terminal output is unchanged.
2. After the report prints, if `--share` is set, the report is re-rendered
   statically into a recording console, converted to the chosen format, and
   copied to the clipboard.
3. On success: `✓ Report copied to clipboard (PNG)`.
4. On any unsupported step (no converter, no clipboard tool, Windows image):
   gracefully fall back to **writing a file** and printing its path. `--share`
   never hard-fails.

## What gets shared

### `rbx run --share`
The full run report, top to bottom:

1. **Limits header** (`_print_limits`) — per-language time & memory limits.
2. **Verdict view** — single-solution verbose listing, or the multi-solution
   per-group testcase grid (captured as its final settled frame, not the live
   animation). With `-d`, the detailed per-group tables.
3. **Timing summary** (`_print_timing`, multi-solution) — `Time limit`,
   `Slowest AC`, `Slowest AC-or-TLE`, `Fastest slow`, per-language when limits
   differ.

### `rbx time --share`
A superset — the estimation report (timing.py `compute_time_limits`):

1. **Run report (for time estimation)** — the run report above (verdicts +
   timing summary; detailed tables when `-d`). Limits header suppressed.
2. **Estimation summary** — `Fastest solution`, `Slowest solution`, the chosen
   **formula**, and the resulting base time limit.
3. **Final limits table** (`render_limits_table` → `build_limits_table`) — the
   per-language-group breakdown: each row = a language group with solution
   count, resolved time limit, and source/origin (estimated / inherited /
   defaulted / override). This is the "detailed timing breakdown".

Scope notes:
- The pre-prompt **"Current limits"** table (cli.py, before strategy selection)
  is **excluded** from the share — it is pre-state and redundant with the final
  table.
- `--share` captures whatever the command prints at the current `-d` level; it
  does not force extra detail.

## Architecture

### New module: `rbx/box/sharing.py`
The only new file. Small hooks added in `cli.py`, `solutions.py`, `timing.py`.

#### Capture
The multi-solution run report is drawn with `rich.live.Live`, so the live
session cannot be recorded directly. Instead:

- Build a `rich.console.Console(record=True)` with a fixed width.
- **Re-render the report statically** into it after the run finishes — every
  renderable derives from the final `RunSolutionResult` / estimation result, so
  the report-builder functions just need to accept a target console and render
  their final state (no `Live`). Refactor report bodies so "build renderables"
  is separable from "print live".
- For `time`, render the run report + estimation summary + limits table into the
  **same** recording console so they stack into one artifact.

#### Convert
- **Text:** `record_console.export_text()`.
- **PNG:** `record_console.export_svg(title=…)` → SVG string → shell out to the
  first available converter (`rsvg-convert` → `magick`/`convert` → `qlmanage`).
  If none found: save the `.svg`, print its path, hint to install a converter.

#### Clipboard — `copy_to_clipboard(data, kind)`
Platform dispatch via subprocess, no new Python deps:

| | Text | PNG image |
|---|---|---|
| macOS | `pbcopy` | `osascript` set clipboard to `«class PNGf»` |
| Linux (X11) | `xclip -selection clipboard` | `xclip -selection clipboard -t image/png` |
| Linux (Wayland) | `wl-copy` | `wl-copy --type image/png` |
| Windows / none | write file, print path | write file, print path |

Detection: `sys.platform`, then `$WAYLAND_DISPLAY` vs `$DISPLAY`, then
`shutil.which` for the tool. Every failure path degrades to writing a file.

#### Flag wiring
`--share` parsed in `cli.py` for both commands. After the normal (live) report
prints, if set, run the static capture path and copy.

## Testing

- **Capture/export:** render a known report into a `record=True` console; assert
  `export_text()` contains the expected lines (limits, verdicts, timing summary,
  group table rows). No subprocess needed.
- **Converter detection:** `mock.patch` `shutil.which` to simulate each
  converter present/absent; assert the right command is built; assert SVG
  fallback when none.
- **Clipboard dispatch:** `mock.patch` `sys.platform`, env vars, and
  `subprocess.run`; assert the correct tool + args per (platform, kind); assert
  file fallback on Windows / missing tool.
- Reuse existing pytest fixtures (`cleandir_with_testdata`, `pkg_from_testdata`)
  for an end-to-end `--share=text` smoke test asserting clipboard content.

[Rich]: https://rich.readthedocs.io/
