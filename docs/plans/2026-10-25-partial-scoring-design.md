# Partial scoring: `quitp` checkers, `min` and `sum` groups

## Problem

A points problem can only score a group all-or-nothing: a test is AC or it is not,
and a group pays its `score` iff every test (and every dependency) passed. IOI-style
problems routinely award *partial* credit per test -- an optimisation problem whose
checker scores the answer on a curve -- and rbx has no way to express, run or package
them:

- `quitp(...)` exits 7, which `process_checker_run_log` reports as `JUDGE_FAILED`
  ("unknown exit code 7").
- `quitf(_pc(k), ...)` exits with `k` itself (testlib only adds 50 under `-DTESTSYS`),
  so `_pc(1)` reads as WA and `_pc(0)` as AC.
- Polygon groups are always `complete-group`; CMS always gets `GroupMin` over binary
  outcomes, and the cms-dev Polygon loader would print a `quitp` value verbatim as the
  0..1 outcome.

The motivating case is `arvore4` (Polygon 489112, contest *seletiva IOI 2026*): groups
5 and 6 award `quitp(0..100)`; the setter also hand-wrote a `checker_cms.cpp` that
prints the 0..100 value where CMS expects 0..1.

## What the judges actually do

Established by reading testlib and cms-dev/cms at master, and by **measuring Polygon**
(invocations on `arvore4` and on a purpose-built probe, `rbx-partial-deps-probe`,
Polygon 614666, invocation 2637352).

### testlib

| Call | Exit | stderr | Meaning |
|---|---|---|---|
| `quitp(x, ...)` | 7 | `points <x> <msg>` | absolute number in [0, 1e6]; unit is the judge's business |
| `quitf(_pc(k), ...)` | `k` (50+k with `-DTESTSYS`) | `partially correct (k) <msg>` | integer, conventionally 0..200 |

`quitp(_pc(k), ...)` silently awards `16 + k` (the enum converts to int).

### Polygon, with "Treat points from checker as a percent"

The setting is the third option of the Tests page's *Enable points* dropdown
(`treatPointsFromCheckerAsPercent`); in `problem.xml` it is
`<judging treat-points-from-checker-as-percent="true">`. A checker's `quitp(x)` is then
a percentage. Measured:

| Policy | Group score |
|---|---|
| `complete-group` | `G * min_i(pct_i) / 100` -- every test's raw percentage counts, whether or not it carries points |
| `each-test` | `sum_i tp_i * pct_i / 100` -- only tests with points pay |

