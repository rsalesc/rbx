# Two-phase `rbx time`

Design for [#693](https://github.com/rsalesc/rbx/issues/693).

## Problem

`rbx time` runs the solutions that bound the limit from below (`inference: lower`,
the accepted ones) and the solutions that bound it from above (`inference: upper`,
the ones expected to be too slow) in a single step, all capped at
`inferenceTimeout`. That single cap serves two incompatible purposes.

For the lower side it is a safety net: an accepted solution that reaches it fails
the estimate. For the upper side it is the only thing that makes the run
terminate at all -- a solution expected to be too slow is expected to run
forever -- and it distorts the measurement it is supposed to produce. A slow
solution killed at the cap measures nothing, so it bounds nothing
(`_InferenceRun.dropped_upper`), and one that survives the cap is measured under
a limit far above the real one. `_warn_if_the_cap_bounded_the_estimate` exists
only to tell the setter that the estimate they are looking at was decided by the
cap rather than by their slow solutions.

The upper side does not need to be measured. It needs to be *checked*: given a
time limit `TL`, every slow solution must take at least `TL * timeLimitToTle`.
That is a question with a cheap answer, and it can only be asked once `TL` is
known.

## Shape

Two phases, one compilation. Every solution is still compiled up front.

**Phase 1 -- estimate.** Only the lower-bound solutions run, capped at
`inferenceTimeout`. The estimate proceeds with an empty upper side, the language
group picker previews lower bounds only, and a candidate `TimingProfile` comes
out.

**Phase 2 -- validate.** Each language group `g` has an estimated limit `TL_g`.
Its slow solutions run at the probe limit

```
L_g = ceil(TL_g * timeLimitToTle)      # exact Fraction arithmetic
```

with `abort_on` slow verdicts, so the first TLE ends that solution's run. Each
slow solution lands in one of two states:

- **TLE at `L_g`** -- validated. Its runtime exceeds `L_g >= TL_g * timeLimitToTle`,
  which is exactly the constraint `compute_bounds` enforces. It contributes no
  measurement.
- **Finished** -- violation, with an exact time. That time feeds
  `slow_timing_per_solution_per_language` unchanged, so `compute_bounds` and
  `_check_bounds` produce the existing "no valid time limit exists for this
  group" diagnostic, naming the binding solution on each side.

The probe limit is chosen so that the two states partition cleanly: a solution
that finishes within `L_g` is measured exactly and judged by the existing
`Fraction` comparison, and one that does not finish is known to clear the bound
without needing a number at all.

## The loop

A violation is not fatal. The measurements phase 2 produced are carried back
into the picker, which re-opens with real upper bounds -- so the live preview now
shows infeasible groupings as the user moves through them, using the
`_check_bounds` machinery that already exists. The picker has three exits:

- **confirm** a new assignment -- phase 2 re-runs against the new limits;
- **proceed anyway** -- accept the current limits despite the violation;
- **cancel** -- abandon the estimate, nothing is written.

The loop terminates on any of the three. The profile is written once, after the
loop settles.

Re-running phase 2 after a re-pick is cheap because knowledge about a slow
solution is monotone. Per solution we keep either an exact time or a lower bound
`>= L` from a TLE, and:

- an exact time never needs re-running -- the check is pure arithmetic;
- a solution that TLE'd at `L` still clears any probe limit `L' <= L`, since a
  lower limit is a weaker demand.

Only solutions whose new probe limit exceeds what is already known are executed
again. In practice a re-pick that lowers a group's limit costs nothing.

## Escapes

`--skip-slow` stops after phase 1: the limit is estimated and written with its
upper bound unchecked, recorded as such in the profile.

Where there is no picker to re-enter -- `--auto`, a single-language problem (the
picker only opens with two or more languages), or a cancelled picker -- the
violation is recorded, warned about loudly, and the profile is written anyway.
This means `rbx time --auto` does not fail on a violated upper bound; the
violation is visible in the profile and in the console output instead.

## What changes

**`rbx/box/timing.py`**

- `_run_for_inference` is parameterized over the solutions it runs and the cap it
  enforces, and called once per phase. Phase 1 passes the lower solutions; this
  is already the code path taken today when `timeLimitToTle` is unset.
- `_InferenceCap.largest_bounded_limit` and
  `_warn_if_the_cap_bounded_the_estimate` are deleted. The cap can no longer
  bound the upper side, because the upper side is no longer in that run.
- `_diagnose_inference_run`'s `dropped_upper` disappears from phase 1 and is
  replaced in phase 2 by the validation record below. The verdict that used to
  mean "unmeasurable, bounds nothing" now means "confirmed too slow".
- `build_timing_profile` gains a mode in which a violated upper bound is recorded
  rather than raised, shared by the "proceed anyway" and the no-picker paths.
- New: the probe-limit computation, the per-solution knowledge cache, and the
  phase-2 driver that decides what to re-run.

**`rbx/box/schema.py`** -- `TimingGroupReport.droppedUpper` is replaced by a
validation record: solutions confirmed too slow, solutions that violated (with
the measured time), and solutions not run. `upperBound` is populated only when a
violation supplied a real measurement.

**`rbx/box/solutions.py`** -- `run_solutions` gains a per-language time limit
override. Today `timelimit_override` is a scalar, but phase 2 needs one limit per
group. `tasks.run_solution_on_testcase` already accepts `limits_override`, so
this is a plumb through `_get_report_skeleton` and `_run_solution`. Report gating
inverts in phase 2: the slow solutions gate the report, TLE being the expected
verdict there.

**`rbx/box/timing_group_picker.py`** -- `GroupAssignment` gains `force: bool`, and
a key binding exits with it. The binding and its legend line are enabled only
when the caller reports a violation to override.

`_INFERENCE_VERIFICATION` stays `ALL_SOLUTIONS` in both phases: `FULL` would turn
on `isDoubleTL` and double the very limits phase 2 probes at.
`build_preview_renderer`'s `lru_cache` is rebuilt per loop iteration, since the
measurements it closes over change between iterations.

## Testing

- Probe-limit arithmetic, including the exactness of `ceil(TL * timeLimitToTle)`
  and the boundary where a solution's time equals `TL * timeLimitToTle`.
- The knowledge cache's re-run decisions: exact time never re-runs, a TLE at `L`
  covers any `L' <= L`, a higher `L'` re-runs.
- `test_timing_inference_run.py` moves from `call_args` to `call_args_list`, with
  cases pinning the two calls' distinct solution sets and limits.
- The violation path end to end: phase 2 finds a fast slow solution, the picker
  re-opens, a re-pick validates, one profile is written.
- `--skip-slow`, and the no-picker warn-and-write path.
