# Partial Scoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support testlib `quitp(percent)` checkers with per-group `min`/`sum` aggregation in
`rbx run`, the Polygon packager and the Polygon `--cms` route.

**Architecture:** A checker result carries a fraction in [0, 1]; one pure module
(`rbx/box/scoring/partial.py`) owns the per-test points split and the group-score rule, and
every consumer (`solutions.py`, Polygon, CMS) reads it. CMS gets `GroupMin` subtasks from a
generalised `flatten` and a checker compiled against an rbx testlib variant that prints
fractions. Design: `docs/plans/2026-10-25-partial-scoring-design.md`.

**Tech Stack:** Python 3 / Pydantic v2 / pytest; C++ testlib; CMS 1.5.1 (remote, for
verification only).

Run tests per touched file only (`uv run pytest <file>`), never the full suite.

---

### Task 1: Outcome and checker result model

**Files:** `rbx/grading/steps.py`, test `tests/rbx/grading/steps_test.py` (or the nearest
existing outcome test).

- Add `Outcome.PARTIALLY_CORRECT = 'partially-correct'` right after `ACCEPTED` (before
  `SKIPPED`; `worst_outcome` ranks by declaration order).
- Add `CheckerResult.score: Optional[float] = None` (fraction in [0, 1]; `None` = derive).
- Add `CheckerResult.fraction() -> float`: `score` if set, else 1.0 for ACCEPTED, else 0.0.
- Tests: worst_outcome ordering with PC; `fraction()` for each case.
- Grep every exhaustive `Outcome` mapping (`grep -rn "Outcome.WRONG_ANSWER" rbx/`) and add PC
  where a style/short name/icon is required (short name `PC`, yellow).

### Task 2: Parse `quitp` and refuse `_pc`

**Files:** `rbx/box/checkers.py` (`process_checker_run_log`), test
`tests/rbx/box/checkers_test.py`.

- `process_checker_run_log` receives the *full* stderr (it currently keeps only the last line
  for the message; keep that for the message).
- Before the exit-code checks: a stderr line starting `partially correct (` ->
  `JUDGE_FAILED`, message telling to use `quitp(percent)`.
- Exit code 7: last stderr line matching `^points\s+(\S+)(.*)$`; parse float; outside
  [0, 100] (or unparsable / missing) -> `JUDGE_FAILED`; 100 -> ACCEPTED (score 1.0);
  0 -> WRONG_ANSWER (score 0.0); else PARTIALLY_CORRECT with `score = x / 100`. Message is
  the remainder after the number.
- `_is_checker_exitcode` admits 7.
- Tests (pure, build `RunLog`s): points 82.5 -> PC 0.825; 100 -> AC; 0 -> WA; 150 -> JF;
  missing line -> JF; `partially correct (1) x` with exit 1 -> JF; multi-line message keeps
  working; exit 0/1/2/3 unchanged.

### Task 3: ExpectedOutcome

**Files:** `rbx/box/schema.py` (`ExpectedOutcome`), tests in `tests/rbx/box/schema_test.py`
(or wherever `ExpectedOutcome.match` is tested).

- New `PARTIALLY_CORRECT = alias('partially correct', 'partial', 'pc')`; matches PC only.
- `INCORRECT` matches PC; `ACCEPTED`, `ACCEPTED_OR_TLE`, `WRONG_ANSWER` do not.
- style yellow, icon `~`.

### Task 4: Schema for aggregation and the points split

**Files:** `rbx/box/scoring/dependencies.py` (`Aggregation`), `rbx/box/schema.py`
(`TestcaseGroup.aggregation`, `PointsScoring.aggregation` doc, `check_scoring_fields`,
`Package.aggregation_for`, `Solution.score` floats), new `rbx/box/scoring/partial.py`, tests
`tests/rbx/box/scoring/partial_test.py`, `tests/rbx/box/schema_test.py`.

- `Aggregation.SUM = alias('sum')`.
- `TestcaseGroup.aggregation: Optional[Aggregation] = None`; binary problems reject it
  (same mechanism as `deps`).
- `Package.aggregation_for(name) -> Aggregation`.
- `Solution.score` accepts floats (exact or range); `expected_score_range` returns floats.
- `partial.test_points(score: int, n: int) -> List[float]`: `round(score / n, 2)` each, the
  last absorbing `score - sum(rest)` (rounded to 2). Tests: 10/3 -> [3.33, 3.33, 3.34];
  33/1; 0/n; n=0 -> [].
- Regenerate the JSON schema/completion spec only if a drift test complains.

### Task 5: The group-score rule

**Files:** `rbx/box/scoring/partial.py`, `rbx/box/solutions.py`
(`get_solution_outcome_report`, `fulfills_expected_score`, score markup), tests
`tests/rbx/box/scoring/partial_test.py` and the existing solutions scoring tests.

