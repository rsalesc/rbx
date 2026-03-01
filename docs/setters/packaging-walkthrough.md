# Packaging a problem

This walkthrough covers the full process of packaging a problem for a judge system,
from profiling time limits all the way to uploading the final package. We'll use
{{boca}} as our target judge, but the overall workflow applies to any
[supported format](/setters/packaging).

We assume you already have a working problem -- tests build, solutions run, and
expected outcomes match. If you're starting from scratch, follow the
[First steps](/setters/first-steps) walkthrough first.

## Overview

Packaging a problem involves three main stages:

1. **Profiling** -- Measure solution timings and decide on a time limit appropriate
   for the target judge's hardware.
2. **Packaging** -- Build the problem into a format the judge system understands.
3. **Uploading** -- Get the package into the judge, either manually or automatically.

## Step 1: Profile the time limit {: #profiling }

Different judge systems run on different hardware. A time limit that works on your
laptop may be too tight -- or too generous -- on the actual judging machine. {{rbx}}
solves this with **limits profiles**: named sets of time/memory limits stored in the
`.limits/` directory of your problem.

!!! info
    For a complete reference on profiling, formulas, and profiles, see the
    [Profiling](/setters/profiling) guide.

### Create a profile for BOCA

The BOCA packager **requires** a limits profile named `boca` to exist.
You create it with the `time` command. Preferrably, log in to your judge
machine, clone your contest's repository and run the command there.

```bash
rbx time -p boca
```

This launches an interactive session that:

1. Shows the current profile (if one already exists).
2. Asks you to choose a **strategy** for deciding the time limit.
3. Runs all accepted solutions with no time limit enforced, measuring their true
   execution times.
4. Applies a formula to the timings and writes the result to `.limits/boca.yml`.

!!! tip
    If you want to skip the interactive prompts and use the default formula, add the
    `--auto` flag:

    ```bash
    rbx time -p boca --auto
    ```

### Choose a strategy

When prompted, you'll see four strategies:

| Strategy                         | When to use                                                                 |
| :------------------------------- | :-------------------------------------------------------------------------- |
| **Estimate** (recommended)       | Let {{rbx}} measure your solutions and apply a formula. Best default.       |
| **Inherit from package**         | Mirror whatever `timeLimit` and `memoryLimit` are set in `problem.rbx.yml`. |
| **Estimate with custom formula** | Like Estimate, but you provide your own formula.                            |
| **Custom time limit**            | You already know the exact time limit you want.                             |

The default formula is:

```text
step_up(max(fastest * 3, slowest * 1.5), 100)
```

