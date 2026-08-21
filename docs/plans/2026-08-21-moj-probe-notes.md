# What the live MOJ actually answers

Task 0 of [the MOJ remote-runner plan](2026-08-20-moj-remote-runner.md), run 2026-08-21
against `moj.naquadah.com.br` (server build `c2716d8-20260820`) as `rsalesc`.

**Method.** No problem was created and nothing was uploaded. `moj testrun` runs *outside*
history and placar and modifies nothing, so four testruns were issued against an existing,
already-calibrated problem the account owns (`rsalesc#delete` — 72 tests, cpp TL 0.614s):
its own reference solution for `AC`, and three deliberately broken one-file programs for
`WA` / `RE` / `TLE`.

---

## 0. `moj testrun` does not work on macOS at all

**This blocks the whole feature for any setter on a Mac, including the author of rbx.**

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

The upstream fix is one character — `base64 < "$sol"` works on both BSD and GNU. **This
should be reported to `cd-moj/moj-cli`.** Until it lands, `rbx time --runner moj` cannot
work on macOS by shelling out to the CLI, and rbx cannot fix it from its side because the
encoding happens inside `moj`. The probe below was obtained by putting a small `base64`
shim ahead of the real binary on `PATH`; that is a debugging aid, not a shipping strategy.

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
one. Per-test `code` uses the short forms above. `MLE` / `OLE` / `PE` / `CE` / `JE` were not
provoked and remain unconfirmed — Task 6's mapping must therefore treat an unknown code as
*unknown*, not silently coerce it.

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

---

## Still open

- Whether a testrun can reach a terminal **failure** status (nothing provoked one).
- The full `code` vocabulary beyond `AC` / `WA` / `RE` / `TLE`.
- Whether `testrun` requires a prior calibration (this problem was already calibrated).
- Whether a submission outside `.moj-meta.json`'s `languages` is really refused.
- Whether a `TLOVERRIDE`-only `conf` change forces recalibration.

The last three need an upload, which this probe deliberately avoided.
