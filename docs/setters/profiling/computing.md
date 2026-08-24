# How the limit is computed

[`rbx time`](estimating.md) hands the measured timings to whatever rule your **environment**
configures, and that rule produces the number. There are two, and they are mutually exclusive:
**ratios**, which bound the limit from both sides, and a **formula**, which computes it from
below.

Both live in `env.rbx.yml`, because a time limit rule is a property of the contest you are
setting, not of one problem in it.

## Time limit ratios

Ratios are the recommended rule, and what {{rbx}}'s default environment configures. Rather than
an expression over the timings, you state how much room the accepted solutions get and how
little the too-slow ones are allowed:

```yaml title="env.rbx.yml"
timing:
  multipliers:
    acToTimeLimit: 2.0    # (1)!
    timeLimitToTle: 1.5   # (2)!
    timeResolution: 100   # (3)!
```

1. The limit is **at least** twice the slowest accepted solution. In our problem the Python
   solution takes about `100 ms`, so the limit must be at least `200 ms`.
2. The limit times `1.5` must still fit inside the fastest too-slow solution. Omit it to leave
   the limit unbounded from above — and see the consequence below.
3. Round the result up to a multiple of `100 ms`, so limits come out as round numbers.

Read together, the two ratios squeeze the limit from both ends. Everything {{rbx}} is looking
for is in one inequality:

```text
acToTimeLimit × (slowest accepted)  ≤  time limit  ≤  (fastest too-slow) ÷ timeLimitToTle
```

Our problem, with the ratios above and the timings from the recording — the Python solution is
the slowest that has to pass, and the quadratic one is the fastest that has to fail:

```text
        2.0 × 100 ms                ≤    200 ms    ≤        300 ms ÷ 1.5
              200 ms                ≤    200 ms    ≤        200 ms
```

`200 ms` is the only limit that satisfies both, and it is what gets written. Widen either ratio
and the window opens; tighten both far enough and it closes.

The reason to prefer ratios is the second one. A formula only knows about the solutions that
should pass, so it can happily produce a limit generous enough for the solution you wrote the
problem to reject. Ratios are checked against **both** sides, and a limit that would let a
too-slow solution through is caught while estimating rather than during the contest.

When no limit satisfies both, `rbx time` names the solution binding each side, writes nothing,
and exits non-zero — so a pipeline notices.

A single problem can override any subset of the ratios, inheriting the rest:

```yaml title="problem.rbx.yml"
timing:
  multipliers:
    timeLimitToTle: 2.0   # this problem's slow solutions are further apart
```

!!! warning "A problem cannot switch the rule on its own"

    The override adjusts ratios the environment already sets. If the environment estimates with
    a formula instead, setting `timing.multipliers` on the problem is an error rather than a
    silent switch — {{rbx}} tells you to add the block to the environment.

## Time limit formulas

A formula is the alternative: an expression over the accepted solutions' timings.

```yaml title="env.rbx.yml"
timing:
  formula: "step_up(max(fastest * 2, slowest * 1.5), 100)"
```

It bounds the limit **from below only**. Nothing checks the result against the solutions you
declared too slow, which is why ratios are the better default.

When the environment configures neither, {{rbx}} falls back to a built-in formula:

```text
{{ default_timing_formula() }}
```

That literal is read out of {{rbx}}'s own source when these docs are built, so it is always the
formula {{rbx}} actually uses.

### Variables

| Variable | Meaning |
| :--- | :--- |
| `fastest` | The worst-case time of the **fastest** accepted solution. |
| `slowest` | The worst-case time of the **slowest** accepted solution. |

!!! note

    Both are a maximum across testcases, then compared across solutions. `fastest` is the
    slowest testcase of the best solution — not the quickest testcase anywhere.

### Functions

| Function | Meaning |
| :--- | :--- |
| `step_up(value, step)` | Round **up** to a multiple of `step`. `step_up(250, 100)` is `300`. |
| `step_down(value, step)` | Round **down**. `step_down(250, 100)` is `200`. |
| `step_closest(value, step)` | Round to the nearest multiple. |
| `max(a, b)` / `min(a, b)` | The larger / smaller of two values. |
| `ceil(x)` / `floor(x)` / `abs(x)` | The usual. |
| `int(x)` / `float(x)` | Conversion. |

The arithmetic operators `+`, `-`, `*`, `/`, `**` and `%` work too.

### Using a formula once

To try one without committing it to the environment:

```bash
rbx time --strategy=estimate_custom
```

{{rbx}} times the solutions as usual, then prompts for the formula to apply.

## Wall time limits

Every solution is bounded by a **wall-clock** limit as well as a CPU one. Java, Kotlin and
Python spend real time starting a JVM or an interpreter before running any of your code, so a
wall limit derived too tightly from the CPU limit produces time-limit verdicts that have nothing
to do with the solution.

{{rbx}} derives it from the CPU limit as `a * x + b`, set environment-wide and overridable per
language. It applies when judging locally and when packaging, so a package carries the same
allowance you tested against. The [Environment
reference](../reference/environment/#wall-time-limits) has the fields.
