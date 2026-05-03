# E2E Testing Strategy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a YAML-driven e2e test framework where dropping a barebones problem package + `e2e.rbx.yml` into `tests/e2e/testdata/` automatically becomes a pytest test that exercises `rbx run`/`build`/`st b`/`pkg <fmt>` with structured assertions.

**Architecture:** Custom pytest collection hook discovers every `e2e.rbx.yml` under `tests/e2e/testdata/`, parses it into a Pydantic `E2ESpec`, and yields one `pytest.Item` per scenario. Each item copies the package to a tmpdir via the existing `TestingPackage` helper, runs each step's `cmd` through Typer's `CliRunner`, then evaluates assertion classes against the resulting stdout/stderr/exit-code/filesystem state. Verdict assertions read on-disk artifacts (`skeleton.yml` for `rbx run`) rather than parsing CLI output.

**Tech Stack:** pytest (custom collection), Pydantic v2, Typer `CliRunner`, `shlex`, `zipfile`, `glob`/`pathlib`, existing `rbx.box.testing.testing_package.TestingPackage`.

**Reference design doc:** `docs/plans/2026-05-03-e2e-testing-strategy-design.md`. Read it before starting any task.

---

## Task 0: Spike — confirm verdict data source on disk

**Why first:** the design hinges on reading per-(solution, group, testcase) verdicts from disk. `skeleton.yml` is the *plan* (it does not contain verdicts — it lists solutions/groups/testcases/limits). Per-evaluation results are written elsewhere by the runner. We must locate the canonical on-disk verdict source before designing the `SolutionsMatcher`.

**Files:**
- Read: `rbx/box/solutions.py` (especially `_get_report_skeleton`, `_produce_solution_items`, `print_run_report`, `_evaluate_item`)
- Read: `rbx/box/ui/utils/run_ui.py` (already reads skeleton + per-eval data)
- Read: `rbx/grading/steps.py` (`Evaluation` dataclass, `Outcome` enum)

**Step 1: Trace `rbx run`**

Run a sample package end-to-end:

```bash
cd tests/rbx/box/packaging/e2e/testdata/simple-problem
uv run rbx run
ls .box/runs/                  # find skeleton.yml + per-solution dirs
find .box/runs/ -type f | head -50
```

Expected: identify the directory containing per-(solution, group, testcase) outcome data and its on-disk format (YAML? individual files?).

**Step 2: Document findings inline**

Append a short "Verdict source" section to the design doc (`docs/plans/2026-05-03-e2e-testing-strategy-design.md`) describing the exact paths, file format, and Pydantic model used. If `Evaluation` is not currently persisted, this task expands to either (a) adding a `--report` flag to `rbx run` that writes a stable JSON/YAML report, or (b) making the runner persist per-eval files. Pick whichever is least invasive; document the choice.

**Step 3: Commit**

```bash
git add docs/plans/2026-05-03-e2e-testing-strategy-design.md
git commit -m "docs(tests): document verdict on-disk source for e2e DSL"
```

---

## Task 1: Scaffold `tests/e2e/` and one fixture package

**Files:**
- Create: `tests/e2e/__init__.py` (empty)
- Create: `tests/e2e/conftest.py` (placeholder)
- Create: `tests/e2e/testdata/simple-ac/problem.rbx.yml`
- Create: `tests/e2e/testdata/simple-ac/sols/main.cpp`
- Create: `tests/e2e/testdata/simple-ac/gens/gen.cpp`
- Create: `tests/e2e/testdata/simple-ac/e2e.rbx.yml`

**Step 1: Build a minimal AC package by hand**

Use `tests/rbx/box/packaging/e2e/testdata/simple-problem/` as a reference. The new package must be small (≤ 5 testcases), have one AC solution, no statements (we add those later), and run `rbx build` cleanly when invoked manually.

**Step 2: Write the smallest possible `e2e.rbx.yml`**

```yaml
scenarios:
  - name: smoke
    steps:
      - cmd: build
```

No assertions yet — exit code 0 is the implicit assertion.

**Step 3: Verify by hand**

```bash
cd tests/e2e/testdata/simple-ac && uv run rbx build && cd -
```

Expected: build succeeds, generated `build/tests/*.in` and `build/tests/*.out` files exist.

**Step 4: Commit**

```bash
git add tests/e2e/
git commit -m "test(e2e): scaffold tests/e2e tree with simple-ac fixture"
```

