# Issues

Issues are the findings {{rbx}} prints after `rbx run`, and whenever you call `rbx issues`. Each one
points at something that's wrong with your problem, or that you should check before the contest.
From a contest folder, `rbx contest issues` shows one row per problem, and `-d` expands each row
into the problem's full list.

There are two families:

- **Package issues** are about how the package is written, so they hold before you ever run
  anything. For example, a problem without a validator.
- **Run issues** come from the last `rbx run`. For example, a solution that didn't get the verdict
  you declared for it.

An issue marked `x` is an **error**: the package doesn't behave the way it says it does. An issue
marked `!` is a **warning**: the package may be fine, but you should check.

## Reading an issue

{{rbx}} prints each issue on one line, and ends the line with the issue's **code** in parentheses:

```text
! sols/main.cpp took 74.2s over the whole testset (budget 60s) (slow-accepted-solution)
! the problem has no validator (no-validator)
```

The code in parentheses is how you look an issue up on this page, and how you tell {{rbx}} to stop
reporting it.
Run `rbx issues -d` to see a longer explanation under each issue.

## Ignoring issues

Some issues don't apply to every problem. An interactive problem may come without samples on
purpose, so `no-samples` is noise there.

To stop reporting an issue for a problem, list its code under `issues.ignore` in the problem's
`problem.rbx.yml`:

```yaml title="problem.rbx.yml"
issues:
  ignore:
    - no-samples
    - compilation-warnings
```

You can do the same in `contest.rbx.yml` to ignore an issue for every problem of the contest. A
problem's own list adds to its contest's, so a problem can ignore more than its contest does, but
never less.

```yaml title="contest.rbx.yml"
issues:
  ignore:
    - compilation-warnings
```

The ignore list applies everywhere issues show up: `rbx issues`, `rbx run`, `rbx contest issues`
and the findings in `rbx summary`.

{{rbx}} rejects a code it doesn't know. A misspelled code fails the package load with a validation
error.

Ignored issues don't disappear completely. Under the list, `rbx issues` prints how many issues it
hid and their codes. `rbx issues --all` (`-a`) lists them with the rest, marked `-` and tagged
`(ignored <code>)`. In `--format json`, they move from `issues` to a separate `ignored` list.

## Tuning thresholds

A few issues fire when something gets too big or too slow. Your preset's
[environment file](setters/reference/environment/index.md), `env.rbx.yml`, sets their limits
under `issues.thresholds`:

```yaml title="env.rbx.yml"
issues:
  thresholds:
    testsetSizeMb: 20 # (1)!
    acceptedTotalTimeSeconds: 60 # (2)!
    stderrSizeMb: 1 # (3)!
```

