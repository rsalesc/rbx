# Limits profiles

A **limits profile** is a file holding one set of limits for the problem — a time limit, a
memory limit, and any per-language adjustments to them. Profiles live in `.limits/` and are
named, so a problem can carry several at once.

They exist because one problem does not have one time limit. The judge park the contest runs on
is not your laptop, and the judge you package for is neither. Keeping the limits *out* of
`problem.rbx.yml` and in a file per target lets you tune each one without the others moving.

## What a profile is

Each profile is a YAML file under `.limits/`, named after the target it describes:

```
my-problem/
├── problem.rbx.yml
└── .limits/
    ├── local.yml      # the default: what `rbx run` uses
    ├── boca.yml       # named for a packager, not for you
    └── polygon.yml
```

`local` is the one you get when you ask for nothing. The other two are named after packagers,
which is not a convention you chose — see [Profiles and packaging](#profiles-and-packaging).

Estimate one, and read it back:

{{ asciinema("time-profiles") }}

The file above carries more than the two limits: the per-language `modifiers` {{rbx}} derived,
the ratios it estimated under, and a per-group record of where each number came from. You do
not have to read that record, and you should not hand-maintain it — it is written for you, and
the [`LimitsProfile`](/schemas/LimitsProfile.json) schema is the authority on what it holds.

The two fields you *will* set by hand are the limits themselves:

```yaml title=".limits/local.yml"
timeLimit: 200        # milliseconds
memoryLimit: 256      # MB
```

## Per-language modifiers

A single time limit across every language is unfair to the slow ones. `modifiers` adjusts the
limit for one language without touching the rest:

```yaml title=".limits/local.yml"
timeLimit: 200
modifiers:
  py:
    time: 600           # (1)!
  java:
    timeMultiplier: 2.0 # (2)!
```

1. Python gets `600 ms` outright, replacing the base limit.
2. Java gets twice whatever the base limit is — `400 ms` here. A multiplier follows the base
   limit when it changes; an absolute `time` does not.

`memory` works the same way for the memory limit. When a language has both `time` and
`timeMultiplier`, the multiplier applies to the `time` you set.

!!! tip

    You rarely write `modifiers` yourself. The [language groups](language-groups.md) picker in
    `rbx time` estimates a limit per group and writes the modifiers that express it.

## Running solutions against a profile

`rbx run` and `rbx irun` take the profile by name:

```bash
rbx run -p boca
rbx irun --profile=polygon
rbx -p boca run          # (1)!
```

1. The flag exists on `rbx` itself as well as on the subcommand. The two mean the same thing,
   and the subcommand's wins if you pass both.

`rbx run` fails if the profile does not exist, rather than falling back to something you did not
ask for.

## Building statements against a profile

Statements print the time limit, so they need to know which one:

```bash
rbx statements build -p icpc
rbx contest statements build -p icpc
```

At problem level a missing profile is an error. At contest level the problems that lack it are
skipped with a warning, so one unprofiled problem does not stop the build. See [Building
statements](../statements/index.md#building).

The flag sets the **active** profile, and `problem.limits` in the template follows it — which is
what you want when the same statement is built once per judge. A statement can also name a
profile itself, through `problem.profiles`:

```latex
Time limit: \VAR{problem.limits.timeLimit} ms          %# (1)!
Time limit on the judge: \VAR{problem.profiles.boca.timeLimit} ms   %# (2)!
```

1. Whichever profile the build is running under, so this line changes with `-p`.
2. Always the `boca` profile, whatever `-p` said. Every profile in `.limits/` is reachable this
   way, keyed by name.

Reach for the second form when one document has to state a limit that is not the one it is being
built against — an editorial quoting the contest's limit, or a handout comparing two judges.
Naming a profile that does not exist is an error at render time, so a statement cannot quietly
print nothing.

The [template context](../statements/context.md) page has the rest of the `problem` namespace.

## Profiles and packaging

Each packager looks for a profile named after itself, which is how a package gets the limits
meant for *its* judge:

```bash
rbx time -p boca
rbx package boca
```

!!! warning

    A packager whose judge enforces limits **requires** its profile. Without one it stops and
    names the command that would create it, rather than shipping a package with limits
    measured for something else.

## When an estimate goes stale

An estimate is only as good as what it was measured against. Rewrite a solution, add a slow
one, change a generator, and the number in the profile stays as it was.

So {{rbx}} records what it measured, next to the number:

```yaml title=".limits/boca.yml"
timeLimit: 1400
estimationChecksum: 'v1.h.9f3a1c22.4b7e0d81.c1a8f930'
```

That string is a checksum of the solutions the estimate was derived from — the accepted ones
that set the limit and the slow ones that validated it — plus, when the tests had been built,
the interactor and the test inputs themselves. The commands that use a profile — `rbx run -p`,
`rbx package`, `rbx st b -p`, `rbx time` — recompute it and warn you when it no longer
matches:

```
The time limit saved in profile boca is stale: the solutions it was estimated from
have changed since it was estimated.
Re-run `rbx time -p boca` to refresh it.
```

It is a warning, not an error: whether the change mattered to the timing is your call.

## Inheriting from the package

Some targets do not need limits of their own — they should use whatever `problem.rbx.yml` says.
Create a profile that inherits:

```bash
rbx time --strategy=inherit -p polygon
```

That writes a `.limits/polygon.yml` containing `inheritFromPackage: true`, and it keeps
reflecting the package's limits as they change.

## Integrating a profile into the package

The other direction: you estimated limits you are happy with, and now you want them to *be* the
package's limits.

```bash
rbx time --integrate -p local
```

This copies the time, memory and output limits and any modifiers from the profile into
`problem.rbx.yml`.

## Scaling every limit locally

`RBX_TIME_MULTIPLIER` multiplies every effective time limit, without editing a profile:

```bash
RBX_TIME_MULTIPLIER=1.5 rbx run
```

Reach for it when you are working on hardware slower than the one the profile was measured on
and you want your solutions judged fairly anyway. It changes nothing on disk, so it will not
follow you into a package.