This takes the maximum of 3x the fastest accepted solution and 1.5x the slowest,
then rounds up to the nearest 100 ms. You can customize this formula in
`env.rbx.yml` -- see the [Profiling](/setters/profiling#time-limit-formulas) docs for
details.

### Review the resulting profile

After the estimation finishes, the profile is saved to `.limits/boca.yml`. It looks
something like this:

```yaml
# .limits/boca.yml
inheritFromPackage: false
timeLimit: 2000
memoryLimit: 256
formula: "step_up(max(fastest * 3, slowest * 1.5), 100)"
```

You can also add per-language overrides if your contest accepts solutions in multiple
languages with different performance characteristics:

```yaml
modifiers:
  py:
    time: 6000          # Python gets a higher time limit (ms)
  java:
    timeMultiplier: 2.0 # Java gets 2x the base time limit
```

!!! tip
    When `rbx time` detects accepted solutions in multiple languages, it will
    automatically prompt you to set per-language limits. You can also edit the profile
    manually or through the TUI (`rbx ui` > **Edit limits profiles**).

### Verify with the profile active

Once your profile is ready, you can run your solutions under the BOCA limits to make
sure everything still passes:

```bash
rbx -p boca run
```

The `-p` (or `--profile`) flag is a **global** flag that tells {{rbx}} to use the
specified limits profile for the run.

### Working with multiple profiles

You can create as many profiles as you need -- one per target judge:

```bash
rbx time -p boca
rbx time -p polygon
rbx time -p local    # the default profile
```

Each profile is independent, so you can tune limits for each judge's hardware
separately.

### Persisting the profile

Now, since the profile is saved into `.limits`, you can push it into your contest's repository,
and access it from any machine. Feel free to follow the next steps in any machine of your choice,
as long as you've pushed the profile into the repository.

## Step 2: Build the package {: #packaging }

With the `boca` limits profile in place, you can now build the BOCA package:

```bash
rbx package boca
```

{{ asciinema("3aYdLnJVUS6dUaF9TWg6UkFMz") }}

This command performs the following steps automatically:

1. **Loads the `boca` limits profile** from `.limits/boca.yml`.
2. **Builds all testcases** -- generators are run, inputs are validated, outputs are
   generated using the main solution.
3. **Verifies all solutions** -- every solution is run against the testcases and its
   outcome is checked.
4. **Builds statements** -- the problem statement is compiled into a PDF.
5. **Produces a `.zip` file** in the BOCA format, ready for upload.

The resulting `.zip` is saved in the problem's `build/` directory.

### Verification levels

By default, packaging runs at **verification level 4** (the maximum), which runs all
solutions and checks their expected outcomes. You can lower this to speed things up
during development:

```bash
rbx package boca -v0  # Only generate tests, no validation
rbx package boca -v1  # Generate tests and validate inputs
rbx package boca -v2  # Also run accepted solutions
rbx package boca -v3  # Also run non-TLE solutions
rbx package boca -v4  # Run all solutions (default)
```

See the [Packaging overview](/setters/packaging#rbx-package) for the full
verification level table.

### Packaging an entire contest

If you're working in a contest directory, you can package all problems at once:

```bash
rbx each package boca
```

Or target specific problems by letter:

```bash
rbx on A package boca       # Only problem A
rbx on A-C package boca     # Problems A through C
rbx on A,C package boca     # Problems A and C
```

## Step 3: Upload to BOCA {: #uploading }

Once you have your `.zip` package, you need to get it into the BOCA server. There are
two ways to do this: **automated upload** via {{rbx}} and **manual upload** through
the BOCA web interface.

### Option A: Automated upload with `-u` {: #automated-upload }

The easiest approach is to use the `--upload` (or `-u`) flag, which builds the
package **and** uploads it in a single step:

```bash
rbx package boca -u
```

{{ asciinema("onJXQDVPELqn2kITmCrbkJeCX", speed=3) }}

#### Set up BOCA credentials

For the upload to work, {{rbx}} needs to know how to connect to your BOCA server.
Set the following environment variables, either in your shell or in a `.env` /
`.env.local` file at the root of your contest:

```bash title=".env"
BOCA_BASE_URL="https://your.boca.com/boca"
BOCA_USERNAME="admin_username"
BOCA_PASSWORD="admin_password"
```

If you're using a judge account instead of an admin account:

```bash title=".env"
BOCA_BASE_URL="https://your.boca.com/boca"
BOCA_JUDGE_USERNAME="judge_username"
BOCA_JUDGE_PASSWORD="judge_password"
```

!!! warning
    The configured user **must** be an admin of the contest in BOCA, otherwise the
    upload will fail. Also make sure the correct contest is **activated** on the BOCA
    server before running the command.

#### Upload an entire contest

You can combine the upload flag with the contest-level commands:

```bash
# Upload all problems
rbx each package boca -u

# Upload only problem A
rbx on A package boca -u

# Upload problems A through C
rbx on A-C package boca -u
```

### Option B: Manual upload {: #manual-upload }

If you prefer not to configure credentials, or if your BOCA instance isn't reachable
from your machine, you can upload the package manually:

1. **Build the package** without the `-u` flag:

    ```bash
    rbx package boca
    ```

2. **Locate the `.zip` file** in the `build/` directory of your problem.

3. **Log in** to the BOCA web interface as a contest admin.

4. **Navigate** to the **Problems** tab and upload the `.zip` file for the
   corresponding problem letter.

!!! tip
    If you run into issues with BOCA packaging or uploading, check the
    [BOCA troubleshooting](/setters/packaging/boca#troubleshooting) section for
    common problems and solutions.

## Next steps

<div class="grid cards" markdown>

-   :fontawesome-solid-clock: **Fine-tune your limits**

    ---

    Learn about custom formulas, per-language modifiers, and the TUI limits editor.

    [:octicons-arrow-right-24: Profiling](/setters/profiling)

-   :fontawesome-solid-box-open: **Explore other formats**

    ---

    Package for Polygon, or other formats supported by {{rbx}}.

    [:octicons-arrow-right-24: Packaging](/setters/packaging)

-   :fontawesome-solid-file-pdf: **Build statements**

    ---

    Create PDF statements using rbxTeX, LaTeX, and Jinja.

    [:octicons-arrow-right-24: Statements](/setters/statements)

-   :fontawesome-solid-gear: **Full CLI reference**

    ---

    See all available flags and commands.

    [:octicons-arrow-right-24: CLI reference](/setters/reference/cli)

</div>