---

## Task 2: Pydantic schema for `e2e.rbx.yml`

**Files:**
- Create: `tests/e2e/spec.py`
- Test: `tests/e2e/test_spec.py`

**Step 1: Write failing tests**

Cover: valid minimal scenario; rejecting unknown keys; defaulting `expect_exit` to 0; rejecting duplicate scenario names; parsing solutions in all three forms (bare verdict, `*` baseline, with overrides); accepting `ExpectedOutcome` aliases (`ac`/`AC`/`accepted`/`wa`); rejecting unknown verdicts.

```python
# tests/e2e/test_spec.py
import pytest
from rbx.box.schema import ExpectedOutcome
from tests.e2e.spec import E2ESpec, parse_spec

def test_minimal():
    spec = parse_spec({"scenarios": [{"name": "s", "steps": [{"cmd": "build"}]}]})
    assert spec.scenarios[0].steps[0].expect_exit == 0

def test_rejects_unknown_keys():
    with pytest.raises(ValueError):
        parse_spec({"scenarios": [{"name": "s", "steps": [{"cmd": "x", "typo": 1}]}]})

def test_rejects_duplicate_scenario_names():
    with pytest.raises(ValueError):
        parse_spec({"scenarios": [
            {"name": "s", "steps": []},
            {"name": "s", "steps": []},
        ]})

def test_solutions_bare_verdict_parses_as_star_map():
    spec = parse_spec({"scenarios": [{"name": "s", "steps": [
        {"cmd": "run", "expect": {"solutions": {"sols/main.cpp": "ac"}}}
    ]}]})
    matcher = spec.scenarios[0].steps[0].expect.solutions
    assert matcher["sols/main.cpp"].star == ExpectedOutcome.ACCEPTED

def test_solutions_full_form():
    spec = parse_spec({"scenarios": [{"name": "s", "steps": [
        {"cmd": "run", "expect": {"solutions": {
            "sols/wa.cpp": {"*": "wa", "samples": "ac", "main_tests/edge": "ac"}
        }}}
    ]}]})
    m = spec.scenarios[0].steps[0].expect.solutions["sols/wa.cpp"]
    assert m.star == ExpectedOutcome.WRONG_ANSWER
    assert m.entries == {"samples": ExpectedOutcome.ACCEPTED,
                          "main_tests/edge": ExpectedOutcome.ACCEPTED}

def test_unknown_verdict():
    with pytest.raises(ValueError):
        parse_spec({"scenarios": [{"name": "s", "steps": [
            {"cmd": "run", "expect": {"solutions": {"sols/x.cpp": "BOGUS"}}}
        ]}]})
```

Run: `uv run pytest tests/e2e/test_spec.py -v`. Expected: all FAIL (module not found).

**Step 2: Implement `tests/e2e/spec.py`**

```python
import pathlib
from typing import Dict, List, Optional, Union
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from rbx.box.schema import ExpectedOutcome


class _Forbid(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SolutionMatcher(_Forbid):
    star: Optional[ExpectedOutcome] = None  # the "*" key
    entries: Dict[str, ExpectedOutcome] = Field(default_factory=dict)


class TestsMatcher(_Forbid):
    count: Optional[int] = None
    groups: Dict[str, int] = Field(default_factory=dict)
    all_valid: bool = True
    exist: List[str] = Field(default_factory=list)


class ZipMatcher(_Forbid):
    path: str
    entries: List[str]


class Expect(_Forbid):
    stdout_contains: Union[str, List[str], None] = None
    stderr_contains: Union[str, List[str], None] = None
    stdout_matches: Optional[str] = None
    files_exist: List[str] = Field(default_factory=list)
    files_absent: List[str] = Field(default_factory=list)
    file_contains: Dict[str, str] = Field(default_factory=dict)
    zip_contains: Optional[ZipMatcher] = None
    zip_not_contains: Optional[ZipMatcher] = None
    solutions: Optional[Dict[str, SolutionMatcher]] = None
    tests: Optional[TestsMatcher] = None


class Step(_Forbid):
    cmd: str
    expect_exit: int = 0
    expect: Expect = Field(default_factory=Expect)


class Scenario(_Forbid):
    name: str
    description: Optional[str] = None
    steps: List[Step] = Field(default_factory=list)


class E2ESpec(_Forbid):
    scenarios: List[Scenario]

    @model_validator(mode='after')
    def _unique_scenario_names(self):
        names = [s.name for s in self.scenarios]
        if len(set(names)) != len(names):
            raise ValueError(f'duplicate scenario names: {names}')
        return self


def _parse_solution_matcher(value) -> SolutionMatcher:
    if isinstance(value, str):
        return SolutionMatcher(star=ExpectedOutcome(value), entries={})
    if isinstance(value, dict):
        star_raw = value.get('*')
        star = ExpectedOutcome(star_raw) if star_raw is not None else None
        entries = {
            k: ExpectedOutcome(v) for k, v in value.items() if k != '*'
        }
        return SolutionMatcher(star=star, entries=entries)
    raise ValueError(f'invalid solution matcher: {value!r}')


def parse_spec(data: dict) -> E2ESpec:
    # Pre-process solutions field: bare strings → SolutionMatcher
    for sc in data.get('scenarios', []):
        for step in sc.get('steps', []):
            sols = step.get('expect', {}).get('solutions')
            if sols:
                step['expect']['solutions'] = {
                    k: _parse_solution_matcher(v) for k, v in sols.items()
                }
    return E2ESpec.model_validate(data)


def load_spec(path: pathlib.Path) -> E2ESpec:
    return parse_spec(yaml.safe_load(path.read_text()))
```

