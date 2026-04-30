# Contest Problem Folder Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When `contest.rbx.yml` is loaded, fail fast and clearly if any `ContestProblem` references a folder that doesn't exist or doesn't contain a `problem.rbx.yml`.

**Architecture:** Two standalone helper functions in `rbx/box/contest/contest_package.py` (`validate_problem_folders_exist` and `validate_problem_folders_are_packages`), each collecting all violations and exiting with a single multi-line `[error]` message. Both are called from `find_contest_package` after `model_from_yaml` succeeds — existence check first, then the package-file check.

**Tech Stack:** Python 3.14, Pydantic v2, Typer, Rich, pytest, ruff.

**Design doc:** `docs/plans/2026-04-30-contest-problem-folder-validation-design.md`

---

## Notes for the implementer

- `find_contest_package` and `find_contest_yaml` are decorated with `@functools.cache`. Integration tests that load real contests from disk **must** call `find_contest_package.cache_clear()` and `find_contest_yaml.cache_clear()` to avoid stale results across tests. Use a `pytest` fixture or call directly inside each test.
- All strings in this codebase use **single quotes** (ruff `Q` rule). Match existing style in `contest_package.py`.
- Imports must be **absolute**, not relative (ruff `TID`).
- The Rich console exposes `console.console.print(...)`. Existing error messages use `'[error]...[/error]'` markup or `style='error'`. Match what's already in `contest_package.py` (uses `[error]...[/error]` with explicit closing tags).
- `ContestProblem.get_path()` returns `self.path or pathlib.Path(self.short_name)`. The returned path may be relative or absolute. Resolve relative paths against the contest root (parent of `contest.rbx.yml`).
- Tests for the helpers should call them directly (no need to load YAML through `find_contest_package`). Construct `Contest(name='c', problems=[ContestProblem(short_name='A', path=...)])` directly.
- `typer.Exit(1)` is raised, not returned. Catch via `pytest.raises(typer.Exit)` and inspect the captured output via `capsys` or rich's recording — matching the existing test patterns (the codebase uses `pytest.raises(typer.Exit)` in several tests).
- Run only contest-related tests during the cycle for fast feedback: `uv run pytest tests/rbx/box/contest/ -v`. Run the full non-CLI suite once at the end.

---

## Task 1: Add failing test for `validate_problem_folders_exist` happy path

**Files:**
- Create: `tests/rbx/box/contest/test_contest_package.py`

**Step 1: Write the failing test**

```python
"""Tests for contest_package validation helpers."""

import pathlib

import pytest
import typer

from rbx.box.contest.contest_package import validate_problem_folders_exist
from rbx.box.contest.schema import Contest, ContestProblem


def _make_contest(*problems: ContestProblem) -> Contest:
    return Contest(name='c', problems=list(problems))


class TestValidateProblemFoldersExist:
    def test_all_folders_exist_does_not_raise(self, tmp_path: pathlib.Path):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'B').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
        )

        validate_problem_folders_exist(contest, tmp_path)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py -v`
Expected: FAIL with `ImportError: cannot import name 'validate_problem_folders_exist'`

**Step 3: Add minimal implementation**

In `rbx/box/contest/contest_package.py`, add (just below the `YAML_NAME = 'contest.rbx.yml'` line):

