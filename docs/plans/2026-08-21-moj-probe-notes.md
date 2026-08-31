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

That prompted the question the probe had left open — what the *rest* of the vocabulary is —
and it turned out not to need probing at all.

### 3d. The full per-test vocabulary — from the judge's source, 2026-08-29

The codes are not the server's invention: mojtools' `build-and-test.sh` writes
`VERDICT[<file>]=<code>` into `log.verdictall`, and `calibreitor.sh`'s `sol_tests_json` — the
same shape the judge agent's `agent_tests_json` produces, as its comment says — parses that
file straight into `{name, code, time, tl}`. Nothing rewrites the string in between, so
`run-testinput` **is** the vocabulary:

| `code` | written when | rbx `Outcome` |
|---|---|---|
| `AC` | comparator exit 4 | `ACCEPTED` |
| `AC,PE` | comparator exit 5 | `ACCEPTED` |
| `WA` | comparator exit 6 | `WRONG_ANSWER` |
| `MLE` | measured RSS over `MEMLIMITMB` | `MEMORY_LIMIT_EXCEEDED` |
| `TLE` | exec time over the language's TL | `TIME_LIMIT_EXCEEDED` |
| `RE` | bwrap exit ≥ 127 | `RUNTIME_ERROR` |
| `RE_NZEC` | bwrap exit ≠ 0 | `RUNTIME_ERROR` |
| `TMT` | legacy "signaled PPDI"; still ranked and named, no longer assigned | `RUNTIME_ERROR` |
| `UE` | comparator exited something else | `JUDGE_FAILED` |

Three notes on the mapping, which is no longer one-to-one:

- **`AC,PE` is a pass.** MOJ scores it as correct (`[[ "$THISVERDICT" =~ "AC" ]]`), ranks it
  with `AC` in `VERDICTORDER`, and canonicalises it to `Accepted`. rbx has no
  presentation-error outcome; turning MOJ's pass into a failure would corrupt the estimate in
  exactly the direction the refusal rule exists to prevent.
- **`UE` is the comparator, not the solution.** MOJ's `VERDICTCANON` collapses it onto
  `Runtime Error`; rbx does not follow, because a broken checker reported as the solution's
  runtime error is the same silent lie in a different costume. `JUDGE_FAILED` says what
  happened.
- **`CE` and `NT` are handled, but not as verdicts of equal standing** — see §3f. Neither is
  written by `run-testinput`, so neither is *expected* in the `code` position; both are
  tolerated there rather than refused, because refusing costs a whole run and neither can
  corrupt an estimate.

`_outcome_for_moj_code` still reads any other `RE_*` as `RUNTIME_ERROR`, as a backstop for a
sibling mojtools might grow — the prefix names the verdict, so the outcome carries no guess.
Everything else is still refused by name. The invented spellings the earlier table warned
about (`PE` and `JE` on their own) are now confirmed **not** to exist.

### 3e. A testcase can appear **twice**, and the last one is the answer — 2026-08-31

