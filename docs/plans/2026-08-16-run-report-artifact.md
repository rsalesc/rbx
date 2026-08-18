# Run Report Artifact Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `rbx run` persist the verdict/score aggregation it already computes, so the VS Code extension can read it instead of re-implementing it in TypeScript.

**Architecture:** A new `rbx/box/run_report.py` defines a small, structured, versioned export model built *from* the existing `SolutionOutcomeReport`. `TraditionalRunReporter.finish_solution` persists it to `.rbx/runs/report.yml` once per solution as each one completes. The extension reads that file for all aggregates and deletes its own — keeping only artifact-path resolution, per-`.eval` field reads, and display formatting.

**Tech Stack:** Python 3 / Pydantic v2 / pytest on the rbx side; TypeScript / esbuild / `node --test` on the extension side.

**Design:** [`2026-08-16-run-report-artifact-design.md`](2026-08-16-run-report-artifact-design.md)

**Background:** the extension currently mirrors ~888 lines of Python in `vscode/src/rbx/`. This plan deletes the *logic* half of that. Models staying mirrored is fine and deliberate (D5).

---

## Key facts to know before starting

- `Outcome` (`rbx/grading/steps.py:38`) serializes as its lowercase-kebab **value** (`wrong-answer`). `ExpectedOutcome` (`rbx/box/schema.py:140`) serializes as its upper-snake **member name** (`WRONG_ANSWER`). They are different vocabularies; never conflate them. The extension already encodes this in `vscode/src/rbx/outcome.ts`.
- `SolutionOutcomeReport.perGroup` holds **only** groups that carry an expectation AND were evaluated. It is not a complete group list — get the full list from `skeleton.groups`.
- `_get_evals_per_group(evals, skeleton)` (`rbx/box/solutions.py:1837`) buckets evaluations by group, assuming `evals` is a gapless prefix of `skeleton.entries`. That holds for our caller.
- A solution's index is its position in `skeleton.solutions`, which is also its directory name under `.rbx/runs/`. The extension depends on this.
- Do **not** serialize `SolutionOutcomeReport` directly: it embeds `solution`, `limits` and `evals` (23 KB JSON schema, and it would duplicate every `.eval` on disk).

---

## Task 1: The export model

**Files:**
- Create: `rbx/box/run_report.py`
- Test: `tests/rbx/box/run_report_test.py`

**Step 1: Write the failing test**

```python
from rbx.box import run_report


def test_report_model_round_trips_through_yaml():
    report = run_report.RunReport(
        solutions=[
            run_report.RunSolutionReport(
                path='sols/main.cpp',
                index=0,
                expectedOutcome='ACCEPTED',
                outcome='accepted',
                status='OK',
                matchesExpectation=True,
                score=100,
                maxScore=100,
                maxTime=0.008,
                maxMemory=10485760,
                failedGroups=[],
                groups=[
                    run_report.RunGroupReport(
                        name='main',
                        outcome='accepted',
                        expectedOutcome=None,
                        matchesExpectation=True,
                        score=100,
                        maxScore=100,
                        maxTime=0.008,
                        maxMemory=10485760,
                    )
                ],
            )
        ],
    )
    assert report.version == 1
    reloaded = run_report.RunReport.model_validate(report.model_dump())
    assert reloaded == report
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/run_report_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rbx.box.run_report'`

**Step 3: Write the minimal implementation**

