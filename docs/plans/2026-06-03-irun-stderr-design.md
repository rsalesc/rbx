# Show stderr in `rbx irun` (issue #266)

## Goal

Let problem setters see a solution's `stderr` when running it interactively via
`rbx irun`. Two presentation modes:

- **Default (separate section):** print `stderr` in its own distinctly-colored
  "Stderr" section, right after the Output / Interaction section.
- **Interleaved (`--merge-stderr` / `-e`):** weave `stderr` into the Output
  (batch) or Interaction (communication) view in **true line order**, with
  `stderr` lines rendered in a distinct color so they are easy to tell apart
  from `stdout`.

Both modes render **only when `-p` / `--print` is set**. Without `-p`, behavior
is unchanged: `irun` just prints the `stderr` file path link
(`solutions.py:969`).

Scope is **`irun` only** (per the issue), not the full `rbx run` report.

## Background

The interactive interaction system already interleaves streams in true write
order:

- `rbx/grading/judge/sandboxes/line_tee.py` / `tee.py` tee each stream into a
  shared `merged_capture` file, tagging each line with a prefix marker:
  `<` = interactor (pipe 0), `>` = solution (pipe 1).
- `rbx/box/testcase_utils.py`:
  - `parse_interaction()` reads the marked lines into
    `TestcaseInteractionEntry(data, pipe)`.
  - `print_interaction()` colors each entry by `pipe` (0 = `status`,
    1 = `info`).
- `irun`'s `run_and_print_interactive_solutions()` (`rbx/box/solutions.py`)
  already prints the interaction for COMMUNICATION problems and the output for
  BATCH problems when `-p` is set.

This design extends that machinery with a third stream: **stderr = pipe 2,
marker `!`, its own color.**

## Approach (reuse the tee / merged-capture machinery)

### Capture

`stderr` is already captured to a file by `run_item` (exposed via
`eval.log.stderr_absolute_path`). The default separate-section view just reads
that file. No sandbox change is needed for the default mode.

The interleaved mode needs a merged capture:

1. **Communication problems:** the solution's `stderr` is tee'd to *both* its
   normal `stderr` file *and* appended to the existing `merged_capture` with
   marker `!`. Result: interactor ↔ solution exchange **and** stderr in one
   true-ordered, 3-color view.
2. **Batch problems:** the plain `run()` path does not tee today. When
   interleave is on, add optional teeing so:
   - `stdout` → (clean stdout file *for the checker*) + (merged-capture, marker `>`)
   - `stderr` → (stderr file) + (merged-capture, marker `!`)

   **Clean stdout is preserved**, so the checker is unaffected.

### Threading the flag

The interleave flag threads through `SolutionReportSkeleton` (next to the
existing `capture_pipes` field) so it reaches the run functions. `irun` only
caches when an explicit `--testcase` is given; making the flag part of the run
skeleton ensures toggling it never serves a stale merged capture.

### Parsing / rendering changes

- `parse_interaction()`: support a third prefix / pipe. For `.interaction` /
  `.pio` files, recognize the `!` prefix → pipe 2.
- `print_interaction()`: add a color for pipe 2 (stderr) — an `error` / red
  style.
- `solutions.py` `run_and_print_interactive_solutions()`: when `-p`, branch on
  the flag:
  - interleave on → render the merged capture (now includes stderr lines).
  - interleave off (default) → render the Output section as today, then a
    colored "Stderr" section reading `stderr_absolute_path`.

## Error handling / edge cases

- **Empty stderr:** default mode skips the section; interleave mode shows no
  stderr lines.
- **Non-UTF8 / large stderr:** reuse existing file reads and capture limits.
- **Checker correctness:** stdout fed to the checker stays clean in both modes.

## Testing

- Unit: `parse_interaction` with the 3rd prefix; `print_interaction` color for
  pipe 2.
- A fixture solution that writes to stderr → assert the default section prints
  it, and that the interleaved merged-file ordering is correct.

## CLI

New option on `irun`:

```
--merge-stderr / -e    Interleave stderr with the solution output in true line
                       order (colored distinctly). Requires -p. Default off:
                       stderr is shown in a separate colored section.
```