`arvore4` group 6 (33 points, all on test 153; percentages 74.06..100): complete-group
gave 24.44 = 33 x 0.7406, each-test gave 27.35 = 33 x 0.8288 (test 153's percentage).

Dependencies, measured on the probe (checker returns the percentage written in the
test; groups of 10 points):

| Group | Setup | Polygon |
|---|---|---|
| g1 | complete; tests 50%, OK | 5 |
| g2 | complete, deps g1; all OK | **5** (not 10: scaled, not gated) |
| g3 | each-test 5+5, deps g1; tests OK, 80% | **5** = 5 min(1, .5) + 5 min(.8, .5) |
| g5 | complete, deps g4 (a `quitp(0)` test) | 0 |
| g7 | complete, deps g6 (each-test, 7/10, lowest test 40%) | **4** = 10 x 0.4 |
| g9, g10 | deps on a WA group | 0, 0 |

So a dependency contributes the **minimum percentage over its tests**, regardless of its
own policy, and that minimum caps each dependent test. That is exactly what
duplicating the dependency's tests into the dependent group does under `GroupMin` --
the rule rbx's `flatten` already implements for CMS and MOJ.

Display trap: the invocation's per-test column shows the raw checker value for a test
with 0 points, and points earned (`pct x tp / 100`) for a test with points. rbx must not
copy that mixed column.

`quitf(_pc(k))` is reported by the community as a Polygon checker failure (not measured).

### CMS (cms-dev/cms master)

- A checker prints the outcome, a float in [0, 1], on stdout and the message on stderr;
  a non-zero exit is a judge error.
- The Polygon loader (`cmscontrib/loaders/polygon.py`) recompiles `check.cpp` against
  its own patched **testlib 0.9.21**, which prints `_points` verbatim (so a percentage
  comes out 100x too large) and `_pc(k)` as `k/200`. It hard-codes `Sum` at 100/N per
  test, then `args.update(cms_conf.datasets['tests'])` -- so `cms_conf.py` can replace
  the score type, its parameters and the `checker` manager.
- `GroupMin`: `sum over subtasks of points x min(outcomes)`. `Sum` has a single weight
  for every test and no groups, so it equals Polygon `each-test` only when every group is
  each-test with equal points; `GroupMin` over one-test subtasks reproduces `each-test`
  in general.

## Design

### Schema

```yaml
scoring:
  aggregation: min        # problem default: min (default) | sum
testcases:
  - name: samples
    aggregation: sum      # optional per-group override
  - name: big
    score: 33
```

- `Aggregation` gains `SUM`.
- `TestcaseGroup.aggregation: Optional[Aggregation] = None`, falling back to
  `scoring.aggregation`; rejected on binary problems by `check_scoring_fields`, like
  `deps` and `score`. Call sites read `pkg.aggregation_for(group)`.
- One global aggregation would not express `arvore4` (group 1 each-test, 2-6 complete).
  Mixing is safe on every backend: Polygon mixes policies natively and CMS expresses both
  under one `GroupMin`.
- `quitp` is **always a percentage** (0..100). No unit field: it is Polygon's native
  mode and what setters already write.
- `TestcaseGroup.score` stays an `int`. Under `sum`, a group's points are split evenly:
  `scoring.test_points(group)` returns `score / n` per test, rounded to 2 decimals, the
  last test absorbing the remainder so the split sums to exactly `score`. It is the
  single source every consumer reads, so `rbx run`, Polygon and CMS cannot disagree by
  a rounding cent.
- `Solution.score` accepts floats; comparisons happen after rounding to 2 decimals.

### Scoring rule

Each test has a score `f` in [0, 1]: AC is 1, `quitp(x)` is `x / 100`, any other verdict
(SKIPPED included) is 0. Let `D(g)` be the tests of `g`'s dependency closure.

| Aggregation | Group score |
|---|---|
| `min` | `G * min(f over own tests and D(g))` |
| `sum` | `sum over own tests i of tp_i * min(f_i, min(f over D(g)))` |

With `f` in {0, 1} both reduce to today's all-or-nothing scoring with dependencies, so
no existing problem changes score. The rule is the one Polygon measures (above) and the
one `flatten` produces for CMS, so all three agree.

### Checker results (`checkers.py`, `rbx/grading/steps.py`)

- Exit 7: take the last stderr line matching `^points (\S+)`; its value must be in
  [0, 100], else `JUDGE_FAILED`. 100 is `ACCEPTED`, 0 is `WRONG_ANSWER`, anything
  between is the new `PARTIALLY_CORRECT`.
- A `partially correct (` prefix is `JUDGE_FAILED` naming the fix (use
  `quitp(percent)`), checked before the exit code because `_pc(1)` exits 1.
- `CheckerResult.score: Optional[float]` carries the fraction in [0, 1]; `None` means
  "derive from the outcome".
- Interactors go through the same `process_checker_run_log`, so they get it for free.
- Rejected alternative: passing `<result-file> -appes` for testlib's XML result. It is
  unambiguous but changes the argv of every checker, including non-testlib ones run in
  testlib mode.
- `Outcome.PARTIALLY_CORRECT` is declared right after `ACCEPTED`, before `SKIPPED`.

### Expected outcomes and reporting

- `accepted` does not match PC; `incorrect` ("any non-AC verdict") does; `wrong answer`
  does not. A new `ExpectedOutcome.PARTIALLY_CORRECT` (aliases `pc`, `partial`) matches
  PC only. In practice partial solutions are pinned by `score:` ranges and
  `outcomePerGroup`.
- `solutions.py`: the per-group `passed()` becomes the rule above. `gotScore` and
  `gotScorePerGroup` become floats; `maxScore` stays an int.
- Display: totals as `[24.44/33 pts]`; per test `PC 74.06%` -- always a percentage.
- Abort gate: never trips on PC. Under `sum`, a WA must not skip the rest of its own
  group (the other tests still pay); skipping the group's dependents stays correct,
  since their score is now 0.
- `irun` stays binary for group totals but shows each test's percentage.
- `run_report.yml`: float scores and a per-test `score`; `REPORT_VERSION` 2; the VS Code
  `report.ts` reads floats and styles PC.

### Polygon packager

- Under points, always emit `<judging treat-points-from-checker-as-percent="true">`. It
  is inert for checkers that never call `quitp`.
- `min` groups: `complete-group`, as today (measured to equal `G * min%`).
- `sum` groups: `each-test`, `<test points>` from `test_points()`,
  `feedback-policy="points"`.
- API upload: `polygon_api.py` already sets `pointsPolicy`; whether the API can set the
  percent mode must be checked during implementation, and a warning issued (enable it
  in the UI) if it cannot.
- Warn when the checker source contains `_pc(`, as MOJ already warns on `quitp`.

### CMS (`cms_conf.py`)

- Score type stays `GroupMin`; `flatten` generalises to return `(points, tests)`
  subtasks: a `min` group is one subtask `[G, own + D]`; a `sum` group is one subtask per
  test, `[tp_i, test_i + D]`.
- `cms_conf.py` compiles `check.cpp` itself, in a temporary directory beside a **CMS
  variant of rbx's bundled testlib** (`_points` -> `x / 100` on stdout, WA -> `0.0`,
  OK -> `1.0`, FAIL -> judge error), and stores it as `managers['checker']`. It is the
  upstream loader's own approach without the 0.9.21 version skew. Rejected: a wrapper
  that executes the real checker, which depends on how CMS lays out its sandbox.
- Interactive: `rbx_cms_report.h`'s `classify` gains a `points` branch printing
  `x / 100`.

### Other packagers

MOJ and BOCA cannot award partial credit; the existing `quitp` warning stays, and
`flatten` refuses `sum` for MOJ by name instead of scoring wrong.

## Testing

- Unit: the stderr parser (including the `_pc` collision and out-of-range values); the
  scoring rule, including that binary verdicts reproduce today's scores and the probe
  table above; `test_points` rounding; `sum` flattening; the Polygon XML; the CMS
  parameters.
- E2E: a fixture under `tests/e2e/` with a `quitp` checker, a `min` group and a `sum`
  group (with a dependency), asserting exact scores.
- Docs: the scoring page, via the `docs-style` skill.
