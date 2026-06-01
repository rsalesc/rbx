# BOCA Exact Fractional Time Limits Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop the BOCA packager from rounding/approximating time limits; always emit a budget whose effective per-run TL equals the real TL exactly, with an optional `minRunningTime` floor.

**Architecture:** Extract two pure helper functions (`_fmt_seconds`, `_compute_reps`) into `rbx/box/packaging/boca/packager.py` so the timing logic is unit-testable without a loaded package. Rewrite `_get_number_of_runs` and `_get_limits` as thin wrappers over those helpers. Add `minRunningTime` to `BocaExtension` and deprecate `maximumTimeError`.

**Tech Stack:** Python 3, Pydantic v2, pytest, ruff. Single-quote strings, absolute imports only.

Design doc: `docs/plans/2026-06-01-boca-exact-fractional-tl-design.md`

---

## Background for the implementer

BOCA's `limits/{lang}` script echoes four lines: total time budget (seconds), number of
repetitions, memory (MB), output limit (KB). The judge runs the solution `repetitions`
times and compares the **total** CPU time against the budget, so the effective per-run
limit is `budget / repetitions`. The current code rounds the budget to an integer, which
shifts the effective TL by up to 20%. We make the budget exact.

Relevant current code:
- `rbx/box/packaging/boca/packager.py:25-32` — `_MAX_REP_TIME`, `_MAX_REPS`, `test_time`.
- `rbx/box/packaging/boca/packager.py:125-162` — `_get_number_of_runs`.
- `rbx/box/packaging/boca/packager.py:164-182` — `_get_limits`.
- `rbx/box/packaging/boca/extension.py:7,13` — `_MAX_REP_ERROR`, `maximumTimeError`.

`_get_pkg_timelimit(language)` returns the per-language time limit in **integer milliseconds**.

---

## Task 1: Add `minRunningTime` and deprecate `maximumTimeError` on `BocaExtension`

**Files:**
- Modify: `rbx/box/packaging/boca/extension.py:10-15`
- Test: `tests/rbx/box/packaging/boca/test_extension.py`

**Step 1: Write the failing tests**

Add to `tests/rbx/box/packaging/boca/test_extension.py`:

```python
def test_min_running_time_defaults_to_none():
    assert BocaExtension().minRunningTime is None


def test_min_running_time_rejects_non_positive():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BocaExtension(minRunningTime=0)
    with pytest.raises(ValidationError):
        BocaExtension(minRunningTime=-5)


def test_min_running_time_accepts_positive_ms():
    assert BocaExtension(minRunningTime=1000).minRunningTime == 1000
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_extension.py -v`
Expected: the three new tests FAIL (`minRunningTime` not a field).

**Step 3: Implement the schema change**

In `rbx/box/packaging/boca/extension.py`, update the import and the model:

```python
from pydantic import BaseModel, Field


class BocaExtension(BaseModel):
    languages: typing.List[BocaLanguage] = []
    flags: typing.Dict[BocaLanguage, str] = {}
    # Optional floor (in milliseconds) on the TOTAL BOCA time budget. When set, the
    # solution is run ceil(minRunningTime / timeLimit) times so the accumulated budget
    # reaches the floor, amortizing fixed startup/JIT overhead and measurement noise on
    # small TLs. The effective per-run TL always stays exactly equal to the real TL.
    minRunningTime: typing.Optional[int] = Field(default=None, gt=0)
    # Deprecated (issue #494): BOCA/safeexec supports fractional time budgets, so rbx no
    # longer rounds TLs. This field is ignored; use `minRunningTime` instead.
    maximumTimeError: typing.Optional[float] = Field(
        default=None,
        deprecated='Ignored since #494; rbx emits exact fractional TLs. Use minRunningTime.',
    )
    preferContestLetter: bool = False
    usePypy: bool = False
```

