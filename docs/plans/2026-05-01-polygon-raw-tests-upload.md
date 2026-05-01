# Polygon Raw Tests Upload Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `--upload-tests-raw` to `rbx package polygon` so the user can upload built test inputs directly when Polygon-side generators fail to upload (issue #390).

**Architecture:** Add a sibling `_upload_testcases_raw` function next to `_upload_testcases` (no refactor of the existing path). CLI flag forces a full local build, plumbs `raw_tests=True` through `upload_problem`, then dispatches to the new function. Pre-flight validation enforces the 1 MiB Polygon limit before any API call.

**Tech Stack:** Python, Typer (CLI), Pydantic models, `rich.progress`, async via `syncer`. Polygon API client at `rbx/box/packaging/polygon/polygon_api.py`.

**Reference docs:**
- Design: `docs/plans/2026-05-01-polygon-raw-tests-upload-design.md`
- Existing CLI: `rbx/box/packaging/main.py:14-79`
- Existing upload: `rbx/box/packaging/polygon/upload.py:258-336` (`_upload_testcases`), `:501-552` (`upload_problem`)
- Helpers being reused: `_save_skip_coinciding_testcases` (`upload.py:184`), `_get_test_params_for_statement` (`upload.py:194`)
- Module CLAUDE.md: `rbx/box/packaging/CLAUDE.md`

**Conventions to follow:**
- Single quotes for strings (ruff `Q` rule).
- Absolute imports only.
- Conventional commits via the project `/commit` skill (`.claude/skills/commit.md`). Use `feat(packaging):` scope for code, `docs(packaging):` for docs.
- No new comments unless the *why* is non-obvious.
- No tests (per design — Polygon upload is currently untested; manual smoke instead).

---

## Task 1: Add module constant and path resolver helper

**Why first:** Smallest atomic piece; nothing depends on yet-unwritten code; easy to land cleanly.

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py`

**Step 1: Add constant near other module constants**

After line 45 (`MAX_WORKERS = 4`), add:

```python
_RAW_TEST_SIZE_LIMIT = 1024 * 1024
```

**Step 2: Add path resolver helper after `_get_freemarker_for_calls`**

Insert after the existing `_get_freemarker_for_calls` function (around line 236), before `_upload_generator`:

```python
def _resolve_raw_test_input_path(
    entry: 'GenerationTestcaseEntry',
) -> Optional[pathlib.Path]:
    if entry.metadata.copied_to.inputPath.is_file():
        return entry.metadata.copied_to.inputPath
    if (
        entry.metadata.copied_from is not None
        and entry.metadata.copied_from.inputPath.is_file()
    ):
        return entry.metadata.copied_from.inputPath
    return None
```

**Step 3: Add the imports the helper needs**

At the top of the file, add `pathlib` to stdlib imports (alphabetical, after `asyncio`):

```python
import asyncio
import pathlib
from concurrent.futures import ThreadPoolExecutor
```

And add `GenerationTestcaseEntry` to the `from rbx.box.generation_schema import` block. Check whether such an import already exists; if not, add:

```python
from rbx.box.generation_schema import GenerationTestcaseEntry
```

(near the other `from rbx.box.*` imports, around line 17). The forward-reference quotes in step 2 mean you can also leave the import inside `TYPE_CHECKING` if that's the prevailing style — check the surrounding imports and match.

**Step 4: Verify imports load**

Run: `cd /Users/rsalesc/Dev/robox.io/.worktrees/polygon-raw-tests && uv run --active python -c "from rbx.box.packaging.polygon import upload; print(upload._RAW_TEST_SIZE_LIMIT)"`
Expected: prints `1048576`.

**Step 5: Format and lint**

Run: `uv run --active ruff format rbx/box/packaging/polygon/upload.py && uv run --active ruff check rbx/box/packaging/polygon/upload.py`
Expected: no errors.

**Step 6: Commit**

```bash
git add rbx/box/packaging/polygon/upload.py
git commit -m "$(cat <<'EOF'
feat(packaging): add raw-test path resolver and size limit

