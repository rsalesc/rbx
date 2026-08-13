# Kattis-like multipliers for time limit inference

Design for [#639](https://github.com/rsalesc/rbx/issues/639).

## Problem

Time limit estimation today evaluates a single formula string over
`(fastest, slowest)`, pooled per language group. The formula encodes a lower
bound only: nothing in the pipeline knows how fast the slow solutions are, so
nothing catches a time limit that lets a solution meant to time out pass.

The [Kattis problem package format](https://icpc.io/problem-package-format/spec/2025-09.html)
models the same decision as a bounded range instead: `ac_to_time_limit` sets a
floor relative to the accepted solutions, `time_limit_to_tle` sets a ceiling
relative to the slow ones, and `time_resolution` quantizes the answer. This
design brings those three parameters to rbx as an alternative to `formula`.

## Semantics

All quantities are integer milliseconds. Per solution, the measured time is the
maximum across its testcases -- the aggregation `solutions._get_evals_time_in_ms`
already performs.

Bounds are computed **per language group**, matching how the formula path
already estimates. For each group:

- `lower = max over lower-bound solutions of (time * acToTimeLimit)`
- `upper = min over upper-bound solutions of (time / timeLimitToTle)`, or
  `+inf` when `timeLimitToTle` is unset
- `timeLimit = step_up(lower, timeResolution)`, which is the smallest multiple
  of the resolution in range; it is an error if that value exceeds `upper`

A group with no lower-bound solutions keeps resolving through `whenEmpty` as it
does today, but its derived limit is rounded to `timeResolution` and, when the
group does have slow solutions, checked against its own upper bound. A group
with neither remains `DEFAULTED`.

### Which solutions bound which side

The existing vocabulary in `solutions.py` already draws this line and is reused
verbatim:

| Solution | Default role |
| --- | --- |
| every expectation is `accepted` | lower |
| any expectation `is_slow()` (`tle`, `tle-or-rte`) | upper |
| anything else, including `accepted-or-tle` | neither |

`accepted-or-tle` is deliberately in neither: it is `add_pass` in the timing
summary, neither good nor slow, and it cannot bound either side without
asserting something the setter did not.

A solution overrides its role with a new field:

```yaml
solutions:
  - path: sols/flaky.cpp
    outcome: accepted
    inference: false      # left out of the estimation run; bounds nothing
  - path: sols/borderline.cpp
    outcome: accepted-or-tle
    inference: upper      # opt in explicitly
```

`inference` accepts `false`, `lower` or `upper`; unset derives from the table
above. `inference: true` is rejected -- it would mean nothing distinct from
unset. `inference: lower` on a solution with a slow expectation is a validation
error: a solution meant to time out cannot bound the limit from below.

## Configuration

```yaml
# env.rbx.yml
timing:
  multipliers:
    acToTimeLimit: 2.0        # required whenever the block is present
    timeLimitToTle: 1.5       # optional
    inferenceTimeout: 10000   # defaults to 10s; only used when timeLimitToTle is set
    timeResolution: 100       # ms
```

`timing.formula` becomes optional and mutually exclusive with
`timing.multipliers`; declaring both is a validation error. Declaring neither
resolves to the current default formula, so every existing `env.rbx.yml` keeps
behaving exactly as it does now.

The bundled default preset switches to the multipliers above. On a problem whose
accepted solutions are close in speed, the old default yields `3 * fastest` and
the new one yields `2 * slowest`, so re-estimating an existing package will
usually tighten its limit by roughly a third. This is intended, but it will show
up in diffs.

A problem overrides any subset of the block:

```yaml
# problem.rbx.yml
timing:
  multipliers:
    inferenceTimeout: 120000   # this problem is slow; ratios inherited
```

The override is a field-by-field merge over the environment block, with the
formula/multipliers exclusivity re-checked on the merged result.

## Running the solutions

When `timeLimitToTle` is **unset** there is no upper bound to compute, so the
estimation run is unchanged: lower-bound solutions only, with no time limit.

When it is set, lower- and upper-bound solutions run together in a single pass
capped at `inferenceTimeout`. `doubleTL` is suppressed for that pass, since it
would silently double the cap for exactly the solutions the cap exists to bound.
Expectations are verified for lower-bound solutions only -- an upper-bound
solution is *supposed* to hit the cap, and its timeout must not abort the run.

## Diagnostics

In escalating severity:

1. An upper-bound solution killed at `inferenceTimeout` is dropped from the
   bound, with a warning naming it.
2. If any solution was dropped **and** the resolved limit exceeds
   `inferenceTimeout / timeLimitToTle`, a prominent warning: the cap, not the
   solutions, is what bounded the estimate, and the upper bound is not
   trustworthy.
3. An upper-bound solution that fails for a reason other than timing out
   (runtime error, wrong answer, judge failure) is an error naming the solution
   and suggesting `inference: false`. Its timing is unusable and dropping it
   quietly is the failure mode the issue asks to avoid.
4. A lower-bound solution killed at `inferenceTimeout` is an error: the
   estimate would rest on a truncated measurement.
5. No multiple of `timeResolution` fits in `[lower, upper]` for some group --
   including an empty range -- is an error naming the binding solution on each
   side. Nothing is written to the limits profile: an unsatisfiable range means
   the solution set contradicts the configured ratios, and writing a limit
   anyway ships one that is known to be wrong.

Inside the interactive language-group picker, (5) renders as an inline error for
the offending grouping, the same way an invalid partition does today, so a
setter can regroup out of it. The hard failure applies when the estimate is
committed.

## What estimation records

The limits profile gains the resolved multipliers alongside the existing
`formula` slot, and each group report gains its bounds and the solutions that
set them:

```yaml
timeLimit: 2000
multipliers: {acToTimeLimit: 2.0, timeLimitToTle: 1.5,
              timeResolution: 100, inferenceTimeout: 10000}
groups:
  - languages: [cpp, c]
    timeLimit: 2000
    lowerBound: {value: 1260, solution: sols/slow_ac.cpp}
    upperBound: {value: 4066, solution: sols/tle.cpp}
    droppedUpper: [sols/hopeless.cpp]
```

This keeps "why is the limit 2000?" answerable from the committed file alone,
and shows how much headroom the slow side actually had. The data is
presentation-only, like the group reports already stored there.

## Surfaces

`rbx time`'s menu currently offers the formula as its recommended entry; it
offers the ratios instead when the environment uses multipliers, and keeps
"custom formula" as an escape hatch that forces the formula path for that run.
The limits table renders the bounds. Documentation updates stay at the level the
current profiling docs sit at.

## Out of scope

Problems scored by points, where a per-group score model makes "the" slow
solution ill-defined, are deferred to a follow-up issue.