Run: `uv run pytest tests/e2e/test_spec.py -v`. Expected: all PASS.

**Step 3: Commit**

```bash
git add tests/e2e/spec.py tests/e2e/test_spec.py
git commit -m "test(e2e): add Pydantic schema for e2e.rbx.yml"
```

---

## Task 3: Pytest collection hook

**Files:**
- Modify: `tests/e2e/conftest.py`
- Create: `tests/e2e/runner.py` (skeleton — `runtest` is a no-op for now, just so collection succeeds)
- Test: `tests/e2e/test_collection.py`

**Step 1: Write failing collection test**

```python
# tests/e2e/test_collection.py
def test_collects_scenarios(pytester):
    pytester.makepyfile(conftest="""
from tests.e2e.conftest import *
""")
    pytester.makefile(".rbx.yml", **{
        "testdata/x/e2e": "scenarios:\n  - name: a\n    steps: []\n  - name: b\n    steps: []\n",
    })
    result = pytester.runpytest("--collect-only", "-q")
    result.stdout.fnmatch_lines(["*x/e2e.rbx.yml::a*", "*x/e2e.rbx.yml::b*"])
```

(Use `pytester` plugin; enable via root `conftest.py` if not already.)

Run: `uv run pytest tests/e2e/test_collection.py -v`. Expected: FAIL.

**Step 2: Implement collection in `tests/e2e/conftest.py`**

```python
import pathlib
import pytest
from tests.e2e.spec import load_spec
from tests.e2e.runner import E2EScenarioItem


class E2EYamlFile(pytest.File):
    def collect(self):
        spec = load_spec(self.path)
        for scenario in spec.scenarios:
            yield E2EScenarioItem.from_parent(
                self, name=scenario.name, scenario=scenario
            )


def pytest_collect_file(parent, file_path):
    if file_path.name == 'e2e.rbx.yml':
        return E2EYamlFile.from_parent(parent, path=file_path)


def pytest_collection_modifyitems(config, items):
    for item in items:
        if isinstance(item, E2EScenarioItem):
            item.add_marker(pytest.mark.e2e)
```

`tests/e2e/runner.py` skeleton:

```python
import pytest
from tests.e2e.spec import Scenario


class E2EScenarioItem(pytest.Item):
    def __init__(self, *, scenario: Scenario, **kwargs):
        super().__init__(**kwargs)
        self.scenario = scenario

    def runtest(self):
        # Implemented in Task 4
        pass

    def reportinfo(self):
        return self.path, 0, f'scenario: {self.name}'
```

Run: `uv run pytest tests/e2e/test_collection.py -v`. Expected: PASS.
Also run `uv run pytest --collect-only tests/e2e/testdata/simple-ac/`. Expected: collects `simple-ac/e2e.rbx.yml::smoke`.

**Step 3: Commit**

```bash
git add tests/e2e/conftest.py tests/e2e/runner.py tests/e2e/test_collection.py
git commit -m "test(e2e): add pytest collection hook for e2e.rbx.yml"
```

---

