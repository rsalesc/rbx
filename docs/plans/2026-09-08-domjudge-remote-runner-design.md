# DOMjudge remote runner -- design

`rbx time --runner domjudge` measures solution timings on a DOMjudge instance
instead of on the setter's machine, the way `--runner moj` already does for the
MOJ judge park. This document records the design and, more importantly, the
handful of DOMjudge behaviours that were **measured against a live server**
rather than assumed -- several of them contradict the obvious reading of the API.

Related:

- [`rbx/box/runners/base.py`](../../rbx/box/runners/base.py) -- the backend seam.
- [`docs/plans/2026-08-20-moj-remote-runner-design.md`](2026-08-20-moj-remote-runner-design.md) -- the MOJ runner this mirrors.
- [`scripts/domjudge/README.md`](../../scripts/domjudge/README.md) -- the local
  server every claim below was verified on (DOMjudge 9.0.0).

## 1. What DOMjudge gives us

`MojRunner` needs five primitives from a judge. DOMjudge has four of them, and
deliberately lacks the fifth.

| MOJ | DOMjudge |
| --- | --- |
| upload a probe package to a private `rbxt-` problem | `POST /contests/{cid}/problems` |
| `calibreitor.sh` derives the time limit on the judge | *nothing -- and rbx does not want it* |
| `moj testrun` (source in the request body) | `POST /contests/{cid}/submissions` |
| poll `status == done` | `GET /contests/{cid}/judgements?submission_id=` |
| per-test timings in `tests[]` | `GET /contests/{cid}/runs?judging_id=` |

The missing calibration is not a gap to work around. rbx already owns the
estimation arithmetic (`timing.multipliers`, `acToTimeLimit`, `timeLimitToTle`);
DOMjudge only has to be an accurate stopwatch, and `run_time` / `max_run_time`
make it one. So there is no `JudgeCalibrated` mode here, only the `ProbePinned`
equivalent -- which removes the whole class of "the judge calibrated something
different from what rbx asked for" failures the MOJ packager has to reason about.

## 2. Findings that changed the design

Each of these was observed on the local server. Each one would have produced a
plausible-looking wrong result if assumed the other way.

### 2.1 A judgement reports its verdict before it is finished

Polling until `judgement_type_id` is non-null is **wrong**. A submission that
fails early gets its verdict as soon as the failing testcase is known, while
judging continues:

```json
{ "judgement_type_id": "TLE", "end_time": null, "max_run_time": null }
```

Reading that judgement yields a null timing and a truncated run list. The poll
therefore keys on **`end_time`**, which is set only when judging is complete and
is what makes `max_run_time` trustworthy.

### 2.2 `run_time` is CPU time, not wall time

The fixture's `slow.cpp` sleeps 1.5s per test. DOMjudge killed it on the wall
clock (verdict `TLE`) and reported `run_time` between 0.016 and 0.037 -- the CPU
it actually burned. So a run's `run_time` is not "the time that caused the
verdict", and a sleep-heavy or I/O-heavy solution measures near zero.

For estimation this is the right number and is internally consistent
(`max_run_time` equals the max of the runs). For validation, the **verdict** is
what rbx reads, not the number, so the mismatch costs nothing there.

### 2.3 Importing a package auto-submits its jury solutions

An import whose zip contains `submissions/` answers `Added 2 jury solution(s)`
and **queues them as real submissions** from the built-in `domjudge` team. On a
timing run those judgings compete with rbx's own for the judgehost and inflate
the very measurements the run exists to take.

A probe package therefore ships **no `submissions/` directory at all**. This is
the single most important difference between a probe package and a real one.

### 2.4 `penalty_time` in a contest payload rewrites *global* configuration

`POST /contests` with `penalty_time` in the payload silently changed the
instance-wide setting from 20 to 0 -- visibly altering the unrelated demo
contest. Contest creation sends only the fields it needs, and never
`penalty_time`.

This is the reason the staging code has an explicit allow-list of contest fields
rather than passing a dict through.

### 2.5 The package's own `externalid` selects the problem it overwrites

Uploading a zip against problem `rbxt-foo` fails with

```
External ID of problem to import into (rbxt-foo) does not match new external ID (simple-problem)
```

unless `domjudge-problem.ini` declares `externalid = rbxt-foo`. Absent that key
DOMjudge derives the id from the *zip filename*, which is the trick pol2dom uses
(it renames the file to `{externalid}.zip`). Declaring `externalid` outright is
less surprising, so the probe packager does that.

### 2.6 Full judging is per-contest-problem, and needs an unlink first

`lazy_eval_results` is global config, but `ContestProblem` overrides it, so rbx
can ask for full judging (`2`) **scoped to its own probe problem** and never
touch a shared setting. The only route is `PUT /contests/{cid}/problems/{id}`,
which refuses when the problem is already linked -- so staging is
`DELETE` (204) then `PUT` with `lazy_eval_results: 2`. Testcases survive the
relink; only the link is replaced.

Verified: with `2`, a solution that times out on testcase 1 still reports runs
for all three testcases.

### 2.7 A contest-problem label must be unique, and a duplicate is a bare 500

`add-data` with a label another problem in the contest already holds answers
`500 Internal Server Error` and nothing else -- no message, no field name.