Remove the `_MAX_REP_ERROR = 0.2` constant (line 7) — it is no longer referenced.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_extension.py -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add rbx/box/packaging/boca/extension.py tests/rbx/box/packaging/boca/test_extension.py
git commit  # use the /commit skill -> feat(boca): add minRunningTime, deprecate maximumTimeError (#494)
```

---

## Task 2: Add the pure `_fmt_seconds` helper

**Files:**
- Modify: `rbx/box/packaging/boca/packager.py` (add module-level helper near line 31)
- Test: `tests/rbx/box/packaging/boca/test_timing.py` (create)

**Step 1: Write the failing test**

Create `tests/rbx/box/packaging/boca/test_timing.py`:

```python
from rbx.box.packaging.boca.packager import _fmt_seconds


def test_fmt_seconds_is_exact():
    assert _fmt_seconds(1234) == '1.234'
    assert _fmt_seconds(2000) == '2.000'
    assert _fmt_seconds(500) == '0.500'
    assert _fmt_seconds(50) == '0.050'
    assert _fmt_seconds(1200) == '1.200'
    assert _fmt_seconds(0) == '0.000'
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_timing.py -v`
Expected: FAIL with ImportError (`_fmt_seconds` not defined).

**Step 3: Implement `_fmt_seconds`**

In `rbx/box/packaging/boca/packager.py`, replace the `test_time` function (lines 31-32)
with:

```python
def _fmt_seconds(ms: int) -> str:
    """Format integer milliseconds as exact fractional seconds (no float rounding)."""
    return f'{ms // 1000}.{ms % 1000:03d}'
```

Leave `_MAX_REPS = 10` (line 28). Remove `_MAX_REP_TIME` (lines 25-27) — it becomes unused
in Task 3; if ruff complains about an unused import of `fabs` (line 3) now, remove it in
Task 3 where the last user disappears (keep this commit green by leaving `fabs` for now if
still referenced).

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_timing.py -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add rbx/box/packaging/boca/packager.py tests/rbx/box/packaging/boca/test_timing.py
git commit  # /commit skill -> refactor(boca): add exact _fmt_seconds helper (#494)
```

---

## Task 3: Add the pure `_compute_reps` helper and rewrite `_get_number_of_runs`

**Files:**
- Modify: `rbx/box/packaging/boca/packager.py:125-162` (`_get_number_of_runs`) and add helper
- Test: `tests/rbx/box/packaging/boca/test_timing.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/packaging/boca/test_timing.py`:

```python
from rbx.box.packaging.boca.packager import _compute_reps


def test_compute_reps_single_run_when_no_minimum():
    assert _compute_reps(1200, None) == (1, False)
    assert _compute_reps(50, None) == (1, False)


def test_compute_reps_ceil_to_reach_minimum_budget():
    # 0.3s TL, 1s minimum -> ceil(1000/300) = 4 reps, budget 1.2s, not capped.
    assert _compute_reps(300, 1000) == (4, False)
    # exact multiple: 0.5s TL, 1s minimum -> 2 reps.
    assert _compute_reps(500, 1000) == (2, False)
    # TL already >= minimum -> 1 rep.
    assert _compute_reps(1500, 1000) == (1, False)


def test_compute_reps_caps_at_max_reps_and_flags():
    # 0.05s TL, 2s minimum would need 40 reps; cap at 10 and flag capped=True.
    assert _compute_reps(50, 2000) == (10, True)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_timing.py -v`
Expected: new tests FAIL (`_compute_reps` not defined).

**Step 3: Implement `_compute_reps` and rewrite `_get_number_of_runs`**

Add the module-level helper (near `_fmt_seconds`):

```python
import math


def _compute_reps(tl_ms: int, min_ms: Optional[int]) -> Tuple[int, bool]:
    """Return (repetitions, was_capped) for a BOCA limits script.

    When `min_ms` is None, always a single run. Otherwise run enough times for the
    accumulated budget (reps * tl) to reach `min_ms`, capped at `_MAX_REPS`. The effective
    per-run TL stays exactly `tl_ms` regardless of the cap.
    """
    if min_ms is None:
        return 1, False
    reps = max(1, math.ceil(min_ms / tl_ms))
    if reps > _MAX_REPS:
        return _MAX_REPS, True
    return reps, False
```