Foundational helpers for the upcoming --upload-tests-raw flag (#390).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add pre-flight validation helper

**Why next:** Pure function, easy to reason about, used by Task 3.

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py`

**Step 1: Import the size formatter**

Find the `from rbx import` line near the top (currently `from rbx import console, utils`). Confirm `utils` is imported — `utils.format_size` is what we'll use.

**Step 2: Add validation helper**

Insert directly after `_resolve_raw_test_input_path` (added in Task 1):

```python
def _validate_raw_tests(
    entries: List['GenerationTestcaseEntry'],
) -> List[str]:
    errors: List[str] = []
    for entry in entries:
        label = entry.short_repr()
        path = _resolve_raw_test_input_path(entry)
        if path is None:
            errors.append(
                f'"{label}" was not built (input file missing)'
            )
            continue
        size = path.stat().st_size
        if size >= _RAW_TEST_SIZE_LIMIT:
            errors.append(
                f'"{label}" is {utils.format_size(size)}, '
                f'exceeds the 1 MiB Polygon limit'
            )
    return errors
```

**Step 3: Verify it loads**

Run: `uv run --active python -c "from rbx.box.packaging.polygon.upload import _validate_raw_tests; print(_validate_raw_tests([]))"`
Expected: prints `[]`.

**Step 4: Format and lint**

Run: `uv run --active ruff format rbx/box/packaging/polygon/upload.py && uv run --active ruff check rbx/box/packaging/polygon/upload.py`
Expected: no errors.

**Step 5: Commit**

```bash
git add rbx/box/packaging/polygon/upload.py
git commit -m "$(cat <<'EOF'
feat(packaging): add raw test pre-flight validator

Collects every oversized or missing-input test into a single error list
so we can abort before any Polygon API call (#390).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Implement `_upload_testcases_raw`

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py`

**Step 1: Add the function**

Insert directly after the existing `_upload_testcases` function (after line 336). Code:

```python
def _upload_testcases_raw(problem: api.Problem):
    entries = asyncio.run(extract_generation_testcases_from_groups())

    errors = _validate_raw_tests(entries)
    if errors:
        console.console.print(
            '[error]Cannot upload raw tests:[/error]'
        )
        for error in errors:
            console.console.print(f'[error]  - {error}[/error]')
        raise typer.Exit(1)

    console.console.print('Clearing existing script...')
    problem.save_script(
        testset='tests', source='<#-- empty placeholder script -->'
    )

    with rich.progress.Progress(speed_estimate_period=5) as progress:
        next_index = 1
        task_id = progress.add_task(
            'Uploading raw testcases...', total=len(entries)
        )
        for entry in entries:
            path = _resolve_raw_test_input_path(entry)
            assert path is not None  # validated above
            content = path.read_text()
            saved = _save_skip_coinciding_testcases(
                problem,
                testset='tests',
                test_index=next_index,
                test_input=content,
                **_get_test_params_for_statement(
                    entry.metadata.copied_from,
                    is_sample=entry.is_sample(),
                ),
            )
            progress.update(task_id, advance=1)
            if saved:
                next_index += 1
        progress.update(task_id, completed=len(entries))
```

**Step 2: Verify it loads**

Run: `uv run --active python -c "from rbx.box.packaging.polygon.upload import _upload_testcases_raw; print('ok')"`
Expected: prints `ok`.

**Step 3: Format and lint**

Run: `uv run --active ruff format rbx/box/packaging/polygon/upload.py && uv run --active ruff check rbx/box/packaging/polygon/upload.py`
Expected: no errors.

**Step 4: Commit**

```bash
git add rbx/box/packaging/polygon/upload.py
git commit -m "$(cat <<'EOF'
feat(packaging): add raw testcase upload path

Sibling of _upload_testcases that uploads built inputs directly,
clears the freemarker script, and skips generator uploads (#390).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Plumb `raw_tests` through `upload_problem`

**Files:**
- Modify: `rbx/box/packaging/polygon/upload.py`

**Step 1: Add the parameter**

In `upload_problem` (around line 501), extend the signature:

```python
async def upload_problem(
    name: str,
    main_language: Optional[str],
    upload_as_english: bool = False,
    upload_only: Optional[Set[str]] = None,
    dont_upload: Optional[Set[str]] = None,
    raw_tests: bool = False,
):
```

**Step 2: Branch the testcase upload**

Find the existing block:

```python
if 'tests' in which_upload:
    _upload_testcases(problem)
```

Replace with:

```python
if 'tests' in which_upload:
    if raw_tests:
        _upload_testcases_raw(problem)
    else:
        _upload_testcases(problem)
```

**Step 3: Verify it loads**

Run: `uv run --active python -c "from rbx.box.packaging.polygon.upload import upload_problem; import inspect; print('raw_tests' in inspect.signature(upload_problem).parameters)"`
Expected: prints `True`.

**Step 4: Format and lint**

Run: `uv run --active ruff format rbx/box/packaging/polygon/upload.py && uv run --active ruff check rbx/box/packaging/polygon/upload.py`
Expected: no errors.

**Step 5: Commit**

```bash
git add rbx/box/packaging/polygon/upload.py
git commit -m "$(cat <<'EOF'
feat(packaging): dispatch raw testcase upload from upload_problem

Adds raw_tests parameter; default behavior unchanged (#390).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Add CLI flag and wire build behavior

**Files:**
- Modify: `rbx/box/packaging/main.py`

**Step 1: Add the typer option**

In the `polygon` command (`main.py:14-79`), add a new option after `dont_upload` and before `validate_statement`:

```python
upload_tests_raw: bool = typer.Option(
    False,
    '--upload-tests-raw',
    help=(
        'Upload built test inputs directly instead of relying on '
        'Polygon-side generators. Skips generator uploads and clears '
        'the test script. All test inputs must be < 1 MiB. Forces a '
        'full local build. Requires --upload.'
    ),
),
```

**Step 2: Validate the flag depends on `--upload`**

Immediately after the function signature, before `should_build = ...`, add:

```python
if upload_tests_raw and not upload:
    raise typer.BadParameter(
        '--upload-tests-raw requires --upload.',
        param_hint='--upload-tests-raw',
    )
```

**Step 3: Force a full build when the flag is set**

Change the existing line:

```python
should_build = not upload and not validate_statement
```

to:

```python
should_build = (not upload and not validate_statement) or upload_tests_raw
```

**Step 4: Pass the flag to `upload_problem`**

In the `if upload:` block at the bottom, extend the call:

```python
await upload_problem(
    name=get_problem_name_with_contest_info(),
    main_language=language,
    upload_as_english=upload_as_english,
    upload_only=set(upload_only or []),
    dont_upload=set(dont_upload or []),
    raw_tests=upload_tests_raw,
)
```

**Step 5: Verify the help text shows the new flag**

Run: `uv run --active rbx package polygon --help`
Expected: output includes a `--upload-tests-raw` line with the help text from Step 1.

**Step 6: Verify the dependency check**

Run: `uv run --active rbx package polygon --upload-tests-raw 2>&1 | head -20 || true`
Expected: exits non-zero with a message mentioning `--upload-tests-raw requires --upload`. (The command may also need to be run from inside a problem directory; if you see the `within_problem` error first, that's also acceptable — the BadParameter check fires after `@within_problem` succeeds, so cd into a sample problem like `testdata/box1` if needed: `cd tests/rbx/box/testdata/box1 && uv run --active rbx package polygon --upload-tests-raw`).

**Step 7: Format and lint**

Run: `uv run --active ruff format rbx/box/packaging/main.py && uv run --active ruff check rbx/box/packaging/main.py`
Expected: no errors.

**Step 8: Commit**

```bash
git add rbx/box/packaging/main.py
git commit -m "$(cat <<'EOF'
feat(packaging): add --upload-tests-raw flag to polygon upload

Forces a full local build, validates the --upload dependency,
and forwards the option to upload_problem (#390).

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Document the new flag in the module CLAUDE.md

**Files:**
- Modify: `rbx/box/packaging/CLAUDE.md`

**Step 1: Update the CLI Commands table**

Find the row in the "CLI Commands" table for `rbx package polygon`. Change the "Extra Options" cell from:

```
`--upload`, `--language`, `--upload-as-english`, `--upload-only`, `--upload-skip`
```

to:

```
`--upload`, `--language`, `--upload-as-english`, `--upload-only`, `--upload-skip`, `--upload-tests-raw`
```

**Step 2: Add a one-line note in the Polygon section**

In the "API Upload (`upload.py`)" bullet list (under `### Polygon`), add a new bullet at the end:

```markdown
- `--upload-tests-raw` escape hatch: uploads built test inputs as raw files (1 MiB cap each), skips generator uploads, and clears the freemarker script. Use when Polygon-side generator compilation is failing.
```

**Step 3: Commit**

```bash
git add rbx/box/packaging/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(packaging): document --upload-tests-raw escape hatch

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Final verification

**Files:** none (verification only)

**Step 1: Lint and format the whole project**

Run: `uv run --active ruff check . && uv run --active ruff format --check .`
Expected: clean.

**Step 2: Smoke-import the modified modules**

Run: `uv run --active python -c "from rbx.box.packaging.polygon import upload; from rbx.box.packaging import main; print('ok')"`
Expected: prints `ok`.

**Step 3: Confirm the help output**

Run: `uv run --active rbx package polygon --help | grep -A1 upload-tests-raw`
Expected: shows the flag line and the first line of the help text.

**Step 4: Inspect the diff**

Run: `git log --oneline main..HEAD`
Expected: 6 commits — Task 1 through Task 6.

Run: `git diff --stat main..HEAD`
Expected: changes only in `rbx/box/packaging/polygon/upload.py`, `rbx/box/packaging/main.py`, `rbx/box/packaging/CLAUDE.md`, and the previously-committed design doc.

**Step 5: Confirm no behavior change for the default path**

Visually re-read the diff in `_upload_testcases` (the existing function) and confirm it is **untouched**. The new flag only adds a sibling and a dispatch branch.

**Step 6 (optional, requires Polygon credentials):** Manual smoke against a real problem. From a problem directory with a small test set (all inputs < 1 MiB), run:

```bash
POLYGON_API_KEY=... POLYGON_API_SECRET=... \
  uv run --active rbx package polygon --upload --upload-tests-raw
```

Expected: full build runs, "Clearing existing script..." prints, every test uploads as raw, no `_upload_generator` calls. Confirm in Polygon UI that tests are present and the script is empty.

If you don't have credentials handy, skip — call this out in the PR description so the reviewer knows to verify before merging.