## Task 4: Step runner + exit code assertion

**Files:**
- Modify: `tests/e2e/runner.py`
- Test: extend `tests/e2e/testdata/simple-ac/e2e.rbx.yml`

**Step 1: Make the smoke scenario pass end-to-end**

Implement `runtest` to:
1. Copy the package directory to a tmpdir (use `TestingPackage(self.path.parent)` — it does this).
2. For each step, run `CliRunner().invoke(rbx_app, shlex.split(step.cmd))`.
3. Assert `result.exit_code == step.expect_exit` with a clear failure message.

```python
import shlex
from typer.testing import CliRunner
from rbx.box.cli import app as rbx_app
from rbx.box.testing.testing_package import TestingPackage


class E2EScenarioItem(pytest.Item):
    ...
    def runtest(self):
        with TestingPackage(self.path.parent) as pkg:
            for step in self.scenario.steps:
                self._run_step(pkg, step)

    def _run_step(self, pkg, step):
        result = CliRunner(mix_stderr=False).invoke(rbx_app, shlex.split(step.cmd))
        if result.exit_code != step.expect_exit:
            raise AssertionError(
                f"[{self.path.parent.name}::{self.scenario.name}] "
                f"step {step.cmd!r} exited {result.exit_code}, expected {step.expect_exit}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
```

**Step 2: Run the smoke test**

```bash
uv run pytest tests/e2e/testdata/simple-ac/e2e.rbx.yml -v
```

Expected: PASS. (The step runs `rbx build`, exit code 0, no assertions.)

**Step 3: Add a negative-test fixture**

Create `tests/e2e/testdata/bad-exit/e2e.rbx.yml`:

```yaml
scenarios:
  - name: nonexistent-cmd
    steps:
      - cmd: this-is-not-a-command
        expect_exit: 2
```

