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
   `sols/good/`, the `TLOVERRIDE` block `ctx.timelimit_override` asks for, and the
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
*pin exactly what this run asked to measure under* -- so the boolean `calibrate` flag
becomes a small mode object (`ProfilePinned` / `JudgeCalibrated` /
`ProbePinned(default_ms, per_rbx_language_ms)`). `ProbePinned` builds a `FixedTimeLimits`
and reuses `fixed_limit_lines` unchanged; `calibration_tl_seconds` then raises
`CALIBRATIONTL` to match on its own.

**Why a mapping and not one number.** This started as `UniformPinned(limit_ms)`, because
`ctx.timelimit_override` was a single cap. Splitting `rbx time` into two phases (#696)
changed the question rather than the answer:

- **Estimation** still asks for one number -- `inferenceTimeout`, the cap every accepted
  solution runs under -- so `ProbePinned` carries `default_ms` and nothing else, and the
  emitted `conf` has a single `TLOVERRIDE[default]`.
- **Validation** asks for `ceil(TL_lang x timeLimitToTle)`, **per language group**. That
  is the bound each slow solution has to clear, and it differs by language by
  construction, since the estimate assigns a different limit to each group.

So the honest thing is to emit what was asked for: one `TLOVERRIDE[<lang>]` per language
the run named, and `TLOVERRIDE[default]` for the rest. What must still never happen is the
thing `UniformPinned` was defensive about -- emitting the *`moj` profile's* per-language
entries alongside a cap this run chose, which would measure some languages under a limit
nobody asked for. `ProbePinned` cannot do that: it consults no profile, only
`ctx.timelimit_override`.

The default, when the run names several languages, is the **loosest** of them rather than
the tightest. Only a language the run did *not* name falls back to it -- and no solution
being measured is in one, since the mapping covers every language being run -- so being
generous there cannot truncate a measurement, while being stingy could.

**A rejected alternative: pin the loosest limit for everybody and compare locally.** A TLE
reports its real time unclamped (see the probe notes), so rbx could run every language at
`max(limits)` and decide the verdict itself. It is worse on both counts that matter. A
slow solution that *finishes* under the loose cap comes back WA or RE rather than TLE, and
`_record_validation_run` reads a non-slow bad verdict as "broke for another reason", so a
solution that is genuinely too slow would be reported as broken. And it costs judge time
on exactly the most expensive solutions, for nothing.

#### The language whitelist is load-bearing here

`.moj-meta.json`'s `languages` is the whitelist of submission languages, and **the API
rejects a submission outside it** -- a testrun included. The packager derives it from the
languages with an **ACCEPTED solution**, which is right for a real problem and wrong here:
a calibration-only package ships one accepted solution, so the whitelist would collapse to
that one language and every testrun of a solution in another language would be refused --
including, in the validation phase, the slow and wrong solutions, which are never accepted
by construction.

So the runner package emits the whitelist from the languages of **every solution in the
package**, not from the shipped ones -- and, deliberately, not from the ones *this batch*
tracks either. The two phases track disjoint solution sets: estimation tracks only the
accepted ones and validation only the ones expected to be too slow. A whitelist built per
batch would therefore differ between the phases even when the limits did not move, paying
an upload and a calibration for nothing; and where it happened to fingerprint equal, the
validation phase would be submitting slow solutions against the estimation phase's
accepted-only whitelist, which the API refuses. A language rbx cannot map to a MOJ id is
refused only when this batch actually runs a solution in it. The narrowing that protects a real problem's
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
5. Dispatch **one testrun at a time**. MOJ caps queued testruns per *account* and answers
   429 past it (waited out, since nothing can cancel a testrun); `moj testrun` cannot pick
   a judge, so two in flight may share one and inflate each other; and the park is shared.
   Dispatch stays eager, so the next testrun leaves the moment the previous finishes rather
   than when the report gets to it.

## The timing flow

`rbx time` runs in two phases (#696, #693), and the split is what decides how many times a
probe package is uploaded. The phases are not an rbx-time detail the runner can ignore:
they differ in *which* solutions run and in *what limit* they run under, and both reach
the runner as a plain `run_solutions` call with a different `timelimit_override`.

### Phase 1, estimation

- `timing._run_for_inference` runs **only the accepted solutions**, capped at
  `strategy.inferenceTimeout`, and passes that as `timelimit_override`. On the MOJ runner
  it becomes one `TLOVERRIDE[default]`, so the judge enforces the cap exactly as the
  sandbox does locally.
- Their timings feed `build_estimation_context` and the existing picker, unchanged.
- The solutions expected to be too slow are **not** run here. That is #696's central
  point: nothing bounds how long they take, so the only limit that could terminate them is
  a cap set for somebody else, and a measurement taken under it answers no question. On a
  shared judge park that also happens to be the expensive half of the run, so the MOJ
  runner gets the saving for free.

There is always a cap. `inferenceTimeout` is a property of the estimation rather than of
the multipliers and is resolved for both estimation modes (#695), so the formula-mode
refusal this design once specified is gone: the runner falls back to the configured
`inferenceTimeout` when a caller passes no override at all, and has nothing left to refuse.
The `-1` "no override" sentinel is still handled -- no `rbx time` phase passes it any more,
but any other caller of `run_solutions` may, and pinning it would emit
`TLOVERRIDE[default]=-0.001` and TLE every measurement.

### Phase 2, validation

- Runs **only the solutions expected to be too slow**, each at
  `ceil(TL_lang x timeLimitToTle)` -- `timing_validation.probe_limit` -- and aborts each at
  its first timeout.
- The limit is `timeLimitToTle x TL`, not the decided TL itself. A solution that is
  supposed to be too slow must be given just enough margin to *prove* it: killed at exactly
  the limit it only shows it was over; killed at the TLE bound it shows it was comfortably
  over, which is what the multiplier means.
- It is **per language**, because the estimate assigns a different limit to each language
  group. The probe pins one `TLOVERRIDE[<lang>]` each; see "A third timing mode" above for
  why the alternative -- one loose cap plus local arithmetic -- was rejected.
- The judge stops each solution at its **first timeout**, because the probe package sets
  `STOPWHEN_TLE=y`. rbx cannot do it: the local gate works by not dispatching the
  testcases after a timeout, and a testrun has already run everything by the time rbx
  looks. Without it, the solutions that are by construction the most expensive in the run
  cost a full testset each to answer a question one test settles. `STOPWHEN_WA`/`_RE` stay
  off, matching `abort_on`, which a WA does not trip either.
- A solution killed there is *confirmed* too slow; one that finishes *violates* the bound
  and hands over the real time. A violation re-opens the picker, so phase 2 may run
  **several times** in one command, at a different set of limits each time.
  `timing_validation.SlowKnowledge` is what keeps that cheap: a solution already killed at
  some limit is also killed at any lower one, and a measured one is answered by
  arithmetic, so only the solutions whose bound went up run again.

### Why the package is uploaded twice, and a problem per phase

This is the cost #696 makes unavoidable, and it is worth stating plainly rather than
rediscovering: **the two phases measure under different limits, and MOJ's limit lives in
the package**. `TLOVERRIDE` is emitted into `conf`, `conf` is inside
`_directory_fingerprint`, so within one command the validation phase re-uploads, and --
since the checksum moved -- very likely re-calibrates. Each extra picker round trip that
changes a limit costs another one.

**So each phase gets its own remote problem**: `<login>#rbxt-<slug>` for estimation and
`…-slow` for validation. On one shared problem the two evict each other -- whichever ran
last leaves its fingerprint recorded, so the next run's first phase always mismatches,
and the second then mismatches what the first just wrote -- which made the upload fast
path *unreachable in practice*. A problem each keeps both packages stable across runs, so
a second `rbx time` at the same limits uploads nothing at all. The id is a suffix on the
slug rather than a second prefix, so `is_rbxt_id` -- the guard against uploading over a
real problem -- keeps one marker; and it is derived rather than stored, so `.moj-id`
still holds the one id the `moj` CLI's own convention expects.

**Reaffirmed 2026-08-21, after the probe found that a TLE reports its time unclamped.**
That finding makes a one-upload alternative sound -- keep `TLOVERRIDE = inferenceTimeout`
for the whole session and recompute the phase-2 verdicts locally, since the real times come
back regardless. It was weighed and **rejected**, now for two reasons rather than one:

- A slow solution runs *to the cap on every test*, by definition. Letting it run to a 10s
  `inferenceTimeout` instead of dying at `timeLimitToTle x TL` multiplies the judge time of
  exactly the solutions that are already the most expensive, across the whole testset, on a
  shared two-judge park.
- `_record_validation_run` reads the judge's *verdict*, not only its timing. A slow
  solution that finishes under a loose cap comes back WA or RE rather than TLE, and a
  non-slow bad verdict is read as "broke for another reason" -- so a solution that is
  genuinely too slow would be reported as broken. Measuring at the real bound is what makes
  the judge's own verdict answer the question being asked.

So the wiring must surface progress during a wait that may run into minutes rather than
looking hung, and the testrun cache must survive across phases -- which it does: its key is
the package fingerprint plus the submitted bytes, so a phase-2 re-run at limits already
probed costs no judge time even though the package moved.

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

**In practice the park is homogeneous, which softens this a lot.** Observed 2026-08-21 via
`moj calibrate --judges`:

```
judge      Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz  online
judge-sp1  Intel(R) Xeon(R) CPU E5-2680 v4 @ 2.40GHz  online
```

Two judges, **the same CPU model**, both online (`moj status`: 2/2, 56 CPUs). So whichever
machine the server picks for a testrun, the timings are comparable, and the cross-host spread
this section warns about is currently near zero. Note what that does *not* mean: identical
CPU models still differ under load, thermal state and memory configuration, so this makes the
limitation tolerable rather than absent — and a park that gains a third, different machine
would silently reintroduce it. `--per-cpu` would today target exactly one judge, which is why
the cross-machine follow-up buys little right now.

## Incremental delivery

| # | Task | What ships |
|---|---|---|
| 0 | **Probe** a throwaway `rbxt-` problem on the live MOJ: does `testrun` require a prior calibration (and a prior `moj validate`); the `code` vocabulary; does the response name the host; is a submission outside `languages` really refused; does a `TLOVERRIDE`-only `conf` change force recalibration | notes + recorded JSON fixtures |
| 1 | Extract `SolutionRunner` / `RunContext` / `LocalRunner`; `run_solutions(runner=)` | pure refactor, no behavior change |
| 2 | `RunnerCapabilities`; audit every consumer of memory, artifacts and checker messages for `None`-tolerance | degradation is safe |
| 3 | `.moj-id` handling and a `moj` CLI wrapper (`whoami`, `upload`, `calibrate`, `check`, `testrun`, `testrun-status`) over `--json` | testable against the recorded fixtures |
| 4 | `MojPackager`: a `ProbePinned` timing mode, a calibration-only solution set, and the widened language whitelist | the package the runner uploads |
| 5 | `MojRunner.prepare` -- upload, calibrate, poll, already-calibrated fast path | `rbx time -p moj --runner moj` reaches a calibrated remote problem |
| 6 | `MojRunner.run_solution` -- testrun fan-out, verdict mapping, background task, concurrency cap | phase 1 end to end |
| 7 | Wire into `timing._run_for_inference` and `timing._validate_upper_bound`; the validation phase's re-upload at `timeLimitToTle x TL` | the full flow, both phases |
| 8 | Cache testrun results by (package checksum, solution digest, `TLOVERRIDE`) | re-runs cost no judge time |

**Task 8, as built.** The three terms the table names turned out to be two: `TLOVERRIDE`
is emitted into the package's `conf`, so it is already inside `_directory_fingerprint` --
which is also why the validation phase misses on every solution whose limit moved, exactly
as "Why the package is uploaded twice" above says it must. So the key is (package fingerprint, remote problem id, the
**amalgamated bytes** submitted, the submitted file name, a cache version). Not the source
path and not its mtime: amalgamation inlines headers, so the same path can be two
programs.

What is stored is the judge's own `TestrunStatus`, run-level verdict included, rather than
the `_TestrunResult` derived from it -- the derivation depends on which testcases the
current run asked about, and a hit goes back through the same `_result_from_status` as a
fresh response, which is what makes a hit and a miss produce identical `Evaluation`s.
Nothing that raises out of that derivation is written, so a `Compilation Error` and an
unrecognised verdict code are never cached; a WA or a TLE is, because it is a real
measurement of a solution that is supposed to fail.

It lives beside the upload record under `get_problem_cache_dir()`, for the same reason:
losing it must cost a redundant testrun, never a wrong measurement. **What it cannot see**
is what `prepare`'s fingerprint cannot see -- rbx has no way to ask MOJ which package a
problem currently holds, so another machine's upload (or a `moj upload` by hand) is
invisible to both -- plus the park itself: its hardware, its load, and which judge the
server picked. A cached timing is a measurement from whenever it was taken. No
`--no-cache` flag: the key covers everything rbx can observe, and for the blind spots the
honest fix is to delete the directory the cache-hit line names.

Task 0 gates 4 and 6; tasks 1 and 2 are independent of every MOJ-specific one and can land
first on their own merits.
