# A run report artifact, so verdict logic lives only in Python

The VS Code extension re-derives from raw artifacts what rbx has already
decided. Of the extension's 1797 lines, 888 sit in `vscode/src/rbx/` mirroring
Python: the outcome ordering, `Outcome.short_name()`, `Outcome.worst_outcome()`,
`ExpectedOutcome.match()`, the skeleton and evaluation models, and — added most
recently — an aggregation that decides a solution's verdict and score.

Nothing verifies any of it. No Python test references `vscode/`; nothing fails
if `Outcome` gains a member or `ExpectedOutcome.match()` changes.

The duplication that matters is the *logic*, not the models. Mirroring a
Pydantic model's field names is cheap and fails loudly. Re-implementing "which
verdict wins" is neither.

## D1. rbx already computes this and discards it

`get_solution_outcome_report()` (`rbx/box/solutions.py:1877-2032`, ~156 lines)
produces a `SolutionOutcomeReport` (`solutions.py:1549-1716`) holding the
pooled verdict, the per-group verdict reports, `gotScore` / `maxScore` /
`gotScorePerGroup` — with `_check_deps` dependency propagation — the
expected-score range check, and an aggregate status.

It is a Pydantic v2 model. It serializes cleanly today. It is never written to
disk, which is the only reason the extension had to re-derive any of it.

So the fix is not to port less. It is to stop throwing the answer away.

## D2. Why not just invoke rbx

The extension is a pure reader and never spawns rbx (v1 design, D2). That
decision turns out to be underjustified by its own comment. `rbx/box/cli.py:198-207`:
when the cache fingerprint does not match the installed version, the root Typer
callback `shutil.rmtree`s `build/` and the whole `.rbx/` directory. An extension
that shelled out to a version-skewed rbx would silently destroy the user's
cache mid-session.

Beyond that: `rbx/grading/caching.py:385` and `rbx/grading/judge/cacher.py:93`
take real `flock`s, so a second process serializes against an in-flight run
rather than corrupting it — safe, but it would stall the tree. And Python
startup with pydantic, typer and rich is far too slow for a watcher debounced
at 200ms.

A file on disk costs nothing to read, races nothing, and needs no rbx on
`PATH`.

## D3. A lean export model, not the internal one

`SolutionOutcomeReport` embeds `solution: Solution`, `limits: Limits` and
`evals: List[Evaluation]`; its JSON schema is 23 KB. Writing it verbatim would
duplicate every evaluation already on disk in `.eval` files and pin an internal
shape as an external contract.

Instead a small model built *from* it, in `rbx/box/run_report.py`:

```python
class RunGroupReport(BaseModel):
    name: str
    outcome: Optional[Outcome]          # worst verdict in the group
    expectedOutcome: Optional[ExpectedOutcome]
    matchesExpectation: bool
    score: int
    maxScore: int
    maxTime: Optional[float]            # seconds
    maxMemory: Optional[int]            # bytes

class RunSolutionReport(BaseModel):
    path: str
    index: int                          # directory name under .rbx/runs
    expectedOutcome: ExpectedOutcome
    outcome: Optional[Outcome]
    status: SolutionOutcomeStatus
    matchesExpectation: bool
    score: int
    maxScore: int
    maxTime: Optional[float]
    maxMemory: Optional[int]
    failedGroups: List[str]
    groups: List[RunGroupReport]

class RunReport(BaseModel):
    version: int = 1
    solutions: List[RunSolutionReport]
```

Structured data only: enum values, seconds, bytes, integers. No `AC`, no
`120 ms`, no `[70/100 pts]`. Rendering stays in the client, where a different
client may reasonably render it differently.

`version` is the stability hedge. A reader that finds a version it does not
know shows the tree without aggregates rather than guessing.

## D4. Written once per solution

`TraditionalRunReporter.finish_solution()` (`solutions.py:2610`) is the single
hook both `LiveRunReporter` and `SingleSolutionRunReporter` route through,
exactly once per solution. The report is computed there — once, and handed to
`render_solution_end` rather than computed a second time by it — and
`.rbx/runs/report.yml` is rewritten with the solutions finished so far.

Per solution, not per group or per testcase. A group-granular write would need
`get_partial_report()` and would buy only a slightly earlier aggregate; a
testcase-granular one would recompute a 156-line report N times per solution.

The consequence is deliberate and visible: **while a solution is running, its
row and its group rows show a progress counter and nothing else.** No
worst-so-far verdict, no max time. Those appear when the solution finishes.
That is the price of having no aggregation in the client, and it is the right
price — a client-side "worst so far" is exactly the logic this document exists
to delete.

Per-testcase rows are unaffected: they read their own `.eval` directly, which
is field access, not logic, and is what keeps live progress working.

`--detailed` bypasses both reporters (`solutions.py:2874`), so it must write the
report on its own path or explicitly not at all; whichever, `rbx run -d` must
not leave a stale report from a previous run.

## D5. What stays in TypeScript

Three things, none of them logic:

- **Structure and paths** — `skeleton.yml` for which testcases exist and their
  artifact stems. Field access.
- **Per-testcase facts** — each `.eval` for verdict, time, memory, message.
  Field access, and the source of live progress.
- **Display** — `accepted` → `AC`, `0.12` → `120 ms`, `[70/100 pts]`. About 60
  lines of formatting and short-name tables.

Deleted: `worstOutcome`, `matches`/`ExpectedOutcome.match()`, `isSlow`, the
`OUTCOMES` ranking, and all of `summary.ts`'s aggregation and scoring.
`outcome.ts` drops from 178 lines to roughly 40 of display mapping.

This also removes a divergence shipped only days ago: the extension awards a
group's score all-or-nothing *without* rbx's `_check_deps` gate, over-reporting
on problems with group dependencies. Reading `gotScorePerGroup` makes the bug
cease to exist rather than remain documented.

## D6. Guarding the seam

The remaining TS tables are display mappings, and unknown values already
degrade safely (`shortName` renders `XX`, an unknown expectation matches). The
`version` field guards the report shape.

What is worth adding is the check that does not exist today: a test asserting
the export model covers every `Outcome` and every `ExpectedOutcome` member, in
the spirit of `tests/rbx/box/completion/enum_consistency_test.py`, so adding an
enum member fails a Python test rather than silently rendering `XX` in an
editor nobody is testing.

Publishing JSON schemas for these models is deliberately out of scope. Worth
noting for later: `utils.model_to_yaml` (`rbx/utils.py:365-368`) already stamps
every `skeleton.yml` with `$schema=.../schemas/SolutionReportSkeleton.json`, a
file that is never generated — a dangling URL in shipped fixtures today.
