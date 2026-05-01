# Polygon Raw Tests Upload — Design

Resolves [#390](https://github.com/rsalesc/rbx/issues/390).

## Problem

`rbx package polygon --upload` relies on Polygon-side test generation: it uploads each generator program plus a freemarker script that tells Polygon how to invoke them. When a generator fails to upload (e.g. unsupported language, broken Polygon-side compilation, or testlib/jngen surprises), the user has no escape hatch: the only way to publish tests on Polygon is by getting that generator to compile remotely.

## Goal

Add an opt-in flag that uploads the **already-built test inputs** as raw files instead of relying on the generator script. This bypasses Polygon-side generation entirely.

## Non-goals

- Changing the default upload behavior. Generator-script uploads remain the default — they're still preferable for problems with large test sets (Polygon caps raw uploads at 1 MiB per test).
- Uploading answer files. Polygon's "invocation" step computes answers from the model solution; we don't second-guess that.
- Contest-level wiring. The contest `polygon` command (`contest_main.py`) does not have an upload feature.
- Touching the existing `_upload_testcases` path. We add a sibling function and dispatch on the new flag.

## Approach

### CLI

Add a new option to `rbx package polygon` (`rbx/box/packaging/main.py`):

```
--upload-tests-raw    bool, default False
```

Help text: *"When set, upload built test inputs directly instead of relying on Polygon-side generators. Skips generator uploads and clears the test script. All test inputs must be < 1 MiB. Forces a full local build."*

Validation:
- If `--upload-tests-raw` is passed without `--upload`, exit with `typer.BadParameter` before any work.
- Orthogonal to `--upload-only` / `--upload-skip` — those still gate which asset categories upload; `--upload-tests-raw` only changes *how* the `tests` category works.

### Build behavior

The current `should_build` short-circuit skips the full build during upload (`samples_only=True`) because Polygon is expected to run the generators. Raw mode needs every test built locally:

```python
should_build = (not upload and not validate_statement) or upload_tests_raw
```

When `--upload-tests-raw --upload` are both set, the full build runs and the local zip package is also produced as a byproduct (matching `rbx package polygon` without `--upload`).

### Upload flow (`rbx/box/packaging/polygon/upload.py`)

Plumb a `raw_tests: bool` argument through `upload_problem`:

```python
async def upload_problem(
    name: str,
    main_language: Optional[str],
    upload_as_english: bool = False,
    upload_only: Optional[Set[str]] = None,
    dont_upload: Optional[Set[str]] = None,
    raw_tests: bool = False,    # NEW
):
    ...
    if 'tests' in which_upload:
        if raw_tests:
            _upload_testcases_raw(problem)
        else:
            _upload_testcases(problem)
```

New helpers and function:

- `_RAW_SIZE_LIMIT = 1024 * 1024` — module-level constant; mirrors the existing inline value at `upload.py:415` for statement resources.
- `_resolve_raw_test_path(entry) -> pathlib.Path` — picks `entry.metadata.copied_to.inputPath`, falling back to `entry.metadata.copied_from.inputPath`. Single source of truth for "where do the raw bytes live."
- `_validate_raw_tests(entries) -> List[str]` — returns a list of human-readable errors:
  - missing built input → `'"<group>/<index>" was not built (input file missing)'`
  - oversized input → `'"<group>/<index>" is <pretty size>, exceeds the 1 MiB Polygon limit'`
- `_upload_testcases_raw(problem)`:
  1. Extract entries via `extract_generation_testcases_from_groups()`.
  2. Run `_validate_raw_tests`. If non-empty, print every error and `raise typer.Exit(1)` — *before any Polygon call*.
  3. Clear the script: `problem.save_script(testset='tests', source='<#-- empty placeholder script -->')`. This drops Polygon's existing generator-based mapping so the new raw tests can take their slots.
  4. Iterate entries with the same `rich.progress.Progress` UX as `_upload_testcases`. For each entry, read the resolved raw bytes, decode as text, and call:
     ```python
     _save_skip_coinciding_testcases(
         problem,
         testset='tests',
         test_index=next_index,
         test_input=content,
         **_get_test_params_for_statement(
             entry.metadata.copied_from,
             is_sample=entry.is_sample(),
         ),
     )
     ```
  5. No generator upload, no jngen upload, no script construction.

### Helper reuse

The new path reuses, unchanged:
- `_save_skip_coinciding_testcases` — silent skip + don't bump `next_index` when Polygon reports a coincidence.
- `_get_test_params_for_statement` — preserves sample-test linkage with statements (including `.pin`/`.pout` and parsed interaction handling).

## Error handling

| Scenario | Handling |
|----------|----------|
| `--upload-tests-raw` without `--upload` | `typer.BadParameter` at CLI dispatch — no work done |
| Some tests > 1 MiB or missing | Pre-flight collects all, prints list, `typer.Exit(1)` — no Polygon calls made |
| Polygon `save_test` fails mid-upload | Let the existing `PolygonRequestFailedException` surface (matches `_upload_generator` behavior) |
| Test coincides with one already on Polygon | Reuse `_save_skip_coinciding_testcases` (existing) — silent skip |
| Build fails before upload | Existing `builder.verify()` already aborts in `run_packager` |

## Testing

No new unit tests for the Polygon upload flow (consistent with the current state — none exist; coverage relies on manual smoke against the real API). Verification before finishing:

- `uv run ruff check .` and `uv run ruff format .` clean.
- `uv run python -c "from rbx.box.packaging.polygon import upload"` imports cleanly.
- `uv run rbx package polygon --help` shows the new flag with help text.

## Files touched

- `rbx/box/packaging/main.py` — add `--upload-tests-raw` option, force full build when set, plumb to `upload_problem`.
- `rbx/box/packaging/polygon/upload.py` — add constant, helpers, `_upload_testcases_raw`, accept `raw_tests` in `upload_problem`.
- `rbx/box/packaging/CLAUDE.md` — one-line note in the Polygon section about the `--upload-tests-raw` escape hatch.
