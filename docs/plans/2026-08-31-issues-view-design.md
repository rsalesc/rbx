# `rbx issues`: a run-issues view for problems and contests

Tracked by [#792](https://github.com/rsalesc/rbx/issues/792).

## The problem

After `rbx run` finishes, telling whether the problem is in a good state is
harder than it should be. Did every solution meet its expectation? Was anything
merely borderline? Did something compile with warnings? The answers are spread
across a solution table, an issue tree, and a few warnings printed at various
points during the run, and none of them survive the process. Ask the same
question five minutes later and the only way to get an answer is to run again.

At contest level it is worse: the state of ten problems lives in ten separate
`.rbx/runs` directories, and the only way to see them together is `rbx each`.

## What already exists

Most of the facts are already on disk. `.rbx/runs/` holds:

- `report.yml` (`rbx/box/run_report.py`) -- per solution: `status`,
  `matchesExpectation`, `pooledMatchesExpectation`, `failedGroups`, `score` and
  `expectedScore`, `maxTime`/`maxMemory`, `runUnderDoubleTl`,
  `doubleTlVerdicts`, `unexpectedNoTleVerdicts`, `sanitizerWarnings`, plus the
  same per group.
- `skeleton.yml` -- solutions, groups, limits, the run's `verification` level
  and its `sanitized` / `only_accepted` flags, and `compilation`
  (`rbx/box/compilation_findings.py`): every solution that failed to compile or
  compiled with warnings, with parsed warnings and a log path.
- `compilation/N.log`, the `.eval` / `.out` / `.err` artifacts.

What is *not* on disk is the accumulation of issues themselves.
`rbx/box/sanitizers/issue_stack.py` is a contextvar stack of `Issue` objects
rendered straight to a Rich tree at process exit, and
`rbx/box/sanitizers/warning_stack.py` is a second, unrelated accumulator for
compiler, sanitizer and linter output.

## Decisions

### `rbx issues`, alongside `rbx summary`

`rbx summary` already exists and answers a different question -- what this
problem *is*: limits, test counts, solutions bucketed by their *declared*
outcome. It stays exactly as it is.

The new command answers what the last *run* revealed:

```
rbx summary   -> what this problem IS
rbx issues    -> what the last RUN revealed
```

with `rbx contest issues` as the contest-level aggregate.

### Issues are derived, not persisted

`rbx issues` is a registry of pure detector functions run over the artifacts
already in `.rbx/runs`. There is no new file to write, no write path to get
wrong, and no second copy of the truth to drift.

This was the main fork. The alternative -- having commands append structured
issue records to an `issues.yml` -- buys coverage of the few producers that have
no on-disk source (linter warnings, statement build failures) at the cost of a
persisted artifact whose staleness has to be reasoned about per producer. Those
producers are deferred instead; see *Deferred* below.

Widening `report.yml` with an `issues:` list was also rejected: that file is
deliberately lean and structured-not-rendered, and it is cleared on every new
run, so anything not produced by `rbx run` would keep vanishing from it.

### `rbx run` re-reads from disk

The post-run render does not pass in-memory objects to the detectors. By the
time a run ends, `RunReportWriter` has already written the complete file; the
file is a few KB. Re-reading it makes it structurally impossible for the
post-run view and a later `rbx issues` to disagree -- the same anti-drift
argument `run_report.py` makes for the facts it publishes.

### The VS Code extension shells out

Detectors are Python. If the extension re-derived them it would reintroduce
exactly the cross-language drift `run_report.py` exists to prevent. So
`rbx issues --format json` is a versioned output contract
(`ISSUES_FORMAT_VERSION`) and the extension renders that. One implementation of
the logic, and the CLI and the extension cannot disagree because they are the
same code path.

### No freshness verdict

A contest row shows *when* the problem last ran ("4m ago", "3d ago", "never")
and nothing more. Deriving a stale/fresh verdict -- whether by mtime heuristics
or by asking the build cache -- was considered and dropped: a wrong verdict on
that is worse than no verdict, and the timestamp is enough for the reader to
judge.

## Architecture

```
.rbx/runs/skeleton.yml --+
.rbx/runs/report.yml   --+--> load_run_state() -> RunState -> DETECTORS -> List[Issue]
.rbx/runs/compilation/ --+                                                     |
                                            +----------------+----------------+
                                            |                |                |
                                     render_compact   render_detailed       to_json
                                            |                |                |
                                     rbx run /          rbx issues -d      VS Code
                                     rbx issues
```

### Layout

```
rbx/box/issues/
  __init__.py     public API only: load_run_state, detect_all, Issue, IssueSeverity
  schema.py       Issue discriminated union, IssueSeverity, ISSUES_FORMAT_VERSION
  run_state.py    RunState + load_run_state()
  detectors.py    the pure detector functions + the DETECTORS registry
  rendering.py    render_compact / render_detailed / render_contest_table / to_json
```

`run_state.py` rather than `state.py`: `rbx/box/state.py` already exists, and
with absolute imports mandatory the two would read confusingly side by side.

Callers -- `rbx/box/cli/commands/issues.py`, `rbx/box/contest/main.py`, and the
post-run hook in `rbx/box/solutions.py` -- import from `rbx.box.issues` and
never reach into a submodule.

### The issue model

Following `run_report.py`'s structured-not-rendered rule: the model carries
fields, never prerendered strings. Wording belongs to the renderer, and a client
with a different surface may reasonably word it differently.

```python
ISSUES_FORMAT_VERSION = 1

class IssueSeverity(str, Enum):
    ERROR = 'error'
    WARNING = 'warning'

class UnmetExpectationIssue(BaseModel):
    kind: Literal['unmet_expectation'] = 'unmet_expectation'
    solution: str
    expected: ExpectedOutcome
    got: Optional[Outcome]
    status: str                     # SolutionOutcomeStatus value
    failedGroups: List[str] = []
    pooledMatchesExpectation: bool  # so the renderer never accuses an expectation that held

class UnexpectedScoreIssue      -> solution, score, expectedScore
class CompilationFailedIssue    -> solution, reason, log
class CompilationWarningsIssue  -> solution, warnings, log
class BorderlineTleIssue        -> solution, groups, doubleTlVerdicts
class HiddenVerdictIssue        -> solution, groups, unexpectedNoTleVerdicts
class UntunedLimitsIssue        -> affectedSolutions

Issue = Annotated[Union[...], Field(discriminator='kind')]
```

Severity is a property of the kind rather than a stored field. Errors:
unmet expectation, unexpected score, compilation failed. Warnings: the rest.

`pooledMatchesExpectation` is carried for the reason `run_report.py` publishes
it: a solution declaring `outcome: incorrect` with an `outcomePerGroup` can fail
only the per-group layer, and saying "expected INCORRECT, got WA" there accuses
an expectation that in fact held.

### Detectors

```python
DETECTORS: List[Callable[[RunState], List[Issue]]] = [
    detect_unmet_expectations,
    detect_unexpected_scores,
    detect_compilation,
    detect_borderline_tle,
    detect_hidden_verdicts,
    detect_untuned_limits,
]
```

Each is a pure function from `RunState` to a list of issues. None touches a
contextvar, a console, or the filesystem beyond the state it was handed. That is
the main practical gain over the issue stack: every detector is unit-testable
against a hand-built `RunState`, with no sandbox, no compilation and no fixture
package.

`RunState` is `{skeleton, report, runs_dir, ran_at}`, where `ran_at` is
`report.yml`'s mtime. `load_run_state` returns `None` when there is no report --
that is the "never run" state, not an error.

### CLI

- `rbx issues [-d/--detailed] [--format rich|json]`, implemented in
  `rbx/box/cli/commands/issues.py` with a matching row in `ENTRIES` carrying the
  same `help=` and `rich_help_panel=`, per the lazy-CLI contract that
  `tests/rbx/box/lazy_cli_test.py` pins.
- `rbx contest issues [-d] [--format json]` in `rbx/box/contest/main.py`,
  reusing `cd.new_package_cd` and `clear_package_cache` the way
  `print_contest_summary` already does.
- Both exit 0 regardless of findings. `rbx issues` is a viewer; `rbx run`
  remains the CI gate.

### Rendering

Compact by default everywhere -- one line per issue, grouped by severity, errors
first:

```
$ rbx issues
  2 errors, 2 warnings   (last run 4m ago)
  x sol/wa.cpp    expected wrong-answer, got accepted
  x sol/bad.cpp   failed to compile
  ! sol/slow.cpp  slow only within 2x TL
  ! limits may not be tuned  -> rbx time
```

`-d/--detailed` expands each into its full explanation -- which groups, which
verdicts, log paths, the `rbx time` rationale. The post-run section of `rbx run`
and standalone `rbx issues` call the same renderer, so nothing renders
differently depending on how the reader got there.

The contest view is one row per problem:

```
  #  Problem      Last run   Err  Warn  Worst issue
  A  add-two      4m ago       0     0  -
  B  paths        4m ago       2     1  sol/wa.cpp: expected WA, got AC
  C  tree-query   never        -     -  not run
  D  strings      3d ago       0     2  compiler warnings (2 solutions)
```

with `-d` following that table with each problem's issues in full.

### What gets retired

`FailedSolutionIssue`, `FailedToCompileSolutionIssue` and `TimingIssue` are
removed from `rbx/box/solutions.py` -- the detectors supersede them, and the end
of `rbx run` renders detector output instead of the issue tree.

`issue_stack` itself survives, for `TooMuchStderrIssue`, the statement-build
issues and the sandbox stack/memory-limit warnings. Those have no on-disk source
yet.

### Error handling

A missing or unparseable `report.yml` reads as "never run". A `report.version`
newer than `REPORT_VERSION` is refused rather than guessed at, which is that
file's own stated rule. At contest level a problem that fails to load becomes an
error row and never aborts the table, matching what `print_contest_summary`
already does.

## Deferred

Each of these gets its own issue:

- A sanitizer-finding detector. The flag is already in `report.yml`; the case
  that matters is a run that otherwise passed.
- A noisy-stderr detector, migrating `TooMuchStderrIssue`. Derivable by sizing
  the `.err` artifact.
- Persisting linter warnings, then a detector over them.
- Persisting statement build failures, then a detector over them.
- Run-context caveats: `sanitized`, `only_accepted`, a subset run, a
  `--fail-fast` abort. All on the skeleton already; they qualify every other
  issue rather than being issues themselves, so they need a rendering decision
  first.
- Config-level checks that need no run at all -- no ACCEPTED solution declared,
  no validator, no samples. These may belong in `rbx summary` rather than here.