```python
def validate_problem_folders_exist(
    contest: Contest, contest_root: pathlib.Path
) -> None:
    pass
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py -v`
Expected: PASS (1 passed)

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "test(contest): add happy-path test for validate_problem_folders_exist"
```

---

## Task 2: Make `validate_problem_folders_exist` actually fail when a folder is missing

**Files:**
- Modify: `rbx/box/contest/contest_package.py`
- Modify: `tests/rbx/box/contest/test_contest_package.py`

**Step 1: Add failing test for missing folder**

Append inside `TestValidateProblemFoldersExist`:

```python
    def test_missing_folder_exits_and_names_short_name(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        # B has no folder.
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        captured = capsys.readouterr()
        assert 'B' in captured.out
        assert 'A' not in captured.out.replace('[error]', '').replace('[/error]', '')
```

(The slightly awkward `replace` checks that 'A' is not mentioned as a problem; `[error]` markup may otherwise contain stray letters.)

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py::TestValidateProblemFoldersExist::test_missing_folder_exits_and_names_short_name -v`
Expected: FAIL — function currently does nothing.

**Step 3: Implement the validator**

Replace the stub in `rbx/box/contest/contest_package.py`:

```python
def validate_problem_folders_exist(
    contest: Contest, contest_root: pathlib.Path
) -> None:
    missing: List[Tuple[str, pathlib.Path]] = []
    for problem in contest.problems:
        problem_path = problem.get_path()
        resolved = (
            problem_path
            if problem_path.is_absolute()
            else contest_root / problem_path
        )
        if not resolved.is_dir():
            missing.append((problem.short_name, resolved))

    if not missing:
        return

    console.console.print(
        '[error]Some contest problems point to folders that do not exist:[/error]'
    )
    for short_name, resolved in missing:
        console.console.print(
            f'[error]  - {short_name}: {resolved}[/error]'
        )
    raise typer.Exit(1)
```

`Tuple` and `List` are already imported. `console`, `typer`, `pathlib` are already imported.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py -v`
Expected: PASS (2 passed)

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "feat(contest): validate that problem folders exist on contest load"
```

---

## Task 3: Cover edge cases for `validate_problem_folders_exist`

**Files:**
- Modify: `tests/rbx/box/contest/test_contest_package.py`

**Step 1: Add four edge-case tests**

Append to `TestValidateProblemFoldersExist`:

```python
    def test_multiple_missing_folders_listed_together(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'B').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
            ContestProblem(short_name='C'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        out = capsys.readouterr().out
        assert 'A' in out
        assert 'C' in out

    def test_custom_relative_path_resolved_against_contest_root(
        self, tmp_path: pathlib.Path
    ):
        (tmp_path / 'probs' / 'alpha').mkdir(parents=True)
        contest = _make_contest(
            ContestProblem(
                short_name='A', path=pathlib.Path('probs') / 'alpha'
            ),
        )

        validate_problem_folders_exist(contest, tmp_path)

    def test_absolute_path_used_as_is(self, tmp_path: pathlib.Path):
        problem_dir = tmp_path / 'somewhere' / 'else'
        problem_dir.mkdir(parents=True)
        contest = _make_contest(
            ContestProblem(short_name='A', path=problem_dir),
        )

        # Passing a different `contest_root` must not affect validation
        # because the path is absolute.
        other_root = tmp_path / 'unrelated'
        other_root.mkdir()
        validate_problem_folders_exist(contest, other_root)

    def test_path_pointing_to_file_is_reported_as_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        # A is a file, not a directory.
        (tmp_path / 'A').write_text('not a folder')
        contest = _make_contest(ContestProblem(short_name='A'))

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        assert 'A' in capsys.readouterr().out
```

**Step 2: Run tests**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py -v`
Expected: PASS (6 passed)

**Step 3: Commit**

```bash
git add tests/rbx/box/contest/test_contest_package.py
git commit -m "test(contest): cover edge cases for problem folder existence check"
```

---

## Task 4: Add `validate_problem_folders_are_packages` (TDD)

**Files:**
- Modify: `rbx/box/contest/contest_package.py`
- Modify: `tests/rbx/box/contest/test_contest_package.py`

**Step 1: Add failing tests**

Append a new test class to `tests/rbx/box/contest/test_contest_package.py`:

```python
from rbx.box.contest.contest_package import (
    validate_problem_folders_are_packages,  # noqa: I001 (placed after existing import)
)


class TestValidateProblemFoldersArePackages:
    def test_folder_with_yaml_does_not_raise(self, tmp_path: pathlib.Path):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        contest = _make_contest(ContestProblem(short_name='A'))

        validate_problem_folders_are_packages(contest, tmp_path)

    def test_folder_without_yaml_exits(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        # No problem.rbx.yml inside.
        contest = _make_contest(ContestProblem(short_name='A'))

        with pytest.raises(typer.Exit):
            validate_problem_folders_are_packages(contest, tmp_path)

        out = capsys.readouterr().out
        assert 'A' in out

    def test_multiple_folders_without_yaml_listed_together(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        (tmp_path / 'B').mkdir()
        (tmp_path / 'C').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
            ContestProblem(short_name='C'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_are_packages(contest, tmp_path)

        out = capsys.readouterr().out
        assert 'B' in out
        assert 'C' in out
```

Move the new import to the top with the existing imports (combine into `from rbx.box.contest.contest_package import (validate_problem_folders_are_packages, validate_problem_folders_exist)`). Drop the inline import comment.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py -v`
Expected: FAIL on import — `validate_problem_folders_are_packages` not defined.

**Step 3: Implement the validator**

In `rbx/box/contest/contest_package.py`, add right after `validate_problem_folders_exist`:

```python
def validate_problem_folders_are_packages(
    contest: Contest, contest_root: pathlib.Path
) -> None:
    missing: List[Tuple[str, pathlib.Path]] = []
    for problem in contest.problems:
        problem_path = problem.get_path()
        resolved = (
            problem_path
            if problem_path.is_absolute()
            else contest_root / problem_path
        )
        if not (resolved / YAML_NAME.replace('contest', 'problem')).is_file():
            missing.append((problem.short_name, resolved))

    if not missing:
        return

    console.console.print(
        '[error]Some contest problem folders are missing problem.rbx.yml:[/error]'
    )
    for short_name, resolved in missing:
        console.console.print(
            f'[error]  - {short_name}: {resolved}[/error]'
        )
    raise typer.Exit(1)
```

> **Stop:** that `YAML_NAME.replace(...)` is too cute. Replace with a direct constant reference. At the top of the file (next to `YAML_NAME`), add:
>
> ```python
> PROBLEM_YAML_NAME = 'problem.rbx.yml'
> ```
>
> and use it in the helper:
>
> ```python
>         if not (resolved / PROBLEM_YAML_NAME).is_file():
> ```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py -v`
Expected: PASS (9 passed total).

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "feat(contest): validate problem folders contain problem.rbx.yml"
```

---

## Task 5: Wire both validators into `find_contest_package`

**Files:**
- Modify: `rbx/box/contest/contest_package.py`

**Step 1: Add a failing integration test**

Append to `tests/rbx/box/contest/test_contest_package.py`:

```python
from rbx.box.contest import contest_package as cp_module


class TestFindContestPackageValidation:
    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()
        yield
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()

    def _write_contest(self, root: pathlib.Path, problems: list[str]) -> None:
        problems_yaml = '\n'.join(f'  - short_name: {p}' for p in problems)
        (root / 'contest.rbx.yml').write_text(
            f'name: c\nproblems:\n{problems_yaml}\n'
        )

    def test_returns_contest_when_all_problem_folders_valid(
        self, tmp_path: pathlib.Path
    ):
        self._write_contest(tmp_path, ['A', 'B'])
        for short_name in ['A', 'B']:
            (tmp_path / short_name).mkdir()
            (tmp_path / short_name / 'problem.rbx.yml').write_text('name: p\n')

        result = cp_module.find_contest_package(tmp_path)

        assert result is not None
        assert [p.short_name for p in result.problems] == ['A', 'B']

    def test_exits_when_a_problem_folder_is_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        self._write_contest(tmp_path, ['A', 'B'])
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        # No B folder.

        with pytest.raises(typer.Exit):
            cp_module.find_contest_package(tmp_path)

        assert 'B' in capsys.readouterr().out

    def test_exits_when_problem_folder_lacks_yaml(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        self._write_contest(tmp_path, ['A'])
        (tmp_path / 'A').mkdir()
        # No problem.rbx.yml in A.

        with pytest.raises(typer.Exit):
            cp_module.find_contest_package(tmp_path)

        out = capsys.readouterr().out
        assert 'A' in out
        assert 'problem.rbx.yml' in out
```

**Step 2: Run the new tests, expect failure**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py::TestFindContestPackageValidation -v`
Expected:
- `test_returns_contest_when_all_problem_folders_valid` → PASS (already works because validation isn't wired yet, so the contest just parses).
- `test_exits_when_a_problem_folder_is_missing` → FAIL (no exit; `get_problems` isn't called by `find_contest_package`).
- `test_exits_when_problem_folder_lacks_yaml` → FAIL (same reason).

**Step 3: Wire the validators**

In `rbx/box/contest/contest_package.py`, modify `find_contest_package`:

```python
@functools.cache
def find_contest_package(root: pathlib.Path = pathlib.Path()) -> Optional[Contest]:
    contest_yaml_path = find_contest_yaml(root)
    if not contest_yaml_path:
        return None
    try:
        contest = utils.model_from_yaml(Contest, contest_yaml_path.read_text())
    except ValidationError as e:
        console.console.print(e)
        console.console.print('[error]Error parsing contest.rbx.yml.[/error]')
        console.console.print(
            '[error]If you are sure the file is correct, ensure you are '
            'in the latest version of [item]rbx[/item].[/error]'
        )
        raise typer.Exit(1) from e

    contest_root = contest_yaml_path.parent
    validate_problem_folders_exist(contest, contest_root)
    validate_problem_folders_are_packages(contest, contest_root)
    return contest
```

Note the order: existence first, then package-file check. If existence fails, we don't reach the second.

**Step 4: Run the integration tests, expect pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py -v`
Expected: PASS (12 passed total).

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "feat(contest): wire problem folder validation into find_contest_package"
```

---

## Task 6: Verify nothing else broke and clean up

**Files:**
- (No new files; verification + cleanup pass.)

**Step 1: Run all contest tests**

Run: `uv run pytest tests/rbx/box/contest/ -v`
Expected: All previously passing tests still pass (28 prior + 12 new = 40 passed, ±a few).

**Step 2: Run the broader non-CLI test suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto`
Expected: PASS (no regressions). If something fails because a test fixture creates a `Contest` and the parent test infrastructure tries to load it with missing problem folders, investigate before claiming success — that's a real regression caused by this change.

**Step 3: Lint & format**

Run: `uv run ruff check . && uv run ruff format .`
Expected: No errors. If ruff reformats anything, stage the changes.

**Step 4: Final commit (only if step 3 changed any files)**

```bash
git status
# If there are formatting changes:
git add -u
git commit -m "style: apply ruff format after contest validation work"
```

If no changes, skip this commit.

**Step 5: Confirm clean tree**

Run: `git status`
Expected: `nothing to commit, working tree clean`.

---

## Done

- Two single-purpose validators in `rbx/box/contest/contest_package.py`.
- Both wired into `find_contest_package` so every contest load checks them.
- Errors collect-and-report all violations with named `short_name`s.
- Integration + unit tests in `tests/rbx/box/contest/test_contest_package.py`.
- No regressions in the non-CLI test suite.
