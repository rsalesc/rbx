# Deprecate BOCA rounding + approximation — exact fractional time limits

Issue: https://github.com/rsalesc/rbx/issues/494

## Problem

BOCA `limits/{lang}` scripts emit a total time budget (line 1, seconds), a number of
repetitions (line 2), memory (line 3), and output limit (line 4). The judge runs the
solution `repetitions` times and compares the **total** CPU time against the budget, so
the effective per-run time limit is `budget / repetitions`.

Historically BOCA only accepted integer budgets, so rbx (inheriting a heuristic from
`box`) picks a repetition count `i` such that

```
|round(tl·i) − tl·i| / (tl·i) ≤ maximumTimeError    (default 20%)
```

and emits `budget = round(tl·i)` as an **integer**. Because the budget is rounded, the
effective per-run TL `budget / i` drifts away from the real TL whenever `tl·i` is not
close to an integer.

Measured drift with the current code (`maximumTimeError = 0.2`):

| TL    | reps | budget | effective per-run TL | drift   |
|-------|------|--------|----------------------|---------|
| 1.2s  | 1    | 1s     | 1.000s               | −16.7%  |
| 0.3s  | 3    | 1s     | 0.333s               | +11.1%  |
| 0.1s  | 9    | 1s     | 0.111s               | +11.1%  |
| 1.9s  | 1    | 2s     | 2.000s               | +5.3%   |
| 3.9s  | 1    | 4s     | 4.000s               | +2.6%   |

This silently changes verdicts: a −16.7% drift makes intended-AC solutions wrongly TLE,
and a +11.1% drift lets intended-TLE solutions wrongly pass. The issue only stayed hidden
on past contests (PdA) because the TL formula resolution happened to be 0.5s, which always
lands on near-integer products. rbx's default formula uses 0.1s resolution, which routinely
produces "ugly" TLs like 1.2s, 3.9s.

`box` allowed this error for BOCA's integer-only constraint. BOCA/safeexec now supports
fractional time budgets (rbx already emits fractional budgets for COMMUNICATION tasks), so
the rounding is no longer necessary and must not be ported.

## Goal

Never approximate the time limit. Always emit a budget whose effective per-run TL equals
the real TL **exactly**.

## Design

Scope: **BOCA packager only**. MOJ already emits `pkg.timeLimit / 1000` directly with no
repetition mechanism, so it is unaffected.

### Repetition count

```
tl_ms  = _get_pkg_timelimit(language)        # int ms
min_ms = extension.minRunningTime            # Optional[int] ms, default None

if min_ms is None:
    reps = 1                                 # single run, exact fractional TL
else:
    reps = max(1, ceil(min_ms / tl_ms))
    if reps > _MAX_REPS:                     # safety cap (= 10)
        warn("minRunningTime could not be fully honored; capping at N reps")
        reps = _MAX_REPS
```

`minRunningTime` is an optional, setter-controlled floor on the **total** BOCA budget
(`reps · tl ≥ minRunningTime`). It exists to amortize fixed startup/JIT overhead and
measurement noise on very small TLs. When unset, rbx always does a single run.

The cap keeps the effective per-run TL exact; only the total budget falls short of the
requested minimum, which is the safe failure mode (a warning is printed).

### Budget formatting (exact, no rounding)

`budget_ms = reps · tl_ms` is exact integer milliseconds. Emit it as fractional seconds
without floating-point rounding:

```python
def _fmt_seconds(ms: int) -> str:
    return f'{ms // 1000}.{ms % 1000:03d}'   # 1234 -> "1.234", 2000 -> "2.000", 500 -> "0.500"
```

- BATCH path: budget = `_fmt_seconds(reps · tl_ms)`, reps as above.
- COMMUNICATION path: reps = 1, budget = `_fmt_seconds(tl_ms)` — replaces the current
  lossy `:.2f` formatting so interactive TLs like 1234ms no longer round to 1.23s.

