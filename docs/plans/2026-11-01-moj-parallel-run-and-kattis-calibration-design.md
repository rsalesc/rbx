# MOJ: parallel `rbx run`, and `rbx time` through MOJ's own Kattis calibration

Status: implemented on `worktree-moj-parallel-kattis-calibration`.

Two changes to the MOJ remote runner (`rbx/box/runners/moj/`), motivated by a
measurement of where `rbx run --runner moj` spends its time, and argued from live
experiments against the judge park on 2026-10-31.

## What was measured

Problem `arroz-e-feijao` (168 tests, batch, points), `sols/lalic-full.cpp`:

| | local (Apple M-series, 8 cores) | MOJ, serial probe | MOJ, parallel probe |
|---|---|---|---|
| sum of per-test times | 9.2 s | 41.0 s | 41.4 s |
| judge wall clock for the testrun (`duration_s`) | -- | 74 s | **29 s** |
| warm `rbx run`, end to end | 16.7 s | ~115 s | **67.6 s** |

- The CPU ratio (4.5x) is the hardware: the park is Xeon E5-2680 v4 @ 2.4 GHz.
- The wall-clock overhead beyond it was the probe's own `ALLOWPARALLELTEST=n`. The
  judge report said `1 teste(s) ao mesmo tempo x 1 CPU(s) por teste (CPUs: 14)`.
- Without it, the agent ran `4 teste(s) ao mesmo tempo x 1 CPU(s) por teste (CPUs:
  14|15|16|17)`: since mojtools 2026-09-24 the agent hands `build-and-test.sh` CPU
  groups and **pins each test to its own CPU**. Per-test times moved by 2.3 ms on
  average (max 20 ms). The old rationale ("56 CPUs, dozens competing, unpinned") is
  stale.
- Remaining fixed costs are MOJ's: ~5 s queue, ~20 s between the end of judging and
  the status reading `done` (the HTML report is generated after `TOTALTIME` is
  taken), and ~110-120 s of calibration on every package change, which the server
  forces before the first testrun even when rbx does not ask for it.

## Change 1: `rbx run` judges in parallel

`RunPurpose.RUN` exists to get **verdicts**, the ones a real submission would get.
Only `ESTIMATION` and `VALIDATION` measure. So the probe's parallelism becomes a
property of the purpose:

| purpose | `ALLOWPARALLELTEST` | `TLERERUN` | why |
|---|---|---|---|
| `ESTIMATION`, `VALIDATION` | `n` | `n` | unchanged: a measurement |
| `RUN` | `y` | `y` | judged exactly as a student submission is |

Both are emitted **explicitly** for `RUN` rather than left to MOJ's defaults, so a
changed upstream default never changes what a package does. `ProbePackage` grows a
`judge_in_parallel: bool` field (default `False`, so every existing caller keeps
measuring); the runner sets it from `ctx.purpose`. The `-run` problem is already
separate from the timing ones, so only it re-uploads.

### The TLE rerun, and duplicate entries

Live, with `fernando-fib.cpp` (expected TLE) on the parallel probe, `TLERERUN=y`:

- 168 tests, **169** entries in `tests[]`. 137 tests TLE'd.
- Exactly **one** test was rerun: `t01_subtask2_001`, the first TLE in the final
  loop's name order. Its second entry is **appended at the end** of `tests[]`.
- Then the rerun stayed TLE, and `build-and-test.sh:710` latched `TLERERUN=n`: no
  later TLE got a second chance.
- Both entries carry `time: 8.20`, the `ETL` kill (`2 + TL + 0.2`); the time comes
  from the per-test timelog file, which the rerun overwrites, so the first entry
  cannot be trusted to hold the parallel measurement either.

The final loop (`build-and-test.sh:673-715`, mojtools `c5d2a64`) also re-applies
`STOPWHEN_*` in order over the final verdicts and runs serially any test the
parallel pool skipped because of a stop that the rerun then cleared. So under
`--fail-fast` a parallel run still stops at the first failure *in name order*, and
the tests after it never get a verdict (they come back absent, i.e. `SKIPPED`).

rbx already reads repeated names last-entry-wins (`TestrunStatus.by_name`), which is
the value the judge itself keeps. What changes is that this now happens on every
`rbx run` with a TLE, not only in a corner case, so the tests pin the observed shape:
the duplicate is appended after every other entry, keeps its verdict whatever it is,
and never inflates the count of expected or missing testcases.

`TLERERUN=y` is kept rather than `n` because it is what real judging does: a TLE
caused by contention gets the serial second chance a student would get. With CPU
pinning that is rare, and it costs one extra run of one test per solution.

## Change 2: `rbx time` with multipliers asks MOJ to calibrate

### When

Only when **both** hold:

- the runner is `moj`, and
- the resolved timing strategy uses **multipliers** (`TimingStrategy.uses_multipliers`).

A formula strategy keeps today's two-phase testrun path unchanged. Multipliers are
exactly MOJ's Kattis method (mojtools `tl-methods.sh`, spec 2025-09 "Problem
timing"):

