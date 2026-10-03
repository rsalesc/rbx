# Estimating a time limit

`rbx time` (alias: `rbx t`) is the command that measures your solutions and writes a [limits
profile](profiles.md) from what it measured.

```bash
rbx time
```

## What a run does

A run moves through four stages. The middle two are where your decisions come in:

1. **Timing.** The accepted solutions run against every testcase. This is the measurement
   everything else is derived from, and it is the slow part.
2. **Bucketing.** You are shown every language the environment knows and asked how to group
   them. See [Language groups](language-groups.md).
3. **Estimating.** The rules your environment configures turn those timings into a limit — one
   per group. See [How the limit is computed](computing.md).
4. **Checking.** Each solution you declared too slow is run at the limit times the upper-bound
   ratio, to confirm it times out. See [Checking the upper bound](#checking-the-upper-bound).

A fifth stage runs the solutions none of these needed, but only if you
[ask for it](#checking-the-rest-of-the-package).

The solutions declared too slow are not timed in stage 1. Nobody needs to know *how* slow they
are, only that they are slow enough, which stage 4 settles far more cheaply.

## Strategies

Before it measures anything, `rbx time` asks how you want the limit defined:

| Strategy | What it does |
| :--- | :--- |
| **Estimate** | Times the solutions and applies whatever the environment configures. The recommended one, and the one the rest of this section assumes. |
| **Inherit from package** | Writes a profile that follows `problem.rbx.yml` instead of measuring. See [Inheriting from the package](profiles.md#inheriting-from-the-package). |
| **Estimate with custom formula** | Times the solutions, then applies a [formula](computing.md#time-limit-formulas) you type in. |
| **Custom time limit** | Asks you for a number of milliseconds and writes that. |

Skip the prompt by passing the strategy, or by taking the configured one:

```bash
rbx time --strategy=estimate
rbx time --auto              # (1)!
```

1. `--auto` picks **Estimate**, and answers every other prompt with its default, including the
   language-group picker. Use this form in scripts.

## Which solutions bound which side

By default a solution's declared outcome decides what it constrains:

- {{tags.accepted}} everywhere: it bounds the limit **from below**. The limit has to be
  generous enough for it.
- Too slow (`tle`, `tle-or-rte`) anywhere: it bounds the limit **from above**. The limit has to
  be tight enough to reject it.
- Anything else, `accepted-or-tle` in particular: it bounds **neither**, because it does not
  claim anything the limit could be measured against.

Override that per solution with `inference`:

```yaml title="problem.rbx.yml"
solutions:
  - path: sols/flaky.cpp
    outcome: ac
    inference: false      # (1)!

  - path: sols/borderline.cpp
    outcome: accepted-or-tle
    inference: upper      # (2)!
```

1. Left out of estimation entirely, and not run while estimating. Use this for a solution
   whose timings you do not trust.
2. Opted in as an upper bound, which its outcome would not have done on its own.

`inference: lower` on a solution declared too slow is rejected: a solution meant to time out
cannot argue that the limit should be *larger*.

## The estimation cap

While `rbx time` estimates the limit there's no limit to enforce yet, so an accepted solution
could run forever. `timing.inferenceTimeout` caps every accepted solution:

```yaml title="env.rbx.yml"
timing:
  inferenceTimeout: 10000   # ms
```

If an accepted solution *hits* the cap, {{rbx}} treats it as an error: its measured time was
cut short, and a cut-short time can't bound the limit from below. The solution stops there and
its remaining testcases are skipped. Raise the cap, or make the solution faster.

A problem can raise it for itself:

```yaml title="problem.rbx.yml"
timing:
  inferenceTimeout: 60000
```

The cap does not apply to the solutions declared too slow. They are never measured, so raising
it does nothing for them.

## Checking the upper bound

A solution declared too slow only has to answer one question: is it slower than the limit
allows? Running it at `limit × timeLimitToTle` (see [How the limit is computed](computing.md))
answers that, without waiting to find out how slow it really is.

So once the limit is decided, {{rbx}} runs each of those solutions against it and reads the
verdict:

- It **runs out of time**: confirmed. Its remaining testcases are skipped; one timeout settles
  the question.
- It **finishes**: the bound is violated, and now there is a real time to report it with.
  {{rbx}} names the solution and what it took.
- It **fails some other way**, a crash or a wrong answer: evidence of nothing either way, and
  an error. Fix it, or set `inference: false`.

A violation does not end the run. The language-group picker reopens, now knowing what the check
found, so its preview shows which groupings cannot work:

{{ asciinema("time-upper-bound-violation") }}

From there you can regroup to satisfy the bound, press ++f++ to keep the limits anyway, or
cancel. The profile isn't written until you choose.

Under `--auto`, or in an environment with only one language, there's no picker to reopen. The
limit is then written anyway, with the violation reported and recorded in the profile.

## Skipping the upper-bound check

```bash
rbx time --skip-slow
```

The estimate is written with its upper bound unchecked. It pays off when the check is the
expensive part, as on [a remote judge](remote.md). Without `timeLimitToTle`
([ratios](computing.md#time-limit-ratios)) there's nothing to check anyway, and this phase never
runs.

## Running each solution several times

One run per testcase is one sample, and a machine under load produces bad samples.

```bash
rbx time --runs=3
```

Each testcase's timing becomes the **maximum** across its runs, which is the pessimistic reading
and the right one for a limit.

## Rehearsing without writing

```bash
rbx time --dry
```

The run goes through every normal step (the measurement, the picker, the estimation and the
upper-bound check), but prints the resulting profile instead of saving it. Nothing on disk
changes, and the [limits profile](profiles.md) you already have stays as it is.

Use it to check that the estimation *works* before you commit to a limit: after changing a
ratio or declaring another solution too slow, or when trying a remote judge for the first time.
It applies to every strategy, and to `--integrate` as well, which leaves `problem.rbx.yml`
untouched under it.

## Checking the rest of the package

The stages above run only the solutions the limit depends on: the accepted ones, and the slow
ones the check had to ask about. Everything else (the solutions you expect to be wrong, and any
slow one the check could skip) has no verdict when the run ends.

```bash
rbx time --run-all
```

A fifth stage then runs exactly those, at the limit that was just written, and the command
fails if any of them does not behave as `problem.rbx.yml` says it does. Solutions that
already ran aren't run again, because their verdicts at the written limit already follow: an
accepted one was measured under a far looser cap, and a slow one timed out at a bound above the
limit.

This stage judges rather than measures, so it runs them exactly as
[`rbx run`](../running/index.md) would: with twice the time limit, and with the warning that
appears when a TLE solution passes within `2*TL`. The verdicts still come from the limit itself
(anything past `1*TL` is a TLE); the extra headroom only adds those warnings to the report. The
earlier stages never double anything: their caps are what the estimate is measured against, and
a doubled cap corrupts the measurement.

Add `--fail-fast` (or `--ff`) to stop each of those solutions at its first non-accepted
verdict. It applies to this stage only and is meant for quick experiments. Under it, the report
drops its timing summary, since a solution that stopped early has no timings for the testcases it
never ran.

### `rbx preship`

```bash
rbx preship
```

`rbx time --auto --run-all` under a name that says what it is for: estimate the limit, check it,
and check every solution against it. It takes `rbx time`'s flags except `--strategy`,
`--auto`, `--integrate` and `--run-all`; see [`rbx preship` in the CLI
reference](../reference/cli.md#rbx-preship).

Both commands also take the `rbx run` flags about how a run is reported, and apply them to every
stage: `-b` for a [judging-time benchmark](../running/index.md#benchmarking-the-judging-time),
and [`--keep-checker-stderr`](../running/index.md#reading-what-the-checker-said). Neither takes
`--sanitized` (sanitizers inflate every timing the estimate rests on), `--verification-level`
(each stage is pinned to the level its job calls for), or a solution filter (both run the whole
package by definition).

## Sharing the report

```bash
rbx time --share png    # or: --share text
```

Captures the run report and the limits table and copies it to your clipboard, for pasting into
wherever the argument about a time limit is happening.

## Every flag

The sections above cover the flags that need some explanation. For the full list, with short
forms and defaults, see [`rbx time` in the CLI reference](../reference/cli.md#rbx-time). It is
generated from the command itself, so it is always up to date.
