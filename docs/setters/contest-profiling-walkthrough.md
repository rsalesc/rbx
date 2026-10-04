# Profiling time limits

This walkthrough covers how a contest arrives at the time limits its judge will actually
enforce: profiling one problem until you trust the number, sweeping the rest of the set,
verifying under the result, and committing it.

!!! note "Prerequisite"
    This page continues the `summer-cup` contest from
    [Scaffolding a contest](/setters/contest-scaffolding-walkthrough) -- problems `A`,
    `B` and `C` sitting in `problems/chocolate`, `problems/gardens` and
    `problems/sum-of-n`. If you haven't gone through it yet, start there.

Since the last step of the guide, `gardens` has gained more solutions: accepted ones in C++
and Python, and `sols/quadratic.cpp`, declared `outcome: tle`. `chocolate` doesn't declare
any slow solution.

[Scaffolding a contest](/setters/contest-scaffolding-walkthrough) ended on `rbx contest summary`, and that table printed a time limit for every
problem. Each of those numbers is the `timeLimit` its author typed into `problem.rbx.yml`
on their own laptop, picked because it felt about right at the time. Let's replace all three
with numbers measured for the judge.

## One limit per judge, not one per problem

A time limit isn't a property of the problem alone. It belongs to the problem *on some
hardware*, and a contest usually involves at least two: the laptop you develop on, and the
judge's machines.

{{rbx}} keeps them apart in **limits profiles** -- a named set of limits stored in a file
under `.limits/`, one per target:

```
problems/gardens/
├── problem.rbx.yml
└── .limits/
    ├── local.yml    # what `rbx run` uses when you ask for nothing
    └── boca.yml     # the judge we're shipping to
```

Notice `.limits/` sits *beside* `problem.rbx.yml`, inside the problem. There is no
contest-level profile: every problem gets its own `.limits/boca.yml`, because every problem
needs its own measurement.

Each packager looks for a profile named after itself, so `rbx package boca` reads the
profile named `boca`. That's why we profile into that name now.

!!! info
    What a profile contains and every command that reads one are covered in
    [Limits profiles](/setters/profiling/profiles).

## Profiling one problem

Let's do `B` first, by hand, so you understand the numbers before letting {{rbx}}
produce them unattended.

```bash
cd problems/gardens
rbx time -p boca
```

{{ asciinema("contest-time-profile") }}

The command first shows the current limits of `gardens` (`1000 ms`, read from its
`problem.rbx.yml`), and then asks how you want the new limit defined. The highlighted
default is the one we want: measure the accepted solutions and apply the rules the
environment configures.

Then nothing new appears on screen for a while: {{rbx}} is timing both accepted solutions.
The command hasn't stalled.

Next, {{rbx}} asks how to group the languages. Languages in the same group share one time
limit ([Language groups](/setters/profiling/language-groups) explains why). Press ++enter++
to accept the default grouping. The table that follows shows:

- **The limit for `gardens`:** a `timeLimit` of `100`, estimated from the accepted
  solutions. [How the limit is computed](/setters/profiling/computing) shows the arithmetic.