| rbx (`timing.multipliers`) | MOJ `conf` | MOJ range |
|---|---|---|
| `acToTimeLimit` | `KATTIS_AC_TO_TIME_LIMIT` (a) | 1..100 |
| `timeLimitToTle` | `KATTIS_TIME_LIMIT_TO_TLE` (b) | 1..100 |
| `timeResolution` (ms) | `KATTIS_TIME_RESOLUTION` (r, seconds) | 0 < r <= 10 |

`TLKATTIS[lang] = ceil(a * W[lang] / r) * r` (at least r), with `W[lang]` the worst
accepted test time over `sols/good` in that language. rbx's multipliers estimate is
`step_up(ceil(a * W_ms), timeResolution)`, the same number. A multiplier outside
MOJ's range is refused before anything is uploaded, naming the field.

### The calibration package

A third probe shape, `ProbeCalibrated`, built by the same `MojPackager`:

- `sols/good/`: every `InferenceRole.LOWER` solution.
- `sols/slow/`: every `InferenceRole.UPPER` solution, when `timeLimitToTle` is set.
- `conf`: no `TLOVERRIDE` (calibration ignores it anyway, `MOJ_CALIBRATING=1`);
  `TLMETHOD=kattis` and the three `KATTIS_*` values; `CALIBRATIONTL` from
  `inferenceTimeout` (the cap the accepted solutions run under, exactly as the local
  estimation phase caps them); `STOPWHEN_TLE=y` (a slow solution's first timeout
  settles its question, as the local abort does).
- `languages`: the languages of the shipped solutions.

It goes to its own remote problem, `<login>#rbxt-<slug>-kattis`, so it never evicts
the testrun probes' fingerprints.

### What calibration does (observed)

`contando-mex`, 91 tests, 5 good + 4 slow solutions, `moj calibrate --all-judges`:

- 3 hosts, concurrently; the whole thing took **~2 min** (upload 9 s).
- Phase 1, the good solutions, in parallel **lanes** (one per CPU group), each
  running its tests one at a time. `W = 0.26 s`, `TLKATTIS[cpp] = 0.6` on every
  host; `time_limits_by_method.kattis.calibrated` is the max across judges.
- Phase 2, the slow solutions, judged against the **new** table. Each stopped at its
  first TLE (24 of 91 tests), killed at `ETL = 2 + 0.6 + 0.2 = 2.8 s`, and MOJ itself
  reported `expect: ok/tle, ratio 4.67, need 1.5`.

### Reading it back

`moj --json calib <id>` per host, per solution, per test `{name, code, time, tl}`.
Only hosts whose `version` equals the top-level `checksum` count (a host that
calibrated an older package is still listed).

- **Accepted solutions** feed `_EstimationContext.lower_timings` directly:
  `lower[rbx_lang][path] = max over fresh hosts of max over tests of round(time *
  1000)`. Any non-AC verdict on a good solution is an error, as the local estimation
  phase makes it (a TLE names `inferenceTimeout`).
- **Slow solutions** seed `SlowKnowledge`. Its worst test over all tests and hosts
  is `t`; then `record_timeout(path, t)` when it timed out (`TLE` anywhere), else
  `record_time(path, t)` when it ran every test, else nothing (truncated without a
  timeout: unmeasured). Any other bad verdict is reported as broken, as
  `_record_validation_run` does.
- The rest of `rbx time` is reused as is: the picker, groups, `whenEmpty`, the
  profile, `upperValidation`. With each language its own group the limit rbx writes
  is MOJ's `TLKATTIS[lang]`; pooling languages takes the max, which is what the
  formula yields too. rbx compares its number to MOJ's for every language it
  estimated and **warns** on a mismatch, keeping MOJ's.

### What feels different

- **No per-solution live report and no testruns.** One barrier: upload, calibrate,
  read. The report is a table per solution (worst time per host, verdict), printed
  from the calibration, and `--share` shares that table.
- **The upper bound is checked once, at MOJ's own limit.** The slow solutions ran
  against `TLKATTIS`, killed at `ETL = TL + 2.2 s`. A slow solution is confirmed when
  that kill time reaches `ceil(TL * b)`. For TL > `2.2 / (b - 1)` (4.4 s at
  b = 1.5) it cannot, and if the picker regroups to a limit above what calibration
  measured, the slow solutions are reported **unverified** (`upperValidation.skipped`)
  with a warning, never re-run by testrun. Regrouping is free; it costs no judge time.
- **`--run-all` still works**, as testruns on the `-run` problem, now in parallel.
- **Cache:** the fast path is the existing fingerprint record. An unchanged package
  that the judge reports calibrated is read back without recalibrating.

### Freshness

`moj check` right after `moj calibrate` can still describe the *previous* calibration.
`is_ready` is therefore not enough: rbx also requires every fresh host's `at` to be
newer than what it recorded before queueing, and refuses a calibration whose
`checksum` is not the uploaded package's.
