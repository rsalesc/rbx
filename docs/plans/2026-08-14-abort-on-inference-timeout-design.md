# Aborting a solution's remaining tests

Stacked on [#643](https://github.com/rsalesc/rbx/pull/643) (Kattis-style timing
inference). Branch: `stack-inference-abort`.

## The problem

`timing.multipliers.inferenceTimeout` caps how long a slow solution may run
while the time limit is being inferred. A solution that hits the cap is
**dropped** from the upper bound (`timing.py:816` `_diagnose_inference_run` →
`dropped_upper`), and `_timings_per_language` (`timing.py:604`) then skips it
entirely.

But the run does not stop. A hopeless solution is re-run at the full cap on
every remaining testcase, and every one of those runs is thrown away. On a
package with 50 tests and a 10s cap that is over eight minutes of wall clock
spent producing nothing.

rbx has never had a way to stop a solution mid-testset. This adds one.

## Scope

A general capability in the solution runner -- "stop running this solution when
the caller says so" -- with time-limit inference as its first and only caller.
No new user-facing configuration in this change.

## Design

### 1. A caller-supplied predicate

`run_solutions` gains an optional `abort_on` argument. It is consulted after
each evaluation completes, and receives everything needed to decide without
reaching back into package state:

```python
@dataclasses.dataclass(frozen=True)
class AbortContext:
    solution: Solution
    group: GroupSkeleton
    entry: TestcaseEntry
    expected_outcome: ExpectedOutcome                    # solution.outcome
    group_expected_outcome: Optional[ExpectedOutcome]    # outcomePerGroup, if set
    evaluation: Evaluation

AbortPredicate = Callable[[AbortContext], bool]
```

The runner stays policy-free; all timing-specific knowledge stays in
`timing.py`.

### 2. Enforcement: a per-solution gate, not a `break`

Evaluations are lazy `Deferred`s and **several consumers independently force
them**: `print_run_report` (`solutions.py:2691`), then
`_diagnose_inference_run` (`timing.py:1081`), then `_timings_per_language`,
plus `_render_detailed_group_table` on the `--detailed` path and the `--share`
re-render at `timing.py:1145`. Breaking out of the report loop would not
prevent the runs -- the next consumer to await them would execute them.

So the gate lives at the `Deferred` level. The deferreds of one solution share
a gate object, consulted inside `run_fn` (`solutions.py:397-438`) *before*
dispatching to `tasks.run_solution_on_testcase`:

```
gate.run(entry, run_fn):
    if gate.is_skipped(entry.group):
        return skipped_evaluation(entry)     # nothing executes
    ev = await run_fn()
    if predicate(AbortContext(...)):
        gate.trip(entry.group)
    return ev
```

Correctness is then independent of *who* awaits first, which no invariant
currently guarantees.

This relies on the run loop being sequential -- it is (no `gather` /
`create_task` anywhere in `solutions.py`, `tasks.py` or `timing.py`; only
compilation is concurrent). That dependency gets a comment.

### 3. Skipped is a verdict, never an absence

`StructuredEvaluation` slots are `Optional[Deferred[Evaluation]]`, so `None`
looks like a free way to say "skipped". It is not:

- **`Deferred` breaks.** `Deferred.cache` *is* the "not computed yet" sentinel
  (`deferred.py:10-21`). A deferred resolving to `None` never memoizes and
  re-runs `func()` on every await -- re-executing the tests we meant to skip.
- **`None` is silently swallowed everywhere.** `timing.py:619` and
  `timing.py:824` both `continue` past it, so a skipped test would read as *no
  evidence*, i.e. indistinguishable from clean. The detailed renderer draws it
  as `...` (`solutions.py:2207`), identical to "not yet awaited".
  `LiveRunReporter` would freeze at `i/..` (`solutions.py:2516`, because
  `render_post_evaluation` is gated behind `if evaluation is not None` at
  `:2455`) -- identical to "still running".
- **Gaps corrupt group attribution.** `_get_evals_per_group`
  (`solutions.py:1663`) buckets by position and documents that a gap "would
  silently shift every later verdict into the wrong group".

Instead, every skipped slot holds a real `Evaluation` carrying a new outcome:

```python
class Outcome(Enum):
    ACCEPTED = 'accepted'
    SKIPPED = 'skipped'          # new, index 1
    WRONG_ANSWER = 'wrong-answer'
    ...
```

**Position matters.** `Outcome.worst_outcome` is `max` by member index
(`steps.py:51`). Index 1 -- immediately after `ACCEPTED` -- gives both
properties we need:

| evals | worst | why it is right |
|---|---|---|
| `AC, AC, SKIPPED` | `SKIPPED` | the solution did not pass everything |
| `AC, TLE, SKIPPED, SKIPPED` | `TLE` | the trip verdict is not masked |

Values are strings, so nothing serialized moves. Because no slot is ever
empty, the positional invariant in `_get_evals_per_group` holds unchanged even
when a later group resumes.

### 4. How far an abort reaches

`deps` are legal **only** under `scoring: points` (`schema.py:1362` rejects
them otherwise), so the two cases do not overlap:

- **`scoring: binary`** -- skip every remaining testcase in every remaining
  group. The verdict is all-or-nothing; nothing later can rescue it.
- **`scoring: points`** -- skip the rest of the current group, plus the
  **reverse-transitive closure** of `deps`: every group that depends on the
  aborted one, directly or indirectly. Independent groups still run and can
  still score.

The POINTS rule only formalizes what already happens: `_check_deps`
(`solutions.py:1822`) awards a group 0 whenever any dep failed, so the
dependent groups were going to score 0 whether or not they ran.

