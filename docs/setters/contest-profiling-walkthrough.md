# Profiling time limits

This walkthrough covers how a contest arrives at the time limits its judge will actually
enforce: profiling one problem until you trust the number, sweeping the rest of the set,
verifying under the result, and committing it.

!!! note "Prerequisite"
    This page continues the `summer-cup` contest from
    [Scaffolding a contest](/setters/contest-scaffolding-walkthrough) -- problems `A`,
    `B` and `C` sitting in `problems/chocolate`, `problems/gardens` and
    `problems/sum-of-n`. If you haven't gone through it yet, start there.

Step 1 ended on `rbx contest summary`, and that table printed a time limit for every
problem. Look at where those numbers came from: each one is the `timeLimit` its author
typed into their own `problem.rbx.yml`, on their own laptop, at whatever moment the
problem felt about right. Three problems, three machines, three guesses.

The judge is none of those machines. Let's replace all three numbers with numbers measured
for it.

## One limit per judge, not one per problem

The limit a problem ships with is not a property of the problem. It's a property of the
problem *on some hardware*, and a contest usually has at least two: the laptop you develop
on, and the park that runs the event.

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
needs its own measurement. What's contest-wide here is the **name**, and keeping it
identical across the set is the whole trick of this page.

That name is not yours to invent. Each packager looks for a profile called after itself, so
the profile that `rbx package boca` will read is the one named `boca` -- which is why we
profile into that name now, several steps before packaging comes up in
[Packaging a problem](/setters/packaging-walkthrough).

!!! info
    What a profile holds, every command that reads one, and the profiles that *don't*
    measure anything (`inheritFromPackage`) are covered in
    [Limits profiles](/setters/profiling/profiles).

## Profiling one problem

Let's do `B` first, by hand, because the numbers are worth understanding once before you
let them be produced unattended.

```bash
cd problems/gardens
rbx time -p boca
```

{{ asciinema("contest-time-profile") }}

The command opens on the limits `gardens` carries today -- `1000 ms`, straight out of its
`problem.rbx.yml` -- and then asks how you want the new limit defined. The highlighted
default is the one we want: measure the accepted solutions and apply the rules the
environment configures.

Then the run goes quiet for a while. {{rbx}} is timing both accepted solutions before it
has anything to bucket, so the **language-group screen only appears once the run reports
are done**. That gap is measurement, not a stall.

The screen that follows asks how to group the languages. Take the default here -- pressing
++enter++ accepts it -- and read the table it settles on. `gardens` lands on a `timeLimit`
of `100`, and the `java, kt` row reads `×2.0 of cpp` against a count of zero solutions:
that limit came from a rule in the environment rather than from anything measured, because
`gardens` has no Java solution to measure. The `(base)` row above it is the limit for
anything the groups don't cover, and the `*` marks the leftover pool -- the table prints a
footnote saying so.

!!! info
    Bucketing, the leftover pool and forcing a group's limit relative to another are all
    taught in [Language groups](/setters/profiling/language-groups). The
    strategy menu is in [Estimating a time limit](/setters/profiling/estimating), and the
    arithmetic that turned the timings into `100` is in
    [How the limit is computed](/setters/profiling/computing).

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
    measurement. Your own problems will land wherever *their* solutions land.

## Reading the profile you got

The estimate is a file, and you can open it:

```bash
head -18 .limits/boca.yml
```

The head of it is the part you'll actually read -- the limit, the per-language `modifiers`
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
what the upper-bound check found. That record is written **for** you. Read it when a number
surprises you; don't hand-maintain it, because the next `rbx time` rewrites it wholesale.

The two things worth editing by hand are the limits themselves. If you know something the
measurement can't (the judge park is being replaced next month, or a language's solutions in
this problem are unrepresentative), set `timeLimit` or a `modifiers` entry directly and the
file stands. Re-running `rbx time -p boca` overwrites it, which is the point: a
hand-edit is a decision you're making until the next measurement, not a permanent one.

## The rest of the contest

`gardens` is done. Two problems to go, and neither needs you to sit through a strategy menu
again, so let's stop answering prompts. Back at the contest root:

```bash
rbx each time -p boca --auto
```

{{ asciinema("contest-time-sweep") }}

`--auto` skips **both** questions: it takes the environment's configured strategy, and it
takes the environment's own language partition instead of opening the picker. That's the
trade this page is built around: go interactive once, on one problem, until you understand
what the numbers mean, then run the whole set unattended.