A fixed label would not merely have been fragile, it would have been *always*
wrong: the estimation and validation problems share one contest by design, so
the second phase `rbx time` staged would collide with the first on every run.
The label is therefore the problem id, which is unique by construction, and is
invisible anyway -- the probe contest has no scoreboard anyone reads.

### 2.8 Judgehost liveness is `enabled` plus `polltime`, not `active`

There is no `active` field. `GET /judgehosts` returns `enabled` and `polltime`,
and both matter: a stock install ships a disabled `example-judgehost1` row, and
an *enabled* judgehost whose daemon has stopped never picks anything up either.
DOMjudge's own threshold for the latter is `judgehost_critical` (120s by
default), so preflight reads it from the server rather than inventing one, and
separates the two cases -- "enable one" and "start the judgedaemon" are different
fixes.

### 2.9 Every install already has a team to submit as

`GET /teams` shows a hidden `domjudge` team in the `system` group -- the one
DOMjudge itself uses for jury submissions. rbx submits as that team and creates
none.

## 3. Architecture

```
rbx/box/runners/domjudge/
    api.py        # the HTTP surface, and nothing else
    staging.py    # preflight + get the probe problem judged-ready
    runner.py     # DomjudgeRunner(SolutionRunner)
```

`api.py` wraps `requests` in `asyncio.to_thread`. The project already depends on
`requests` and not on any async HTTP client, and the runner's concurrency is a
handful of in-flight polls -- not a workload that justifies a new dependency.

Credentials come from `RBX_DOMJUDGE_SERVER` / `_USERNAME` / `_PASSWORD`. Which
DOMjudge a setter can reach is a property of their machine, not of the problem,
so this is deliberately *not* an `env.rbx.yml` or `problem.rbx.yml` setting --
the same reasoning that keeps `RBX_MOJ_BINARY` out of the package.

## 4. `prepare`

Preflight first, because every unmet precondition otherwise shows up as a run
that waits forever rather than as an error:

1. `GET /config` -- `verification_required` hides judgements and runs from every
   list query (`j.verified = 1`), so a run against such an instance would poll
   an empty list until it gave up. Refuse by name.
2. `GET /judgehosts` -- zero active means submissions are stored and never
   judged. Refuse. More than one means timings come from different machines and
   the API offers no way to pin one: warn, do not refuse.
3. Ensure the `rbx-timing` contest exists, with an end time far in the future.
   The end time is load-bearing twice: past it, submissions are stored but never
   processed, and `RunController` filters the runs list on
   `s.submittime < c.endtime`.
4. Ensure the probe problem for this `RunPurpose` -- `rbxt-<hash>-estimation` or
   `-validation`. Two problems rather than one, because the purposes pin
   different limits and sharing one would re-upload on every alternation. That
   is the thrash `RunPurpose` exists to prevent.
5. Upload the probe package, then `DELETE` + `PUT` the link with
   `lazy_eval_results: 2`.

## 5. `run_solution`

One `POST /submissions` per solution (`problem`, `language`, `team_id=domjudge`,
source as `code[]`), dispatched on a background task so every solution is queued
while the report is still printing the first -- the reason the seam is per
solution rather than per testcase.

The N deferreds for a solution share one job, because `Deferred` memoizes each
deferred's own result and would otherwise submit N times.

Polling keys on `end_time` (§2.1), is bounded (a dead judging must fail rather
than hang), and writes chips into `RunProgress` as it goes.

## 6. Pairing runs to entries

DOMjudge gives a run an `ordinal` and no testcase name, so pairing is positional
-- and the position is *not* entry order. `_write_testcases` numbers samples and
secrets with separate counters, and DOMjudge orders `data/sample/*` before
`data/secret/*`, so the ordinal order is "every sample in entry order, then every
secret in entry order". Whenever a non-sample group precedes a sample one, that
differs from `entries`.

This is derivable exactly rather than guessed: the runner rebuilds the same
permutation the packager used and inverts it. On top of that, a run list whose
length does not match the entry count is **not paired at all** -- the solution
keeps its `max_run_time` and loses per-testcase detail. Silent misattribution is
the failure mode worth spending a guard on.

## 7. Capabilities

```python
RunnerCapabilities(
    measures_memory=False,           # absent from the API
    captures_artifacts=False,        # no .out/.err over HTTP
    reports_checker_messages=False,  # JudgingRunOutput is not serialized
    supports_nruns=False,            # one judging per submission
    supports_abort=False,            # batch backend, as with MOJ
    supports_sanitizers=False,       # the judge compiles the submission
    supports_unchecked=False,        # the judge always checks
)
```

DOMjudge has no memory-limit verdict -- an over-memory run surfaces as `RTE`, so
`MEMORY_LIMIT_EXCEEDED` is the one lossy verdict mapping. The packager already
documents this for `@EXPECTED_RESULTS@`.

## 8. Out of scope

- **Compile flags.** DOMjudge compiles submissions with an *instance-global*
  script; a package cannot ship one. The stock `cpp` script carries no `-std`,
  while rbx's default preset uses `-std=c++20`, so a C++20 solution can fail to
  compile on the judge. Detecting that needs `GET /executables/{id}` and a
  comparison rbx has no vocabulary for yet; for now a compile error is reported
  as what it is.
- **Contest teardown.** Staging is idempotent and reused across runs; removing
  the probe contest is a separate explicit action, never something a run does.
- **Interactive problems.** The packager supports `custom interactive`, but
  measuring an interactive solution's timing on DOMjudge is untested.
