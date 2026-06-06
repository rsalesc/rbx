# Promote tests to manual tests — design

**Status:** approved 2026-06-03. Tracks [#442](https://github.com/rsalesc/rbx/issues/442).

## Problem

When `rbx stress` finds a failing input, the natural next step is to keep it as a
regression test. Today the only "make it stick" route appends the **generator call** to a
`.txt` generator script (`rbx/box/cli.py`, the post-match prompt) — so the input is
*regenerated* on every `rbx build`. There is no one-command way to freeze the **actual
failing input** as a static manual test, and no general way to promote an already-existing
(generated) test into a static manual test.

## Scope

Two related features sharing one core:

1. **`rbx tests promote`** — promote already-existing tests (e.g. generated ones) into a
   glob-backed manual test group as static `.in` files.
2. **Stress manual route** — let a stress finding be saved as a static manual test from the
   get-go, as an alternative to the existing generator-script route, surfaced in the same
   post-match picker.

Both write **input only** — no `.out` is written. The normal build pipeline regenerates
expected outputs for manual tests via the main solution, exactly as it does for any manual
test today. This keeps the features simple and sidesteps the "what if the main solution is
the one under stress" concern.

## Shared core — `rbx/box/promotion.py`

A single function does the actual work, used by both entry points:

```python
def promote_input_to_group(
    input_path: pathlib.Path,
    group: TestcaseGroup,
    *,
    name: str | None = None,
) -> pathlib.Path:
    ...
```

Behavior:

- Resolve the group's folder from its `testcaseGlob` (the directory portion of e.g.
  `tests/manual/<group>/*.in`).
- Choose the filename: explicit `name` if provided, else the next free **zero-padded
  counter** (`000.in`, `001.in`, …) by scanning existing files in the folder.
- Write the `.in` (input only). No `.out`.
- Return the written path.

Group creation is handled at the call sites (interactive prompt only — see below), not in
the core, so the core stays a pure "write this input into this existing group" primitive.

## Feature 1 — `rbx tests promote`

- New `tests` Typer sub-app (a home for future test-management commands), command
  `promote`.
- Signature: `rbx tests promote [SELECTORS...] [--group/-G NAME]`
  - `SELECTORS` are `[group]/[index]` strings, reusing the existing `--testcase` format and
    `get_parsed_entry` parsing.
  - `--group/-G` names the destination manual group.

### Non-interactive (CLI / agent-friendly)

- Selectors provided as args **and** `--group` provided.
- For each selector: resolve the built `.in` from the build test directory
  (`package.get_build_testgroup_path`). If the test is not built yet, build it on demand via
  `generators.generate_testcases(testcase_entry=...)`.
- Feed each `.in` to the shared core with the chosen group.
- If `--group` names a group that **does not exist** (or is not glob-backed), **error** with
  a hint to create it interactively. No auto-create in non-interactive mode.

### Interactive

- No selectors → present a **multi-select UI** of built tests to migrate.
- Destination: if `--group` omitted, show a group picker listing glob-backed manual groups
  plus `(create new manual group)` and `(skip)`.
  - `(create new manual group)` → **prompt the user for the folder/glob path explicitly**
    (no hardcoded default), `mkdir -p` the folder, and append a `testcases` entry with the
    `testcaseGlob` to `problem.rbx.yml` (ruyaml, preserving comments), then clear the package
    cache. Mirrors the existing `(create new script)` flow in stress.
- Per-test name prompt, defaulting to the zero-padded counter.

## Feature 2 — stress integration

- Keep today's post-match `Confirm.ask` ("Do you want to add the tests that were found to a
  test group?").
- The group picker now lists **both** script-backed groups *and* glob-backed manual groups,
  plus `(create new script)`, `(create new manual group)`, `(skip)`.
  - Script group → existing append-generator-call behavior (unchanged).
  - Manual group → shared core, writing each finding's failing `.in` as a static file.
  - `(create new manual group)` → same explicit-folder prompt + `mkdir -p` as Feature 1.
- All findings are saved (matches today's multi-finding behavior for the script route).

## Error handling

- `--group` named but missing or not glob-backed → clear error with a creation hint.
- Invalid selector or out-of-range index → error naming the offending selector.
- Build-on-demand failure → propagate the build error.

## Testing

- Unit tests for `promotion.py`: next-counter selection, explicit-name collision handling,
  glob-dir resolution, group creation in `problem.rbx.yml`.
- CLI test for `rbx tests promote` non-interactive (selectors + `--group`) and the
  missing-group error path.
- Stress test asserting the manual-group branch writes a static `.in` and registers the
  group.
- Reuse `cleandir_with_testdata` / `pkg_from_testdata` fixtures from
  `tests/rbx/box/conftest.py`.

## Docs follow-up (tracked from #437)

- Update step 4 ("Making it stick") of `docs/setters/stress-testing-walkthrough.md` to
  mention the manual-test route, and remove/soften the "future release (#442)" note now that
  it has landed.

## Out of scope

- Promoting with a pre-baked `.out` (input-only is uniform across both features).
- A TUI promote action (CLI primitive ships first; TUI wiring can follow later).
- Auto-creating groups in non-interactive mode (explicit creation only, interactively).