Add `Tuple` to the `typing` import at the top (`from typing import List, Optional, Tuple`).

Replace the entire body of `_get_number_of_runs` (lines 125-162) with:

```python
    def _get_number_of_runs(self, language: BocaLanguage) -> int:
        extension = get_extension_or_default('boca', BocaExtension)
        tl_ms = self._get_pkg_timelimit(language)
        reps, capped = _compute_reps(tl_ms, extension.minRunningTime)
        if capped:
            console.console.print(
                f'[warning]minRunningTime of {extension.minRunningTime}ms could not be '
                f'fully honored for language [item]{language}[/item] (TL is {tl_ms}ms); '
                f'capping at {reps} run(s). The effective TL stays exact.[/warning]'
            )
        return reps
```

Now remove the dead code:
- Delete `_MAX_REP_TIME` (lines 25-27 in the original).
- Remove `from math import fabs` (line 3) — `fabs` is no longer used (we use `math.ceil`).
  Keep `import math`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_timing.py -v`
Expected: all PASS.

**Step 5: Run ruff to confirm no unused imports/vars**

Run: `uv run ruff check rbx/box/packaging/boca/packager.py`
Expected: no errors. Fix any unused-import findings.

**Step 6: Commit**

```bash
git add rbx/box/packaging/boca/packager.py tests/rbx/box/packaging/boca/test_timing.py
git commit  # /commit skill -> fix(boca): compute reps from minRunningTime without rounding (#494)
```

---

## Task 4: Rewrite `_get_limits` to emit exact fractional budgets

**Files:**
- Modify: `rbx/box/packaging/boca/packager.py:164-182` (`_get_limits`)
- Test: `tests/rbx/box/packaging/boca/test_timing.py`

**Step 1: Write the failing test**

This needs a real package, so use an existing packaging fixture. First inspect how
`tests/rbx/box/packaging/boca_next/` builds a package (see its `conftest.py` and
`test_manifest.py`) and reuse that fixture style. The test should:

1. Build/load a BOCA package whose problem TL is an "ugly" value (e.g. 1200ms).
2. Call `BocaPackager(...)._get_limits('cpp')`.
3. Assert the emitted script's first echo is `1.200` and second echo is `1` (no drift,
   not rounded to `1`/`1` budget=1 like the old behavior would give for 1.2s).

Sketch (adapt fixture/setup to the existing conftest helpers):

```python
def test_get_limits_emits_exact_fractional_budget(...fixture that yields a BocaPackager in a
        problem with timeLimit 1200ms and no minRunningTime...):
    script = packager._get_limits('cpp')
    lines = [ln for ln in script.splitlines() if ln.startswith('echo ')]
    assert lines[0] == 'echo 1.200'   # budget
    assert lines[1] == 'echo 1'       # reps


def test_get_limits_with_min_running_time(...fixture: timeLimit 300ms, minRunningTime 1000...):
    script = packager._get_limits('cpp')
    lines = [ln for ln in script.splitlines() if ln.startswith('echo ')]
    assert lines[0] == 'echo 1.200'   # 4 * 0.300
    assert lines[1] == 'echo 4'
```

If a full package fixture is too heavyweight, an acceptable alternative is to test
`_get_limits` with `_get_pkg_timelimit`, `_get_pkg_memorylimit`, and
`package.find_problem_package_or_die` patched via `unittest.mock.patch`, asserting the two
echo lines. Prefer reusing a real fixture if one already exists in `boca_next/conftest.py`.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_timing.py -v`
Expected: FAIL — current code emits `echo 1` (budget rounded to integer 1) for the 1200ms
case, so the assertion `echo 1.200` fails. This is the regression guard for the bug.

**Step 3: Implement the rewrite**

Replace `_get_limits` (lines 164-182) with:

