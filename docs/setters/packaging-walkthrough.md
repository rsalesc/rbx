# Packaging a problem

This walkthrough covers the process of turning a finished problem into a package a
judge system can ingest, and getting that package into the judge. We'll use
{{boca}} as our target judge, but the overall workflow applies to any
[supported format](/setters/packaging).

We assume you already have a working problem -- tests build, solutions run, and
expected outcomes match. If you're starting from scratch, follow the
[First steps](/setters/first-steps) walkthrough first.

!!! note "Prerequisite"
    The BOCA packager **requires** a *limits profile* named `boca` -- a named set of
    time and memory limits, stored in `.limits/boca.yml` -- to exist in your problem.
    You create it by profiling the problem against the judge's hardware, which is what
    [Profiling time limits](/setters/contest-profiling-walkthrough) walks you through.
    If you haven't done that yet, start there and come back once `.limits/boca.yml` is
    in place.

## Overview

Packaging a problem involves two main stages:

1. **Packaging** -- Build the problem into a format the judge system understands.
2. **Uploading** -- Get the package into the judge, either manually or automatically.

## Step 1: Build the package {: #packaging }

With the `boca` limits profile in place, you can now build the BOCA package:

```bash
rbx package boca
```

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

Or target specific problems. The selector takes short names, problem names, aliases and
folders, comma-separated, plus ranges, globs and `!` exclusions:

```bash
rbx on A package boca          # Only problem A
rbx on A..C package boca       # Problems A through C
rbx on A,C package boca        # Problems A and C
rbx on sum-of-n package boca   # By name or folder
rbx on '*,!D' package boca     # Everything except D
```

## Step 2: Upload to BOCA {: #uploading }

Once you have your `.zip` package, you need to get it into the BOCA server. There are
two ways to do this: **automated upload** via {{rbx}} and **manual upload** through
the BOCA web interface.

### Option A: Automated upload with `-u` {: #automated-upload }

The easiest approach is to use the `--upload` (or `-u`) flag, which builds the
package **and** uploads it in a single step:

```bash
rbx package boca -u
```

<!-- Still hosted on asciinema.org: reproducing an upload needs a live BOCA
     server, which the recording pipeline has no way to stand up. -->
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
rbx on A..C package boca -u
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