1. The largest the built testset may get, in MiB. Used by [`large-testset`](#large-testset).
2. The most CPU time an accepted solution may spend summed over every test, in seconds. Used by
   [`slow-accepted-solution`](#slow-accepted-solution).
3. The most a solution may print to stderr on one test, in MiB. Used by
   [`noisy-stderr`](#noisy-stderr).

The snippet shows the current defaults, which the
[environment schema](setters/reference/environment/schema.md) also lists. You only need to write
the ones you want to change. A threshold you leave out keeps its default.

Thresholds live in the environment rather than in each problem because they describe the judge your
problems go to, and every problem of a contest goes to the same judge. To let one problem go over a
threshold, ignore the issue for that problem instead.

## Package issues

### `no-accepted-solution` {: #no-accepted-solution }

**Error.** No solution in `problem.rbx.yml` is declared `accepted` or `accepted or tle`.

Without an accepted solution, nothing establishes what a correct output is, so every expected
answer the package generates is unverified. Declare your model solution with `outcome: accepted`.

### `no-validator` {: #no-validator }

**Warning.** The problem doesn't declare a validator.

Without one, you can't be sure the generated tests obey the constraints the statement promises. See
[Validators](setters/verification/validators.md) for how to write one. If you write every test by
hand and check them some other way, ignore this issue for the problem.

### `no-samples` {: #no-samples }

**Warning.** The `samples` group doesn't have any tests, so the statement has no examples to show.

Interactive problems sometimes come without samples on purpose. Ignore this issue for those.

### `empty-test-group` {: #empty-test-group }

**Warning.** A group declared in `problem.rbx.yml` doesn't have any tests.

This is usually a generator script that doesn't call anything, or a glob that doesn't match any
file. The issue says which group it is. The `samples` group is left to `no-samples` instead.

### `large-testset` {: #large-testset }

**Warning.** The built testset, inputs and expected answers together, is larger than
`testsetSizeMb`.

Judges cap how large a package may be, and a large testset makes every upload and every submission
slower. Look for redundant large tests first. If the problem does need them, ignore this issue for
the problem, or raise the threshold for the whole environment.

{{rbx}} measures the tests on disk, so this issue appears only once the tests are built, by
`rbx build` or `rbx run`.

**Tunable** with [`testsetSizeMb`](#tuning-thresholds).

### `missing-statement-language` {: #missing-statement-language }

**Warning.** The problem has no statement at all.

`rbx contest issues` also reports a problem that has no statement in one of the languages the
contest's statements use. `rbx issues` and `rbx run` look at one problem at a time, so they report
only a problem with no statement whatsoever.

### `explanation-missing-language` {: #explanation-missing-language }

**Warning.** A sample explanation file written with language blocks doesn't define a block for every
language the problem has a statement in.

The statement in the missing language goes without that explanation, and the statement build
doesn't warn you about it. The issue says which sample and which file it is.

## Run issues

These come from the last `rbx run`, and change every time you run again.

### `unmet-expectation` {: #unmet-expectation }

**Error.** A solution didn't get the verdict its `outcome` or `outcomePerGroup` declares. For
example, a solution declared `wrong answer` that was accepted.

Either the solution or its declaration is wrong. `rbx issues -d` shows the expected verdict, the
verdict it got and the groups that failed.

### `unexpected-score` {: #unexpected-score }

**Error.** On a points problem, a solution scored outside the `score` range it declares.

### `compilation-failed` {: #compilation-failed }

**Error.** A solution didn't compile, so it didn't run at all.

This one is easy to miss otherwise, since a solution that fails to compile is left out of the run's
table entirely. `rbx issues -d` links the compilation log.

### `compilation-warnings` {: #compilation-warnings }

**Warning.** A solution compiled, but the compiler printed warnings. `rbx issues -d` lists the first
few, and links the full log.

### `sanitizer-finding` {: #sanitizer-finding }

**Warning.** On a run with sanitizers, such as `rbx run -s`, a sanitizer reported something, like an
out-of-bounds access or a signed overflow.

The verdict may well be right on your machine and different on the judge. `rbx issues -d` links the
sanitizer output.

### `borderline-tle` {: #borderline-tle }

**Warning.** A solution declared as too slow did time out, but finished within twice the time limit.

By default, {{rbx}} runs every solution with twice the time limit, and reports a time-out for
anything past the real limit. A solution declared as too slow that still finishes inside that
doubled window is only barely too slow, so the testset doesn't prove what its declaration claims.
Consider adding a test that makes it decisively slow.

### `hidden-verdict` {: #hidden-verdict }

**Warning.** A solution was reported as too slow, but behind the time-out it gave a verdict its
declaration doesn't allow, such as a wrong answer. Once the time limit changes, that verdict can
surface on the judge.

### `noisy-stderr` {: #noisy-stderr }

**Warning.** A solution printed more than `stderrSizeMb` to stderr on one test.

That's almost always debug output left behind. It costs time on every test, and some judges fail a
submission that prints this much. `rbx issues -d` links the largest stderr file.

**Tunable** with [`stderrSizeMb`](#tuning-thresholds).

### `slow-accepted-solution` {: #slow-accepted-solution }

**Warning.** A solution declared `accepted` spent more than `acceptedTotalTimeSeconds` of CPU time,
summed over every test.

Every test may fit the time limit comfortably and the total still cost the judge minutes for every
correct submission, which adds up quickly during a contest. Look for redundant large tests.

{{rbx}} checks this only after a run that evaluated every test without sanitizers. A sum over part
of the testset understates the total, and sanitizers make every test slower than it would be on the
judge.

**Tunable** with [`acceptedTotalTimeSeconds`](#tuning-thresholds).

### `untuned-limits` {: #untuned-limits }

**Warning.** Solutions missed their expectations by being too fast or too slow, on a run that ran
every test and used the limits declared in `problem.rbx.yml` rather than a
[limits profile](setters/profiling/index.md) (`rbx run -p <profile>`).

The declared limits may not suit your hardware. Run `rbx time` to estimate a profile on this
machine.