Run: `uv run pytest tests/e2e/testdata/bad-exit/ -v`. Expected: PASS (Typer returns 2 for unknown commands; verify by hand and adjust if Typer's exit code differs).

**Step 4: Commit**

```bash
git add tests/e2e/runner.py tests/e2e/testdata/
git commit -m "test(e2e): implement step runner with exit-code assertion"
```

---

## Task 5: Generic assertions — stdout/stderr/files/file_contains

**Files:**
- Create: `tests/e2e/assertions.py`
- Modify: `tests/e2e/runner.py`
- Test: extend a fixture's `e2e.rbx.yml`

**Step 1: Write failing tests at the assertion level**

Unit-test each assertion class independently in `tests/e2e/test_assertions.py`. Each class takes a constructed input (a fake `result` for stdout matchers, a tmpdir for filesystem matchers), exercises the matcher, and asserts pass/fail.

**Step 2: Implement each assertion class**

```python
# tests/e2e/assertions.py
import glob
import pathlib
import re
from dataclasses import dataclass
from typing import List


@dataclass
class AssertionContext:
    package_root: pathlib.Path
    stdout: str
    stderr: str


def _as_list(v):
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def check_stdout_contains(ctx: AssertionContext, expected) -> None:
    for needle in _as_list(expected):
        if needle not in ctx.stdout:
            raise AssertionError(f'stdout missing {needle!r}')


def check_stderr_contains(ctx: AssertionContext, expected) -> None:
    for needle in _as_list(expected):
        if needle not in ctx.stderr:
            raise AssertionError(f'stderr missing {needle!r}')


def check_stdout_matches(ctx: AssertionContext, pattern: str) -> None:
    if not re.search(pattern, ctx.stdout):
        raise AssertionError(f'stdout did not match /{pattern}/')


def check_files_exist(ctx: AssertionContext, patterns: List[str]) -> None:
    for pat in patterns:
        if not glob.glob(str(ctx.package_root / pat)):
            raise AssertionError(f'no file matched {pat!r}')


def check_files_absent(ctx: AssertionContext, patterns: List[str]) -> None:
    for pat in patterns:
        if glob.glob(str(ctx.package_root / pat)):
            raise AssertionError(f'unexpected file matched {pat!r}')


def check_file_contains(ctx: AssertionContext, mapping) -> None:
    for path, needle in mapping.items():
        text = (ctx.package_root / path).read_text()
        if needle.startswith('/') and needle.endswith('/') and len(needle) > 2:
            if not re.search(needle[1:-1], text):
                raise AssertionError(f'{path}: regex {needle} no match')
        elif needle not in text:
            raise AssertionError(f'{path}: missing {needle!r}')
```

**Step 3: Wire into runner**

In `_run_step`, after the exit-code check, dispatch each non-None field of `step.expect` to the corresponding `check_*` function. Keep a tight whitelist; one block per matcher.

**Step 4: Extend `simple-ac/e2e.rbx.yml`**

```yaml
scenarios:
  - name: smoke
    steps:
      - cmd: build
        expect:
          files_exist:
            - "build/tests/*.in"
```

Run: `uv run pytest tests/e2e/testdata/simple-ac/ -v`. Expected: PASS.

**Step 5: Commit**

```bash
git add tests/e2e/assertions.py tests/e2e/runner.py tests/e2e/test_assertions.py tests/e2e/testdata/simple-ac/e2e.rbx.yml
git commit -m "test(e2e): add stdout/stderr/file assertions"
```

---

## Task 6: Zip assertions

**Files:**
- Modify: `tests/e2e/assertions.py`
- Modify: `tests/e2e/runner.py`
- Test: `tests/e2e/test_assertions.py`

**Step 1: Tests**

In `test_assertions.py`, build a small `.zip` in a tmpdir with `zipfile.ZipFile`, exercise `check_zip_contains` with both literal entries and globs (`*.xml`, `limits/*`), and `check_zip_not_contains`.

**Step 2: Implement**

```python
import fnmatch
import zipfile

def _glob_in_zip(zip_path: pathlib.Path, pattern: str) -> bool:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    return any(fnmatch.fnmatch(n, pattern) for n in names)


def check_zip_contains(ctx, matcher) -> None:
    zip_paths = glob.glob(str(ctx.package_root / matcher.path))
    if not zip_paths:
        raise AssertionError(f'no zip matched {matcher.path!r}')
    zip_path = pathlib.Path(zip_paths[0])
    for entry in matcher.entries:
        if not _glob_in_zip(zip_path, entry):
            raise AssertionError(f'{zip_path.name}: missing entry {entry!r}')


def check_zip_not_contains(ctx, matcher) -> None:
    zip_paths = glob.glob(str(ctx.package_root / matcher.path))
    if not zip_paths:
        return
    zip_path = pathlib.Path(zip_paths[0])
    for entry in matcher.entries:
        if _glob_in_zip(zip_path, entry):
            raise AssertionError(f'{zip_path.name}: unexpected entry {entry!r}')
```

Wire into runner.

**Step 3: Add a fixture exercising it**

Build a fixture (`tests/e2e/testdata/pkg-boca/`) — minimal package, scenario:

```yaml
scenarios:
  - name: package-boca
    steps:
      - cmd: build
      - cmd: pkg boca
        expect:
          files_exist: ["build/boca/*.zip"]
          zip_contains:
            path: build/boca/*.zip
            entries: [description.xml]
```

Run: `uv run pytest tests/e2e/testdata/pkg-boca/ -v`. Expected: PASS.

**Step 4: Commit**

```bash
git add tests/e2e/
git commit -m "test(e2e): add zip_contains/zip_not_contains assertions"
```

---

## Task 7: `solutions:` matcher (verdict matrix)

**Files:**
- Modify: `tests/e2e/assertions.py`
- Test: `tests/e2e/test_solutions_matcher.py`

**Prereq:** Task 0 must be done; the on-disk verdict source is now known. The implementation below assumes per-test `Evaluation` files exist; adjust file paths to match what Task 0 documents.

**Step 1: Write failing tests**

Construct fake on-disk evaluation data in a tmpdir mirroring the real layout. Cover:
- Bare-verdict form passes when all groups match.
- `*: wa` + `samples: ac` correctly resolves group-by-name override.
- Per-test override (`group/test_id: ac`) takes precedence over group entry.
- Sparse coverage: only specified entries are checked; other groups/tests can have any verdict.
- Failure cases: clear message naming the (solution, group/test, expected, actual).
- Solutions in the YAML that don't exist in the package → assertion error.

**Step 2: Implement**

Outline (concrete code depends on Task 0):

```python
def check_solutions(ctx, matchers):
    # Load the verdict report (path determined by Task 0).
    report = _load_verdict_report(ctx.package_root)

    for sol_path, matcher in matchers.items():
        if sol_path not in report.solutions:
            raise AssertionError(f'solution {sol_path!r} not in run report')

        # Per-test entries: keys containing "/"
        # Per-group entries: identifier-like keys
        per_test = {k: v for k, v in matcher.entries.items() if '/' in k}
        per_group = {k: v for k, v in matcher.entries.items() if '/' not in k}

        # 1. Per-test assertions.
        for test_path, expected in per_test.items():
            actual = report.test_verdict(sol_path, test_path)
            if not expected.match(actual):
                raise AssertionError(
                    f'{sol_path} / {test_path}: expected {expected.name}, got {actual.name}'
                )

        # 2. Per-group assertions (explicit + '*' fallback).
        for group_name in report.group_names(sol_path):
            if group_name in per_group:
                expected = per_group[group_name]
            elif matcher.star is not None:
                expected = matcher.star
            else:
                continue  # sparse: not asserted
            actual = report.group_outcome(sol_path, group_name)
            if not expected.match(actual):
                raise AssertionError(
                    f'{sol_path} / {group_name}: expected {expected.name}, got {actual.name}'
                )
```

Use `ExpectedOutcome.match(outcome: Outcome)` from `rbx/box/schema.py` — the same matcher rbx already uses for `problem.rbx.yml`'s `outcome:` field. Do **not** reinvent verdict comparison.

**Step 3: Add a multi-solution fixture**

Build `tests/e2e/testdata/mixed-solutions/` with one AC solution, one WA solution, exercising the full matcher syntax. Run end-to-end:

```bash
uv run pytest tests/e2e/testdata/mixed-solutions/ -v
```

Expected: PASS.

**Step 4: Commit**

```bash
git add tests/e2e/
git commit -m "test(e2e): add solutions verdict matcher"
```

---

## Task 8: `tests:` matcher (build-time generation/validation report)

**Files:**
- Modify: `tests/e2e/assertions.py`
- Test: `tests/e2e/test_tests_matcher.py`

**Prereq:** confirm whether `rbx build` currently persists a structured generation/validation report. Inspect during the task; if not, the smallest acceptable change is to write `build/tests/_report.json` (or yaml) listing each generated test path, group, and validation status.

**Step 1: Tests**

Cover: total `count`, per-group `groups: {name: int}`, `all_valid: true` when all generated tests passed validation, `all_valid: false` allowed (don't enforce), `exist:` with literal paths under `build/tests/`.

**Step 2: Implement**

```python
def check_tests(ctx, matcher):
    report = _load_build_report(ctx.package_root)
    if matcher.count is not None and report.count != matcher.count:
        raise AssertionError(f'tests.count: expected {matcher.count}, got {report.count}')
    for grp, n in matcher.groups.items():
        actual = report.group_count(grp)
        if actual != n:
            raise AssertionError(f'tests.groups.{grp}: expected {n}, got {actual}')
    if matcher.all_valid and not report.all_valid:
        raise AssertionError('tests.all_valid: some tests failed validation')
    for path in matcher.exist:
        if not (ctx.package_root / 'build' / 'tests' / path).exists():
            raise AssertionError(f'tests.exist: missing {path!r}')
```

**Step 3: Extend the simple-ac fixture**

```yaml
- cmd: build
  expect:
    tests:
      count: 5
      all_valid: true
```

Run: PASS.

**Step 4: Commit**

```bash
git add tests/e2e/
git commit -m "test(e2e): add tests build-report matcher"
```

---

## Task 9: Statement build assertions (`st b`)

**Files:**
- Test: `tests/e2e/testdata/with-statement/`

**Step 1: Build a fixture with a minimal statement**

Reuse `template.rbx.tex` and `statements/` layout from `simple-problem`. Add `mock_pdflatex` style mocking? **No** — the `e2e` mark already implies real LaTeX. If LaTeX is not on CI, mark this scenario `@pytest.mark.slow` via a YAML hint (see Task 11 — pytest-marker passthrough).

Scenario:

```yaml
scenarios:
  - name: statement
    steps:
      - cmd: build
      - cmd: st b
        expect:
          files_exist: [build/statements/statement.pdf]
```

**Step 2: Run**

```bash
uv run pytest tests/e2e/testdata/with-statement/ -v -m e2e
```

Expected: PASS (or SKIP if LaTeX missing locally — fine).

**Step 3: Commit**

```bash
git add tests/e2e/testdata/with-statement/
git commit -m "test(e2e): add statement-build fixture"
```

---

## Task 10: Migrate existing CLI e2e tests

**Files:**
- Move/recreate: `tests/rbx/box/cli/problem_test.py` content as YAML scenarios under `tests/e2e/testdata/`.
- Delete: `tests/rbx/box/cli/problem_test.py` (after parity).
- Optionally relocate: `tests/rbx/box/packaging/e2e/testdata/simple-problem/` → `tests/e2e/testdata/simple-problem/` (only if no other test references it).

**Step 1: Mirror `test_default_preset_problem`**

Create `tests/e2e/testdata/default-preset/e2e.rbx.yml`:

```yaml
scenarios:
  - name: full-pipeline
    steps:
      - cmd: run
      - cmd: unit
      - cmd: st b
      - cmd: pkg boca
      - cmd: pkg polygon
```

The original test relies on the default preset being copied in. Reuse the preset-copy logic from the existing `pkg_from_resources` fixture by adding a small per-package opt-in: a top-level `setup:` key in `e2e.rbx.yml` referencing a preset name. Add this to the schema (Task 2 extension), not as a separate concept.

If preset-copy is too invasive, alternative: the `default-preset` fixture directory directly contains the materialized preset files (committed). Choose whichever produces less ongoing maintenance.

**Step 2: Mirror `test_interactive_problem`**

Same approach for the interactive package. The original used `tests/rbx/box/cli/testdata/problems/interactive` — copy its files under `tests/e2e/testdata/interactive/`.

**Step 3: Delete the old Python tests**

```bash
git rm tests/rbx/box/cli/problem_test.py
```

Verify: `uv run pytest tests/rbx/box/cli/` runs cleanly (or is empty).

**Step 4: Commit**

```bash
git add -A
git commit -m "test(e2e): migrate CLI e2e tests to YAML DSL"
```

---

## Task 11: Slow/docker passthrough

**Files:**
- Modify: `tests/e2e/spec.py` (add `markers: List[str]` to `Scenario`).
- Modify: `tests/e2e/conftest.py` (apply markers in `pytest_collection_modifyitems`).

**Step 1: Schema**

```yaml
scenarios:
  - name: heavy
    markers: [slow]
    steps: [...]
```

**Step 2: Implementation**

In `pytest_collection_modifyitems`, after adding `e2e`, also apply each marker name from `scenario.markers` (whitelisted to `slow`, `docker` — reject unknown to avoid typo bugs).

**Step 3: Commit**

```bash
git commit -am "test(e2e): support slow/docker markers per scenario"
```

---

## Task 12: README + docs

**Files:**
- Create: `tests/e2e/README.md` (how to add a new e2e package, schema reference, examples).
- Update: `tests/rbx/box/packaging/e2e/README.md` to point at the new tree.
- Update top-level `CLAUDE.md` testing section to mention `mise run test-e2e` and the YAML DSL.

**Step 1: Write the README**

Cover: directory layout, how to add a new package, full schema with one example per matcher, how to run a single scenario, how to debug a failing assertion (`-v`, look at stdout/stderr in the failure message), the marker passthrough.

**Step 2: Commit**

```bash
git add tests/e2e/README.md tests/rbx/box/packaging/e2e/README.md CLAUDE.md
git commit -m "docs(e2e): document YAML-driven e2e test framework"
```

---

## Task 13: CI verification

**Files:** none (verification only).

**Step 1: Run the new e2e suite locally**

```bash
mise run test-e2e
```

Expected: all e2e tests pass. Runtime: capture and document in the README.

**Step 2: Run the unit suite to confirm exclusion**

```bash
mise run test
```

Expected: zero `tests/e2e/...` entries collected. (The `e2e` mark filter excludes them.)

**Step 3: Inspect CI workflow**

Read `.github/workflows/tests.yml` (already open in the IDE). Confirm `mise run test-e2e` is invoked in CI; if not, add it as a separate job (matching existing patterns).

**Step 4: If CI changes were needed, commit**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: run e2e suite via mise run test-e2e"
```

---

## Out of scope (documented in design doc)

- `rbx stress` matchers — needs structured `--report` flag added to `stress` first.
- Migrating `tests/rbx/box/packaging/e2e/test_boca_e2e.py` — stays Python.
- Multi-language statement assertions — trivial extension once v1 lands.
- Contest-level packages — same DSL would extend; deferred.
