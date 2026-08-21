# A `timing`-level `inferenceTimeout`

Closes [#694](https://github.com/rsalesc/rbx/issues/694).

## The problem

`inferenceTimeout` is the cap a solution runs under while `rbx time` estimates a
time limit. It lives under `timing.multipliers`, and it is honoured only when the
environment estimates with ratios *and* `timeLimitToTle` is set *and* the package
has a solution to bound the limit from above (`timing.py:_run_for_inference`).

Two things are wrong with that:

1. **It is not a ratio.** The multipliers say what relation the limit must have to
   the measured times. The cap says how long rbx is willing to wait for a
   measurement in the first place -- a property of the estimation run, not of the
   arithmetic that follows it.
2. **A formula estimate has no cap at all.** Its accepted solutions run unbounded,
   so one that loops forever hangs `rbx time` with nothing to report. Raising the
   cap for such a problem is not even expressible: writing
   `timing.multipliers.inferenceTimeout` in a formula-mode package is rejected,
   since the environment has no multipliers block to override.

## The change

`inferenceTimeout` becomes a `timing`-level field, in `env.rbx.yml` and in
`problem.rbx.yml` alike:

```yaml
timing:
  inferenceTimeout: 10000
  multipliers:
    acToTimeLimit: 2.0
    timeLimitToTle: 1.5
```

It applies to **every** estimation run. Semantics per solution are unchanged, and
now reach the formula path too:

- an upper-bound solution that hits it is dropped from the upper bound, with a
  warning (and the "the cap bounded this estimate" warning still fires when the
  resolved limit is above `inferenceTimeout / timeLimitToTle`);
- a lower-bound solution that hits it is an error -- its measurement is truncated,
  so it bounds nothing;
- either way the solution stops there, so its remaining testcases are skipped.

### Resolution

One function, `timing_config.resolve_inference_timeout`, most specific first:

| # | Source |
| - | ------ |
| 1 | `problem.rbx.yml` → `timing.inferenceTimeout` |
| 2 | `problem.rbx.yml` → `timing.multipliers.inferenceTimeout` (deprecated) |
| 3 | `env.rbx.yml` → `timing.inferenceTimeout` |
| 4 | `env.rbx.yml` → `timing.multipliers.inferenceTimeout` (deprecated) |
| 5 | `DEFAULT_INFERENCE_TIMEOUT` (10s) |

The resolved value is carried on `TimingStrategy` next to the formula/multipliers,
so no consumer re-derives it -- including `rbx time --formula`, whose custom
formula overrides how the limit is derived but not the cap it is measured under,
and the MOJ packager, which feeds it to `CALIBRATIONTL`.

### Backwards compatibility

`timing.multipliers.inferenceTimeout` keeps working, in both files, and is marked
deprecated in the schema. It becomes `Optional` there (it no longer carries the
10s default, which moved to the resolution above), so a persisted limits profile
written from now on simply omits it.

Declaring both spellings **in the same file** is a validation error: they are one
setting, and silently preferring one would hide a typo'd cap. Declaring the new
one in the problem while the environment still uses the old one is fine -- that is
rule 1 beating rule 4, and it is how a package migrates ahead of its preset.

## Behavior change

An estimation that was previously uncapped is now capped at 10s by default: a
formula-mode problem, and a ratio-mode one with no `timeLimitToTle` or no slow
solutions. A package whose accepted solutions legitimately take longer than that
now fails the estimate with the message that names the fix
(`raise inferenceTimeout`). That is the point of the field -- an accepted solution
that runs longer than rbx is willing to wait was never measured, it was truncated.
