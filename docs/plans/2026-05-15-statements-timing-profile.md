# Statement Timing-Profile Flag Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `-p/--profile <name>` to `rbx st b` and `rbx contest st b` so statements render against a specific timing profile, with strict validation (problem level) and skip-with-warn (contest level).

**Architecture:** Both subcommands accept `--profile, -p`. The statement builder already reads the active profile from `rbx.box.limits_info.profile_var` and exposes `problem.limits.timelimit_for_language(...)` to the Jinja/rbxTeX layer — so no template, schema, or builder changes are needed. The only new logic is (a) wiring the flag through `limits_info.use_profile(...)`, (b) strictly validating the profile exists at the problem level, and (c) filtering out problems missing the profile at the contest level (warn + skip; error if zero problems remain).

**Tech Stack:** Python, Typer, Pydantic v2, pytest. Existing primitives: `rbx.box.limits_info.use_profile`, `rbx.box.limits_info.get_saved_limits_profile`, `rbx.box.limits_info.get_limits_profile(..., fallback_to_package_profile=False)`.

**Design doc:** `docs/plans/2026-05-15-statements-timing-profile-design.md`.

**Issue:** [#456](https://github.com/rsalesc/rbx/issues/456).

---

## Background a new engineer must read first

- `rbx/box/limits_info.py` — the whole file (especially `profile_var`, `use_profile`, `get_saved_limits_profile`, `get_limits_profile`).
- `rbx/box/statements/build_statements.py:300-335` — see how `StatementBuilderProblem.limits` already calls `get_limits_profile(profile=get_active_profile())`. This is why the Jinja side needs no changes.
- `rbx/box/cli.py:152-217` — the global `-p/--profile` flag on the root callback. The new subcommand flags compose with this (subcommand wins, last set).
- `rbx/box/CLAUDE.md` and `rbx/box/statements/CLAUDE.md` — module overviews.
- `tests/rbx/box/test_timing.py:295-360` — examples of writing `.limits/<profile>.yml` files in `testing_pkg` fixtures.
- `tests/rbx/box/statements/test_build_statements.py` — existing test patterns for the statement builder, including the `mock_environment` and `chdir_tmp_path` fixtures.
- `tests/rbx/box/conftest.py` and `tests/rbx/box/contest/conftest.py` — `cleandir_with_testdata` and `testing_pkg` fixtures; `.limits/` is already gitignored in the fixture write-out, so `.limits/<x>.yml` files inside a `testdata/` package will be copied through.

**TDD discipline:** every task that changes code starts with a failing test, then implementation, then green test, then commit. Use the existing `mise run lint` / `uv run pytest` invocations.

---

## Task 1: Add `-p/--profile` to `rbx st b` (problem-level), strict validation

**Files:**
- Modify: `rbx/box/statements/build_statements.py` (around lines 435-513)
- Test: `tests/rbx/box/statements/test_build_statements.py`

**Approach:** Add a `profile: Optional[str]` Typer option to `build(...)`, thread it through to `execute_build(...)`, and inside `execute_build` (before anything else) call `limits_info.get_limits_profile(profile, fallback_to_package_profile=False)` to validate. Then wrap the rest of `execute_build` in `with limits_info.use_profile(profile):`. The existing inner code (`build_statement_bytes` line 316) already reads the active profile.

### Step 1: Write failing test — strict failure when profile is missing

Add to `tests/rbx/box/statements/test_build_statements.py`. This is a unit-level test against `execute_build` (sync wrapper via `asyncio.run`) inside a `cleandir_with_testdata` package that has statements but no `.limits/icpc.yml`.

```python
# At the top of the file, augment imports:
import asyncio
from rbx.box.statements.build_statements import execute_build

@pytest.mark.test_pkg('box/statements/testdata/with_statement')
def test_execute_build_strict_profile_missing_exits(cleandir_with_testdata):
    with pytest.raises(typer.Exit) as exc_info:
        asyncio.run(
            execute_build(
                verification=0,
                names=None,
                languages=None,
                output=StatementType.PDF,
                samples=False,
                vars=None,
                validate=False,
                profile='does-not-exist',
            )
        )
    assert exc_info.value.exit_code == 1
```

> If `box/statements/testdata/with_statement` doesn't exist, pick an existing minimal-statement fixture by inspecting `tests/rbx/box/statements/testdata/` and update the marker accordingly. The fixture must (a) parse as a valid problem package and (b) have at least one statement. Do not invoke pdflatex — the missing-profile error must trigger before any rendering.

Run: `uv run pytest tests/rbx/box/statements/test_build_statements.py::test_execute_build_strict_profile_missing_exits -v`
Expected: FAIL with `TypeError: execute_build() got an unexpected keyword argument 'profile'`.

### Step 2: Add the `profile` parameter and validation logic

In `rbx/box/statements/build_statements.py`:

- Extend `execute_build(...)` signature with `profile: Optional[str] = None` (after `validate`).
- At the very top of the function (before `pkg = package.find_problem_package_or_die()`), if `profile is not None`, call `limits_info.get_limits_profile(profile, fallback_to_package_profile=False)` to trigger the existing strict error path (prints message and raises `typer.Exit(1)`).
- Wrap the body of `execute_build` (everything after the validation call) in `with limits_info.use_profile(profile):`.
- Extend the Typer `build(...)` command (around line 476) with:

```python
profile: Annotated[
    Optional[str],
    typer.Option(
        '-p',
        '--profile',
        help='Timing profile to render the statement against. Must exist in this problem.',
    ),
] = None,
```

- Pass `profile=profile` through the `execute_build(...)` call at line 513.
- Add the import: `from rbx.box import limits_info` if not already present (it is — confirm).

Run: `uv run pytest tests/rbx/box/statements/test_build_statements.py::test_execute_build_strict_profile_missing_exits -v`
Expected: PASS.

### Step 3: Write failing test — profile applies and reaches the builder

Add a second test that confirms the profile takes effect. Don't render PDFs; instead assert against `limits_info.get_active_profile()` inside `use_profile`, or call `build_statement_bytes` with `output_type=StatementType.MARKDOWN` (cheap) on a fixture that has a `.limits/icpc.yml` setting `timeLimit: 5000` and verify the rendered markdown contains "5000" via `{{ problem.limits.timeLimit }}` in the template.

Cheapest, most direct version (no template surgery needed): assert that `execute_build(profile='icpc', ...)` does NOT raise when a matching `.limits/icpc.yml` exists in the fixture, AND that during the call the active profile is `'icpc'`. Use `monkeypatch` to replace `execute_build_on_statements` with a sentinel that records `limits_info.get_active_profile()`.

```python
@pytest.mark.test_pkg('box/statements/testdata/with_statement')
def test_execute_build_strict_profile_applies(cleandir_with_testdata, monkeypatch):
    # Provide a profile in the fixture.
    (pathlib.Path('.limits')).mkdir(exist_ok=True)
    (pathlib.Path('.limits/icpc.yml')).write_text('timeLimit: 5000\n')

    seen = {}
    async def fake_execute_build_on_statements(statements, *args, **kwargs):
        seen['profile'] = limits_info.get_active_profile()

    monkeypatch.setattr(
        'rbx.box.statements.build_statements.execute_build_on_statements',
        fake_execute_build_on_statements,
    )
    asyncio.run(
        execute_build(
            verification=0,
            names=None,
            languages=None,
            output=StatementType.PDF,
            samples=False,
            vars=None,
            validate=False,
            profile='icpc',
        )
    )
    assert seen['profile'] == 'icpc'
```

> Add the missing imports (`pathlib`, `from rbx.box import limits_info`).

Run: `uv run pytest tests/rbx/box/statements/test_build_statements.py::test_execute_build_strict_profile_applies -v`
Expected: PASS (the implementation in Step 2 already does this).

### Step 4: Run the full file to make sure nothing else broke

Run: `uv run pytest tests/rbx/box/statements/test_build_statements.py -v`
Expected: ALL PASS.

### Step 5: Lint and format

Run: `uv run ruff check rbx/box/statements/build_statements.py tests/rbx/box/statements/test_build_statements.py && uv run ruff format rbx/box/statements/build_statements.py tests/rbx/box/statements/test_build_statements.py`
Expected: clean / no diffs after format.

### Step 6: Commit

Use the `/commit` skill (conventional commits required):

```
feat(statements): add -p/--profile to rbx st b with strict validation (#456)
```

---

## Task 2: Add `-p/--profile` to `rbx contest st b` (contest-level), skip-with-warn

**Files:**
- Modify: `rbx/box/contest/statements.py:25-132`
- Modify: `rbx/box/contest/build_contest_statements.py:180-229` (and likely `build_statement` higher up — read the full function)
- Test: new file `tests/rbx/box/contest/test_statements_profile.py`

**Approach:** Add a `profile: Optional[str]` Typer option to the contest `build(...)`. Before any work, compute the eligible problem subset (problems whose `.limits/<profile>.yml` file exists). If empty, exit 1. Otherwise warn for each skipped problem, then run the existing samples loop and statement loop limited to the eligible subset. Wrap each problem-level `build_statement_bytes` call in `limits_info.use_profile(profile)` (already done via the new `problems_of_interest`/`build_statement` pipeline if you push the profile through; alternatively, set it once at the contest level since the contest already CDs per problem and reads the contextvar — confirm during implementation).

### Step 1: Write failing test — contest build skips problems missing the profile

In a new file `tests/rbx/box/contest/test_statements_profile.py`. Use the existing contest test fixtures. Inspect `tests/rbx/box/contest/testdata/` and pick a small two-problem contest fixture; if none has exactly the shape needed, create one (a contest with problems `A` and `B`, where only `A/.limits/icpc.yml` exists). Mock the heavy per-problem statement build via monkeypatch to record which problems were processed and which were skipped.

```python
import asyncio
import pathlib

import pytest
import typer

from rbx.box import limits_info
from rbx.box.contest import statements as contest_statements_cli
from rbx.box.statements.schema import StatementType


@pytest.mark.test_pkg('box/contest/testdata/two_problems')
def test_contest_build_skips_problems_missing_profile(cleandir_with_testdata, monkeypatch):
    # Only problem A has the icpc profile.
    (pathlib.Path('A/.limits')).mkdir(parents=True, exist_ok=True)
    (pathlib.Path('A/.limits/icpc.yml')).write_text('timeLimit: 5000\n')

    built_for = []
    async def fake_build_statement(statement, contest, *, problems_of_interest=None, **kwargs):
        built_for.append([p.short_name for p in (problems_of_interest or [])])
        return pathlib.Path('fake.pdf')

    monkeypatch.setattr(
        'rbx.box.contest.statements.build_statement',
        fake_build_statement,
    )

    asyncio.run(
        contest_statements_cli.build.__wrapped__(  # bypass @syncer.sync if needed
            verification=0,
            names=None,
            languages=None,
            validate=False,
            output=StatementType.PDF,
            samples=False,
            vars=None,
            install_tex=False,
            profile='icpc',
        )
    )

    assert built_for, 'expected at least one statement build call'
    # B must NOT be in any built statement's problems_of_interest.
    for problems in built_for:
        assert 'B' not in problems
```

> The Typer-decorated `build` may be wrapped by `@syncer.sync` and `@within_contest`. If `.__wrapped__` is the wrong attribute, find the underlying async function or use `typer.testing.CliRunner` to invoke the CLI end-to-end instead. Read how `tests/rbx/box/contest/test_contest_main.py` (if present) calls contest CLI commands and mirror it.

Run: `uv run pytest tests/rbx/box/contest/test_statements_profile.py -v`
Expected: FAIL (likely `TypeError: unexpected keyword argument 'profile'`).

### Step 2: Add `--profile` option + eligible-subset filtering to the CLI

In `rbx/box/contest/statements.py`:

1. Add the parameter to `build(...)`:

   ```python
   profile: Annotated[
       Optional[str],
       typer.Option(
           '-p',
           '--profile',
           help='Timing profile to render statements against. Problems missing this profile are skipped with a warning.',
       ),
   ] = None,
   ```

2. After `contest = find_contest_package_or_die()`, compute the eligible subset:

   ```python
   eligible_problems: List[ContestProblem] = list(contest.problems)
   if profile is not None:
       eligible_problems = []
       for problem in contest.problems:
           saved = limits_info.get_saved_limits_profile(profile, root=problem.get_path())
           if saved is None:
               console.console.print(
                   f'[warning]Skipping problem [item]{problem.short_name}[/item]: timing profile [item]{profile}[/item] is not defined for it.[/warning]'
               )
               continue
           eligible_problems.append(problem)
       if not eligible_problems:
           console.console.print(
               f'[error]No problems in this contest define the timing profile [item]{profile}[/item].[/error]'
           )
           raise typer.Exit(1)
   ```

3. Replace the existing samples loop's iterator from `contest.problems` to `eligible_problems`. After the loop, `problems_of_interest` is already a list filtered by sample success; keep that behaviour, but when `samples=False` the value stays `None` — in that case set `problems_of_interest = eligible_problems` if `profile is not None`, so the downstream `build_statement` sees the restricted subset:

   ```python
   if profile is not None and problems_of_interest is None:
       problems_of_interest = eligible_problems
   ```

4. Wrap the per-statement loop in `with limits_info.use_profile(profile):` so that when the inner `build_statement_bytes` runs (it CDs into each problem) it reads the right active profile. Note: `build_contest_statements._build_problem_statements` itself does NOT currently set a profile context, so this single contest-level `use_profile` wrapper is sufficient because the contextvar is process-global within the request.

5. Add imports: `from rbx.box import limits_info`.

Run: `uv run pytest tests/rbx/box/contest/test_statements_profile.py -v`
Expected: PASS.

### Step 3: Add failing test — all-missing case exits 1

Append to the same test file:

```python
@pytest.mark.test_pkg('box/contest/testdata/two_problems')
def test_contest_build_all_missing_profile_exits(cleandir_with_testdata):
    with pytest.raises(typer.Exit) as exc_info:
        asyncio.run(
            contest_statements_cli.build.__wrapped__(
                verification=0,
                names=None,
                languages=None,
                validate=False,
                output=StatementType.PDF,
                samples=False,
                vars=None,
                install_tex=False,
                profile='nonexistent',
            )
        )
    assert exc_info.value.exit_code == 1
```

Run: `uv run pytest tests/rbx/box/contest/test_statements_profile.py::test_contest_build_all_missing_profile_exits -v`
Expected: PASS (Step 2 already implements the empty-subset branch).

### Step 4: Run the full contest test suite

Run: `uv run pytest tests/rbx/box/contest/ -v`
Expected: ALL PASS. If any pre-existing test fails because it called `build(...)` positionally and our new `profile=None` parameter shifted positions, fix those call sites (they should already use keyword arguments — Typer commands are typically called via the CLI, not directly).

### Step 5: Lint and format

Run: `uv run ruff check rbx/box/contest/statements.py tests/rbx/box/contest/test_statements_profile.py && uv run ruff format rbx/box/contest/statements.py tests/rbx/box/contest/test_statements_profile.py`
Expected: clean.

### Step 6: Commit

```
feat(contest/statements): add -p/--profile to rbx contest st b with skip-with-warn (#456)
```

---

## Task 3: End-to-end CLI smoke (optional but recommended)

**Files:**
- Test: `tests/e2e/<existing-statement-fixture>/e2e.rbx.yml` — add a case OR new fixture directory.

This is a guard against regressions in the full Typer wiring. The unit tests above use direct function calls; an E2E run exercises argument parsing, the global callback, and Typer help routing. See `tests/e2e/README.md` for the DSL.

### Step 1: Add a scenario that runs `rbx st b -p localprofile --output markdown --no-samples` on a fixture that has a `.limits/localprofile.yml`

Pick an existing E2E fixture under `tests/e2e/` that already builds a markdown statement. Add a `.limits/localprofile.yml` (with `timeLimit: 7777`) and append a step that runs `rbx st b -p localprofile -o MARKDOWN --no-samples` and greps the output markdown for `7777`. If no such fixture exists, skip this task — the unit tests are sufficient.

Run: `mise run test-e2e -- -k <new-scenario>`
Expected: PASS.

### Step 2: Commit

```
test(e2e): cover statements -p profile selection (#456)
```

---

## Task 4: Update user-facing docs

**Files:**
- Modify: any markdown under `docs/` that documents `rbx st b` or `rbx contest st b` (search with `rg -l "rbx st b|rbx statements build|rbx contest st b" docs/`).

### Step 1: Add a short paragraph and example

Document the new flag in the appropriate place. Mention:

- Behaviour: validates the profile exists; for contests, skips problems missing the profile.
- Equivalent to `rbx -p <profile> st b` for the problem-level command (subcommand wins if both passed).

### Step 2: Commit

```
docs: document -p/--profile on statement build commands (#456)
```

---

## Task 5: Final verification

### Step 1: Run the test subset relevant to this change

Run: `uv run pytest tests/rbx/box/statements tests/rbx/box/contest tests/rbx/box/test_timing.py -v`
Expected: ALL PASS.

### Step 2: Run lint across touched files

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

### Step 3: Manual sanity check on a real package

In a real problem package with at least one `.limits/<profile>.yml`:

```bash
uv run rbx st b -p <profile> --output MARKDOWN --no-samples
```

Confirm the rendered markdown reflects the profile's time limit. Then:

```bash
uv run rbx st b -p typo --output MARKDOWN --no-samples
```

Confirm the command exits non-zero with the "Limits profile not found" error.

### Step 4: Use the finishing-a-development-branch skill

REQUIRED SUB-SKILL: `superpowers:finishing-a-development-branch` to decide between PR, merge, or further cleanup.