Read off mojtools while chasing [#824](https://github.com/rsalesc/rbx/issues/824), and it is
not an anomaly: it is what the judge does on every TLE.

`build-and-test.sh` runs the testset in parallel (`NPROC` jobs), then walks it a second time
and reruns any testcase that came back `TLE` — *"Rerun: because got TLE while running
parallel tests"* — because a timeout measured while N tests shared the machine is not a
timeout. Each call of `run-testinput` **appends** its own line:

```sh
echo "VERDICT[$FILE]=$VERDICT" >> $workdirbase/log.verdictall
```

and `sol_tests_json` walks that file line by line into the `{name, code, time, tl}` array.
So a reran testcase arrives **twice** in `tests`: first the contended measurement, then the
one the judge kept. (It gives up after one rerun — a second `TLE` sets `TLERERUN=n` — so a
name appears at most twice, though nothing here depends on that.)

**The last entry wins**, and that is the judge's own rule rather than a tiebreak rbx
invented: `build-and-test.sh` re-`source`s `log.verdictall` after the rerun and reads the
testcase's verdict straight back out of the bash array, which is last-assignment-wins.

`TestrunStatus.by_name` used to *refuse* a repeated name — it read a duplicate as the kind of
misattribution that pairing-by-name exists to prevent — and so failed the whole run with
"the judge reported more than one test named `…`" on a testrun MOJ considers perfectly
ordinary. It now keeps the last entry. Reading the first would have been worse than the
refusal: it feeds the estimate a time the judge itself discarded.

### 3f. `CE` and `NT` in the `code` position — tolerated, 2026-08-31

Neither is written by `run-testinput`, so §3d's argument stands: they are not expected
per-test. But `gen-report.sh` shows both are real spellings in mojtools' vocabulary
(`VERDICTFULLNAME` carries `[CE]="Compilation Error"` and `[NT]="Não executado"`, and the
report's verdict histogram iterates `AC "AC,PE" WA TLE RE RE_NZEC TMT UE NT`), and the judge
*agent*'s `agent_tests_json` — which `sol_tests_json` only claims to mirror — is server-side
and cannot be read from here. So "cannot reach the `code` position" was an inference about
code rbx has never seen.

The cost of that inference being wrong is a **whole failed run**, and the cost of tolerating
the two codes is nothing, because neither can put a wrong number into an estimate:

- **`CE` → `COMPILATION_ERROR`.** It is what the code says. A run-level compile error still
  takes §7b's `ran_nothing` path, which is the one that explains itself properly.
- **`NT` → dropped, not mapped** (`_UNEXECUTED_MOJ_CODES`). It names the *absence* of a
  verdict — `gen-report.sh` substitutes it for an input file with no `log.verdictall` entry,
  which is a testset cut short — so every `Outcome` would be a claim about the solution that
  nothing measured. Dropping it puts the testcase back on the path of one MOJ never
  mentioned: `SKIPPED`, no timing, and counted in the "reported no result for N of M"
  warning.

Unknown codes are still refused by name. This widens what rbx reads; it does not weaken the
rule that a code it cannot read stops the run.

### 3g. `Unknown ERROR` on a run whose testcases all look fine — 2026-08-31

Reported from a real run: a testrun whose per-test codes were only `AC` and `TLE` came back
with a **run-level** verdict of `Unknown ERROR`. Traced through mojtools and the CD-MOJ
server (`cd-moj/cdmoj`, which is open source), and it has exactly one source.

**The server never produces it.** `judged.sh:390` merges the worker's payload wholesale and
the read handler is a bare `jq -c '{success:true} + .'` (`api/v1/handlers/problems/test-run.sh:110`),
so `verdict`, `verdict_canon`, `correct`, `total_tests` and `tests[]` are all the worker's
own words. The only verdict the server ever *synthesizes* is the literal `Judge Error` — and
not even that for a testrun, because the `_testrun` divert (`judged.sh:418`) runs before that
fallback. A payload with no verdict therefore yields **no `verdict` key**, never `UE`.

So it always comes from `build-and-test.sh`'s second-to-last decision:

```sh
[[ "$SMALLRESP" =~ "AC" ]] && (( RESPERRO > 0 )) && SMALLRESP=UE
```

`SMALLRESP` is the worst verdict across the testcases that *reported* one; `RESPERRO` counts
inputs that reported none (`RESP="INPUT NOT TESTED"`, line ~514). The line reads: **every
testcase I have a verdict for passed, and at least one produced no verdict at all** — a
statement about the judging run, not about the submission.

**How the testset comes up short**, and why a `TLE` can be sitting in `tests` while this
fires:

1. A testcase returns non-zero during the parallel dispatch (`3` = TLE, `6` = WA, `≥126` = RE)
   and the loop breaks at line ~475 — `(( RET != 0 )) && [[ "$RUNALL" != "y" ]] && break`.
   Every remaining input is then never executed. **`RUNALL` is the 4th argv of
   `build-and-test.sh`, not a package setting**, and it defaults to `no`; it appears as `y`
   only in the server's dev-only gateway (`server/judge-gw/judge.sh:106`), so what the
   production agent passes cannot be determined from open source. This break is independent
   of the `STOPWHEN_*` bits — which is worth knowing, because `STOPWHEN_TLE=n` alone does not
   keep a run going.
2. Each unexecuted input hits line ~514 in the second loop, so `RESPERRO > 0`.
3. If the testcase that broke the loop was a **`TLE` that passed on its `TLERERUN` rerun**
   (§3e), lines ~516-525 overwrite its verdict with `AC`. Now every *tested* verdict is `AC`,
   `SMALLRESP` stays `AC`, and line ~568 flips it to `UE`.

That is the reported shape: the discarded `TLE` is still in `tests`, nothing in the array
looks wrong, and the run as a whole is `Unknown ERROR`.

**The signature**, for reading one of these off a real response:

- `verdict` = `Unknown ERROR,<n>p`, and `verdict_canon` = **`Runtime Error`** —
  `VERDICTCANON[UE]`, naming a failure of the solution that did not happen. This is the one
  place `canonical_verdict`'s preference for the canon spelling inverts, and why
  `_note_on_run_verdict` reads the raw `verdict`.
- `correct < total_tests`: `TOTALTESTS` counts every input file (line ~403) while `CORRECT`
  counts only tested ones. The cheapest discriminator available.
- `tests[]` truncated to the inputs actually dispatched.

rbx now appends the judge's own words to the "reported no result for N of M testcases"
warning when the run-level verdict is this one, and stays quiet for the rest of the
vocabulary — a `Wrong Answer` at run level only repeats what the per-test codes already said.

**Still unread:** the agent's `agent_tests_json`, which builds `tests[]`. It lives in a
separate, non-public repo (`judge/agent/moj-agent.sh`, per `server/judge-gw/PULL.md:51`).
`calibreitor.sh`'s `sol_tests_json` says it is the same format, and *it* walks
`log.verdictall` line by line — which is what §3e's duplicate rests on. Two consumers that
dedupe instead, by sourcing the file into a bash array, are `gen-report.sh:35-36` and
`build-and-test.sh:484-485`; so `report.html` shows one row per testcase while a line-walking
`tests[]` would show two. That difference is the check to run against a real reran testrun.

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
observed in the `code` position. `_OUTCOME_BY_MOJ_CODE` did not grow a `CE` entry on this
evidence — it grew one later, on the different argument in §3f.

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
  a `done` run with a run-level verdict — see §3b). Partly answered by the server source: a
  worker payload without a verdict leaves the register with no `verdict` key rather than a
  failure status, and the server's own `Judge Error` fallback is skipped for testruns (§3g).
- Whether the production judge agent passes `RUNALL=y` to `build-and-test.sh`, which decides
  whether a single failing testcase truncates the whole testset (§3g). Not in any public
  repo; it needs a testrun against a problem with more testcases than the judge has cores.
- Whether the agent's `agent_tests_json` duplicates a reran testcase the way
  `sol_tests_json` does (§3e, §3g).
- ~~The full `code` vocabulary~~ — closed 2026-08-29 by reading mojtools' `run-testinput`;
  see §3d.
- Whether `testrun` requires a prior calibration (this problem was already calibrated).
- Whether a submission outside `.moj-meta.json`'s `languages` is really refused.
- Whether a `TLOVERRIDE`-only `conf` change forces recalibration.

The last three need an upload, which this probe deliberately avoided.
