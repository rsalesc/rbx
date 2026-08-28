# What the live MOJ actually answers

Task 0 of [the MOJ remote-runner plan](2026-08-20-moj-remote-runner.md), run 2026-08-21
against `moj.naquadah.com.br` (server build `c2716d8-20260820`) as `rsalesc`.

**Method.** No problem was created and nothing was uploaded. `moj testrun` runs *outside*
history and placar and modifies nothing, so four testruns were issued against an existing,
already-calibrated problem the account owns (`rsalesc#delete` — 72 tests, cpp TL 0.614s):
its own reference solution for `AC`, and three deliberately broken one-file programs for
`WA` / `RE` / `TLE`.

---

## 0. `moj testrun` did not work on macOS at all — FIXED UPSTREAM, 2026-08-21

**Resolved the same day.** The fix is merged and released: build **`b6b0c21-20260821`**
replaces the broken encode with the portable helper —

```sh
_b64enc "$sol" > "$b64f"          # -w0/arquivo-posicional são GNU: no BSD as DUAS pontas falham
```

— and `moj update` picks it up. Verified here afterwards, **without any shim**:
`moj testrun rsalesc#delete wa.cpp --no-wait` → `enfileirado no juiz: run 383fd4cc…`.
So the MOJ runner is exercisable end-to-end on macOS from this build onward. The rest of
this section is kept as the record of what was wrong and how it was found.

---

**This blocked the whole feature for any setter on a Mac, including the author of rbx.**

`cmd_testrun` encodes the submission with

```sh
base64 -w0 "$sol" > "$b64f" 2>/dev/null || base64 "$sol" | tr -d '\n' > "$b64f"
```

BSD `base64` (macOS) has **no `-w`** *and* **rejects a positional file argument** — it
requires `-i <file>`. So the first branch fails, the fallback fails too, and the command
dies before it ever reaches the network:

```
base64: invalid argument /path/to/wa.cpp
Usage:	base64 [-Ddh] [-b num] [-i in_file] [-o out_file]
```

The fix is to redirect rather than pass the file — and `moj` already ships a portable helper
for exactly this, `_b64enc` in `lib/core.sh` (`base64 -w0 < "$1" || base64 < "$1" | tr -d '\n'`),
which `cmd_testrun` simply does not use.

