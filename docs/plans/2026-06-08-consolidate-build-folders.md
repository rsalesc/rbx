# Consolidate Build Folders Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make contest statement builds honor the configurable `buildDir` and use the same `build/statements/` intermediate folder name as problems.

**Architecture:** Add two cached path helpers to `contest_package.py` mirroring the problem-side helpers in `package.py` (`get_contest_build_path` → `find_contest(root) / environment.get_build_dir()`, and `get_contest_statements_build_path` → that `/ 'statements'`). Then rewire the two hardcoded `pathlib.Path('build')` sites in `build_contest_statements.py` to use them.

**Tech Stack:** Python 3, Pydantic v2, pytest, Typer.

Design doc: `docs/plans/2026-06-08-consolidate-build-folders-design.md`

---

### Task 1: Add contest build-path helpers

**Files:**
- Modify: `rbx/box/contest/contest_package.py` (add `environment` import + two helpers after `find_contest`, ~line 209)
- Test: `tests/rbx/box/contest/test_contest_package.py`

**Step 1: Write the failing tests**

Add a new test class at the end of `tests/rbx/box/contest/test_contest_package.py`:

```python
class TestContestBuildPaths:
    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        cp_module.find_contest_yaml.cache_clear()
        cp_module.get_contest_build_path.cache_clear()
        cp_module.get_contest_statements_build_path.cache_clear()
        yield
        cp_module.find_contest_yaml.cache_clear()
        cp_module.get_contest_build_path.cache_clear()
        cp_module.get_contest_statements_build_path.cache_clear()

    def test_build_path_uses_default_build_dir(self, tmp_path: pathlib.Path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')

        assert cp_module.get_contest_build_path(tmp_path) == tmp_path / 'build'

    def test_statements_build_path_under_build(self, tmp_path: pathlib.Path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')

        assert (
            cp_module.get_contest_statements_build_path(tmp_path)
            == tmp_path / 'build' / 'statements'
        )

    def test_build_path_honors_custom_build_dir(self, tmp_path: pathlib.Path):
        from unittest import mock

        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')

        with mock.patch.object(
            cp_module.environment, 'get_build_dir', return_value=pathlib.Path('out')
        ):
            cp_module.get_contest_build_path.cache_clear()
            cp_module.get_contest_statements_build_path.cache_clear()
            assert cp_module.get_contest_build_path(tmp_path) == tmp_path / 'out'
            assert (
                cp_module.get_contest_statements_build_path(tmp_path)
                == tmp_path / 'out' / 'statements'
            )
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py::TestContestBuildPaths -v`
Expected: FAIL with `AttributeError: ... has no attribute 'get_contest_build_path'`

**Step 3: Write minimal implementation**

In `rbx/box/contest/contest_package.py`, add `environment` to the box import:

```python
from rbx.box import cd, environment
```

Then add, right after `find_contest` (after line 209):

```python
@functools.cache
def get_contest_build_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    return find_contest(root) / environment.get_build_dir()


@functools.cache
def get_contest_statements_build_path(
    root: pathlib.Path = pathlib.Path(),
) -> pathlib.Path:
    return get_contest_build_path(root) / 'statements'
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_package.py::TestContestBuildPaths -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "feat(contest): add buildDir-aware contest build-path helpers (#353)"
```

---

### Task 2: Rewire contest statement builder to the helpers

**Files:**
- Modify: `rbx/box/contest/build_contest_statements.py:383-384` (`get_statement_build_dir`) and `:410`
- Test: `tests/rbx/box/contest/test_contest_package.py` (the helpers test above already covers path resolution; add a focused assertion on `get_statement_build_dir`)

**Step 1: Write the failing test**

Add to the `TestContestBuildPaths` class:

```python
    def test_statement_build_dir_uses_statements_folder(
        self, tmp_path: pathlib.Path
    ):
        from rbx.box.contest import build_contest_statements
        from rbx.box.contest.schema import ContestStatement
        from rbx.box.statements.schema import StatementType

        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        statement = ContestStatement(
            name='st', path=pathlib.Path('st.rbx.tex'), type=StatementType.rbxTeX
        )

        with cd.new_package_cd(tmp_path):
            result = build_contest_statements.get_statement_build_dir(statement)

        assert result == tmp_path / 'build' / 'statements' / 'st'
```

> Verify the `ContestStatement` constructor args and `StatementType` member during
> implementation — read `rbx/box/contest/schema.py` and `rbx/box/statements/schema.py`
> and adjust the minimal valid construction if needed. `cd` is already imported in
> the module under test; import it in the test if not present.

**Step 2: Run test to verify it fails**

Run: `uv run pytest "tests/rbx/box/contest/test_contest_package.py::TestContestBuildPaths::test_statement_build_dir_uses_statements_folder" -v`
Expected: FAIL — result is `build/statement_build/st`, not `<tmp>/build/statements/st`.

**Step 3: Write the implementation**

In `rbx/box/contest/build_contest_statements.py`, ensure the contest_package import exists (add if missing):

```python
from rbx.box.contest import contest_package
```

Replace `get_statement_build_dir` (lines 383-384):

```python
def get_statement_build_dir(statement: ContestStatement) -> pathlib.Path:
    return contest_package.get_contest_statements_build_path() / statement.name
```

Replace the final output path (line 410):

```python
    statement_path = (
        contest_package.get_contest_build_path() / statement.name
    ).with_suffix(last_output.get_file_suffix())
```

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/box/contest tests/rbx/box/statements -q`
Expected: PASS (no regressions; new assertion passes).

**Step 5: Lint and format**

Run: `uv run ruff check rbx/box/contest/build_contest_statements.py rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py && uv run ruff format rbx/box/contest/build_contest_statements.py rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py`
Expected: clean.

**Step 6: Commit**

```bash
git add rbx/box/contest/build_contest_statements.py tests/rbx/box/contest/test_contest_package.py
git commit -m "refactor(contest): build statements under buildDir/statements (#353)"
```

---

### Task 3: Final verification

**Step 1:** Re-read the issue and design doc; confirm both inconsistencies are resolved (buildDir honored + folder renamed).

**Step 2:** Run the broader contest + statements + naming suites once more:
`uv run pytest tests/rbx/box/contest tests/rbx/box/statements tests/rbx/box/test_naming.py -q`
Expected: PASS.

**Step 3:** Grep for any remaining hardcoded contest build literals:
`grep -rn "statement_build\|pathlib.Path('build')" rbx/box/contest/`
Expected: no matches.
