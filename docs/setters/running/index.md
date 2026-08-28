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

## Failing fast

`--fail-fast` (`--ff`) stops a solution at its **first non-accepted verdict**, instead of
running it through the whole testset.

```bash
rbx run --fail-fast
```

{{ asciinema("fail-fast") }}

It is a shortcut for quick experimentation, and its report must not be trusted to validate a
problem: the testcases that never ran are reported as **failed**, not as unmeasured, and the
timing summary is omitted entirely, since a solution that stopped early was only timed on the
testcases that ran.

## Reading what the checker said

A checker's verdict line is only its **last** line. Everything it printed before that —
differing tokens, a dump of the offending context, whatever debugging it does — is
discarded, and even the line that survives is clipped when it is shown.

`--keep-checker-stderr` keeps the whole thing. Every testcase then gets a `.checker.err`
file next to its output, holding exactly what the checker wrote:

```bash
rbx run --keep-checker-stderr
rbx irun sol.cpp -t samples/0 --keep-checker-stderr
```

The report prints the path of the file for the testcase whose message it shows, and the
run explorer (`rbx ui`) opens it with `4`. Nothing else changes: the verdict, the
message and every other artifact are exactly what they would have been without the flag.

It is a debugging flag, not an everyday one — a `.checker.err` per testcase per solution
adds up, and almost nobody reads them. Reach for it when a verdict surprises you.

!!! tip
    You do not have to decide up front. Checker runs are cached, so re-running the same
    command *with* the flag after an unexpected verdict still writes the file — the
    checker's output is already in the cache, and the re-run is a cache hit.

## Running on the judge itself

`--runner` runs the solutions **on the judge park** rather than in the sandbox on your machine,
and reports the verdicts and timings the judge produced.

```bash
rbx run --runner moj
```

See [Running on the judge itself](/setters/running/remote/) for why you would, what the setup
needs, and what a judge cannot report back.

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

## Benchmarking the judging time

`rbx run` tells you how long each **solution** took, and nothing about how long **judging**
took. The checker, though, runs once per testcase per solution, and on a problem with a
heavy checker it can dominate the wall clock of a whole run.

`--benchmark` (`-b`) reports that cost. It takes a level, just like `-v`, and the level is
required — a bare `-b` is an error:

```bash
# 0 is the default: nothing is benchmarked, and the report is the one above
rbx run -b0

# 1 benchmarks the solution run: how long the checker — and, on an interactive
# problem, the interactor — spent judging
rbx run -b1
```

Each solution then gets an extra block under its `Time:` and `Memory:` lines, naming the
testcase that was slowest to judge, with its breakdown, and the totals over the whole
testset:

```{.bash .no-copy}
Benchmark: slowest test secret/12 - 290 ms judging (90 ms solution + 200 ms checker)
Total judging: 555 ms (checker: 215 ms)
```

Judging time is the solution's time plus the checker's, plus the interactor's on an
[interactive problem](/setters/grading/interactors/), where it appears as a third term in
both the breakdown and the totals.

When several solutions ran, the report closes with the problem-wide extremes:

```{.bash .no-copy}
Benchmark summary
Slowest solution to judge: 1.0 s, sols/slow.cpp
Most checker time: 600 ms, sols/main.cpp
Slowest testcase to judge: 501 ms, secret/12
```

Notice the durations follow the value: milliseconds below a second, seconds above it. A
`-` means the value was never measured — no checker ran on that testcase, or the sandbox
reported no clock — which is a different fact from a measured zero, and never rendered as
one.

`rbx irun` takes `-b1` too. There, the checker (and interactor) time is printed on each
testcase's block, along with the summary. There is no per-solution block: with a single
testcase, "slowest test" would say nothing.

!!! tip
    These timings are captured on **every** run, benchmarked or not — `-b` only decides
    what gets printed. So `rbx ui` shows you the checker time of a run you've already
    done, without re-running anything.

Checker runs are cached, and a cached checker reports the time it took when it actually
ran. {{rbx}} never re-runs a checker to benchmark it: the stored measurement is the
uncached cost, which is the number worth having.

Under `--fail-fast` every total is a **lower bound**, since a solution that stopped early
was only judged on the testcases that ran. The report says so:

```{.bash .no-copy}
Total judging: 3.1 s (checker: 400 ms) (over 7/40 tests judged)
```

Unlike the timing summary, which `--ff` drops entirely because time limit inference reads
it, the benchmark feeds no inference. A marked lower bound is more useful than nothing.
