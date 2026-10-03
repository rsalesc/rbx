# How the limit is computed

[`rbx time`](estimating.md) hands the measured timings to whatever rule your **environment**
configures, and that rule produces the number. There are two, and they are mutually exclusive:
**ratios**, which bound the limit from both sides, and a **formula**, which computes it from
below.

Both are set in `env.rbx.yml`, because a time limit rule is a property of the contest you are
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

1. The limit is **at least** twice the slowest accepted solution. In our problem the C++
   solution takes `37 ms`, so the C++ limit must be at least `74 ms`.
2. The limit times `1.5` must still fit inside the fastest too-slow solution. Omit it and the
   solutions expected to be too slow aren't run, so nothing bounds the limit from above.
3. Round the result up to a multiple of `100 ms`, so limits come out as round numbers.

Together, the two ratios bound the limit from both ends:

```text
acToTimeLimit × (slowest accepted)  ≤  time limit  ≤  (fastest too-slow) ÷ timeLimitToTle
```

{{rbx}} doesn't time the too-slow solutions up front, though. It takes the smallest round limit that
satisfies the left side, then checks the right side by running each too-slow solution at
`limit × timeLimitToTle`.

Take the C++ group in our problem, with the ratios above and the timings from [the
recording](index.md#estimating-a-limit): `2.0 × 37 ms = 74 ms`, rounded up to `100 ms`. {{rbx}}
then runs the quadratic solution at
`100 ms × 1.5 = 150 ms`. It's still running when that time is up, which confirms the bound.

The second ratio is why we recommend ratios. A formula only looks at the solutions that should
pass, so it can produce a limit high enough to accept the solution the problem was meant to
reject. Ratios are checked against **both** sides, and a limit that would let a
too-slow solution through is caught while estimating rather than during the contest.

When no limit satisfies both, `rbx time` names the solution that binds each side and reopens
the language-group picker, so you can regroup or keep the limit anyway. Under `--auto`, or
when the environment defines only one language, there's no picker: it doesn't write a limit, and
exits non-zero. In the same no-picker case, a failed [upper-bound
check](estimating.md#checking-the-upper-bound) still writes the limit, with the violation
recorded in the profile.

A problem can override any subset of the ratios and inherit the rest:

```yaml title="problem.rbx.yml"
timing:
  multipliers:
    timeLimitToTle: 2.0   # this problem's slow solutions are further apart
```

!!! warning "A problem cannot switch the rule on its own"
    The override adjusts ratios the environment already sets. If the environment estimates with
    a formula instead, setting `timing.multipliers` on the problem is an error. {{rbx}} doesn't
    switch rules silently, and tells you to add the block to the environment instead.

## Time limit formulas

The other rule is a formula, an expression over the accepted solutions' timings.

```yaml title="env.rbx.yml"
timing:
  formula: "step_up(max(fastest * 2, slowest * 1.5), 100)"
```

It bounds the limit **from below only**. {{rbx}} doesn't check the result against the solutions
you declared too slow, which is why ratios are the better default.

When the environment configures neither, {{rbx}} falls back to a built-in formula:

```text
{{ default_timing_formula() }}
```

### Variables

| Variable | Meaning |
| :--- | :--- |
| `fastest` | The worst-case time of the **fastest** accepted solution. |
| `slowest` | The worst-case time of the **slowest** accepted solution. |

!!! note
    Both are a maximum across testcases, then compared across solutions. `fastest` is the
    slowest testcase of the best solution, not the quickest testcase anywhere.

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

Solutions are bounded by a **wall-clock** limit as well as a CPU one. Java, Kotlin and
Python spend real time starting a JVM or an interpreter before running any of your code, so a
wall limit derived too tightly from the CPU limit produces time-limit verdicts that have nothing
to do with the solution.

{{rbx}} derives it from the CPU limit as `wallTimeMultiplier × limit + wallTimeIncrement`, set
environment-wide and overridable per language. It applies both when judging locally and when
packaging for {{boca}}, so a BOCA package gets the same allowance you tested against. The
[Environment reference](../reference/environment/index.md#wall-time-limits) has the fields.
