# Promote: batch filename editor + glob-aware filenames — design

**Status:** approved 2026-06-05. Refines the `rbx testcases promote` interactive flow on PR #521 (#442).

## Problems (from a real interaction)

```
? Select tests to promote to manual tests: done (2 selections)
? Choose the manual group to promote into: (create new manual group)
? Name for the new manual group: manual
? Glob for the new manual group (e.g. tests/manual/corner/*.in): manual_tests/manual-*.in
? Filename stem for program-random/0: 000
? Filename stem for program-random/1: 001
Moved program-random/0 to manual_tests/000.in (removed from testplan/random.py:1).
Moved program-random/1 to manual_tests/001.in (removed from testplan/random.py:2).
```

1. **Correctness bug.** The chosen glob was `manual_tests/manual-*.in`, but the files were
   written as `manual_tests/000.in` / `manual_tests/001.in` — which do **not** match the
   group's own glob (`manual-*.in`). The promoted tests are silently NOT picked up by the
   group at build time. Root cause: `manual_group_dir` returns `Path(glob).parent` and
   `promote_input_to_group` writes `parent / f'{stem}.in'`, ignoring the glob's filename
   pattern. `existing_testcase_stems` / `next_testcase_name` likewise scan `parent/*.in`
   rather than files matching the group glob.
2. **Cumbersome UX.** The interactive flow asks for a filename stem once *per selected test*,
   in a loop. For several tests this is repetitive.

## Goals

- Derive destination filenames by filling the glob's wildcard, so promoted files always match
  the group glob.
- Replace the per-test prompt loop with a single batch editor: show every selected test with
  its auto-derived filename, each optionally editable, on one screen.

## Decisions (locked)

- **Default fill** = glob-aware zero-padded counter (collision-checked against files matching
  the glob, deducing each existing file's `*` portion).
- **Batch UI** = an in-terminal `prompt_toolkit` form.
- **Editable unit** = the *stem* (the `*` fill) only; render the full relative path as a live
  preview around the editable stem.

## Part 1 — Core: glob-aware filenames (`rbx/box/promotion.py`)

This is the bug fix and also powers feature (2). It lives in the shared core, so it corrects
the **stress** route (which also calls `promote_input_to_group`) for free.

- `fill_glob(glob: str, stem: str) -> pathlib.Path` — replace the **last** `*` in `glob` with
  `stem`. Examples: `manual_tests/manual-*.in` + `000` -> `manual_tests/manual-000.in`;
  `tests/manual/*.in` + `000` -> `tests/manual/000.in` (identical to today for the simple
  case). If `glob` has no `*`, raise a clear error ("manual group glob must contain a `*`").
  For multiple `*`, fill only the last (the others are treated as fixed text).
- `stems_matching_glob(glob: str, base_dir=Path()) -> Set[str]` — enumerate files on disk
  matching `glob` and return the substring each file's last `*` captured. Build a regex from
  the glob (escape literal text, `*` -> `(.*)`, anchored) and take the last capture group.
  Replaces `existing_testcase_stems`'s `parent/*.in` scan.
- `next_testcase_name(glob, used=None, base_dir=Path()) -> str` — lowest free `f'{i:03d}'`
  not in `stems_matching_glob(glob) | used`. (Signature changes from `folder` to `glob`; keep
  the `used` reserve-set behavior used by the batch defaults.)
- `promote_input_to_group(input_path, group, *, name, base_dir=Path()) -> pathlib.Path` —
  write to `base_dir / fill_glob(group.testcaseGlob, name_or_default)`, creating parent dirs.
  Still INPUT ONLY (never writes `.out`/`.ans`).
- `manual_group_dir` may stay (still useful as the parent dir for `mkdir`), but filename
  derivation must go through `fill_glob`.

Keep all functions pure/at the seam so they're unit-testable without a terminal.

## Part 2 — Batch filename editor (`rbx/box/testcases/main.py`, `_promote_interactive`)

Replace the `for entry in chosen_entries: questionary.text(...)` loop with one
`prompt_toolkit` form.

- Pure pieces (unit-testable, keep OUT of the TUI):
  - default stems: assign sequential glob-aware counters across the batch (reuse
    `next_testcase_name` with a growing `used` set — same simulate-the-counter logic as today).
  - `validate_stems(stems: list[str]) -> Optional[str]`: returns an error message if any stem
    is empty or if two stems collide (would overwrite one file); else None. (On-disk
    collisions are already avoided by the defaults; a user edit can reintroduce one.)
  - full-path preview: `str(fill_glob(group.testcaseGlob, stem))` per row.
- The TUI (`prompt_toolkit.Application`, run via `run_async()` since the command is async):
  - One row per selected test: source shown read-only (`group/index (full_repr())`) and an
    editable stem field; the fixed glob prefix/suffix + `.in` rendered (dimmed) around the
    stem so the full relative path reads as a live preview.
  - Key bindings: Tab / Up / Down move between rows; Enter submits; Esc or Ctrl-C aborts
    (returns None -> no writes, consistent with current Ctrl-C semantics). Submit is blocked
    while `validate_stems` reports an error (show the message inline).
  - Returns `list[(entry, stem)]` (or None on abort).
- The surrounding flow is unchanged: generate input -> `promote_input_to_group(..., name=stem)`
  -> print "Moved ..." -> after all writes, `remove_script_entries(promoted)`.

## Part 3 — Scope

- Batch editor: interactive `promote` only.
- Non-interactive `promote` (`--name` / auto-counter for multiple): keep its shape but route
  through the glob-aware core, so `--name foo` fills the glob's `*` with `foo`.
- Stress manual route: code unchanged; inherits the glob-aware filename fix via the core.

## Testing

- **Core (pure):** `fill_glob` (simple `*`, prefixed `manual-*.in`, multiple `*` -> last,
  no-`*` error); `stems_matching_glob` (extracts the right substring, ignores non-matching
  files in the same dir); `next_testcase_name` glob-aware counter incl. `used`;
  `promote_input_to_group` writes a path that matches the group glob (regression test for the
  bug: glob `manual_tests/manual-*.in` -> file `manual_tests/manual-000.in`).
- **Batch helpers (pure):** default-stem assignment is sequential & collision-free;
  `validate_stems` catches empties and duplicates.
- **Interactive form:** factor logic so the bulk is covered by the pure tests; optionally a
  smoke test driving the `prompt_toolkit.Application` via `create_pipe_input()` (type a stem,
  submit) asserting the returned mapping. If the pipe-input test proves flaky/heavy, rely on
  the pure-helper tests and keep the `Application` a thin shell.
- **Existing tests:** update `tests/rbx/box/testcases/test_promote.py` interactive tests that
  mocked `questionary.text` per row — they now drive the batch editor (mock the new
  form-runner helper to return the stem mapping, OR assert via the pure helpers). Keep the
  non-interactive and stress tests green; add the glob-match regression assertion.

## Out of scope

- Editing the full path (only the `*`-fill stem is editable; the rest is fixed so the result
  always matches the glob).
- Any change to the stress picker's behavior beyond the inherited filename fix.
