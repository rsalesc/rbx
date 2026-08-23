# Running

{{rbx}} offers several ways to run your solutions. The sections below cover each one.

## Running solutions on the whole testset

`rbx run` runs the selected solutions on every testcase, or all declared solutions if you
select none. It reports an outcome per solution, plus timing and memory usage for the whole
testset.

{{ asciinema("run-basic") }}

Some examples:

```bash
# Run all solutions on all testcases
rbx run

# Run a single solution (or a list of solutions) on all testcases
rbx run <solution-name> ...

# Run all AC solutions on all testcases
rbx run --outcome AC

# Run all WA solutions on all testcases
rbx run --outcome WA

# Run all solutions, and provide a table-like output instead
# of the default output
rbx run -d

# Interactively pick which solutions to run
rbx run -c
```

You can also set the verification level.

```bash
rbx run -v{0,1,2,3,4}
```

You can read more about each verification level [here](/setters/verification/#verification-level).

By default, {{rbx}} runs solutions at the maximum verification level: tests are built and
verified, every solution runs with twice the time limit, and a warning appears when a TLE
solution passes within `2*TL`.

Solutions are also bounded by a configurable **wall (real) time** limit, derived from the CPU
time limit. See [Wall time limits](/setters/reference/environment/#wall-time-limits).

Inspect the results of a run with `rbx ui`:

{{ asciinema("ui-navigation") }}

## Running on the judge itself

`rbx run` runs the solutions in the sandbox on your machine. `--runner` is the other
way: run them **on the judge park**, through the judge's own CLI, and read the verdicts
and timings the judge produced.

```bash
# Run every solution on MOJ instead of locally
rbx run --runner moj
```

The setup is the same one `rbx time --runner moj` uses — you must be logged in to the
[`moj` CLI](https://github.com/cd-moj/moj-cli), and {{rbx}} uploads a throwaway problem
of its own rather than touching one you published. See [Measuring on the judge
itself](/setters/profiling/#measuring-on-the-judge-itself) for the whole story, including
what a judge cannot report back.

Two things are specific to `rbx run`:

- The judge enforces **the same time limits your local run would**: the ones from the limits
  profile in effect, per language group.
- `--fail-fast` is honoured by the judge: it stops a solution at its first non-accepted
  verdict, and the testcases it never reached are reported as skipped, as they are
  locally. Toggling the flag changes the uploaded package, so the first run after a
  toggle pays for an upload and a calibration.

`--no-check` is **refused** on a remote runner: the judge always judges with the packaged
checker, so there is no run it could do that means "do not check".

## Sharing a report

`--share` captures a run report (or a time-estimation report) as it appears in
your terminal and copies it to your **clipboard**, ready to paste into a chat, an
issue, or an email.

```bash
# Copy the run report to the clipboard as an image (PNG)
rbx run --share png

# Copy it as plain text instead
rbx run --share text

# Works for the time-estimation report too — this captures the run report
# *and* the per-language-group time limits table
rbx time --share png
```

A few things to keep in mind:

- `--share png` requires an **SVG-to-PNG converter** on your `PATH`. {{rbx}}
  looks for `rsvg-convert`, then ImageMagick (`magick`/`convert`), then macOS
  `qlmanage`. If none is found, the report is saved as an SVG file instead and
  its path is printed.
- Copying an **image** to the clipboard is supported on **macOS** and **Linux**
  (the latter needs `xclip` or `wl-copy`). On other platforms, or when no
  clipboard tool is available, the report is written to a file in your build
  directory and its path is printed.
- `--share text` works everywhere a clipboard tool is available, and falls back
  to a file otherwise.

## Running tests with custom inputs

You might want to run your solutions on a testcase that is not part of the testset, or even on a specific
testcase of the testset.

`rbx irun` does that, and selects solutions the same way `rbx run` does:

```bash
# Run a single solution (or a list of solutions) on a specific testcase
rbx irun <solution-name> ...

# Run all AC solutions on a specific testcase
rbx irun --outcome AC

# Interactively pick which solutions to run
rbx irun -c
```

By default, `rbx irun` prompts you to type a testcase input. Press `Ctrl+D` when you're done.

{{rbx}} then runs the solutions on that testcase and writes the results into files. Pass `-p`
to print them to the console instead.

{{ asciinema("irun-stdin") }}

When printing with `-p`, the solution's `stderr` is shown in its own colored section right after the output.
To weave it into the output in true line order, add `--merge-stderr` / `-e`, which shows where
each log line was emitted relative to the program's output. The interleaved `stderr` lines are
colored distinctly, and the clean output is left untouched, so the checker still sees what the
solution printed.

```bash
# Interleave stderr with the output in true line order (requires -p)
rbx irun <solution-name> -t sample/0 -p -e
```

For [interactive (communication) problems](/setters/grading/interactors/), `-e` folds the solution's `stderr`
into the interaction view as a third stream, alongside the interactor and solution messages.

!!! tip
    By default, the test you've written will be validated, so make sure you've typed it perfectly.

    If you want to disable validation, you can pass the `-v0` flag to set the verification level to 0.

You can also specify a certain testcase of the testset to run using the `-t` flag followed by the *testcase notation*, which
is composed of `<testgroup-name>/<testcase-index>`. For instance, `samples/0` is the first testcase in the `sample` testgroup,
and `secret/10` is the 11th testcase in the `secret` testgroup.

```bash
rbx irun -t sample/0
```

{{ asciinema("irun-testcase") }}

You can also name a [generator call](/setters/testset/generators/#generator-call) to produce the testcase.

```bash
rbx irun -g "gen 100 123" -p
```

{{ asciinema("irun-generator") }}