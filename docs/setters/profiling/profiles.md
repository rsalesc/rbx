# Limits profiles

A **limits profile** is a file holding one set of limits for the problem — a time limit, a
memory limit, and any per-language adjustments to them. Profiles live in `.limits/` and are
named, so a problem can carry several at once.

They exist because one problem does not have one time limit. The judge park the contest runs on
is not your laptop, and {{boca}} is neither. Keeping the limits *out* of `problem.rbx.yml` and
in a file per target lets you tune each one without the others moving.

## What a profile is

Each profile is a YAML file under `.limits/`, named after the target it describes:

```
my-problem/
├── problem.rbx.yml
└── .limits/
    ├── local.yml      # (1)!
    ├── boca.yml       # (2)!
    └── polygon.yml
```

1. The default. `rbx run` uses this one unless told otherwise.
2. What the {{boca}} packager looks for. The name is not a convention you chose — see
   [Profiles and packaging](#profiles-and-packaging).

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

!!! note

    `rbx irun` takes only the long `--profile`. Its `-p` is already `--print`.

## Building statements against a profile

Statements print the time limit, so they need to know which one:

```bash
rbx statements build -p icpc
rbx contest statements build -p icpc
```

At problem level a missing profile is an error. At contest level the problems that lack it are
skipped with a warning, so one unprofiled problem does not stop the build. See [Building
statements](../statements/index.md#building).

## Profiles and packaging

Each packager looks for a profile named after itself, which is how a package gets the limits
meant for *its* judge:

```bash
rbx time -p boca
rbx package boca
```

!!! warning

    The {{boca}} packager **requires** the `boca` profile. Without it the packager stops and
    tells you to run `rbx time -p boca` first, rather than shipping a package with limits
    measured for something else.

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

## Editing a profile by hand

Profiles are plain YAML, so an editor works. Point it at the schema for completion and
validation:

```yaml title=".limits/local.yml"
# yaml-language-server: $schema=https://rsalesc.github.io/rbx/schemas/LimitsProfile.json
```

There is also a profile editor in the {{rbx}} TUI, reachable from `rbx ui`. It is marked *in
development*, so prefer the file or `rbx time` for anything you intend to keep.

## Scaling every limit at once

`RBX_TIME_MULTIPLIER` multiplies every effective time limit, without editing a profile:

```bash
RBX_TIME_MULTIPLIER=1.5 rbx run
```

Reach for it when you are working on hardware slower than the one the profile was measured on
and you want your solutions judged fairly anyway. It changes nothing on disk, so it will not
follow you into a package.