- `partial.group_scores(groups, fractions, closure) -> Dict[str, float]` where `groups` are
  (name, score, aggregation, test-count), `fractions[name]` is the list of per-test fractions
  (missing tests = 0), `closure(name)` the dependency closure. Rule:
  - `dep_min = min(f over tests of closure(g))` (1.0 if none)
  - `min`: `score * min(own_min, dep_min)`
  - `sum`: `sum(tp_i * min(f_i, dep_min))`
  Round each group to 2 decimals.
- Tests: binary fractions reproduce all-or-nothing; the Polygon probe table
  (design doc) exactly: g2 = 5, g3 = 5, g5 = 0, g7 = 4.
- `solutions.py`: replace `_check_deps`/`passed()` with fractions from evals
  (`eval.result.fraction()`); `got_score`/`got_score_per_group` floats; record every group
  (0 included) in `gotScorePerGroup`. Groups without built tests keep today's handling.
- Score markup prints at most 2 decimals, trailing zeros dropped (`24.44`, `40`).
- `fulfills_expected_score` compares after rounding to 2 decimals.

### Task 6: Abort gate

**Files:** `rbx/box/solutions.py` (`_AbortGate`), test the gate's existing test module.

- PC never trips the gate.
- Under `sum`, a failing test does not skip the rest of its own group; dependents are still
  skipped.

### Task 7: Reporting

**Files:** `rbx/box/solutions.py` (per-test markup), `rbx/box/run_report.py`,
`vscode/src/rbx/report.ts` (+ its tests), tests `tests/rbx/box/run_report_test.py`.

- Per-test line for PC: `PC 74.06%`; compact mark distinct from AC.
- `run_report`: `REPORT_VERSION = 2`; group/solution `score` floats; each eval gains `score`
  (fraction) when present.
- `report.ts`: accept version 2 and float scores; PC style.

### Task 8: Flatten into subtasks; CMS score parameters; MOJ

**Files:** `rbx/box/scoring/dependencies.py` (`flatten`), `rbx/box/packaging/cms/scoring.py`,
`rbx/box/packaging/moj/packager.py`, tests `tests/rbx/box/scoring/dependencies_test.py`,
`tests/rbx/box/packaging/cms/*`.

- New `subtasks(deps, tests_by_group, aggregation_for, points_for) -> List[(group, points,
  tests)]`: `min` -> one subtask with own + closure tests; `sum` -> one subtask per own
  test `[tp_i, [test_i] + closure tests]`.
- CMS `group_min_parameters` builds regexes from `subtasks`; points may be floats.
- MOJ: any `sum` group -> refuse by name (keeps `flatten`'s min-only contract).

### Task 9: Polygon packager

**Files:** `rbx/box/packaging/polygon/xml_schema.py`, `rbx/box/packaging/polygon/packager.py`,
`rbx/box/packaging/polygon/polygon_api.py` / upload path, tests
`tests/rbx/box/packaging/polygon/*`.

- `Judging.treat_points_as_percent` -> `treat-points-from-checker-as-percent`, `true` under
  points.
- `sum` group -> `points-policy="each-test"`, `feedback-policy="points"`, test points from
  `test_points`; `min` unchanged.
- Warn when the checker source contains `_pc(`.
- API upload: find whether the percent mode is settable; else warn.

### Task 10: CMS checker build

**Files:** new `rbx/resources/packagers/cms/testlib_cms.h` (or a patch applied to the bundled
testlib at package time), `rbx/resources/packagers/cms/polygon_cms_conf.py`,
`rbx/box/packaging/cms/polygon_loader.py`, `rbx/resources/packagers/cms/rbx_cms_report.h`,
tests under `tests/rbx/box/packaging/cms/`.

- CMS testlib variant: in `InStream::quit`, under `RBX_CMS`, print the outcome on stdout
  (`1.0`/`0.0`/`x/100`), message on stderr, exit 0; FAIL -> exit 1; argv order swapped to
  CMS's (input, correct, contestant).
- `cms_conf.py` compiles `check.cpp` with that header in a temp dir and stores
  `managers['checker']` for batch problems.
- `rbx_cms_report.h`: `points x` -> print `x/100`.
- Local test: compile the variant with a `quitp` checker and assert stdout/exit codes.

### Task 11: E2E fixture

**Files:** `tests/e2e/testdata/partial-scoring/` (see `tests/e2e/README.md`).

- A `quitp` checker; groups `samples`, `a` (`min`, 40), `b` (`sum`, 60, deps `a`); solutions
  with exact expected scores (full, partial-on-a, wa-on-b-test).

### Task 12: Docs

Use the `docs-style` skill. Document `aggregation`, `quitp` percent and PC on the scoring
page; Polygon/CMS pages mention the percent mode and the checker build.

### Task 13: Live verification (subagents)

- CMS 1.5.1 on `rbx-teste` (`/root/cms-rbx-test`, container `cms-rbx-test-cms-1`, harness
  scripts in `work/`): import the `--cms` zip of the e2e fixture; submit the fixture's
  solutions; scores must equal `rbx run`'s.
- Polygon: upload the plain zip / API and confirm the same scores.

### Task 14: PR
