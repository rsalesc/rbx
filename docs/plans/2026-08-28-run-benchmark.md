# `rbx run --benchmark` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `--benchmark` / `-b` to `rbx run` and `rbx irun`, so `-b1` reports how much time the checker (and interactor) spent judging each solution, and `rbx ui` can show per-testcase checker time.

**Architecture:** The checker's `RunLog` is already produced in `rbx/box/checkers.py:_check` and thrown away. Keep its timing on `CheckerResult`, which is already persisted into each testcase's `.eval` artifact — so capture is unconditional and free, `rbx ui` reads it for any run, and `-b` gates *reporting* only. A new `rbx/box/benchmark.py` owns the level enum, the aggregation over evaluations, and the two report blocks.

**Tech Stack:** Python 3.12+, Pydantic v2, Typer, Rich, pytest. Package manager is `uv`; run everything through `uv run`.

**Design doc:** [`docs/plans/2026-08-28-run-benchmark-design.md`](2026-08-28-run-benchmark-design.md). Read it before Task 1 — it records *why* each decision was taken, and the answers to the questions you would otherwise be tempted to re-litigate.

**Out of scope:** `-b2` (benchmarking test generation and validation) — tracked in [#801](https://github.com/rsalesc/rbx/issues/801). Also out of scope: the machine-readable `rbx/box/run_report.py` projection; benchmark data does not go into `report.yml` in this pass.

---

## Orientation (read once, before Task 1)

Things about this codebase that will bite you if you do not know them:

- **Run everything with `uv run`.** `uv run pytest ...`, `uv run ruff check .`, `uv run rbx ...`.
- **Do not run the full test suite.** It is slow and produces spurious sandbox wall-clock timeouts. Run only the test files each task touches.
- **Single quotes** for strings, **absolute imports only** (relative imports are banned by ruff's `TID` rule). Run `uv run ruff format .` and `uv run ruff check --fix .` before every commit.
- **Commits must be Conventional Commits** — commitizen's pre-commit hook rejects anything else. The allowed types and the exact workflow are in `.claude/skills/commit.md`; use that skill for every commit in this plan. If the hook rejects a commit, fix and make a **new** commit, never amend.
- **`utils.model_to_yaml` dumps with `exclude_unset=True, exclude_none=True`.** That is the whole reason optional timing fields cost existing `.eval` files zero bytes. Do not "helpfully" give them non-`None` defaults.
- **A skipped testcase is `Outcome.SKIPPED`** with `log.time is None` (see `solutions._record_skipped_evaluation`). Every aggregation in this plan filters on `eval.result.outcome != Outcome.SKIPPED`. Never coalesce an unmeasured value to `0` — the codebase is deliberate about this and reports `-` instead.
- **Test helpers already exist**: `tests/rbx/box/conftest.py` gives you `make_evaluation(outcome, time_ms=..., memory_bytes=..., testcase_index=...)` and the `mock_skeleton(solutions, entries_per_group=...)` fixture. Use them; do not hand-roll `Evaluation` objects.
- **The completion spec is committed and drift-tested.** Adding a CLI flag makes `tests/rbx/box/completion/drift_test.py` fail until you regenerate `rbx/box/completion/_spec.py`. Task 10 does that. `mise run gen-completion-spec` is a no-op inside a worktree — run the underlying command directly (Task 10 spells it out).

---

## Task 1: `RunTiming` on `CheckerResult`

**Files:**
- Modify: `rbx/grading/steps.py` (near `class CheckerResult`, ~line 328)
- Test: `tests/rbx/grading/steps_timing_test.py` (create)

**Step 1: Write the failing tests**

```python
import pathlib

from rbx import utils
from rbx.grading.steps import CheckerResult, Outcome, RunLog, RunTiming


def test_of_returns_none_for_a_missing_run_log():
    assert RunTiming.of(None) is None


def test_of_carries_both_clocks_off_the_run_log():
    timing = RunTiming.of(RunLog(time=0.048, wall_time=0.051))
    assert timing == RunTiming(time=0.048, wall_time=0.051)


def test_a_result_without_timing_adds_no_keys_to_the_dumped_yaml():
    # The `.eval` artifact is written with `model_to_yaml`, which drops None.
    # A run whose checker never executed must write exactly the bytes it always
    # did, so this file format stays backward compatible.
    dumped = utils.model_to_yaml(CheckerResult(outcome=Outcome.ACCEPTED))
    assert 'checker_timing' not in dumped
    assert 'interactor_timing' not in dumped


def test_timing_round_trips_through_yaml(tmp_path: pathlib.Path):
    result = CheckerResult(
        outcome=Outcome.ACCEPTED,
        checker_timing=RunTiming(time=0.048, wall_time=0.051),
    )
    path = tmp_path / 'result.yml'
    path.write_text(utils.model_to_yaml(result))

    reloaded = utils.model_from_yaml(CheckerResult, path.read_text())
    assert reloaded.checker_timing == RunTiming(time=0.048, wall_time=0.051)
    assert reloaded.interactor_timing is None
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/grading/steps_timing_test.py -v`
Expected: FAIL — `ImportError: cannot import name 'RunTiming'`.

**Step 3: Implement**

In `rbx/grading/steps.py`, immediately **above** `class CheckerResult`:

```python
class RunTiming(BaseModel):
    """How long one judging program took on one testcase.

    Both clocks are kept even though only CPU time is reported today: storing
    the wall clock costs nothing, and lets a later benchmarking level report it
    without migrating the `.eval` format.

    `None` means *unmeasured*, never zero. A checker that never ran -- the
    solution TLE'd or crashed, so `_check_pre_output` short-circuited -- has no
    timing at all, and reporting `0 ms` for it would claim a measurement that
    was never taken.
    """

    time: Optional[float] = None
    wall_time: Optional[float] = None

    @staticmethod
    def of(log: Optional['RunLog']) -> Optional['RunTiming']:
        if log is None:
            return None
        return RunTiming(time=log.time, wall_time=log.wall_time)
```

And add to `CheckerResult`:

```python
    # How long the checker took on this testcase, and -- for communication
    # problems -- the interactor. Captured on every run regardless of
    # `--benchmark`, because `exclude_none` makes it free and `rbx ui` can then
    # show it for any past run. See docs/plans/2026-08-28-run-benchmark-design.md.
    checker_timing: Optional[RunTiming] = None
    interactor_timing: Optional[RunTiming] = None
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/grading/steps_timing_test.py -v`
Expected: 4 passed.

**Step 5: Format, lint, commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/grading/steps.py tests/rbx/grading/steps_timing_test.py
```
Commit (via the `/commit` skill): `feat(grading): carry checker and interactor timing on CheckerResult`

---

## Task 2: Populate `checker_timing` in `checkers._check`

**Files:**
- Modify: `rbx/box/checkers.py` (`_check`, ~line 264)
- Test: `tests/rbx/box/checkers_test.py`

**Step 1: Write the failing test**

Read the existing tests in `tests/rbx/box/checkers_test.py` first and copy the fixture style of whichever test already compiles and runs a real checker — do not invent a new harness. Add:

```python
async def test_check_records_the_checker_timing(...):
    """A real checker run leaves its measured time on the result."""
    result = await checkers.check(...)  # mirror the neighbouring test's setup

    assert result.checker_timing is not None
    assert result.checker_timing.time is not None
    assert result.checker_timing.wall_time is not None


async def test_check_records_no_timing_when_the_checker_never_ran(...):
    """A solution that TLE'd short-circuits before the checker is invoked."""
    result = checkers.check_with_no_output(
        RunLog(exitstatus=SandboxBase.EXIT_TIMEOUT)
    )

    assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    assert result.checker_timing is None
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/checkers_test.py -k timing -v`
Expected: FAIL — `checker_timing is None` on the first test.

**Step 3: Implement**

In `_check`, after `checker_run_log` is computed and `processed_checker_result` is built, stamp the timing on every result `_check` can return **from the point the checker actually ran**. The function has two return statements after that point (`if skip_run_log: return result` and `return _convert_tle(result, run_log)`), so set it once before them:

```python
    result = processed_checker_result
    result.checker_timing = RunTiming.of(checker_run_log)

    if skip_run_log:
        return result
    return _convert_tle(result, run_log)
```

`_convert_tle` mutates and returns the same object, so the timing survives it. Add `RunTiming` to the `rbx.grading.steps` import block at the top of the file.

Note the early `OUTPUT_LIMIT_EXCEEDED` return above still leaves the timing `None`, which is correct: that path also never runs the checker.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/checkers_test.py -v`
Expected: all pass, including the two new ones.

**Step 5: Format, lint, commit**

Commit: `feat(checkers): record the checker's execution time on its result`

---

## Task 3: Populate `interactor_timing` in `check_communication`

**Files:**
- Modify: `rbx/box/checkers.py` (`check_communication`, ~line 392)
- Test: `tests/rbx/box/checkers_communication_test.py`

**Step 1: Write the failing test**

Mirror the setup of the existing communication tests. Assert that a result coming back from `check_communication` carries `interactor_timing` with a non-`None` `time`, **on more than one code path** — pick one test where the interactor decides the verdict and one where the checker does, because `check_communication` has many returns.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/checkers_communication_test.py -k timing -v`
Expected: FAIL — `interactor_timing is None`.

**Step 3: Implement**

`check_communication` already funnels **every** return through `_extra_check_and_sanitize`. That is the single hook:

```python
    def _extra_check_and_sanitize(result: CheckerResult) -> CheckerResult:
        result.sanitizer_warnings = _check_sanitizer_warnings(run_log)
        # Every return path of `check_communication` passes through here, which
        # is why the interactor's timing is stamped on at this one point rather
        # than at each of the eight returns.
        result.interactor_timing = RunTiming.of(interactor_run_log)
        return result
```

Check the tail of the function for any `return` that does **not** go through the helper and route it through one if you find it. Note the final `result = await check(...)` (step 6) returns a result that already carries `checker_timing`, and is then passed through `_extra_check_and_sanitize`, so it ends up with both.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/checkers_communication_test.py -v`
Expected: all pass.

**Step 5: Format, lint, commit**

Commit: `feat(checkers): record the interactor's execution time on its result`

---

## Task 4: The benchmark module — level and aggregation

**Files:**
- Create: `rbx/box/benchmark.py`
- Test: `tests/rbx/box/benchmark_test.py` (create)

This task is pure computation; printing is Task 5. Keep it that way — the aggregation is what the tests can pin cheaply.

**Step 1: Write the failing tests**

```python
import pytest

from rbx.box import benchmark
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.grading.steps import Outcome, RunTiming
from tests.rbx.box.conftest import make_evaluation


def timed(outcome, *, time_ms, checker_ms=None, interactor_ms=None, index=0):
    """`make_evaluation`, plus the judging timings this module reads."""
    eval = make_evaluation(outcome, time_ms=time_ms, testcase_index=index)
    if checker_ms is not None:
        eval.result.checker_timing = RunTiming(time=checker_ms / 1000.0)
    if interactor_ms is not None:
        eval.result.interactor_timing = RunTiming(time=interactor_ms / 1000.0)
    return eval


def test_judging_time_sums_solution_checker_and_interactor():
    eval = timed(Outcome.ACCEPTED, time_ms=100, checker_ms=20, interactor_ms=5)
    assert benchmark.judging_time(eval) == pytest.approx(0.125)


def test_judging_time_is_none_when_the_solution_was_never_timed():
    # A skipped testcase must not report an instantaneous judging time.
    assert benchmark.judging_time(timed(Outcome.SKIPPED, time_ms=None)) is None


def test_judging_time_counts_an_unmeasured_checker_as_absent_not_zero():
    eval = timed(Outcome.TIME_LIMIT_EXCEEDED, time_ms=1000)
    assert benchmark.judging_time(eval) == pytest.approx(1.0)


def test_solution_benchmark_picks_the_slowest_testcase_to_judge(mock_skeleton, tmp_path):
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 3})
    evals = [
        timed(Outcome.ACCEPTED, time_ms=100, checker_ms=10, index=0),
        # Slowest *judging*, though not the slowest solution run: the point of
        # the whole feature is that these two can disagree.
        timed(Outcome.ACCEPTED, time_ms=90, checker_ms=200, index=1),
        timed(Outcome.ACCEPTED, time_ms=150, checker_ms=5, index=2),
    ]

    bench = benchmark.build_solution_benchmark(solution, skeleton, evals)

    assert bench is not None
    assert bench.slowest.entry == skeleton.entries[1].group_entry
    assert bench.slowest.judging_time == pytest.approx(0.29)
    assert bench.slowest.checker_time == pytest.approx(0.2)
    assert bench.total_judging_time == pytest.approx(0.555)
    assert bench.total_checker_time == pytest.approx(0.215)
    assert bench.judged == 3
    assert bench.total == 3
    assert not bench.partial


def test_solution_benchmark_is_partial_when_testcases_were_skipped(mock_skeleton, tmp_path):
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 3})
    evals = [
        timed(Outcome.WRONG_ANSWER, time_ms=100, checker_ms=10, index=0),
        timed(Outcome.SKIPPED, time_ms=None, index=1),
        timed(Outcome.SKIPPED, time_ms=None, index=2),
    ]

    bench = benchmark.build_solution_benchmark(solution, skeleton, evals)

    assert bench is not None
    assert bench.judged == 1
    assert bench.total == 3
    assert bench.partial


def test_solution_benchmark_is_none_when_nothing_was_judged(mock_skeleton, tmp_path):
    solution = Solution(path=tmp_path / 'sol.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([solution], entries_per_group={'test': 2})
    evals = [timed(Outcome.SKIPPED, time_ms=None, index=i) for i in range(2)]

    assert benchmark.build_solution_benchmark(solution, skeleton, evals) is None


def test_problem_benchmark_ranks_solutions(mock_skeleton, tmp_path):
    slow_judge = Solution(path=tmp_path / 'a.cpp', outcome=ExpectedOutcome.ACCEPTED)
    heavy_checker = Solution(path=tmp_path / 'b.cpp', outcome=ExpectedOutcome.ACCEPTED)
    skeleton = mock_skeleton([slow_judge, heavy_checker], entries_per_group={'test': 2})
    per_solution = [
        benchmark.build_solution_benchmark(
            slow_judge,
            skeleton,
            [timed(Outcome.ACCEPTED, time_ms=500, checker_ms=1, index=i) for i in range(2)],
        ),
        benchmark.build_solution_benchmark(
            heavy_checker,
            skeleton,
            [timed(Outcome.ACCEPTED, time_ms=10, checker_ms=300, index=i) for i in range(2)],
        ),
    ]

    problem = benchmark.build_problem_benchmark([b for b in per_solution if b])

    assert problem is not None
    assert problem.slowest_to_judge.solution.path == slow_judge.path
    assert problem.most_checker_time.solution.path == heavy_checker.path
    assert problem.slowest_testcase.judging_time == pytest.approx(0.51)


def test_problem_benchmark_is_none_without_any_solution_benchmarks():
    assert benchmark.build_problem_benchmark([]) is None
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/benchmark_test.py -v`
Expected: FAIL — `ModuleNotFoundError: rbx.box.benchmark`.

**Step 3: Implement**

Create `rbx/box/benchmark.py`. Keep the top-level imports light — this module is imported by the CLI command modules.

```python
"""Benchmarking of the judging phase, behind `rbx run --benchmark`.

`rbx run` already reports how long each *solution* took. It says nothing about
how long *judging* took, and on a problem with a heavy checker the checker can
dominate the wall clock of a full run. This module turns the checker and
interactor timings that every evaluation now carries (see
`rbx.grading.steps.RunTiming`) into the two blocks `-b1` prints.

The timings themselves are captured unconditionally; the level only decides
whether anything is printed. See docs/plans/2026-08-28-run-benchmark-design.md.
"""

import dataclasses
from enum import Enum
from typing import List, Optional

from rbx.box.schema import Solution
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.steps import Evaluation, Outcome


class BenchmarkLevel(Enum):
    """How much of a run to benchmark. Mirrors `VerificationLevel`."""

    NONE = 0
    SOLUTIONS = 1


def _timing_seconds(timing) -> float:
    """An unmeasured program contributes nothing, rather than a zero."""
    if timing is None or timing.time is None:
        return 0.0
    return timing.time


def checker_time(eval: Evaluation) -> float:
    return _timing_seconds(eval.result.checker_timing)


def interactor_time(eval: Evaluation) -> float:
    return _timing_seconds(eval.result.interactor_timing)


def was_judged(eval: Evaluation) -> bool:
    """Whether this testcase actually ran.

    A `--fail-fast` run persists a `SKIPPED` evaluation for every testcase after
    the one that decided the verdict, with no time on it at all.
    """
    return eval.result.outcome != Outcome.SKIPPED and eval.log.time is not None


def judging_time(eval: Evaluation) -> Optional[float]:
    """Solution time + checker time + interactor time, in seconds.

    `None` when the solution itself was never timed: there is no judging time
    for a testcase that never ran.
    """
    if not was_judged(eval):
        return None
    return (eval.log.time or 0.0) + checker_time(eval) + interactor_time(eval)


@dataclasses.dataclass
class TestcaseJudging:
    entry: TestcaseEntry
    judging_time: float
    solution_time: float
    checker_time: float
    interactor_time: float


@dataclasses.dataclass
class SolutionBenchmark:
    solution: Solution
    slowest: TestcaseJudging
    total_judging_time: float
    total_checker_time: float
    total_interactor_time: float
    judged: int
    total: int

    @property
    def partial(self) -> bool:
        """Whether some testcases never ran, making every total a lower bound."""
        return self.judged < self.total


@dataclasses.dataclass
class ProblemBenchmark:
    slowest_to_judge: SolutionBenchmark
    most_checker_time: SolutionBenchmark
    slowest_testcase: TestcaseJudging
    partial: bool


def build_solution_benchmark(
    solution: Solution,
    skeleton,  # SolutionReportSkeleton; untyped to keep this module's imports light
    evals: List[Evaluation],
) -> Optional[SolutionBenchmark]:
    """Aggregate one solution's evaluations, or None if none of them ran."""
    judgings: List[TestcaseJudging] = []
    for eval, entry in zip(evals, skeleton.entries):
        total = judging_time(eval)
        if total is None:
            continue
        judgings.append(
            TestcaseJudging(
                entry=entry.group_entry,
                judging_time=total,
                solution_time=eval.log.time or 0.0,
                checker_time=checker_time(eval),
                interactor_time=interactor_time(eval),
            )
        )

    if not judgings:
        return None

    return SolutionBenchmark(
        solution=solution,
        slowest=max(judgings, key=lambda j: j.judging_time),
        total_judging_time=sum(j.judging_time for j in judgings),
        total_checker_time=sum(j.checker_time for j in judgings),
        total_interactor_time=sum(j.interactor_time for j in judgings),
        judged=len(judgings),
        # `evals` can be shorter than the skeleton mid-run, so the denominator
        # is the testset, not the list handed in.
        total=len(skeleton.entries),
    )


def build_problem_benchmark(
    benchmarks: List[SolutionBenchmark],
) -> Optional[ProblemBenchmark]:
    if not benchmarks:
        return None
    return ProblemBenchmark(
        slowest_to_judge=max(benchmarks, key=lambda b: b.total_judging_time),
        most_checker_time=max(benchmarks, key=lambda b: b.total_checker_time),
        slowest_testcase=max(
            (b.slowest for b in benchmarks), key=lambda j: j.judging_time
        ),
        partial=any(b.partial for b in benchmarks),
    )
```

Check the real name of the `group_entry` attribute on `GenerationTestcaseEntry` (see `rbx/box/generation_schema.py`) and of `TestcaseEntry` before writing this — the plan uses `entry.group_entry`, matching `solutions.get_solution_eval`'s usage.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/benchmark_test.py -v`
Expected: all pass.

**Step 5: Format, lint, commit**

Commit: `feat(benchmark): aggregate checker and interactor timings per solution`

---

## Task 5: Rendering the two blocks

**Files:**
- Modify: `rbx/box/benchmark.py`
- Test: `tests/rbx/box/benchmark_test.py`

**Step 1: Write the failing tests**

Render into a `rich.console.Console(record=True, width=120)` and assert over `console.export_text()`. Assert on *substance*, not exact spacing:

```python
def test_solution_block_names_the_slowest_test_and_the_totals(...):
    ...
    out = render(benchmark.print_solution_benchmark, bench)
    assert 'test/1' in out
    assert 'checker' in out
    assert 'over' not in out  # complete run says nothing about partiality


def test_solution_block_marks_a_partial_run(...):
    out = render(benchmark.print_solution_benchmark, partial_bench)
    assert 'over 1/3 tests judged' in out


def test_solution_block_omits_the_interactor_when_there_was_none(...):
    out = render(benchmark.print_solution_benchmark, non_interactive_bench)
    assert 'interactor' not in out.lower()


def test_problem_block_names_both_extremes(...):
    out = render(benchmark.print_problem_benchmark, problem)
    assert 'a.cpp' in out
    assert 'b.cpp' in out
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/benchmark_test.py -k block -v`
Expected: FAIL — `AttributeError: module has no attribute 'print_solution_benchmark'`.

**Step 3: Implement**

Add to `rbx/box/benchmark.py`. Import `rich.console` and the formatters lazily inside the functions if you want to keep the module's import cost down; `get_formatted_time` and `get_formatted_time_in_seconds` live in `rbx/box/formatting.py` — grep for where `solutions.py` imports them and use the same source. Times are in **seconds** here and those helpers take **milliseconds**, so convert at the boundary and nowhere else.

Shape of the output (match the surrounding report's Rich style — `[status]`, `[hilite]`, `href()` for solution paths, as `TimingSummary.print` does):

```
Benchmark: slowest test test/1 - 290 ms judging (90 ms solution + 200 ms checker)
Total judging: 555 ms (checker: 215 ms)
```

with `, N ms interactor` / `(checker: X, interactor: Y)` added only when `total_interactor_time > 0`, and ` (over 1/3 tests judged)` appended to the totals line when `bench.partial`.

The problem block:

```
Benchmark summary
Slowest solution to judge: 1.02 s, sols/a.cpp
Most checker time: 600 ms, sols/b.cpp
Slowest testcase to judge: 510 ms, test/0 of sols/a.cpp
```

Both functions take `(console: rich.console.Console, bench)` so the `--share` recording console can be passed instead of the real one.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/benchmark_test.py -v`
Expected: all pass.

**Step 5: Format, lint, commit**

Commit: `feat(benchmark): render the per-solution and problem-level blocks`

---

## Task 6: The `-b` flag and its completer

**Files:**
- Modify: `rbx/box/benchmark.py` (add `BenchmarkParam`, `parse_level`)
- Modify: `rbx/box/completion/completers.py` (~line 155, next to `_VERIFICATION_TABLE`)
- Test: `tests/rbx/box/benchmark_test.py`, `tests/rbx/box/completion/enum_consistency_test.py`

**Step 1: Write the failing tests**

```python
# benchmark_test.py
def test_parse_level_accepts_the_implemented_levels():
    assert benchmark.parse_level(0) == benchmark.BenchmarkLevel.NONE
    assert benchmark.parse_level(1) == benchmark.BenchmarkLevel.SOLUTIONS


def test_parse_level_rejects_b2_and_points_at_the_tracking_issue():
    with pytest.raises(typer.BadParameter) as exc:
        benchmark.parse_level(2)
    assert '801' in str(exc.value)


def test_parse_level_rejects_nonsense():
    with pytest.raises(typer.BadParameter):
        benchmark.parse_level(7)
```

```python
# enum_consistency_test.py -- alongside the verification one
def test_benchmark_table_matches_benchmark_level_enum():
    from rbx.box.benchmark import BenchmarkLevel

    table = dict(completers._BENCHMARK_TABLE)  # noqa: SLF001
    expected = {str(level.value): level.name for level in BenchmarkLevel}
    assert table == expected
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/benchmark_test.py tests/rbx/box/completion/enum_consistency_test.py -v`
Expected: FAIL on the three new tests.

**Step 3: Implement**

In `rbx/box/benchmark.py`:

```python
BENCHMARK_ISSUE_URL = 'https://github.com/rsalesc/rbx/issues/801'


def parse_level(value: int) -> BenchmarkLevel:
    """Turn the `-b` flag's int into a level, rejecting the unimplemented ones.

    `-b2` -- benchmarking test generation and validation -- is specified but not
    built. Rejecting it outright is deliberate: silently treating it as `-b1`
    would hand back a report that quietly omits half of what was asked for.
    """
    try:
        return BenchmarkLevel(value)
    except ValueError:
        pass
    if value == 2:
        raise typer.BadParameter(
            'Benchmark level 2 (test generation and validation) is not '
            f'implemented yet. Follow {BENCHMARK_ISSUE_URL}.'
        )
    raise typer.BadParameter(
        f'Invalid benchmark level {value}. Valid levels are '
        f'{", ".join(str(level.value) for level in BenchmarkLevel)}.'
    )


def _benchmark_autocompletion():
    # Indirected through a function for the same reason
    # `environment._verification_autocompletion` is: keeps this module's import
    # surface off `rbx.annotations`.
    from rbx import annotations

    return annotations._adapt('benchmark_level')  # noqa: SLF001


BenchmarkParam = Annotated[
    int,
    typer.Option(
        '--benchmark',
        '-b',
        help='Benchmark level: 0 (off), 1 (benchmark the solution run).',
        default_factory=lambda: BenchmarkLevel.NONE.value,
        autocompletion=_benchmark_autocompletion(),
    ),
]
```

Verify that a bare `-b` (no value) yields `1`. Typer's int option normally *requires* a value; if `-b` alone errors, give the option `flag_value=BenchmarkLevel.SOLUTIONS.value` (Click supports `flag_value` on a non-boolean option) and add a test asserting `rbx run -b` behaves as `-b1`. Do not skip this check — the design promises bare `-b` means `-b1`.

In `rbx/box/completion/completers.py`, next to `_VERIFICATION_TABLE`:

```python
_BENCHMARK_TABLE = (
    ('0', 'NONE'),
    ('1', 'SOLUTIONS'),
)


@register_completer('benchmark_level')
def complete_benchmark_level(
    ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    return [CompletionItem(v, help=h) for v, h in _BENCHMARK_TABLE]
```

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/rbx/box/benchmark_test.py tests/rbx/box/completion/enum_consistency_test.py tests/rbx/box/completion/registry_test.py -v`
Expected: all pass.

**Step 5: Format, lint, commit**

Commit: `feat(cli): add the --benchmark level flag and its completer`

---

## Task 7: Wire `-b1` into `rbx run`

**Files:**
- Modify: `rbx/box/cli/commands/run.py` (`run`, ~line 76)
- Modify: `rbx/box/solutions.py` (`TraditionalRunReporter`, `print_run_report`)
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Write the failing test**

Drive `print_run_report` (or `TraditionalRunReporter.finish_solution` directly, whichever the neighbouring tests already exercise) with a recording console at `BenchmarkLevel.SOLUTIONS` and assert the block appears; then at `BenchmarkLevel.NONE` and assert it does **not**.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/solutions_test.py -k benchmark -v`
Expected: FAIL — `print_run_report() got an unexpected keyword argument 'benchmark'`.

**Step 3: Implement**

1. `TraditionalRunReporter.__init__` takes `benchmark: BenchmarkLevel = BenchmarkLevel.NONE` and stores it. Both subclasses pass `*args, **kwargs` through, so they need no change.

2. In `TraditionalRunReporter.finish_solution`, **after** `render_solution_end` returns the report — this is the one place both reporters converge, so the block is written once:

```python
        report = self.render_solution_end(self.current_solution)
        if report is not None and self.benchmark == BenchmarkLevel.SOLUTIONS:
            bench = benchmark.build_solution_benchmark(
                self.current_solution, self.result.skeleton, report.evals
            )
            if bench is not None:
                benchmark.print_solution_benchmark(self.console, bench)
                self.solution_benchmarks.append(bench)
```

Collect the per-solution benchmarks on the reporter (`self.solution_benchmarks: List[SolutionBenchmark] = []` in `__init__`) so Task 8 can build the problem block from them without recomputing.

3. `print_run_report` grows `benchmark: BenchmarkLevel = BenchmarkLevel.NONE`, forwards it to `report_cls(...)`, and — because `_print_detailed_run_report` is a separate path — forwards it there too. Under `--detailed` the per-testcase table is unchanged; only the blocks are added.

4. `rbx/box/cli/commands/run.py`'s `run` gains `benchmark_level: benchmark_module.BenchmarkParam`, calls `benchmark_module.parse_level(benchmark_level)` early (next to `_set_timing_profile`, so a bad level costs a build), and passes the level to **both** `print_run_report` calls — the terminal one and the `--share` recording one.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v`
Expected: all pass — including the existing tests, which must be untouched at `BenchmarkLevel.NONE`.

**Step 5: Verify by hand on a real package**

```bash
cd tests/e2e   # pick any fixture package with solutions and a checker
uv run rbx run -b1
uv run rbx run -b1 --ff
uv run rbx run          # must be byte-identical to before this branch
```
Expected: the per-solution block appears under `-b1`; under `--ff` it carries `(over N/M tests judged)`; plain `rbx run` is unchanged.

**Step 6: Format, lint, commit**

Commit: `feat(run): print the per-solution benchmark block under -b1`

---

## Task 8: The problem-level block

**Files:**
- Modify: `rbx/box/solutions.py` (`print_run_report`, `_print_detailed_run_report`)
- Test: `tests/rbx/box/solutions_test.py`

**Step 1: Write the failing test**

Two solutions, one slow to run with a cheap checker and one fast to run with an expensive one; assert both are named in the output, and that the block appears even under a `--ff`-shaped (partial) input, marked partial.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/solutions_test.py -k problem_benchmark -v`
Expected: FAIL.

**Step 3: Implement**

In `print_run_report`, after the existing `_print_timing` call — and **outside** the `if not single_solution and timing:` guard, because the benchmark block is printed regardless of `--ff` and regardless of solution count:

```python
    if benchmark == BenchmarkLevel.SOLUTIONS:
        problem_bench = benchmark_module.build_problem_benchmark(
            reporter.solution_benchmarks
        )
        if problem_bench is not None:
            benchmark_module.print_problem_benchmark(console, problem_bench)
```

Mirror it in `_print_detailed_run_report`.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v`
Expected: all pass.

**Step 5: Verify by hand**

`uv run rbx run -b1` on a package with several solutions — the summary must name real solution paths and a real testcase.

**Step 6: Format, lint, commit**

Commit: `feat(run): print the problem-level benchmark summary under -b1`

---

## Task 9: Wire `-b1` into `rbx irun`

**Files:**
- Modify: `rbx/box/cli/commands/run.py` (`irun`, ~line 354)
- Modify: `rbx/box/solutions.py` (`run_and_print_interactive_solutions`, ~line 1403)
- Test: `tests/rbx/box/solutions_test.py`

Per the design: `irun -b1` prints per-testcase checker/interactor time on each testcase's block, and the problem-level summary. **No** per-solution block — with one testcase, "slowest test" says nothing.

**Step 1: Write the failing test**

Assert that at `BenchmarkLevel.SOLUTIONS` the per-testcase output carries a checker time, and that the problem summary is printed after the loop; at `NONE`, neither.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/solutions_test.py -k irun_benchmark -v`
Expected: FAIL.

**Step 3: Implement**

`run_and_print_interactive_solutions` gains `benchmark: BenchmarkLevel = BenchmarkLevel.NONE`. Inside the `async for item in items:` loop, right after `_print_solution_outcome`, print a one-line per-testcase timing when the level is on:

```
Checker: 48 ms
```

(plus `Interactor:` when there is an interactor timing). Accumulate `build_solution_benchmark(sol, skeleton, [eval])` into a list as you go, and after the loop call `build_problem_benchmark` / `print_problem_benchmark`.

`irun` in `run.py` gains `benchmark_level: benchmark_module.BenchmarkParam`, parses it early, and forwards the level. `-b` is free in `irun` (`-p` is `--print` there, but `-b` is unused) — confirm no collision before wiring.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/solutions_test.py -v`
Expected: all pass.

**Step 5: Verify by hand**

`uv run rbx irun -b1 -t test/0` on a fixture package.

**Step 6: Format, lint, commit**

Commit: `feat(irun): report checker timing per testcase under -b1`

---

## Task 10: `rbx ui` shows the checker time

**Files:**
- Modify: `rbx/box/ui/utils/run_ui.py` (`get_run_testcase_metadata_markup`, ~line 225)
- Test: `tests/rbx/box/ui/` — find the existing test module for `run_ui`; create `tests/rbx/box/ui/test_run_ui.py` if there is none. Note this directory uses the `test_*.py` prefix, unlike the `*_test.py` suffix everywhere else under `tests/rbx/box/`.

Note there is **no** `-b` gate here: capture is unconditional, so the UI reads whatever the `.eval` holds.

**Step 1: Write the failing test**

```python
def test_metadata_markup_shows_the_checker_time(...):
    markup = run_ui.get_run_testcase_metadata_markup(skeleton, solution, entry)
    assert 'Checker:' in markup
    assert '48 ms' in markup


def test_metadata_markup_shows_a_dash_when_the_checker_never_ran(...):
    # A TLE'd testcase short-circuits before the checker; '-' says
    # 'unmeasured', which is not the same claim as '0 ms'.
    assert 'Checker:[/b] -' in markup


def test_metadata_markup_shows_the_interactor_line_only_when_there_is_one(...):
    assert 'Interactor:' not in non_interactive_markup
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_run_ui.py -v`
Expected: FAIL.

**Step 3: Implement**

In `get_run_testcase_metadata_markup`, after the existing `Time: ... / Memory: ...` line:

```python
    checker_timing = eval.result.checker_timing
    lines.append(
        f'[b]Checker:[/b] '
        f'{_format_judging_time(checker_timing)}'
    )
    if eval.result.interactor_timing is not None:
        lines.append(
            f'[b]Interactor:[/b] '
            f'{_format_judging_time(eval.result.interactor_timing)}'
        )
```

where `_format_judging_time` returns `solutions._UNMEASURED` (`'-'`) for a `None` timing or a `None` `time`, and `get_formatted_time(int(timing.time * 1000))` otherwise. Reuse the existing `_UNMEASURED` constant rather than spelling `'-'` again.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/ -v`
Expected: all pass.

**Step 5: Verify by hand**

`uv run rbx run` then `uv run rbx ui`, navigate to a testcase, confirm the checker line is there.

**Step 6: Format, lint, commit**

Commit: `feat(ui): show the checker execution time for each testcase`

---

## Task 11: Regenerate the completion spec and the CLI reference

**Files:**
- Modify: `rbx/box/completion/_spec.py` (generated)
- Modify: `docs/setters/reference/cli.md` (generated)

**Step 1: Confirm the drift**

Run: `uv run pytest tests/rbx/box/completion/drift_test.py -v`
Expected: FAIL — the committed spec has no `--benchmark` on `run`/`irun`.

**Step 2: Regenerate**

`mise run gen-completion-spec` is a **no-op inside a worktree**, so run its body directly:

```bash
uv run python -m rbx.box.completion.serialize
uv run ruff format rbx/box/completion/_spec.py
```

**Step 3: Verify**

Run: `uv run pytest tests/rbx/box/completion/ -v`
Expected: all pass.

**Step 4: Regenerate the CLI reference**

`docs/setters/reference/cli.md` is generated by `rbx/box/dump_cli_docs.py` and is rewritten by a docs build. Regenerate it the way the repo does (grep `dump_cli_docs` in `mise.toml` / `mkdocs.yml` for the entry point) and commit **only** the `--benchmark` additions — revert any unrelated churn the generator introduces.

**Step 5: Commit**

Commit: `chore(completion): regenerate the spec and CLI reference for --benchmark`

---

## Task 12: Documentation

**Files:**
- Modify: whichever page under `docs/setters/` covers `rbx run`'s flags (grep for `--fail-fast` to find it)

Follow [`docs/plans/docs-writing-style-guide.md`](docs-writing-style-guide.md) — notably: introduce a concept before using it, and never forward-reference a mechanism the reader has not met.

Cover: what `-b1` measures (checker and interactor time, per testcase, per solution, per problem); that timings are captured on every run so `rbx ui` shows them without `-b`; that a cached checker reports its original measured time, which is the uncached cost and the number worth having; and that under `--ff` the totals are lower bounds and say so. Do **not** document `-b2`.

**Verify:** build the docs non-strict (`uv run mkdocs build`) — there are ~9 pre-existing unrelated `--strict` warnings, so do not use `--strict` and do not try to fix them. Check that the docs build did not rewrite `docs/setters/reference/cli.md` beyond Task 11's changes.

**Commit:** `docs(run): document the --benchmark flag`

---

## Task 13: Final verification

**Step 1: Run every test file this branch touched**

```bash
uv run pytest \
  tests/rbx/grading/steps_timing_test.py \
  tests/rbx/box/benchmark_test.py \
  tests/rbx/box/checkers_test.py \
  tests/rbx/box/checkers_communication_test.py \
  tests/rbx/box/solutions_test.py \
  tests/rbx/box/run_report_test.py \
  tests/rbx/box/completion/ \
  tests/rbx/box/ui/ \
  -v
```

Do **not** run the whole suite: it is slow and produces spurious sandbox timeouts. Known-unrelated pre-existing failures in this repo: C++/sandbox/docker tests, and `test_compute_walltime_uses_active_environment`. If one of those fails, it is not yours.

**Step 2: Lint**

```bash
uv run ruff check . && uv run ruff format --check .
```

**Step 3: Confirm `-b0` changed nothing**

Run a package with and without the branch and diff the output of a plain `uv run rbx run`. It must be identical. Then confirm an `.eval` written by a plain run gained the `checker_timing` key and nothing else.

**Step 4: Push and open a PR**

Reference the design doc and #801 in the PR body.

---

## Notes for the executor

- **Do not** re-open decisions the design doc settled — cached times reported as-is with no warning, unconditional capture, CPU time reported, `-b2` rejected. They were asked and answered.
- **Do not** add per-testcase benchmark output to `rbx run`'s terminal report in any mode, including `--detailed`. That was explicitly ruled out.
- If a task turns out to be bigger than one commit, split it — but keep each commit green.