This assumes the caller's predicate only trips on an outcome that already
dooms the group. Documented as a contract on `abort_on`; the timing predicate
satisfies it.

### 5. Expectations and scoring

`SKIPPED` is a real, non-passing verdict -- getting it means the testcase was
not awarded. It is **not** treated as missing evidence.

- A testcase evaluating to `SKIPPED` did not pass.
- A group made entirely of skipped tests reports `SKIPPED` as its outcome.
- `ExpectedOutcome.match(Outcome.SKIPPED)` is **`True` for every expectation
  except `ACCEPTED`**. Implemented as an early branch in `match`
  (`schema.py:250`), since the per-member arms would otherwise each return
  `False`.

Scores follow from this with no special-casing: an aborted group fails, so it
scores 0, and `_check_deps` zeroes its dependents.

### 6. On disk and in the TUI

The skipped evaluation is persisted as a normal `.eval` artifact. `rbx ui`
does not read `StructuredEvaluation` at all -- it reads `skeleton.yml` plus
`.eval` files (`ui/utils/run_ui.py:41-83`), and its only "hasn't run" signal
is *a missing `.eval`*. Without the artifact, an aborted solution would flip
the whole row to `INCOMPLETE` (`run_ui.py:203`) and every skipped test would
be indistinguishable from one that never ran.

With the artifact, the TUI renders `SKIPPED` explicitly. It still counts as
not-AC under the "failing only" filter (`run_test_explorer.py:199-205`), which
is correct under §5.

### 7. Timing integration

When a cap is active (`timing.py:1030`), `_run_for_inference` passes:

```python
abort_on=lambda ctx: ctx.evaluation.result.outcome.is_slow()
```

Both roles abort. An upper-bound solution that hits the cap is dropped from
the bound anyway; a lower-bound solution that hits it is already a fatal error
(diagnostic 4). Neither needs further tests.

`_diagnose_inference_run` needs an explicit guard: it classifies an UPPER
solution with any non-AC, non-slow outcome as `failed_upper` (fatal), and
`SKIPPED` is both. Skipped evaluations must be ignored there, and in
`_timings_per_language` and `_print_timing`, which have no timing data to read
from them.

## Accepted tradeoff: aborting can hide a fatal diagnosis

Aborting destroys evidence, and in one case that evidence would have changed
the verdict of the estimation run. This is known and accepted; it is not a bug
report.

`_diagnose_inference_run` ranks `broken` above `timed_out`: an upper-bound
solution that fails for a NON-timing reason (a wrong answer, a crash) is
**fatal** (`failed_upper`, the run stops and no profile is written), while one
that is merely too slow is a **warning** (`dropped_upper`, the profile is
written without it). Under BINARY scoring the gate skips every remaining
testcase of the solution, so once it trips on a slow verdict, no later
testcase can ever contribute the wrong answer that would have made the run
fatal.

Concretely, with an upper-bound solution that hits the cap on test 1 and is
wrong on tests 2-3, under `check=True`:

- before this change: fatal, no profile written, the setter is told the
  solution is broken;
- after this change: a `dropped_upper` warning, and the profile is written.

It is **order-dependent**. Put the wrong-answer testcase first and the abort
trips only after the wrong answer is already in `outcomes`, so the fatal path
returns. The same package can therefore be diagnosed either way depending on
testcase order alone.

We accept this. The estimate itself is unaffected either way -- a dropped
solution bounds nothing, so the number rbx writes is the same number it would
have written -- and what is lost is a diagnostic about a solution the setter
mislabeled, which the ordinary `rbx run` reports on the full testset without a
cap. The alternative -- running every remaining testcase of a hopeless
solution purely to keep classifying it -- is exactly the wall clock this
change exists to stop spending. The warning text is deliberately left as is.

## Consumers that must classify `SKIPPED`

Adding an enum member makes most of these compile-time or review-visible:

- `steps.py:38` enum + `short_name()`; `solutions.py:1129-1198` short-name and
  style maps (`SKIP`, dim).
- `schema.py:250` `ExpectedOutcome.match` early branch.
- `timing.py:604` `_timings_per_language`, `timing.py:816`
  `_diagnose_inference_run`, `solutions.py:1984` `_print_timing` -- exclude
  from timing statistics and from failure classification.
- `solutions.py:2143` detailed renderer cell; `solutions.py:2475`
  `LiveRunReporter` -- a distinct marker, not a frozen `i/..`.
- `solutions.py:1703` `get_solution_outcome_report` / `_get_verdict_report`.
- `ui/utils/run_ui.py`, `ui/screens/run_test_explorer.py`.

## Testing

- **Gate:** trips on the first matching evaluation; every later slot for that
  solution is `SKIPPED` and no sandbox run happens for it; other solutions are
  unaffected.
- **Span:** BINARY skips the whole remainder; POINTS skips the current group
  and its reverse-dep closure while independent groups still run and score.
- **Ordering:** `worst_outcome` over `[AC, SKIPPED]` is `SKIPPED`; over
  `[AC, TLE, SKIPPED]` is `TLE`.
- **Expectations:** `match(SKIPPED)` is `True` for every `ExpectedOutcome`
  except `ACCEPTED`.
- **Artifacts:** a skipped testcase produces a readable `.eval`, and the TUI
  helpers render it as skipped rather than as a missing run.
- **e2e:** a package with a hopeless slow solution under a small
  `inferenceTimeout` runs it exactly once, and the estimate is unchanged from
  the pre-abort behavior.

## Out of scope

- Any user-facing flag (`rbx run --fail-fast`) or per-solution setting. The
  capability is built to support one later; nothing is exposed now.
- Aborting the *whole run* rather than one solution.
- Revisiting the `dropped_upper` diagnostics from #643.