```python
"""The run summary rbx publishes for other tools to read.

`rbx run` already decides every solution's verdict and score in
`solutions.get_solution_outcome_report`, then throws the answer away. This
module is the on-disk form of that answer, so a client -- the VS Code
extension today -- can render a run without re-deriving any of it.

Deliberately *structured*, not rendered: enum values, seconds, bytes and
integers. Turning `accepted` into `AC` and `0.008` into `8 ms` is the client's
business, and a different client may reasonably differ.

Deliberately *lean*: `SolutionOutcomeReport` embeds the solution, its limits
and every evaluation. Those either live elsewhere on disk already (`.eval`
files) or are internal shape that must not become an external contract.
"""

from typing import List, Optional

from pydantic import BaseModel

from rbx.box.schema import ExpectedOutcome
from rbx.grading.steps import Outcome

# Bump when a change would make an older reader misread the file. Readers must
# ignore a report whose version they do not know rather than guess at it.
REPORT_VERSION = 1


class RunGroupReport(BaseModel):
    """How one testcase group fared, for one solution."""

    name: str
    # Worst verdict in the group; absent when nothing in it was evaluated.
    outcome: Optional[Outcome] = None
    # Only set when the solution declares an `outcomePerGroup` for this group.
    expectedOutcome: Optional[ExpectedOutcome] = None
    matchesExpectation: bool = True
    score: int = 0
    maxScore: int = 0
    # Max, not sum: the slowest testcase is the one judged against the limit.
    maxTime: Optional[float] = None  # seconds
    maxMemory: Optional[int] = None  # bytes


class RunSolutionReport(BaseModel):
    path: str
    # Position in `skeleton.solutions`, which is also the directory name under
    # `.rbx/runs/`. Clients resolve artifact paths with it.
    index: int
    expectedOutcome: ExpectedOutcome
    outcome: Optional[Outcome] = None
    status: str
    # `status == OK`, hoisted out so a client need not know the status values.
    matchesExpectation: bool = True
    score: int = 0
    maxScore: int = 0
    maxTime: Optional[float] = None
    maxMemory: Optional[int] = None
    failedGroups: List[str] = []
    groups: List[RunGroupReport] = []


class RunReport(BaseModel):
    version: int = REPORT_VERSION
    solutions: List[RunSolutionReport] = []
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/run_report_test.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/box/run_report.py tests/rbx/box/run_report_test.py
git commit -m "feat(run): add the structured run report model (#25)"
```

---

## Task 2: Build a report entry from a SolutionOutcomeReport

**Files:**
- Modify: `rbx/box/run_report.py`
- Test: `tests/rbx/box/run_report_test.py`

The builder needs `(solution_index, solution_path, skeleton, outcome_report)` and derives everything else. Import `_get_evals_per_group` and `Outcome.worst_outcome` rather than reimplementing bucketing or ranking.

**Step 1: Write the failing test**

Use the real pipeline rather than hand-built models — build a package and run it, then assert on the produced entry. Reuse `pkg_from_testdata` / `cleandir_with_testdata` from `tests/rbx/box/conftest.py`, and the scored fixture `tests/e2e/testdata/outcome-per-group` (groups `small`=40, `big`=60; `sols/main.cpp` all-AC, `sols/partial.cpp` WA on `big` only).

```python
@pytest.mark.test_pkg('outcome-per-group')
async def test_report_entry_matches_what_rbx_decided(pkg_from_testdata):
    # ... run the package through the normal run path, then:
    entry = report.solutions[1]  # sols/partial.cpp
    assert entry.path == 'sols/partial.cpp'
    assert entry.index == 1
    assert entry.outcome == Outcome.WRONG_ANSWER
    assert entry.score == 40
    assert entry.maxScore == 100
    assert [g.name for g in entry.groups] == ['small', 'big']
    assert entry.groups[0].outcome == Outcome.ACCEPTED
    assert entry.groups[0].score == 40
    assert entry.groups[1].outcome == Outcome.WRONG_ANSWER
    assert entry.groups[1].score == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/run_report_test.py -v`
Expected: FAIL — the builder does not exist.

**Step 3: Write the implementation**

```python
def _max_of(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def build_solution_report(
    index: int,
    skeleton: 'SolutionReportSkeleton',
    report: 'SolutionOutcomeReport',
) -> RunSolutionReport:
    """Project the internal outcome report onto the published shape.

    Every decision here is read off `report`, never recomputed: the worst
    verdict comes from `Outcome.worst_outcome`, the scores from
    `gotScorePerGroup` -- which already applies the `_check_deps` dependency
    gate -- and the expectation results from `perGroup`. Recomputing any of it
    would reintroduce exactly the divergence this module exists to remove.
    """
    evals_per_group = _get_evals_per_group(report.evals, skeleton)

    groups = []
    for group in skeleton.groups:
        group_evals = evals_per_group.get(group.name, [])
        per_group = report.perGroup.get(group.name)
        groups.append(
            RunGroupReport(
                name=group.name,
                outcome=Outcome.worst_outcome(e.result.outcome for e in group_evals)
                if group_evals
                else None,
                expectedOutcome=per_group.expectedOutcome if per_group else None,
                matchesExpectation=per_group.status.ok() if per_group else True,
                score=report.gotScorePerGroup.get(group.name, 0),
                maxScore=group.score,
                maxTime=_max_of(e.log.time for e in group_evals),
                maxMemory=_max_of(e.log.memory for e in group_evals),
            )
        )

    return RunSolutionReport(
        path=str(report.solution.path),
        index=index,
        expectedOutcome=report.expectedOutcome,
        outcome=Outcome.worst_outcome(report.gotVerdicts) if report.gotVerdicts else None,
        status=report.status.value,
        matchesExpectation=report.status.ok(),
        score=report.gotScore,
        maxScore=report.maxScore,
        maxTime=_max_of(e.log.time for e in report.evals),
        maxMemory=_max_of(e.log.memory for e in report.evals),
        failedGroups=report.failedGroups,
        groups=groups,
    )
```