`rbx each` opens the command app: a sidebar listing every problem on the left, the selected
problem's output on the right. Three things about it are worth knowing before you watch it
work.

- **The pane does not follow the sweep.** The selection stays on `A` from start to finish.
  `B` and `C` announce themselves only by their sidebar marks turning from a ring into a
  tick. Move between them with the arrow keys; each tab keeps its own scrollback, already
  scrolled to the end of its run, so nothing is lost by having looked elsewhere.
- **The app doesn't exit when the sweep finishes.** It sits there. Press ++q++ to quit.
- **A failure in one problem doesn't stop the others.** Every problem runs; the ones that
  broke are the ones with a red mark when it's over.

The pane is still on `A`, so compare it against `B`. `chocolate` declares no solution as too slow, so
there is no upper bound to derive and no upper bound to check -- its report simply ends
after the limits table, with no "confirmed too slow" line. That absence is the *healthy*
outcome for a problem shaped like that, not a step that failed silently -- worth knowing,
because the ratios it prints still recite the upper-bound rule that, here, nothing triggers.

Three files exist now, one per problem:

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

A single problem is a single command, so {{rbx}} skips the app entirely and runs it in
place. Two or more and you get the sidebar again.

`-i` (`--inline`) makes that the rule rather than the exception. It runs every problem's
chain straight in your terminal, one after another, printing which command is running for
which problem and nothing else:

```bash
rbx on -i A,C time -p boca --auto
rbx each --inline time -p boca --auto
```

You lose the sidebar and the per-problem scrollback, and you get plain, scrollable output
you can pipe or read in a log -- plus an exit code that is non-zero if any command failed.
That makes it the mode to reach for over a handful of problems, and the one to use from a
script or any other tool that can't answer a TUI.

!!! tip
    `-k` (`--keep-going`) keeps a problem's chain running after one of its commands fails.
    It belongs to `rbx on` and `rbx each`, not to `time`, so it has to come **before** the
    command it wraps -- and before the problem selector too, on `rbx on`:
    `rbx on -k A,C time -p boca --auto`.

## Verify under the limits you just wrote

New limits are a new judgment on every solution you have, and the fastest way to find out
whether they hold is to run against them:

```bash
rbx each run -p boca
```

Same app, same three tabs, and this time every solution in the contest is judged under
`.limits/boca.yml` rather than under `problem.rbx.yml`. What you want is what you had
before profiling: every solution getting the outcome it declares.

An {{tags.accepted}} solution that now fails is the interesting case, and it means the
limit is tighter than that solution can live with. Two ways out, and they are genuinely
different decisions:

- **Re-profile.** If the machine was loaded, or the solution changed since the estimate,
  the measurement was bad. Run `rbx time -p boca` again -- and see
  [running each solution several times](/setters/profiling/estimating#running-each-solution-several-times)
  for the flag that makes a noisy machine's samples usable.
- **Raise that language's limit.** If the measurement was fine and the language is simply
  slower than its group's estimate allows for, the grouping is what's wrong. Bump its
  `modifiers` entry, or regroup it in the picker.

What you should *not* do is widen the base limit until the failure goes away. The
upper-bound check exists to catch exactly that, and it will.

## Make it stick

A profile is only worth measuring if it survives the walk from your machine to whoever
builds the packages. Commit it:

```bash
git add problems/*/.limits/boca.yml
git commit -m "profile time limits for the judge"
```

You won't have to fight `.gitignore` for it. The default preset's problem `.gitignore`
ignores one profile and one only:

```gitignore title="problems/gardens/.gitignore"
.limits/local.yml
```

That asymmetry is deliberate. `local` is the throwaway: measured on whichever laptop
happened to run `rbx time`, meaningless to anyone else, and rewritten constantly. Every
other profile is a claim about a real judge, and belongs in the repository the moment it's
written. `boca.yml` is tracked from birth.

Which leaves the question of *where* you measured. A limit is a claim about hardware, so
the honest place to run `rbx time` is the judging machine itself: log into it, clone the
contest, sweep, commit. If you can't, and often you can't, your laptop is fine. It is still
enormously better than the number an author guessed, as long as you know which machine the
profile is describing.

!!! info
    There's a third option for judges that expose their own CLI: `rbx time --runner` runs
    the measurements **on the judge park** while you stay at your desk. It's MOJ-only
    today, and needs judge access. See
    [Measuring on the judge itself](/setters/profiling/remote).

## Next steps

Every problem in the contest now carries limits measured for the judge, and the packagers
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
