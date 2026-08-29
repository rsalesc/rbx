# Estimating a time limit

`rbx time` (alias: `rbx t`) is the command that measures your solutions and writes a [limits
profile](profiles.md) from what it measured.

```bash
rbx time
```

## What a run does

A run moves through four stages, and the middle two are where your attention is worth spending:

1. **Timing.** The accepted solutions run against every testcase. This is the measurement
   everything else is derived from, and it is the slow part.
2. **Bucketing.** You are shown every language the environment knows and asked how to group
   them. See [Language groups](language-groups.md).
3. **Estimating.** The rules your environment configures turn those timings into a limit — one
   per group. See [How the limit is computed](computing.md).
4. **Checking.** Each solution you declared too slow is run against the limit, to confirm it
   really is. See [Checking the upper bound](#checking-the-upper-bound).

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

Skip the prompt by naming the strategy, or by taking the configured one:

```bash
rbx time --strategy=estimate
rbx time --auto              # (1)!
```

1. `--auto` uses the configured strategy and answers every prompt with its default, including
   the language-group picker. This is the form to reach for in a script.

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

1. Left out of estimation entirely, and not run. Use this for a solution whose timings you do
   not trust.
2. Opted in as an upper bound, which its outcome would not have done on its own.

`inference: lower` on a solution declared too slow is rejected: a solution meant to time out
cannot argue that the limit should be *larger*.

## The estimation cap

While the limit is being estimated there is no limit yet to enforce, so a solution left alone
could run forever. `timing.inferenceTimeout` is the ceiling every accepted solution runs under
during `rbx time`:

```yaml title="env.rbx.yml"
timing:
  inferenceTimeout: 10000   # ms
```

An accepted solution that *hits* the cap is an error, not a data point: its measured time was
cut short, so it cannot honestly bound the limit from below. The solution stops there and its
remaining testcases are skipped, since they would measure nothing usable. Raise the cap, or make
the solution faster.

A single problem can raise it for itself:

```yaml title="problem.rbx.yml"
timing:
  inferenceTimeout: 60000
```

The cap does not apply to the solutions declared too slow — they are never measured, so raising
it does nothing for them.

## Checking the upper bound

A solution declared too slow only has to answer one question: is it slower than the limit
allows? Running it *at* that bound answers it, without waiting to find out how slow it really
is.

So once the limit is decided, {{rbx}} runs each of those solutions against it and reads the
verdict:

- It **runs out of time** — confirmed. Its remaining testcases are skipped; one timeout settles
  the question.
- It **finishes** — the bound is violated, and now there is a real time to report it with.
  {{rbx}} names the solution and what it took.
- It **fails some other way**, a crash or a wrong answer — evidence of nothing either way, and
  an error. Fix it, or set `inference: false`.

A violation does not end the run. The language-group picker reopens, now knowing what the check
found, so its preview shows which groupings cannot work:

{{ asciinema("time-upper-bound-violation") }}

From there you can regroup to satisfy the bound, press ++f++ to keep the limits anyway, or
cancel. Nothing is written until you pick one.

Where there is no picker to reopen — under `--auto`, or in a problem with a single language —
the violation is reported and recorded in the profile, and the limit is written anyway.

## Skipping the upper-bound check

```bash
rbx time --skip-slow
```

The estimate is written with its upper bound unchecked. Useful when the check is the expensive
part, as it is [on a remote judge](remote.md). If the environment sets no upper-bound ratio
there is nothing to check, and this phase never runs.

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

Everything a normal run does — the measurement, the picker, the estimation, the upper-bound
check — happens, and the profile it arrives at is printed instead of saved. Nothing on disk
changes, so the [limits profile](profiles.md) you already have survives the rehearsal.

That makes it the flag to reach for when the question is whether the estimation *works* —
a ratio you just changed, a solution you just declared too slow, a remote judge you are trying
for the first time — rather than what limit to commit to. It applies to every strategy, and to
`--integrate` as well, which leaves `problem.rbx.yml` untouched under it.

## Checking the rest of the package

The four stages above run only the solutions the limit depends on: the accepted ones, and the
slow ones the check had to ask about. Everything else — the solutions you expect to be wrong,
and any slow one the check could skip — has no verdict at all when the run ends.

```bash
rbx time --run-all
```

A fifth stage then runs exactly those, at the limit that was just written, and the command
fails if any of them does not behave as `problem.rbx.yml` says it does. The solutions that
already ran are not run again: an accepted one was measured under a far looser cap, and a slow
one timed out at a bound above the limit, so both answers already hold.

Add `--fail-fast` (or `--ff`) to stop each of those solutions at its first non-accepted
verdict. It applies to this stage only, it is for quick experimentation, and the report drops
its timing summary under it — a solution that stopped early was not timed on the testcases that
never ran.

### `rbx preship`

```bash
rbx preship
```

`rbx time --auto --run-all` under a name that says what it is for: estimate the limit, check it,
and check every solution against it. It takes the rest of `rbx time`'s flags — `--dry`,
`--runs`, `--profile`, `--runner`, `--skip-slow`, `--fail-fast`, `--share` — but not the ones
`--auto` settles (`--strategy`, `--integrate`).

Both commands also take the `rbx run` flags about how a run is reported, and apply them to every
stage: `-b` for a [judging-time benchmark](../running/index.md#benchmarking-the-judging-time),
and [`--keep-checker-stderr`](../running/index.md#reading-what-the-checker-said). Neither takes
`--sanitized` (sanitizers inflate every timing the estimate rests on), `--verification-level`
(pinned, so the estimation cap is never doubled), or a solution filter (both run the whole
package by definition).

## Sharing the report

```bash
rbx time --share png    # or: --share text
```

Captures the run report and the limits table and copies it to your clipboard, for pasting into
wherever the argument about a time limit is happening.

## Every flag

The sections above cover the flags worth explaining. For the exhaustive list, with its short
forms and defaults, see [`rbx time` in the CLI reference](../reference/cli.md#time-t) — it is
generated from the command itself, so it cannot fall behind.
