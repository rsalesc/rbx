# `rbx run --benchmark` design

**Date:** 2026-08-28
**Status:** approved, not yet implemented

## Problem

`rbx run` reports how long each solution took, but says nothing about how long
*judging* took. The checker runs once per testcase per solution, and on problems
with a heavy checker it can dominate the wall clock of a full run -- yet its cost
is invisible. A setter who wants to know whether the checker is the bottleneck,
or which testcase is expensive to judge, has no way to find out.

The checker's `RunLog` is already produced on every check, in
`rbx/box/checkers.py:_check`, and thrown away. Everything below is a matter of
keeping it and reporting it.

## Scope

`--benchmark` / `-b` takes a level, mirroring `-v`:

- `-b0` -- no benchmarking. The default; output is byte-identical to today's.
- `-b1` -- benchmark the solution-running phase: checker (and interactor) time
  per testcase, summarised per solution and per problem.
- `-b2` -- benchmark test generation and validation too. **Out of scope here**;
  tracked in [#801](https://github.com/rsalesc/rbx/issues/801). `-b2` is
  rejected by validation for now.

## Data model

The checker's timing rides back on `CheckerResult`, in `rbx/grading/steps.py`:

```python
class RunTiming(BaseModel):
    time: Optional[float] = None       # CPU seconds
    wall_time: Optional[float] = None

    @staticmethod
    def of(log: Optional[RunLog]) -> Optional['RunTiming']: ...


class CheckerResult(BaseModel):
    ...
    checker_timing: Optional[RunTiming] = None
    interactor_timing: Optional[RunTiming] = None
```

`CheckerResult` is the right carrier: `checkers.py` is the only place that holds
the checker's run log, and `Evaluation.result` is already persisted into the
`.eval` artifact, so `rbx/box/tasks.py` needs no change at all. The two
alternatives were rejected -- putting the fields on `TestcaseLog` mixes two
programs' measurements into one `RunLog` subclass whose `time`/`memory` mean
*the solution's*, and a new `Evaluation.judging` sub-model still needs a
transport out of `checkers.py`, so it is the same change plus a hop.

Both clocks are stored; only CPU time is reported. Storing the wall clock costs
nothing and lets `-b2` report it later without a format migration.

### Capture is unconditional

Every run writes the timings, regardless of `-b`. They are two floats per
evaluation, and `utils.model_to_yaml` dumps with `exclude_none=True`, so a
testcase whose checker never ran writes exactly the bytes it writes today. The
payoff is that `rbx ui` can show checker time for *any* past run rather than
only for runs that happened to be benchmarked. `-b` gates reporting alone.

### Where the timings are set

- `checkers._check` sets `checker_timing` from the `checker_run_log` it already
  computes, after `checker_mode.convert_run_log`.
- `checkers.check_communication` sets `interactor_timing` from the
  `interactor_run_log` it receives. Every one of its return paths funnels
  through `_extra_check_and_sanitize`, which is the single hook to stamp it on.

A testcase where the checker never ran -- `_check_pre_output` short-circuits on
TLE, RTE, MLE and friends before `code.run_item` is reached -- leaves both fields
`None`. That is deliberately distinct from a measured zero, and renders as `-`.

### Cached checker runs

Checker execution goes through `steps_with_caching.run`, so a warm cache replays
a stored `RunLog`. That stored log carries the time the checker *actually* took
when it ran, which is the number worth reporting: the value of the benchmark is
the uncached, worst-case judging cost. So cached times are reported as-is, with
no warning, and `-b1` never forces a re-run.

## Reporting

### Per-solution block (`rbx run` only)

Appended under each solution's existing `Time:` / `Memory:` lines:

```
Benchmark: slowest test tests/3 - 1.2 s judging (1.15 s solution + 48 ms checker)
Total judging: 14.3 s  (checker: 1.9 s)
```

"Judging time" for a testcase is solution time + checker time + interactor time.
Interactive problems get the interactor as a third term in both the breakdown and
the totals.

### Problem-level block

Printed after the timing summary:

- the slowest solution to judge, by total judging time;
- the solution that consumed the most checker time;
- the single slowest testcase to judge across the whole run.

### Under `--fail-fast`

A solution that stops at its first bad verdict is not judged on the remaining
testcases, so every total is a lower bound. Unlike the timing summary -- which is
dropped entirely under `--ff`, because time limit inference reads it -- both
benchmark blocks still print, computed over the testcases that actually ran and
marked with the count:

```
Total judging: 3.1 s  (checker: 0.4 s)  (over 7/40 tests judged)
```

Benchmark output is diagnostic and feeds no inference, so a marked lower bound is
more useful than nothing.

### `--share`

Both blocks are rendered into the recording console too, so a shared report is
not missing them.

### `rbx irun`

Per-testcase checker and interactor times are printed on each testcase's block,
and the problem-level summary is printed. The per-solution block is skipped: with
a single testcase, "slowest test" says nothing.

### Not printed

Per-testcase times never appear in `rbx run`'s terminal output, in any mode,
including `--detailed`. The plain report is one character per testcase and the
detailed table is already wide; `rbx ui` is where per-test detail is read.

## Flag

Mirroring `VerificationLevel` in `rbx/box/environment.py`:

```python
class BenchmarkLevel(Enum):
    NONE = 0
    SOLUTIONS = 1
```

`-b` / `--benchmark`, an int option with `default_factory` returning `0`, bare
`-b` meaning `1`, and an autocompletion adapter alongside `verification_level`.
A level outside `{0, 1}` is an error naming #801, so `-b2` never
silently under-delivers. Both `rbx run` and `rbx irun` take it; `-b` is free in
both (`irun` already spends `-p` on `--print`, but not `-b`).

## `rbx ui`

`rbx/box/ui/utils/run_ui.py:get_run_testcase_metadata_markup` gains a line under
the existing time/memory line:

```
Time: 1.15 s / Memory: 12 MB
Checker: 48 ms
```

with an `Interactor:` line for communication problems. Unmeasured reads `-`.
Because capture is unconditional, this works for any run recorded after this
change ships, benchmarked or not; runs recorded before it show `-`.

## Testing

- Aggregation helpers in `rbx/box/solutions.py`: all-unmeasured input, partial
  (`--ff`-shaped) input, interactive input with an interactor term.
- Round trip: `checker_timing` survives `.eval` write and read, and a `None`
  timing adds no keys to the dumped YAML.
- CLI: `-b1` prints both blocks; `-b2` is rejected.
- UI: the checker line renders, and reads `-` when nothing was measured.

## Follow-up

`-b2` -- benchmarking test generation and validation -- is tracked in
[#801](https://github.com/rsalesc/rbx/issues/801) and is not implemented here.