- **The `java, kt` row:** it reads `×2.0 of cpp` with zero solutions. `gardens` has no Java
  solution to measure, so this limit comes from a rule in the environment
  ([Configuring groups in the environment](/setters/profiling/language-groups#configuring-groups-in-the-environment)).
- **The `(base)` row:** the limit for languages outside every group.
- **The `*`:** it marks the leftover pool, the languages you didn't put in a group
  ([Bucketing languages](/setters/profiling/language-groups#bucketing-languages)).

The run closes on the check that makes the number trustworthy:

```
✓ 1 solution expected to be too slow was confirmed too slow for the estimated limit.
```

That's `sols/quadratic.cpp`, the solution `gardens` declares with `outcome: tle`, run at the
limit {{rbx}} just picked and timing out as it was supposed to. A limit nothing is checked
against is still a guess.

!!! warning "`100 ms` next to a declared `1000 ms`"
    `problem.rbx.yml` says `timeLimit: 1000` and the profile says `100`. Nothing is wrong.
    In this problem the C++ solution runs in under `30 ms` and the Python one in under
    `50 ms`, the environment asks for twice the slowest accepted solution, and the result
    rounds up to the nearest `100 ms`. The `1000` was the author's guess; the `100` is a
    measurement. Your own problems will get whatever limit *their* solutions call for.

## Reading the profile you got

The estimate is a file, and you can open it:

```bash
head -18 .limits/boca.yml
```

The top of the file is the part you'll read: the limit, the per-language `modifiers`
that express the grouping, and the `multipliers` ratios it was estimated under:

```yaml title=".limits/boca.yml"
timeLimit: 100
modifiers:
  py:
    time: 100
  java:
    time: 200
  # ...
multipliers:
  acToTimeLimit: 2.0
  timeLimitToTle: 1.5
  timeResolution: 100
```

The file runs to about seventy lines, though. Below what's shown above, each group gets a
record of *where its number came from*: whether it was `estimated` from its own solutions
or derived by `multiplier` from another group, how many solutions it was drawn from, and
what the upper-bound check found. Don't edit that part by hand: the next `rbx time`
overwrites it.

You can edit the limits themselves by hand. Maybe the judge's machines are being replaced next
month, or a language's solutions in this problem are unrepresentative. In cases like
these, set `timeLimit` or a `modifiers` entry directly, and {{rbx}} uses your value until
you re-run `rbx time -p boca`, which overwrites it.

## The rest of the contest

`gardens` is done. The other two problems don't need you to sit through a strategy menu
again, so let's stop answering prompts. Back at the contest root:

```bash
rbx each time -p boca --auto
```

{{ asciinema("contest-time-sweep") }}

`--auto` skips **both** questions: it takes the environment's configured strategy, and it
takes the environment's own language partition instead of opening the picker. This is the
approach we recommend: profile one problem interactively until you understand the numbers,
then run the whole set unattended.

`rbx each` opens the command app: a sidebar listing every problem on the left, the selected
problem's output on the right. A few things to know before you watch it run:

- **The pane does not follow the sweep.** The selection stays on `A` from start to finish.
- **The app doesn't exit when the sweep finishes.** It sits there. Press ++q++ to quit.
- **A failure in one problem doesn't stop the others.** Every problem runs; the ones that
  broke are the ones with a red mark when it's over.

The pane is still on `A`, so compare it against `B`. `chocolate` doesn't declare any
solution as too slow, so there is no upper bound to derive or check, and its report ends
after the limits table, with no "confirmed too slow" line. For a problem like this, that's
the *expected* outcome, and no step failed silently. The ratios it prints still mention the
upper-bound rule, even though nothing triggers it here.

There is now one file per problem:

```
problems/chocolate/.limits/boca.yml
problems/gardens/.limits/boca.yml
problems/sum-of-n/.limits/boca.yml
```

To redo a subset rather than the whole contest, `rbx on` takes the same command:

```bash
rbx on A,C time -p boca --auto   # two problems, in the command app
rbx on B time -p boca --auto     # one problem, straight in your terminal
```

With one problem there is only one command to run, so {{rbx}} skips the app and runs it in
place. With two or more, you get the sidebar again.

`-i` (`--inline`) makes that the rule rather than the exception. It runs every problem's
chain straight in your terminal, one after another, printing which command is running for
which problem and nothing else:

```bash
rbx on -i A,C time -p boca --auto
rbx each --inline time -p boca --auto
```

You give up the sidebar and the per-problem scrollback; in return you get plain output you
can pipe or keep in a log, and a non-zero exit code if any command failed. Use it when
you're working on a few problems, and from a script or any other tool that can't drive a
TUI.

!!! tip
    `-k` (`--keep-going`) keeps a problem's chain running after one of its commands fails.
    It belongs to `rbx on` and `rbx each`, not to `time`, so it has to come **before** the
    command it wraps -- and before the problem selector too, on `rbx on`:
    `rbx on -k A,C time -p boca --auto`.

## Reading the three numbers together

The sweep wrote a `.limits/boca.yml` into each problem, and the command the scaffolding
page ended on is the place to read them side by side:

```bash
rbx contest summary
```

The main table is unchanged -- those are still the package limits, the ones each author
typed. Below it there is now one extra table per profile any problem saved, so a
`Profile: boca` table lists what every problem will actually be judged under on the judge.
A problem the sweep skipped shows up there too, dimmed, under its package limits: that is
the fallback packaging would use, and the dimming is the reminder that nobody measured it.

## Verifying under the new limits

New limits are a new judgment on every solution you have, and the fastest way to find out
whether they hold is to run against them:

```bash
rbx each run -p boca
```

Same app, same three tabs, and this time every solution in the contest is judged under
`.limits/boca.yml` rather than under `problem.rbx.yml`. As before profiling, every
solution should get the outcome it declares.

If an {{tags.accepted}} solution now fails, the limit is too tight for it. You can fix this
in one of two ways, and they mean different things:

- **Re-profile.** If the machine was loaded, or the solution changed since the estimate,
  the measurement was bad. Run `rbx time -p boca` again -- and see
  [running each solution several times](/setters/profiling/estimating#running-each-solution-several-times)
  for the flag that makes samples from a machine with unstable timings usable.
- **Raise that language's limit.** If the measurement was fine and the language is simply
  slower than its group's estimate allows for, the grouping is what's wrong. Bump its
  `modifiers` entry, or regroup it in the picker.

Don't keep widening the base limit until the failure goes away. The upper-bound check
exists to catch exactly that, and it will.

## Committing the profiles

Whoever builds the packages needs the profile you measured, so commit it:

```bash
git add problems/*/.limits/boca.yml
git commit -m "profile time limits for the judge"
```

You won't have to fight `.gitignore` for it. The default preset's problem `.gitignore`
ignores one profile and one only:

```gitignore title="problems/gardens/.gitignore"
# ...
.limits/local.yml
# ...
```

The preset ignores `local` on purpose. It's measured on whichever laptop happened to
run `rbx time`, so it means nothing to anyone else and gets rewritten all the time. Every
other profile describes a real judge, and belongs in the repository as soon as it's
written. `boca.yml` is tracked from the start.

Which leaves the question of *where* you measured. A limit is a claim about hardware, so
the honest place to run `rbx time` is the judging machine itself: log into it, clone the
contest, sweep, commit. If you can't, and often you can't, your laptop is fine. It is still
enormously better than the number an author guessed, as long as you know which machine the
profile is describing.

!!! info
    There's a third option for some judges: `rbx time --runner` runs the measurements
    **on the judge itself** while you stay at your desk. It supports MOJ and DOMjudge today
    (not BOCA), and needs access to the judge. See
    [Measuring on the judge itself](/setters/profiling/remote).

## Next steps

Every problem in the contest now has limits measured for the judge, and the packagers
know where to find them.

<div class="grid cards" markdown>

-   :fontawesome-solid-rocket: **Package and ship a problem**

    ---

    Continue the track: turn a profiled problem into a `.zip` the judge can ingest, and
    upload it.

    [:octicons-arrow-right-24: Packaging a problem](/setters/packaging-walkthrough)

-   :fontawesome-solid-clock: **The whole of profiling**

    ---

    Strategies, the ratios behind the number, per-language modifiers, and the group picker
    in full.

    [:octicons-arrow-right-24: Profiling](/setters/profiling)

-   :fontawesome-solid-file-lines: **Build the task sheet**

    ---

    Statements print the time limit, so they take a profile too.

    [:octicons-arrow-right-24: Contest statements](/setters/statements/contest)

</div>