Verify the real signatures before writing: `Outcome.worst_outcome` (`rbx/grading/steps.py:55`) — confirm whether it is a `staticmethod` taking an iterable and what it returns for an empty one. Confirm `Evaluation.log.time` / `.memory` are the right attribute paths (`rbx/grading/steps.py:301` `TestcaseLog`). Import `_get_evals_per_group` from `rbx.box.solutions`; if that creates a circular import, move the helper into `run_report.py` and have `solutions.py` import it from there.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/run_report_test.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/box/run_report.py tests/rbx/box/run_report_test.py
git commit -m "feat(run): project the outcome report onto the published shape (#25)"
```

---

## Task 3: Persist the report, once per solution

**Files:**
- Modify: `rbx/box/run_report.py` (writer)
- Modify: `rbx/box/solutions.py` (`finish_solution`, both `render_solution_end`s, skeleton write site)
- Test: `tests/rbx/box/run_report_test.py`

**Step 1: Write the failing test**

```python
@pytest.mark.test_pkg('outcome-per-group')
async def test_run_writes_report_yml(pkg_from_testdata):
    # run the package, then:
    path = pkg_from_testdata / '.rbx' / 'runs' / 'report.yml'
    assert path.is_file()
    loaded = run_report.RunReport.model_validate(yaml.safe_load(path.read_text()))
    assert loaded.version == 1
    assert [s.path for s in loaded.solutions] == [
        'sols/main.cpp', 'sols/partial.cpp', 'sols/mislabeled.cpp',
    ]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/run_report_test.py -v`
Expected: FAIL — no `report.yml`.

**Step 3: Implement**

Add to `run_report.py`:

```python
REPORT_FILENAME = 'report.yml'


def report_path(runs_dir: pathlib.Path) -> pathlib.Path:
    return runs_dir / REPORT_FILENAME


def clear_report(runs_dir: pathlib.Path) -> None:
    """Drop a previous run's report.

    Called when a new skeleton is written. Without this an interrupted run
    would leave the last run's verdicts on disk, and a client cannot tell a
    stale report from a current one.
    """
    report_path(runs_dir).unlink(missing_ok=True)


class RunReportWriter:
    """Accumulates solution reports and rewrites the file as each one lands.

    Rewritten whole rather than appended: the file is a few KB, and a whole
    rewrite is atomic enough for a reader that tolerates a missing or
    half-written file by treating it as "no aggregates yet".
    """

    def __init__(self, runs_dir: pathlib.Path):
        self._path = report_path(runs_dir)
        self._report = RunReport()

    def add(self, entry: RunSolutionReport) -> None:
        self._report.solutions.append(entry)
        self.flush()

    def flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(utils.model_to_yaml(self._report))
```

In `solutions.py`:

1. At the skeleton write site (`solutions.py:704-705`), call `run_report.clear_report(runs_dir)` right after writing `skeleton.yml`. A new skeleton means a new run.
2. Change `TraditionalRunReporter.render_solution_end` (base, `:2615`) to return `Optional[SolutionOutcomeReport]` instead of `bool`; both overrides (`:2681` `LiveRunReporter`, `:2787` `SingleSolutionRunReporter`) already hold the `report` from `_print_solution_outcome` — return it instead of `report.status.ok()`.
3. In `finish_solution` (`:2608`), capture that report, persist it, and derive the boolean:

```python
def finish_solution(self) -> bool:
    assert self.current_solution is not None
    report = self.render_solution_end(self.current_solution)
    if report is not None:
        self.report_writer.add(
            run_report.build_solution_report(
                self.result.skeleton.solutions.index(...), self.result.skeleton, report
            )
        )
    self.current_solution = None
    self.current_solution_evals = []
    return report is None or report.status.ok()
