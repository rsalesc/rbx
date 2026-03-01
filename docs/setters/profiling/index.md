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
# Estimate a time limit using the default formula (interactive)
rbx time

# Estimate automatically (no prompts)
rbx time --auto

# Create a profile for BOCA packaging
rbx time -p boca

# Write the estimated limits back into problem.rbx.yml
rbx time --integrate
```

## The `rbx time` command

The `rbx time` command (alias: `rbx t`) estimates a time limit for the problem by running all accepted
solutions and applying a formula to their timings.

### How it works

1. **Displays current profile** -- If a profile already exists for the given name, its current limits are shown.
2. **Strategy selection** -- You are prompted to choose how to define the time limit (unless `--auto` or `--strategy` is used).
3. **Solution execution** -- For formula-based strategies, all accepted solutions are run against all testcases with no time limit enforced, so that the true execution times can be measured.
4. **Time report** -- The fastest and slowest solution times are shown, along with per-language breakdowns if solutions in multiple languages exist.
5. **Formula evaluation** -- The formula is applied to compute the estimated time limit.
6. **Per-language limits** -- If solutions exist in multiple languages and their estimated limits differ, you are prompted to select which languages should have language-specific time limits.
7. **Profile persistence** -- The result is written to `.limits/<profile>.yml`.

### Strategies

When you run `rbx time`, you are prompted to choose a strategy:

| Strategy | Description |
| :--- | :--- |
| **Estimate** (recommended) | Runs all accepted solutions and applies the default formula to estimate the time limit. |
| **Inherit from package** | Creates a profile that inherits all limits directly from `problem.rbx.yml`. |
| **Estimate with custom formula** | Same as Estimate, but prompts you for a custom formula. |
| **Custom time limit** | Prompts you for an explicit time limit in milliseconds. |

You can skip the interactive prompt by using `--strategy` or `--auto`:

```bash
# Use the default formula without prompts
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
| `--auto` | `-a` | `false` | Automatically estimate using the default formula (no prompts). |
| `--strategy` | `-s` | _(interactive)_ | Strategy to use: `estimate`, `inherit`, `estimate_custom`, or `custom`. |
| `--integrate` | `-i` | `false` | Write the profile's limits back into `problem.rbx.yml` (see [Integrating profiles](#integrating-profiles-into-the-package)). |
| `--runs` | `-r` | `0` | Number of runs per solution. `0` uses the environment default. |
| `--detailed` | `-d` | `false` | Print a detailed table view of per-testcase results. |
| `--check` | | `true` | Build outputs and run checker during estimation. |
| `--validate` | | `true` | Validate inputs and outputs during estimation. |

### Multiple runs

By default, each solution is run once per testcase. If you want more stable timing measurements (e.g., to
reduce variance from system load), use `--runs` to run each solution multiple times:

```bash
rbx time --runs=3
```

The maximum time across all runs for each testcase is used as the timing for that testcase.

## Time limit formulas

Formula-based estimation is the recommended approach. A formula is a mathematical expression that
takes the timing data from accepted solutions and produces a time limit.

### Default formula

The default formula is:

```text
step_up(max(fastest * 3, slowest * 1.5), 100)
```

This means: take the maximum of 3x the fastest solution time and 1.5x the slowest solution time,
then round up to the nearest multiple of 100 ms.

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

# The formula that was used to estimate the time limit (informational)
formula: "step_up(max(fastest * 3, slowest * 1.5), 100)"
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
    When `rbx time` detects that your accepted solutions are written in multiple languages with different
    performance characteristics, it will prompt you to set per-language time limits automatically.

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
