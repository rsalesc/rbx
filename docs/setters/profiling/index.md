# Profiling

In {{rbx}}, profiling is the process of measuring the execution time of solutions and coming
up with time limits for the problem. Time limits are stored in **limits profiles**, which can be
created and managed through the CLI or the TUI.

## Why profile?

Different judge systems (BOCA, Polygon, etc.) may run on different hardware with different performance
characteristics. A time limit that works well on your local machine may be too tight or too generous
on the actual judge. By creating separate profiles for each target system, you can fine-tune
limits independently.

Even if you only target a single judge, profiling automates the tedious process of choosing a time limit
that is generous enough for intended solutions but tight enough to reject slow ones.

## Quick start

```bash
# Estimate a time limit using the configured strategy (interactive)
rbx time

# Estimate automatically (no prompts)
rbx time --auto

# Create a profile for BOCA packaging
rbx time -p boca

# Write the estimated limits back into problem.rbx.yml
rbx time --integrate
```

## The `rbx time` command

The `rbx time` command (alias: `rbx t`) estimates a time limit for the problem by running its
solutions and applying the estimation strategy configured in the environment: either the
[time limit ratios](#time-limit-ratios) (the default) or a [formula](#time-limit-formulas).

### How it works

1. **Displays current profile** -- If a profile already exists for the given name, its current limits are shown.
2. **Strategy selection** -- You are prompted to choose how to define the time limit (unless `--auto` or `--strategy` is used).
3. **Solution execution** -- For estimating strategies, the accepted solutions are run against all testcases, so that their true execution times can be measured. Every one of them is capped at [`inferenceTimeout`](#the-estimation-cap). The solutions expected to be too slow are *not* run here; see [Checking the upper bound](#checking-the-upper-bound).
4. **Time report** -- The fastest and slowest solution times are shown, along with per-language breakdowns if solutions in multiple languages exist.
5. **Estimation** -- The ratios (or the formula) are applied to compute the estimated time limit.
6. **Language groups** -- You are shown every environment language and can place each one into a group, so related languages (e.g. `c`/`cpp`, or `java`/`kotlin`) share a single estimated limit and unrepresented languages inherit a sensible limit instead of falling back to the base. See [Language groups](#language-groups).
7. **Upper-bound check** -- Each solution expected to be too slow is run at the limit the estimate demands of it, to confirm it really is too slow. See [Checking the upper bound](#checking-the-upper-bound).
8. **Profile persistence** -- The result is written to `.limits/<profile>.yml`, together with the chosen grouping and what the check found.

All the steps in one run, taking the recommended **Estimate** strategy and the default
grouping — note the preview table updating as the languages are bucketed, and the strategy
printed just above the limits that get written:

{{ asciinema("time-estimate", speed=2) }}

### Strategies

When you run `rbx time`, you are prompted to choose a strategy:

| Strategy | Description |
| :--- | :--- |
| **Estimate** (recommended) | Runs the solutions and estimates the time limit with whatever the environment configures: the ratios or a formula. |
| **Inherit from package** | Creates a profile that inherits all limits directly from `problem.rbx.yml`. |
| **Estimate with custom formula** | Same as Estimate, but prompts you for a custom formula. |
| **Custom time limit** | Prompts you for an explicit time limit in milliseconds. |

You can skip the interactive prompt by using `--strategy` or `--auto`:

```bash
# Use the configured strategy without prompts
rbx time --auto

# Directly select a strategy
rbx time --strategy=estimate
rbx time --strategy=inherit
rbx time --strategy=custom
rbx time --strategy=estimate_custom
```

### Flags

| Flag | Short | Default | Description |
| :--- | :--- | :--- | :--- |
| `--profile` | `-p` | `local` | Name of the profile to create or update. |
| `--auto` | `-a` | `false` | Automatically estimate using the configured strategy (no prompts). |
| `--strategy` | `-s` | _(interactive)_ | Strategy to use: `estimate`, `inherit`, `estimate_custom`, or `custom`. |
| `--integrate` | `-i` | `false` | Write the profile's limits back into `problem.rbx.yml` (see [Integrating profiles](#integrating-profiles-into-the-package)). |
| `--runs` | `-r` | `0` | Number of runs per solution. `0` uses the environment default. |
| `--detailed` | `-d` | `false` | Print a detailed table view of per-testcase results. |
| `--check` | | `true` | Build outputs and run checker during estimation. |
| `--validate` | | `true` | Validate inputs and outputs during estimation. |
| `--skip-slow` | | `false` | Stop after the estimate, leaving the upper bound unchecked (see [Checking the upper bound](#checking-the-upper-bound)). |
| `--runner` | | `local` | Where to run the solutions being timed (see [Measuring on the judge itself](#measuring-on-the-judge-itself)). |

### Multiple runs

By default, each solution is run once per testcase. If you want more stable timing measurements (e.g., to
reduce variance from system load), use `--runs` to run each solution multiple times:

```bash
rbx time --runs=3
```

The maximum time across all runs for each testcase is used as the timing for that testcase.

## Time limit ratios

This is how {{rbx}} estimates by default. Instead of an expression over the measured timings,
you state how much room the accepted solutions get and how little room the solutions expected
to be too slow are allowed:

| Ratio | Meaning |
| :--- | :--- |
| `acToTimeLimit` | The time limit is **at least** this multiple of the slowest accepted solution. |
| `timeLimitToTle` | The time limit times this must still fit within the fastest solution expected to be too slow. Omit it to leave the limit unbounded from above. |
| `timeResolution` | The time limit is rounded up to a multiple of this, in milliseconds. |

Unlike a formula, the ratios bound the time limit from **both** sides, so a limit that would
let a solution meant to time out pass is caught while estimating: when no limit satisfies the
ratios, `rbx time` says which solution binds each side, writes nothing to the profile, and
exits with a non-zero status — as it does for any estimation that produces no limit, so a
pipeline running it notices.

Configure them environment-wide in `env.rbx.yml`:

```yaml
timing:
  multipliers:
    acToTimeLimit: 2.0
    timeLimitToTle: 1.5
    timeResolution: 100
```

A single problem can override any subset of them in its `problem.rbx.yml`; the ratios it does
not mention are inherited from the environment:

```yaml
timing:
  multipliers:
    timeLimitToTle: 2.0   # this problem's slow solutions are further apart
```

## The estimation cap

While the limit is being estimated there is no limit to enforce yet, so a solution left to run
freely could run forever. `timing.inferenceTimeout` is the cap the accepted solutions run under
during `rbx time`, in milliseconds, whichever strategy estimates the limit -- ratios or formula:

```yaml
timing:
  inferenceTimeout: 10000   # ms; defaults to 10s
```

An accepted solution that hits the cap is an error: its measured time is truncated, so it
cannot bound the limit from below. Raise the cap, or speed the solution up. Either way the
solution stops there -- its remaining testcases are skipped, since they would measure nothing
usable.

The cap does not apply to the solutions expected to be too slow. They are not measured at all;
they are checked against the estimated limit instead, at a limit derived from it. Raising
`inferenceTimeout` therefore does nothing for them.

A single problem can raise it in its `problem.rbx.yml`:

```yaml
timing:
  inferenceTimeout: 60000   # this problem's solutions are slower than most
```

!!! note "The old spelling"

    This used to live under `timing.multipliers`, where it only applied to ratio-based
    estimation. That spelling still works in both files, but it is deprecated, and declaring
    both in the same file is an error.

### Which solutions bound which side

By default, a solution expected to be accepted everywhere bounds the limit from below, a
solution expected to be too slow (`tle`, `tle-or-rte`) anywhere bounds it from above, and
anything else — `accepted-or-tle` in particular — bounds neither side. Override that per
solution with `inference`:

```yaml
solutions:
  - path: sols/flaky.cpp
    outcome: accepted
    inference: false      # left out of the estimation entirely; it is not run

  - path: sols/borderline.cpp
    outcome: accepted-or-tle
    inference: upper      # opt in explicitly as an upper bound
```

`inference: lower` on a solution expected to be too slow is rejected: a solution meant to
time out cannot bound the limit from below.

## Checking the upper bound

A solution expected to be too slow does not need to be measured. It needs to answer one
question: does it take at least `timeLimitToTle` times the estimated limit? Running it at
exactly that bound answers it, without waiting to find out how slow it really is.

So once the limit is decided, `rbx time` runs each of those solutions at
`timeLimitToTle × <the limit for its language>`, and reads the verdict:

- It **runs out of time** -- confirmed. It respects the upper bound, and its remaining
  testcases are skipped: one timeout settles the question.
- It **finishes** -- the upper bound is violated, and now there is a real time to report it
  with. `rbx` names the solution, what it took, and what the limit demands of it.
- It **fails some other way** (a crash, a wrong answer) -- evidence of nothing either way, and
  an error. Fix it, or set `inference: false` to leave it out.

A violation is not the end of the run. The language-group picker re-opens, this time knowing
what the check found, so its preview shows which groupings cannot work. From there you can
regroup to satisfy the bound, press ++f++ to keep the limits anyway, or cancel. Nothing is
written until you settle on one of the three.

Where there is no picker to re-open -- `--auto`, or a problem with a single language -- the
violation is reported, recorded in the profile under `upperValidation`, and the limit is
written anyway.

Re-checking after a regroup is cheap: a solution that already ran out of time at some limit
also runs out of time at any lower one, and a solution that finished is answered by arithmetic.
Only the solutions whose bound went up are run again.

Pass `--skip-slow` to stop after the estimate, leaving the upper bound unchecked:

```console
$ rbx time --skip-slow
```

Without `timeLimitToTle` there is no upper bound to check, so this phase does not run at all.

## Measuring on the judge itself

`rbx time` measures where {{rbx}} runs, so the well-lit path is to run it *on* the judge
machine. `--runner` is the other way: measure the solutions **on the judge park**, through
the judge's own CLI, and feed the timings into the same estimation you would get locally.

MOJ is the first backend:

```console
$ rbx time -p moj --runner moj
```

`rbx run` takes the same flag — see [Running on the judge
itself](/setters/running/#running-on-the-judge-itself). Each command uploads to a problem
of its own (`…-run` for `rbx run`, `…-slow` for the phase below), so alternating between
them never costs a re-upload.

You must be logged in to the [`moj` CLI](https://github.com/cd-moj/moj-cli) — {{rbx}}
reuses its session and never handles your credentials. {{rbx}} uploads a **throwaway
timing problem** of its own, named `<your-login>#rbxt-<problem-id>` and recorded in a
committed `.moj-id`, so two setters on the same problem reach the same one. It never
touches a problem it did not create: a package already bound to a real MOJ problem is
refused by name rather than overwritten.

### What the judge cannot tell you

A judge reports less than a local sandbox does, and {{rbx}} says so up front rather than
quietly reporting less:

- **No memory usage**, no `.out`/`.err` artifacts, and a verdict code rather than the
  checker's own message.
- `--runs` greater than one, a sanitizer, and interactive (`communication`) problems are
  **refused by name** before anything is uploaded — each would produce a report answering a
  different question than the one you asked.

### The two phases, and the two uploads

MOJ enforces the time limit from inside the package, so the limit {{rbx}} is measuring
under has to be *in* what it uploads. The two phases measure under different limits:

1. **Estimating** runs the accepted solutions under the [estimation
   cap](#the-estimation-cap), one limit for every language.
2. **Checking the upper bound** runs the solutions expected to be too slow at
   `timeLimitToTle × <the limit for its language>`, which differs per language group.

So the package is uploaded twice, and the second upload usually costs a calibration wait
too. Each round trip through the language-group picker that *changes* a limit costs
another one. Finished runs are cached, so re-running `rbx time`, or regrouping back onto
limits already probed, costs no judge time at all — and `--skip-slow` stops after the
estimate, which is the one-upload path.

## Time limit formulas

A formula is the alternative to the ratios above: a mathematical expression that takes the
timing data from accepted solutions and produces a time limit. It bounds the limit from below
only — nothing checks it against the solutions expected to be too slow. Set `timing.formula`
in `env.rbx.yml` to use it; it is mutually exclusive with `timing.multipliers`.

### Default formula

When the environment configures neither ratios nor a formula, {{rbx}} falls back to a built-in
default formula, which is currently:

```text
{{ default_timing_formula() }}
```

That literal is read from `DEFAULT_TIMING_FORMULA` in `rbx/box/environment.py` when these docs
are built, so it is always the formula {{rbx}} actually estimates with — the code is the
authoritative source, not this page. Read it with the [variables](#variables) and
[functions](#functions) below: the outer `step_up(..., 100)` rounds the estimate up to the
nearest multiple of 100 ms.

### Variables

| Variable | Description |
| :--- | :--- |
| `fastest` | Maximum time (in ms) of the fastest accepted solution across all testcases. |
| `slowest` | Maximum time (in ms) of the slowest accepted solution across all testcases. |

!!! note
    `fastest` and `slowest` refer to the maximum time across testcases for the fastest/slowest _solution_,
    not the fastest/slowest individual testcase. In other words, `fastest` is the worst-case time of the
    best solution.

### Functions

| Function | Description |
| :--- | :--- |
| `step_up(value, step)` | Round `value` **up** to the nearest multiple of `step`. E.g., `step_up(250, 100)` = `300`. |
| `step_down(value, step)` | Round `value` **down** to the nearest multiple of `step`. E.g., `step_down(250, 100)` = `200`. |
| `step_closest(value, step)` | Round `value` to the **closest** multiple of `step`. |
| `max(a, b)` | Maximum of two values. |
| `min(a, b)` | Minimum of two values. |
| `int(x)` | Convert to integer. |
| `float(x)` | Convert to float. |
| `ceil(x)` | Ceiling function. |
| `floor(x)` | Floor function. |
| `abs(x)` | Absolute value. |

Standard math operators are also available: `+`, `-`, `*`, `/`, `**`, `%`.

### Providing a custom formula

You can provide a custom formula in three ways:

=== "CLI flag"

    ```bash
    rbx time --strategy=estimate_custom
    # You will be prompted to enter the formula interactively
    ```

=== "Environment file"

    Set the default formula in your `env.rbx.yml`:

    ```yaml
    timing:
      formula: "step_up(max(fastest * 2, slowest * 1.5), 100)"
    ```

    Read more in the [Environment reference](../reference/environment/#timing-estimation).

### Formula examples

```text
# Conservative: 2x fastest, 1.5x slowest, round to 500ms
step_up(max(fastest * 2, slowest * 1.5), 500)

# Tight: 1.5x slowest, round to 100ms
step_up(slowest * 1.5, 100)

# Fixed multiplier on fastest
step_up(fastest * 4, 100)
```

## Language groups

By default, a single time limit is estimated from the pooled timings of all accepted solutions
and applied to every language. This is a problem when your accepted solutions don't cover every
language your contest accepts: a language with no solutions (say, Java in a problem solved only in
C++ and Python) would simply inherit the base limit, which may be far too tight for it.

**Language groups** solve this. When you run `rbx time`, you are shown every environment language
and can bucket related languages together. Each group gets its own estimated time limit from the
formula, computed from the pooled timings of the accepted solutions in that group:

- **Grouped** `[N]` -- the language belongs to numbered group `N` (`1`–`9`). Languages in the
  same group share one estimated limit. Place compiled languages like `c`/`cpp` together, and
  `java`/`kotlin` together.
- **Singleton** `[X]` -- the language gets its own bucket (toggle with `space`/`tab`).
- **Unbucketed** `[ ]` -- the default. All unbucketed languages join a single **leftover pool**
  that is estimated together, so an unrepresented language inherits a represented sibling's limit
  instead of the base limit. The leftover row is listed **first** in the table, marked with a `*`.

The picker is **prepopulated from `env.rbx.yml`**: any groups you configure there appear
preselected. After estimation, a per-group table is printed showing the estimated time limit
for each group.

### Forcing a relative limit

While in the picker you can **force** a group's time limit to be computed relative to another
group instead of from its own measured timings:

- Press <kbd>r</kbd> on a language to open an inline editor and derive its group's limit from
  another group as `multiplier × reference + increment` (the formula is shown in the editor).
  The reference can be another group or the **base estimate**; the increment is an optional
  constant in milliseconds. In the editor, <kbd>Tab</kbd> switches the focused field
  (reference / multiplier / increment), <kbd>←</kbd>/<kbd>→</kbd> (or <kbd>h</kbd>/<kbd>l</kbd>)
  change the reference, you type to set the multiplier and increment, <kbd>Enter</kbd> commits,
  <kbd>Esc</kbd> cancels, and <kbd>c</kbd> clears the rule.
- Press <kbd>R</kbd> to reset the whole grouping and all relative rules back to what
  `env.rbx.yml` defines.

Unlike the env `whenEmpty` fallback (which only applies to groups that have **no** solutions),
a forced relative **always overrides** the group's measured estimate.

!!! warning "A derived limit can be one the group's own solutions cannot meet"

    Because the override is total, a group can end up with a limit **below** what its own
    accepted solutions need -- deriving `java` from `cpp` at `×1.0` gives it `cpp`'s limit
    however slow the Java solutions actually are. {{rbx}} checks every derived limit against
    the group's own measurements and flags the row in the table, in the picker preview as
    well as in the final report:

    ```
    java  1  200 ms  ×1.0 of cpp ⚠ needs ≥ 1800 ms (sol.java takes 900 ms)
    ```

    The row is red when the group's accepted solutions do not pass at the limit at all, and
    yellow when they pass but without the margin `acToTimeLimit` asks for. The bound is
    recorded in the profile under `lowerViolation`. This is a warning, not an error: the
    limit is written as asked, so regroup or drop the reference if it was not what you
    meant.

Press <kbd>Enter</kbd> to confirm, or pass `--auto` to skip the prompt and use the configured
env groups as-is.

Groups are configured (and given empty-group fallbacks via `whenEmpty`) in `env.rbx.yml`. See the
[Environment reference](../reference/environment/#language-groups) for the full schema and
semantics.

## Wall time limits

In addition to the CPU time limit estimated above, every solution is bounded by a **wall (real)
time** limit. Slow languages (Java, Kotlin, Python) spend significant wall-clock time on JVM /
interpreter startup before doing any real work, so a wall limit derived too tightly from the CPU
limit produces spurious time-limit verdicts.

{{rbx}} computes the wall time limit from the CPU time limit with a configurable `a * x + b`
formula (`wallTimeMultiplier` and `wallTimeIncrement`), configurable environment-wide and
overridable per language. The same formula is used both when judging locally and when packaging
for BOCA. See the [Environment reference](../reference/environment/#wall-time-limits) for details.

## Limits profiles

Profiles are the mechanism {{rbx}} uses to store and manage time/memory limits independently of
the problem package itself. Each profile is a YAML file stored in the `.limits/` directory of your
problem.

### File structure

```
my-problem/
├── problem.rbx.yml
├── .limits/
│   ├── local.yml        # Default profile
│   ├── boca.yml         # Profile for BOCA packaging
│   └── polygon.yml      # Profile for Polygon packaging
```

### Profile schema

A profile file follows the [`LimitsProfile`](/schemas/LimitsProfile.json) schema:

```yaml
# .limits/local.yml

# Inherit all limits from problem.rbx.yml instead of specifying them here.
# When true, the fields below are ignored.
inheritFromPackage: false

# Global limits
timeLimit: 2000       # Time limit in milliseconds
memoryLimit: 256      # Memory limit in MB
outputLimit: 65536    # Output limit in KB

# Per-language overrides
modifiers:
  py:
    time: 6000        # Python gets a higher time limit (ms)
  java:
    timeMultiplier: 2.0  # Java gets 2x the base time limit

# What the time limit was estimated with (informational): the ratios, or the
# formula when the environment configures one instead.
multipliers:
  acToTimeLimit: 2.0
  timeLimitToTle: 1.5
  timeResolution: 100

# How languages were grouped during estimation (presentation-only metadata,
# written automatically by `rbx time`; never used for limit resolution).
groups:
  - languages: [c, cpp]
    timeLimit: 2000
  - languages: [py]
    timeLimit: 6000
```

### Per-language modifiers

The `modifiers` section allows you to override limits for specific languages. This is useful
when your problem accepts solutions in multiple languages with very different performance characteristics.

| Field | Description |
| :--- | :--- |
| `time` | Override the time limit for this language (in ms). Replaces the global `timeLimit`. |
| `timeMultiplier` | Multiply the effective time limit by this factor. Applied **after** `time` if both are set. |
| `memory` | Override the memory limit for this language (in MB). |

The effective time limit for a language is computed as:

1. Start with the global `timeLimit`.
2. If the language has a `time` modifier, use that instead.
3. If the language has a `timeMultiplier`, multiply the result by it.

!!! tip
    You don't usually edit `modifiers` by hand. When you run `rbx time`, the interactive
    [language groups](#language-groups) picker estimates a limit per group of languages and writes
    the resulting per-language modifiers for you.

### The `local` profile

By default, `rbx time` writes to a profile named `local`. This profile is used when you run
solutions with `rbx run` without specifying a profile.

### Using profiles when running solutions

You can tell {{rbx}} to use a specific limits profile when running solutions with the global `--profile` flag:

```bash
rbx --profile=boca run
rbx -p polygon run
```

This applies the limits from the specified profile instead of the package defaults.

### Using profiles when building statements

The statement build commands accept a `-p` / `--profile` flag so the time limits
printed in the statement reflect a specific profile:

```bash
rbx statements build -p icpc
rbx contest statements build -p icpc
```

At the problem level the command fails if the profile doesn't exist; at the
contest level problems missing the profile are skipped with a warning. See
[Building statements](../statements/index.md#rendering-against-a-timing-profile)
for details.

### Profiles and packaging

When you package a problem, {{rbx}} automatically uses the profile that matches the packager name.
For example, the BOCA packager looks for a profile named `boca`:

```bash
# First, create the boca profile
rbx time -p boca

# Then package for BOCA
rbx package boca
```

!!! warning
    The BOCA packager **requires** a profile named `boca` to exist. If it doesn't, the packager will fail
    and ask you to run `rbx time -p boca` first.

### Inheriting from the package

If you want a profile to simply mirror the limits defined in `problem.rbx.yml`, you can create
an inheriting profile:

```bash
rbx time --strategy=inherit -p polygon
```

This creates a `.limits/polygon.yml` with `inheritFromPackage: true`. The profile will always
reflect whatever limits are set in `problem.rbx.yml`.

### Integrating profiles into the package

If you've estimated limits in a profile and want to write them back into `problem.rbx.yml`
(for example, to make them the new defaults), use the `--integrate` flag:

```bash
rbx time --integrate -p local
```

This copies `timeLimit`, `memoryLimit`, `outputLimit`, and any `modifiers` from the profile
into your `problem.rbx.yml`. It is useful when you've fine-tuned limits in a profile and want
to persist them as the package defaults.

## Editing profiles in the TUI

You can also create and edit limits profiles visually using the {{rbx}} TUI:

```bash
rbx ui
```

Select **"Edit limits profiles"** from the main menu to open the limits editor. The editor provides:

- **Profile sidebar** -- Browse and select from all existing profiles in `.limits/`.
- **Create new profile** -- Type a name and press Enter to create a new profile.
- **Inherit toggle** -- Switch between inheriting from the package or setting custom limits.
- **Global limits** -- Edit `timeLimit` and `memoryLimit` directly.
- **Per-language modifiers** -- Add or edit `time`, `timeMultiplier`, and `memory` overrides for specific languages.
- **Save** (<kbd>Ctrl+S</kbd>) -- Write changes to disk.
- **Delete** (<kbd>d</kbd> twice) -- Delete the selected profile.

!!! tip
    The TUI is especially handy for quickly tweaking per-language modifiers after an initial
    `rbx time` estimation.

## Manually editing profiles

Since profiles are plain YAML files in the `.limits/` directory, you can also edit them directly
with any text editor. The schema is available at [`LimitsProfile`](/schemas/LimitsProfile.json).

You can add the following YAML language server directive at the top of your profile file for
editor autocompletion and validation:

```yaml
# yaml-language-server: $schema=https://rsalesc.github.io/rbx/schemas/LimitsProfile.json
```

## Environment variable override

You can globally scale all time limits by setting the `RBX_TIME_MULTIPLIER` environment variable:

```bash
RBX_TIME_MULTIPLIER=1.5 rbx run
```

This multiplies all effective time limits by the given factor, which can be useful for running
on slower hardware without changing any profile.