Filed upstream as [`cd-moj/moj-cli#1`](https://github.com/cd-moj/moj-cli/pull/1) and merged
the same day; see the banner above. Note `moj update` re-fetches the server's build, so it
both delivers this fix and **undoes any local patch** applied while waiting for it.

The probe below was taken *before* the fix, by putting a small `base64` shim ahead of the
real binary on `PATH` — a debugging aid, never a shipping strategy, since rbx must not ship
a workaround for another tool's bug. The findings are unaffected: the shim only changed how
the source got encoded, not what the judge did with it.

---

## 1. The run id is a 32-character hex digest, not a number

```
enfileirado no juiz: run d89e6b7735c675fd7b50b3354ba64097  (wa.cpp contra rsalesc#delete)
```

Four for four: `d89e6b77…`, `6ac43642…`, `a3325da0…`, `d908d1cb…`.

**`cli.py`'s `_RUN_ID_RES` uses `(\d+)` and therefore refuses every real run id.** It fails
loudly rather than truncating — which is the behaviour we designed for, and it is why this
was caught in one command rather than as a 404 later — but it is wrong and must widen to
`[A-Za-z0-9_-]+`, the alternative the code comment already names. The design doc's claim
that "the CLI's `$run` is numeric in every example" was my inference, not an observation.

The surrounding prose is exactly as parsed: `enfileirado no juiz: run <ID>  (<file> contra <id>)`.

## 2. The response **does** name the judge host

`host = 'judge-sp1'` on every completed run. The design doc's "Known limitation: the judge
is not selectable" said testrun does not report one. It does — so a run's timings can be
attributed to a machine after the fact even though the machine cannot be *chosen*, and a
cross-host comparison is checkable rather than merely hoped for.

(The park is currently homogeneous anyway — two `Intel Xeon E5-2680 v4 @ 2.40GHz`, both
online — and only `judge-sp1` had calibrated this problem.)

## 3. `verdict_canon` is the field to map from

| solution | `verdict` | `verdict_canon` | per-test `code` |
|---|---|---|---|
| reference | `Accepted,100p` | `Accepted` | `AC` |
| constant output | `Wrong Answer,0p` | `Wrong Answer` | `WA` |
| `abort()` | `Runtime Error,0p` | `Runtime Error` | `RE` |
| infinite loop | `Time Limit Exceeded,0p` | `Time Limit Exceeded` | `TLE` |

`verdict` carries the score suffix (`,100p`); **`verdict_canon` does not** and is the stable
one. Per-test `code` uses the short forms above. `MLE` / `OLE` / `PE` / `JE` were not
provoked and remain unconfirmed — Task 6's mapping must therefore treat an unknown code as
*unknown*, not silently coerce it.

### 3c. `RE_NZEC` — observed 2026-08-29, from a user's run

A real `moj testrun` came back with the per-test `code` `RE_NZEC`, and rbx refused it as an
unknown code, failing the whole run. It is the qualified spelling of the `RE` already in the
table: a non-zero exit code is a runtime error.

`_OUTCOME_BY_MOJ_CODE` gained the entry, and `_outcome_for_moj_code` reads any `RE_*` code as
`RUNTIME_ERROR` — the prefix names the family, so unobserved members (`RE_SIGSEGV` and the
like) carry no guess about the outcome. Everything outside the family is still refused by
name; the reason for refusing — a wrong outcome silently corrupting the time-limit estimate —
does not apply to a code that already says it is a runtime error.

### 3b. `Compilation Error` — observed 2026-08-21, by accident

The first end-to-end `rbx time --runner moj` submitted solutions that did not build on the
judge, and every testrun came back:

```json
{"status": "done", "verdict": "Compilation Error", "verdict_canon": "Compilation Error",
 "correct": 0, "total_tests": 0, "tests": []}
```

So `Compilation Error` joins the confirmed `verdict_canon` vocabulary — **as a run-level
verdict, never as a per-test `code`**. There is no per-test anything: a submission that does
not compile never reaches the testset, so the `tests` array is empty and `CE` was *not*
observed in the `code` position. `_OUTCOME_BY_MOJ_CODE` therefore still has no `CE` entry,
and should not grow one on this evidence.

What rbx said about it was `MOJ reported no result for 6 of 6 testcases ... Those testcases
are left unmeasured` — true, useless, and pointing at the wrong thing entirely. See section
7b for the shape that tells this apart from a truncated run.

## 4. `STOPWHEN_*` really does truncate a testrun — the Task 4 fix was necessary

| run | `correct`/`total_tests` | test entries returned |
|---|---|---|
| AC | 72 / 72 | **72** |
| WA | 0 / 72 | **4** |
| RE | 0 / 72 | **4** |
| TLE | 0 / 72 | **5** |

A failing solution comes back with a handful of tests out of 72, because this problem's
`conf` sets `STOPWHEN_WA/TLE/RE=y` and `build-and-test.sh` breaks out of the loop.

This was flagged during Task 4 review as *plausible but unexamined*, and the probe package
was changed to suppress `STOPWHEN_*` on suspicion. **It is real.** Without that change,
phase 2 — which times the slow and wrong solutions, the ones that fail by construction —
would have measured 4 tests out of 72 and reported the result as a complete timing vector.

## 5. The `tests` array is not ordered

AC run, first three entries: `['t01_handmade_002', 'sample2', 't01_handmade_001']`. Not
lexicographic, not authored order. Tests run in parallel (56 CPUs across the park) and
results come back as they finish.

**Pairing by name is therefore load-bearing, not stylistic.** Pairing by position would
misattribute essentially every timing. This is what `MojPackager.testcase_names()` exists
for.

## 6. A TLE reports its real time, not the limit

`{'name': 'sample1', 'code': 'TLE', 'time': 2.81, 'tl': 0.614}` — ~4.6× the limit, not
clamped to it. Useful for phase 2: a solution killed at the cap still reports how far over
it was. The exact kill threshold was not determined.

## 7. Shape while still running

```json
{"status": "queued", "run": "...", "filename": "...", "lang": "cpp",
 "login": "rsalesc", "problem_id": "rsalesc#delete", "requested_at": ..., "success": true}
```

**No `tests` key at all** while queued — `TestrunStatus` already assumes this. Only
`status == "done"` carries results. No terminal *failure* status was observed, so the
question "can a testrun end in a state that is neither queued nor done?" is **still open**,
and the bounded poll stays necessary.

Fields on a completed run beyond those already modelled: `host`, `lang`, `login`,
`filename`, `problem_id`, `requested_at`, `finished_at`, `success`, `report`,
`verdict_canon`, `score`, `score_kind` (`'tests'`), `score_max`.

## 7b. Shape when the run failed as a whole

A `status` of `done` does **not** mean the testset ran. The three shapes seen so far, and
the only two fields that tell them apart:

| what happened | `total_tests` | `len(tests)` | `verdict_canon` |
|---|---|---|---|
| ran everything | 72 | 72 | `Accepted` |
| ran, `STOPWHEN_*` cut it short (§4) | **72** | 4–5 | `Wrong Answer` / `Runtime Error` / `Time Limit Exceeded` |
| never ran a testcase (§3b) | **0** | 0 | `Compilation Error` |

**`total_tests` is the discriminator, not `len(tests)`.** It is the judge's own count of the
tests it set out to run, so a truncated run still reports the full 72 while a run that died
before entering the testset reports 0. `len(tests) == 0` cannot separate them: a
`STOPWHEN_*` problem whose *first* test fails would legitimately return zero entries out of
72, and calling that a build failure would be a fresh wrong diagnosis in place of the old
one. `cli.TestrunStatus.ran_nothing` is that predicate (`done`, no `tests`, no
`total_tests`); `MojRunner` fails the whole solution on it rather than degrading each
testcase to `SKIPPED`, and quotes `moj testrun-status <run> --report <file>`, which is where
the compiler output actually lives — rbx never sees it.

Note this is still not a terminal *failure* `status`: the run above finished `done` with
`success: true`. A failing **status** remains unobserved.

---

## Still open

- Whether a testrun can reach a terminal **failure** status (a compile error does not: it is
  a `done` run with a run-level verdict — see §3b).
- The full `code` vocabulary beyond `AC` / `WA` / `RE` / `RE_NZEC` / `TLE` — in
  particular, which other members of the `RE_*` family MOJ emits.
- Whether `testrun` requires a prior calibration (this problem was already calibrated).
- Whether a submission outside `.moj-meta.json`'s `languages` is really refused.
- Whether a `TLOVERRIDE`-only `conf` change forces recalibration.

The last three need an upload, which this probe deliberately avoided.
