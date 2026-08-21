# Remote solution runners, and MOJ as the first one

Issue: [#689](https://github.com/rsalesc/rbx/issues/689).

`rbx time` decides a time limit from timings measured **where rbx runs**. The well-lit
path is therefore to walk to the judge machine and run it there. This design keeps that
path untouched and adds a second one: measure the timings **on the judge park itself**,
through the judge's own CLI, and feed them into the estimation logic rbx already has.

MOJ is the motivating case. The seam is deliberately general, because `rbx run` wants the
same thing later.

## What the MOJ CLI actually offers

Read from [`cd-moj/moj-cli`](https://github.com/cd-moj/moj-cli) (`moj`, build
`c2716d8-20260820`). More is available than the issue assumes:

| Command | What it gives |
|---|---|
| `moj testrun <id\|dir> <file> [--no-wait]` | Runs **one standalone solution on the judge** -- same jail, same calibrated TL as a real submission -- outside history/placar. Returns `{run}`. Requires **edit** permission (the result exposes hidden tests). |
| `moj testrun-status <run>` | `{status, verdict, correct, total_tests, duration_s, tl_used, tests: [{name, code, time, tl}]}` |
| `moj calibrate <id> [--hosts h1,h2 \| --all-judges \| --per-cpu]` | Queues calibration. Repeating does not duplicate (`already_queued` per host). |
| `moj calibrate --judges` | The park: `{host, cpu, online}`. |
| `moj calib <id> --json` | The whole calibration by extension: **per host**, per solution dir (`good/pass/slow/wrong`), per test `{name, code, time, tl}`. |
| `moj --json check <id>` | `{validation, calib, tl}`; `tl.calibrated`, `tl.being_calibrated`, `tl.needs_recalibration`, `tl.tl_override`. **`--json` is a global flag and goes before the subcommand**, not after. |
| `moj upload <id> <dir>` | Tars the directory itself and uploads. |
| `moj whoami` | The login. |

### Confirmed from the CLI source

The repo is not readable anonymously (`raw.githubusercontent.com` 404s), so these were read
through the authenticated contents API, from `moj` and `lib/core.sh`. Recording them here
so nobody re-derives them:

- **`moj whoami` does not honour `--json`.** It prints `login: <x>  nome: <y>` and the login
  must be parsed out of that line (`cmd_whoami`).
- **A session-less command exits non-zero and writes to stderr.**
  `need_login(){ [[ -f "$(token_file)" ]] || die "faça '$MOJ_TOOL login' primeiro."; }` and
  `die(){ printf '%s: %s\n' "$MOJ_TOOL" "$*" >&2; exit 1; }`. So a wrapper that captures
  only stdout loses the reason.
- **`moj testrun --no-wait` prints prose, not JSON, even under `--json`.** It returns at
  `cmd_testrun`'s `[[ "$wait" == 1 ]] || { ...; return 0; }` — *before* the `RAW` branch
  inside the polling loop — after `echo "enfileirado no juiz: run $run  (...)"`. The run id
  has to be parsed out of that line. Passing `--json` to `testrun` therefore buys nothing.
- **`moj --json testrun-status` is real JSON**, carrying `status`, `verdict`, `correct`,
  `total_tests`, `duration_s`, `tl_used` and `tests[].{name,code,time,tl}`.
- **The CLI's own wait is bounded and knows only one terminal state.** `cmd_testrun` loops
  200 times at 3s (~10 minutes) testing `[[ "$st" == done ]]`, then gives up and tells the
  user to check later. It handles no failure status. So `MojRunner`'s poll needs its own
  bound — a judge that never reaches `done` must not hang the run — and **whether the
  server can report a terminal failure state is still an open probe question**.

Two facts shape the design:

- **`moj testrun` accepts a directory containing `.moj-id`** in place of an id
  (`cmd_testrun` reads `"$ref/.moj-id"`). So binding an rbx package to a remote problem
  through that file is the CLI's own convention, not an invention.
- **`TLOVERRIDE` in `conf` beats the calibrated TL**, per language, and `moj check`
  surfaces it as `⚙ TL OVERRIDE (vence o calibrado)`. **rbx already speaks it**:
  [#685](https://github.com/rsalesc/rbx/pull/685) replaced the old slope-zero
  `TLMOD[calibrafactor]` pinning with `TLOVERRIDE[default]`, per-language entries and a
  `CALIBRATIONTL` floor
  ([`packaging/moj/timing.py`](../../rbx/box/packaging/moj/timing.py)). The runner
  therefore needs no new emission machinery -- only a way to ask for a limit that is not
  the `moj` profile's.

## The seam: `SolutionRunner`

Today [`solutions.py`](../../rbx/box/solutions.py) splits cleanly already:
`run_solutions` calls `_get_report_skeleton` (compile + testcase layout) and then
`_produce_solution_items`, which calls `_run_solution` once per (solution, group) and gets
back `List[Deferred[Evaluation]]` -- one deferred per testcase.

The backend seam goes at exactly that grain, **per solution**, because that is MOJ's grain:
one testrun judges a solution against every test at once.

**As built** (Tasks 1-2; this replaces the sketch this section originally carried, which
differed in three ways worth knowing about -- see below):

```python
@dataclasses.dataclass(frozen=True)
class RunnerCapabilities:
    measures_memory: bool = True             # TestcaseLog.memory
    captures_artifacts: bool = True          # .out / .err / .log beside the .eval
    reports_checker_messages: bool = True    # CheckerResult.message
    supports_nruns: bool = True
    supports_abort: bool = True              # can SAVE the work of a skipped testcase
    supports_interactive: bool = True
    supports_sanitizers: bool = True


class SolutionRunner(Protocol):
    name: str
    caps: RunnerCapabilities

    async def prepare(self, ctx: RunContext) -> None: ...
    def run_solution(self, solution, entries, ctx: RunContext) -> List[Deferred[Evaluation]]: ...
```

`RunContext` carries the skeleton, the checker and interactor digests, `verification`,
`timelimit_override`, `nruns`, `abort_on`, and the progress handle.

Three corrections the implementation forced, each of which would have broken `MojRunner`:

1. **`run_solution` is called once per SOLUTION, with the whole testset flattened in group
   order.** The first cut kept `_produce_solution_items`' group loop and called the runner
   inside it -- which is per *group*, and would have fired one `moj testrun` per group per
   solution while the docstring above claimed otherwise.
2. **There is no `finalize`.** It fired inside a `finally` around item production, which
   only *builds* thunks -- so it ran before a single deferred resolved, and would have torn
   a remote session down before the first result was fetched. Nothing needs it: the remote
   problem is persistent by design (`.moj-id` is committed and reused), so a half-calibrated
   problem is the next run's starting point, not garbage. A correctly-timed teardown hook
   can be added when something actually needs one.
3. **The abort/skip gate is not the backend's job.** `_gated_evaluation` in `solutions.py`
   wraps each returned deferred *when the run asks for `abort_on` and the backend declares
   `supports_abort`*; a run without `abort_on` gets the backend's deferreds unwrapped, which
   is a deliberate guarantee pinned by a test. Otherwise every backend would re-implement
   `_AbortGate` correctly or silently lose the abort -- and a batch backend would have a
   real judge verdict overwritten with `SKIPPED`.

### The deferreds do not change

This is a requirement of the issue and it falls out naturally. `MojRunner.run_solution`
starts the remote work **in the background immediately** and hands back deferreds that all
await the same job:

```python
def run_solution(self, solution, entries, ctx):
    job = asyncio.create_task(self._submit_and_poll(solution))   # queued on the judge now
    return [Deferred(lambda e=e: self._slice(job, e)) for e in entries]
```

Slice by MOJ **test name**, never by position -- see `run_solution()` below.

Two mechanics this sketch glosses over, both found while reviewing the branch:

- **`Deferred` will not memoize the shared job for you.** `Deferred.__call__`
  ([`deferred.py`](../../rbx/box/deferred.py)) memoizes each deferred's *own* result with a
  bare `if self.cache is None` and no lock. N deferreds over one submission need `MojRunner`
  to hold the job itself (an `asyncio.Task`, awaited by all of them) -- which the sketch does,
  but nothing in `Deferred` enforces it.
- **`MojPackager.package()` writes a `.zip` into `build_path` and returns its path**, while
  `moj upload` wants a *directory*. The runner uploads the directory and should not leave the
  stray archive behind.

Consumption order is unchanged, so the report streams exactly as it does locally; but every
solution is already sitting in the judge queue while the first one is still being printed.
This is why the estimation loop uses `testrun` per solution rather than reading one
`moj calib --json`: calibration would be a single barrier, testrun gives incremental progress.

### Degrading when the backend knows less

A remote runner cannot report everything a sandbox can. `RunnerCapabilities` makes the gap
explicit so the consumers can be audited once rather than discovered by crash:

- **memory** -- `TestcaseLog.memory` is already `Optional`, and
  `_get_evals_memory_in_bytes` already returns `Optional[int]`. MLE detection and the
  limits columns need auditing.
- **artifacts** -- no `.out` / `.err`. `_record_skipped_evaluation` already establishes the
  precedent: write the `.eval` only, and let the log viewer render "(does not exist)".
  Never write an empty file that claims the run produced no output.
- **checker message** -- MOJ judges with the packaged checker and returns a code, not a
  message. `CheckerResult.message` says it was judged remotely.
- **`nruns > 1`** -- each testrun is one run. Either N submissions, or refuse with a clear
  message. Refusing is the default; judge time is a shared resource.
- **`abort_on`** -- a testrun has already run every test by the time rbx sees it, so the
  abort saves nothing and is ignored. Nothing may assume `SKIPPED` evaluations appear.
  That sentence is only true because the probe package **suppresses `STOPWHEN_*`**
  (`_stopwhen_lines`): a BINARY problem would otherwise ship `STOPWHEN_WA/TLE/RE=y`,
  and `build-and-test.sh` checks those before the `RUNALL` guard -- so the first
  failure of a slow or wrong solution, which fails by construction, would break out of
  the loop and return a *prefix* of the tests. Nothing is judged on a probe, so the
  judge-time saving buys nothing to weigh against the lost timings.

### Selecting a runner

An explicit `--runner` flag, with an optional per-profile default in `env.rbx.yml`:

```console
$ rbx time -p moj --runner moj
```

```yaml
# env.rbx.yml
runners:
  moj:
    type: moj
    concurrency: 2
profiles:
  moj: {runner: moj}
```

The flag rather than the profile name, because a limits profile is just the
`limits/<name>.yml` file `rbx time` *writes*; making its name select a backend would couple
an output to a transport, and would leave no way to estimate MOJ limits on a local machine.
The same flag is what `rbx run --runner moj` will use later.

## The MOJ runner

### `prepare()`

1. `moj whoami` -> the login. Not logged in is a hard error naming `moj login`; the CLI's
   session is reused, rbx never handles credentials.
2. Read-or-create `.moj-id` at the **rbx package root**, git-tracked, holding
   `{"id": "<login>#rbxt-<problem-id>"}`. Committing it is what makes two setters on the
   same problem reach the same remote problem instead of each orphaning one on the server.
3. Build a MOJ package with `MojPackager`, carrying **only the model solution** in
   `sols/good/`, a **uniform** `TLOVERRIDE` taken from `ctx.timelimit_override`, and the
   full submission-language whitelist (see below).
4. `moj upload <id> <dir>`.
5. `moj calibrate <id>`, then poll `moj --json check <id>` until it is ready -- which is
   `calibrated and not being_calibrated and not needs_recalibration`, the third clause
   included because an upload that moved the checksum leaves a *stale* calibration that
   still reports `calibrated: true`. `MojCheck.is_ready` is that predicate. Skipped
   entirely when the problem is already ready.

**The uploaded package never has to contain the solutions being timed.** `moj testrun`
takes the source in the request body, and calibration only needs one `good/` solution to
succeed at all. So a whole session is one upload and one calibration however many solutions
get measured -- which is also why the package can stay minimal.

#### A third timing mode, not a new one

`_time_limit_lines` today refuses to guess between two modes: the `moj` limits profile
pins the limits, or `--calibrate` hands them to the judge. The runner needs a third --
*pin every language to one explicit number* -- so the boolean `calibrate` flag becomes a
small mode object (`ProfilePinned` / `JudgeCalibrated` / `UniformPinned(limit_ms)`).
`UniformPinned` builds `FixedTimeLimits(base_ms=limit_ms, per_language_ms={})` and reuses
`fixed_limit_lines` unchanged; `calibration_tl_seconds` then raises `CALIBRATIONTL` to
match on its own.

The limit must be **uniform across languages**, which is why this is not just
`_fixed_time_limits` with a different profile. `ctx.timelimit_override` is a single cap --
the inference timeout, or `timeLimitToTle x TL` -- and emitting the profile's per-language
`TLOVERRIDE` entries alongside it would silently measure some languages under a *tighter*
cap than rbx asked for, quietly truncating exactly the timings the estimate rests on.

#### The language whitelist is load-bearing here

`.moj-meta.json`'s `languages` is the whitelist of submission languages, and **the API
rejects a submission outside it** -- a testrun included. The packager derives it from the
languages with an **ACCEPTED solution**, which is right for a real problem and wrong here:
a calibration-only package ships one accepted solution, so the whitelist would collapse to
that one language and every testrun of a solution in another language would be refused --
including, in phase 2, the slow and wrong solutions, which are never accepted by
construction.

So the runner package emits the whitelist from the languages of **every solution rbx may
testrun**, not from the shipped ones. The narrowing that protects a real problem's
submission surface buys nothing on a private, throwaway `rbxt-` problem.

Relatedly, MOJ picks the language from the **file extension** of the uploaded source
(`moj testrun` sends `filename: basename(sol)`), so the amalgamated file must carry the
right one.

### `run_solution()`

1. Amalgamate the solution to a single file. MOJ compiles a submission from one file, and
   the packager already does this for the solutions it ships.
2. `moj testrun <dir> <file> --no-wait`, and parse the run id out of the prose it prints.
   **No `--json`** -- see "Confirmed from the CLI source": `--no-wait` returns before the
   JSON branch, so the flag buys nothing and the id has to be read from the text.
3. Poll `moj --json testrun-status <run>` until `status == "done"`.
4. Map each `{name, code, time, tl}` onto an `Evaluation`. Tests are paired **by name**
   through [`packaging/moj/naming.py`](../../rbx/box/packaging/moj/naming.py), the same
   module that named them into the package -- never by position, so a naming change can
   never silently misattribute a timing.
5. Cap the in-flight testruns (`concurrency`, default 2). The judge park is shared.

## The timing flow

Phase 1, estimation:

- `timing._run_for_inference` already computes an `_InferenceCap` and passes
  `timelimit_override=cap.timeout`. On the MOJ runner that becomes `TLOVERRIDE`, so the cap
  is enforced by the judge exactly as the sandbox enforces it locally.
- The lower-bound and upper-bound solutions are testrun; their timings feed
  `estimate_time_limit` and the existing picker unchanged.

### What to pin when there is no cap

`timing.py` passes `timelimit_override=-1` -- the "no override" sentinel -- whenever
`_InferenceCap` is `None`, which is every problem with no `timeLimitToTle` multiplier and
every problem with no upper-bound solution. That is not an edge case, and **MOJ always
enforces a time limit**, so "unlimited" is not expressible in a probe package the way it is
in the local sandbox. `UniformPinned` rejects `<= 0` rather than emitting `TLOVERRIDE=-0.001`,
so the runner has to decide. It decides like this:

1. A cap exists -> pin `cap.timeout`.
2. No cap, but the environment configures `timing.multipliers` -> pin its `inferenceTimeout`
   (`schema.py:858`, `gt=0`, default 10s). Its own description is "the time limit enforced on
   solutions while estimating", which is exactly the question being asked; the "only used
   when `timeLimitToTle` is set" clause is about the *upper bound*, not about how long rbx is
   willing to wait.
3. No multipliers at all -- a problem estimating with a **formula** -- **refuse**, naming
   `timing.multipliers.inferenceTimeout` in `env.rbx.yml` as the thing to set.

Refusing in case 3 rather than inventing a number is the same call `rbx package moj` already
makes when `--calibrate` needs an `acToTimeLimit` a formula does not define.

Phase 2, validation:

- Re-upload with **`TLOVERRIDE = timeLimitToTle x decided TL`**, not the decided TL itself.
  A solution that is supposed to be too slow must be given just enough margin to *prove*
  it: killed at exactly the limit, it only shows it was over; killed at the TLE cap, it
  shows it was comfortably over, which is what the multiplier means. Correct solutions are
  unaffected -- they finish far below either.
- Testrun the remaining solutions (the ones `rbx time` already runs) at that cap, and judge
  every measured time against the decided TL.

Changing `conf` moves the package checksum, so phase 2's upload very likely forces a second
calibration wait. Whether a `TLOVERRIDE`-only change really does -- given that `TLOVERRIDE`
overrides the calibrated TL anyway -- is a probe item below, and the answer decides whether
phase 2 costs a wait or is nearly free.

## Known limitation: the judge is not selectable

`moj calibrate` targets judges (`--hosts`, `--per-cpu`, `--all-judges`, and `--judges`
lists host + CPU + online). **`moj testrun` does not**: `cmd_testrun` posts only
`{id, filename, code_b64}` to `/problems/test-run` and the server picks the machine. On a
heterogeneous park that is timing noise rbx cannot control, and a time limit must be safe on
the *slowest* judge.

`moj calib --json` does report per-host timings, for every solution dir. So the escape hatch
exists: one `moj calibrate --per-cpu` with the full solution set gives cross-machine data.
This design does not use it, because it is a single barrier and loses the incremental
progress that motivated testrun in the first place. It is the natural follow-up once the
runner works, and is called out here so the limitation is not rediscovered later.

## Incremental delivery

| # | Task | What ships |
|---|---|---|
| 0 | **Probe** a throwaway `rbxt-` problem on the live MOJ: does `testrun` require a prior calibration (and a prior `moj validate`); the `code` vocabulary; does the response name the host; is a submission outside `languages` really refused; does a `TLOVERRIDE`-only `conf` change force recalibration | notes + recorded JSON fixtures |
| 1 | Extract `SolutionRunner` / `RunContext` / `LocalRunner`; `run_solutions(runner=)` | pure refactor, no behavior change |
| 2 | `RunnerCapabilities`; audit every consumer of memory, artifacts and checker messages for `None`-tolerance | degradation is safe |
| 3 | `.moj-id` handling and a `moj` CLI wrapper (`whoami`, `upload`, `calibrate`, `check`, `testrun`, `testrun-status`) over `--json` | testable against the recorded fixtures |
| 4 | `MojPackager`: a `UniformPinned` timing mode, a calibration-only solution set, and the widened language whitelist | the package the runner uploads |
| 5 | `MojRunner.prepare` -- upload, calibrate, poll, already-calibrated fast path | `rbx time -p moj --runner moj` reaches a calibrated remote problem |
| 6 | `MojRunner.run_solution` -- testrun fan-out, verdict mapping, background task, concurrency cap | phase 1 end to end |
| 7 | Wire into `timing._run_for_inference`; phase 2 upload at `timeLimitToTle x TL` and the remaining solutions | the full flow |
| 8 | Cache testrun results by (package checksum, solution digest, `TLOVERRIDE`) | re-runs cost no judge time |

Task 0 gates 4 and 6; tasks 1 and 2 are independent of every MOJ-specific one and can land
first on their own merits.