```python
    def _get_limits(self, language: BocaLanguage) -> str:
        pkg = package.find_problem_package_or_die()
        tl_ms = self._get_pkg_timelimit(language)
        if pkg.type == TaskType.COMMUNICATION:
            # Interactive tasks only support a single run.
            no_of_runs = 1
        else:
            no_of_runs = self._get_number_of_runs(language)
        time_limit = _fmt_seconds(tl_ms * no_of_runs)
        return (
            '#!/bin/bash\n'
            f'echo {time_limit}\n'
            f'echo {no_of_runs}\n'
            f'echo {self._get_pkg_memorylimit(language)}\n'
            f'echo {pkg.outputLimit}\n'
            f'exit 0\n'
        )
```

Note: COMMUNICATION now also routes through `_fmt_seconds`, replacing the lossy `:.2f`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/packaging/boca/test_timing.py -v`
Expected: all PASS.

**Step 5: Commit**

```bash
git add rbx/box/packaging/boca/packager.py tests/rbx/box/packaging/boca/test_timing.py
git commit  # /commit skill -> fix(boca): emit exact fractional time budgets in limits (#494)
```

---

## Task 5: Sweep for other references and regression-check the full BOCA suite

**Files:**
- Inspect: anything referencing `test_time`, `_MAX_REP_TIME`, `maximumTimeError`,
  `_MAX_REP_ERROR`.

**Step 1: Grep for stale references**

Run: `grep -rn "test_time\|_MAX_REP_TIME\|_MAX_REP_ERROR\|maximumTimeError" rbx/ tests/ docs/ --include='*.py' --include='*.md'`
Expected: no remaining *functional* uses in `rbx/` (only the deprecated field definition in
`extension.py` and doc mentions). Fix any leftover importers of `test_time`.

Also check docs: `grep -rn "maximumTimeError\|rounding" docs/` and update the BOCA docs page
if it documents `maximumTimeError` (mark deprecated, document `minRunningTime`).

**Step 2: Run the full BOCA packaging test suites**

Run:
```bash
uv run pytest tests/rbx/box/packaging/boca tests/rbx/box/packaging/boca_next -v
```
Expected: all PASS. Investigate any failure — `boca_next/test_manifest.py` or
`test_tasks.py` may assert on the limits script content and need updating to the new exact
format (this is expected and correct; update the assertions to match exact fractional
budgets / single runs).

**Step 3: Run ruff over the touched files**

Run: `uv run ruff check rbx/box/packaging/boca/ tests/rbx/box/packaging/boca/`
And: `uv run ruff format rbx/box/packaging/boca/ tests/rbx/box/packaging/boca/`
Expected: clean.

**Step 4: Commit any fixups**

```bash
git add -p
git commit  # /commit skill -> test(boca): update limits assertions for exact TLs (#494)
```

---

## Task 6: Final verification

**Step 1: Run the broader packaging test slice**

Run: `uv run pytest tests/rbx/box/packaging -n auto`
Expected: all PASS (excluding pre-existing C++/sandbox/docker failures known to fail on
this machine — see project memory; verify any failure is one of those, not a regression).

**Step 2: Manually confirm the fix removes drift**

Run a quick sanity check matching the original repro:
```bash
uv run python -c "
from rbx.box.packaging.boca.packager import _compute_reps, _fmt_seconds
for tl_ms, min_ms in [(1200, None), (300, 1000), (50, 2000), (1234, None)]:
    reps, capped = _compute_reps(tl_ms, min_ms)
    budget = _fmt_seconds(tl_ms * reps)
    print(f'tl={tl_ms}ms min={min_ms} -> reps={reps} budget={budget}s eff={tl_ms}ms capped={capped}')
"
```
Expected: `tl=1200 -> reps=1 budget=1.200`, `tl=300 min=1000 -> reps=4 budget=1.200`,
`tl=50 min=2000 -> reps=10 budget=0.500 capped=True`, `tl=1234 -> reps=1 budget=1.234`.
Effective per-run TL = `budget/reps` equals the original TL exactly in every row.

**Step 3: Confirm nothing else regressed**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto -q`
Expected: PASS apart from the documented pre-existing failures.
```
```