```

Construct `self.report_writer` in `TraditionalRunReporter.__init__` from `package.get_problem_runs_dir()`.

**Critical:** do not call `get_solution_outcome_report` a second time to get the report. It runs with `report_issues=True` and calling it twice would double-push issues onto the issue stack. Thread the existing instance through.

Resolve the solution index by position in `skeleton.solutions` — match on identity or `str(path)`, and assert it was found rather than defaulting to 0.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/run_report_test.py -v`
Expected: PASS

Then check nothing else broke: `uv run pytest tests/rbx/box/solutions_test.py -v` (and any test asserting on `finish_solution`'s return).

**Step 5: Commit**

```bash
git add rbx/box/run_report.py rbx/box/solutions.py tests/rbx/box/run_report_test.py
git commit -m "feat(run): persist the run report to .rbx/runs/report.yml (#25)"
```

---

## Task 4: Cover the detailed path

**Files:**
- Modify: `rbx/box/solutions.py` (`_print_detailed_run_report`, around `:2472`)
- Test: `tests/rbx/box/run_report_test.py`

`print_run_report` returns early into `_print_detailed_run_report` when `detailed=True` (`solutions.py:2861`), bypassing the reporters entirely — so `rbx run -d` would write no report. That path already computes `report = _print_solution_outcome(...)` at `:2472`.

**Step 1: Write the failing test** — same as Task 3's but running with `detailed=True`; assert `report.yml` exists and lists every solution.

**Step 2: Run it** — Expected: FAIL, no file.

**Step 3: Implement** — build a `RunReportWriter` in `_print_detailed_run_report` and `add()` each report as it is computed.

**Step 4: Run tests** — both detailed and non-detailed report tests pass.

**Step 5: Commit**

```bash
git commit -m "feat(run): write the run report from the detailed path too (#25)"
```

---

## Task 5: Guard the enum seam

**Files:**
- Test: `tests/rbx/box/run_report_test.py`

Nothing today fails when `Outcome` gains a member, even though clients switch on its values. Mirror `tests/rbx/box/completion/enum_consistency_test.py`.

**Step 1: Write the test**

```python
def test_every_outcome_is_publishable():
    """A new Outcome must be a conscious decision, not a silent XX in a client."""
    for outcome in Outcome:
        entry = run_report.RunGroupReport(name='g', outcome=outcome)
        assert run_report.RunGroupReport.model_validate(entry.model_dump()).outcome is outcome


def test_every_expected_outcome_is_publishable():
    for expected in ExpectedOutcome:
        entry = run_report.RunSolutionReport(
            path='s.cpp', index=0, expectedOutcome=expected, status='OK'
        )
        assert run_report.RunSolutionReport.model_validate(entry.model_dump()).expectedOutcome is expected
```

**Step 2-4:** Run; these should pass immediately. If one fails, the serialization of that member is the bug — fix it rather than weakening the test.

**Step 5: Commit**

```bash
git commit -m "test(run): assert every outcome survives the published report (#25)"
```

---

## Task 6: Extension reads the report

**Files:**
- Create: `vscode/src/rbx/report.ts`
- Test: `vscode/src/rbx/report.test.ts`

**Step 1: Write the failing test**

```typescript
test('a report of an unknown version is ignored rather than guessed at', () => {
  assert.strictEqual(parseReport({ version: 99, solutions: [] }), undefined);
});

test('a solution report parses its aggregates', () => {
  const report = parseReport({
    version: 1,
    solutions: [{
      path: 'sols/main.cpp', index: 0, expectedOutcome: 'ACCEPTED',
      outcome: 'accepted', status: 'OK', matchesExpectation: true,
      score: 100, maxScore: 100, maxTime: 0.008, maxMemory: 10485760,
      failedGroups: [], groups: [],
    }],
  });
  assert.strictEqual(report?.solutions[0].score, 100);
});
```

**Step 2: Run** — `cd vscode && npm test`. Expected: FAIL, module missing.

**Step 3: Implement** `parseReport` using the existing tolerant helpers in `vscode/src/rbx/wire.ts` (`asRecord`, `asArray`, `asNumber`, `asString`, `field`). Return `undefined` for a missing file, an unparseable one, or `version !== 1` — all of which mean "render without aggregates".

**Step 4: Run** — PASS.

**Step 5: Commit**

---

## Task 7: Delete the duplicated logic from the extension

**Files:**
- Modify: `vscode/src/rbx/store.ts`, `vscode/src/rbx/summary.ts`, `vscode/src/rbx/outcome.ts`, `vscode/src/runTree.ts`
- Modify: `vscode/src/rbx/summary.test.ts`

**Delete from `outcome.ts`:** `OUTCOMES`, `outcomeRank`, `worstOutcome`, `isSlow`, `matches`, and the `ExpectedOutcome` union. **Keep:** `SHORT_NAMES`/`shortName`, `expectedShortName`, `isAccepted` — display mappings, not ranking.

**Delete from `summary.ts`:** `summarizeGroup`/`summarizeSolution`'s outcome and score derivation, `groupPassed`, `failingGroups`. **Keep:** `formatTime`, `formatMemory`, `formatScore`, and the `done`/`total` progress count (a count of `.eval` files present is not logic).

`formatCounts` currently orders by `outcomeRank`. That ordering *is* the worst-outcome ranking — replace it with descending count, then name, so no ordering knowledge remains in TS.

**`store.ts`:** load `report.yml` alongside `skeleton.yml`; hang the matching `RunSolutionReport` off `SolutionRun` and `RunGroupReport` off `GroupRun`, matched by index and group name. Both optional — absent while a run is in flight.

**`runTree.ts`:** when a node has a report, render verdict/score/time/memory from it; when it does not, render only the progress counter. Per D4 this is the visible behaviour change: **mid-run, solution and group rows show `12/40` and nothing more.** Update the tooltip the same way. Testcase rows are unchanged — they read their own `.eval`.

Rewrite `summary.test.ts` accordingly: drop the tests asserting worst-outcome and score derivation (that logic now lives in Python and is tested there), keep and extend the formatting and description tests.

**Verify:** `cd vscode && npm run typecheck && npm test && npm run compile`.

**Commit** once green.

---

## Task 8: End-to-end check against a real run

Not a unit test — do this by hand before opening the PR, the way the previous change was verified.

```bash
mkdir -p /tmp/rbx-check && cp -r tests/e2e/testdata/outcome-per-group/. /tmp/rbx-check/
cd /tmp/rbx-check && uv run --project <repo> rbx run
cat .rbx/runs/report.yml
```

Assert by eye that `report.yml` agrees with what `rbx run` printed — `sols/main.cpp` at 100/100, `sols/partial.cpp` at 40/100 with `big` scoring 0, `sols/mislabeled.cpp` FAILED via its per-group expectations.

Then build a temporary harness (as in the previous round) that renders the tree through `store.ts` + `summary.ts` and confirm it matches. **Specifically confirm the `_check_deps` fix**: find or construct a package with group dependencies where the old TypeScript over-reported, and check the tree now agrees with rbx.

Also confirm `rbx run -d` writes the report, and that `rbx clean` followed by a fresh run leaves no stale one.

---

## Task 9: Documentation

**Files:**
- Modify: `vscode/README.md` — the "What it reads" table gains `report.yml`; the run-tree section notes that aggregates appear when a solution finishes.
- Modify: `rbx/box/CLAUDE.md` — a line on `run_report.py` being the published contract, and that it must stay structured, versioned, and free of rendered strings.
- Modify: `docs/plans/2026-08-11-vscode-extension-design.md` — note that D2's rationale is now backed by `cli.py:198-207` (a version-skewed rbx rmtree's the cache), and that D3 is superseded by the report artifact.

**Commit**, then open the PR.

---

## Out of scope

- Publishing JSON schemas for these models (`schema_export.py` `MODELS`). Noted in the design as a follow-up; it would incidentally fix the dangling `$schema=.../SolutionReportSkeleton.json` URL that `utils.model_to_yaml` stamps into every `skeleton.yml`.
- The `irun` variant (`.rbx/runs/.irun/`), which the extension does not read.
- Per-group or per-testcase write granularity (explicitly rejected in D4).