### Removed / deprecated

- Remove `test_time`, the inner `rounding_error` / `error_percentage` helpers,
  `_MAX_REP_TIME`, and the "TL too large → 1 run" branch (redundant: no minimum ⇒ 1 run).
- Keep `_MAX_REPS = 10` as the repetition safety cap.
- `BocaExtension.maximumTimeError`: keep the field for backward compatibility (no schema
  break), mark it `deprecated=`, and stop reading it. Emit a one-time warning if a user
  has set it, pointing them to `minRunningTime`.
- Add `BocaExtension.minRunningTime: Optional[int] = None` (milliseconds), validated `> 0`.

### Worked examples (post-fix)

| TL     | minRunningTime | reps        | budget | effective TL | note                  |
|--------|----------------|-------------|--------|--------------|-----------------------|
| 1.2s   | (unset)        | 1           | 1.200  | 1.2s         | exact                 |
| 0.3s   | 1000ms         | 4           | 1.200  | 0.3s         | exact                 |
| 0.05s  | 2000ms         | 10 (capped) | 0.500  | 0.05s        | exact, warns budget<2s|
| 1.234s | (unset)        | 1           | 1.234  | 1.234s       | exact                 |

### Judge-side `run/{lang}` scripts (resources)

Emitting a fractional budget in `limits/{lang}` is only half the fix: the BOCA judge runs
the submission through `rbx/resources/packagers/boca/run/{lang}`, which receives the budget
as `$3` and passes it to `safeexec -t$time`. `safeexec.c` parses `-t` with `atof`, so it
accepts fractional CPU limits — but the batch `run/*` scripts wrapped `$3` in **bash
integer** operations:

```bash
time=$3
if [ "$time" -gt "0" ]; then        # errors on "1.200": integer expression expected
  let "ttime = $time + 30"          # bash integer arithmetic, also errors
else
  time=1                            # <-- silently resets the CPU limit to 1 second
  ttime=30
fi
```

With a fractional `$3`, the comparison errors (returns false) and the `else` branch resets
`time=1`, so **every** batch problem would be judged with a 1-second CPU limit regardless of
its real TL. The interactive `run/*` scripts already avoid this by computing an integer
ceiling via `awk` for the bash-only operations while still passing the fractional `$time` to
safeexec. The fix mirrors that in all eight batch scripts (`c`, `cc`, `cpp`, `java`, `kt`,
`py2`, `py3`, and the unused `bkp` template):

```bash
time=$3
rtime=$(awk "BEGIN {print int($time+0.9999999)}")   # ceil, for bash integer ops only
if [ "$rtime" -gt "0" ]; then
  let "ttime = $rtime + 30"                           # wall limit = ceil(time) + 30
else
  time=1
  ttime=30
fi
# safeexec still receives the exact fractional CPU budget: ... -t$time -T$ttime ...
```

MOJ run scripts use a different runtime and never had this block, so they are unaffected.

## Behavior change note

Packages that previously got "nice" TLs now get a single run with the identical effective
TL — no verdict change, but the emitted `limits/{lang}` files change (reps may drop to 1
and the budget becomes fractional). Packages with "ugly" TLs stop drifting, which is the
fix. The old multi-run rounding behavior is gone entirely.

## Testing (TDD)

- Unit: `_get_number_of_runs` returns 1 when `minRunningTime` unset; `ceil` behavior when
  set; cap + warning path when `min/tl > _MAX_REPS`.
- Unit: `_fmt_seconds` exactness (1234 → "1.234", 2000 → "2.000", 500 → "0.500", 50 → "0.050").
- Integration: package a fixture with an "ugly" TL (e.g. 1200ms) and assert the emitted
  `limits/cpp` script contains the exact budget and reps (regression guard for the drift).
  Reuse existing BOCA packaging test fixtures.
- Assert a set `maximumTimeError` no longer affects the emitted limits.
