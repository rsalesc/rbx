# Profiling

In {{rbx}}, **profiling** is the process of measuring how long your solutions take and turning
those measurements into a time limit for the problem.

Picking that number by hand is guessing. Too generous and the quadratic solution you wrote the
problem to reject gets accepted; too tight and a correct solution in Python fails on a judge
whose machine is slower than yours. And it is not one number: the same problem needs a
different limit on your laptop and on each judge it ships to.

{{rbx}} measures instead. One command times your solutions and turns the timings into a limit,
using rules your [environment](../reference/environment/index.md) configures. The result goes
into a **limits profile**, and you can keep one profile per judge you ship to.

## Motivational problem

Every page in this section uses the same problem. It asks
for the number of pairs of values in a list that add up to `K`, and it is solved three ways:

```yaml title="problem.rbx.yml"
solutions:
  - path: sols/main.cpp        # (1)!
    outcome: ac
  - path: sols/main.py         # (2)!
    outcome: ac
  - path: sols/quadratic.cpp   # (3)!
    outcome: tle
```

1. Sorts, then walks the list from both ends: `O(n log n)`.
2. The same idea in Python, and several times slower for it. Two accepted solutions in
   different languages is what makes a *per-language* limit mean anything.
3. Compares every pair: `O(n²)`. This is the solution the time limit exists to reject, and
   saying so with `outcome: tle` is what lets {{rbx}} check the limit against it.

Notice that no solution is written in Java. That's deliberate: [Language
groups](language-groups.md) covers how {{rbx}} still gives Java a limit.

## Estimating a limit

Run `rbx time`:

```bash
rbx time
```

It first asks how you want the limit defined, then builds the problem and times the accepted
solutions. Next it asks you how to bucket the languages, and checks the limit it arrived at
against the solutions you said were too slow:

{{ asciinema("time-estimate") }}

!!! note "Don't worry about following all of that yet"
    Each piece of that recording has its own page, listed under [Where to go
    next](#where-to-go-next).

The table at the end has the result. `cpp` gets `100 ms` from its own measurements, `py` gets
`200 ms` from its own, and `java`, which no solution uses, gets `×2.0 of cpp`, because the
environment says an unsolved language should follow C++ rather than fall back to the base
limit.

## Using the limit

The estimate is written to `.limits/local.yml`, and `local` is the profile {{rbx}} runs with
when you do not ask for another:

```bash
rbx run
```

For a judge with hardware of its own, estimate into a profile named after it, and ask for that
profile by name:

```bash
rbx time -p boca   # (1)!
rbx run -p boca
```

1. A packager looks for the profile named after it, so this is the one `rbx package boca` will
   use. See [Profiles and packaging](profiles.md#profiles-and-packaging).

## Where to go next

<div class="grid cards" markdown>

-   :material-file-document-outline: **[Limits profiles](profiles.md)**

    Profile files, and every command that reads one.

-   :material-timer-outline: **[Estimating a time limit](estimating.md)**

    `rbx time` in full: strategies, the estimation cap, and the upper-bound check.

-   :material-calculator: **[How the limit is computed](computing.md)**

    The ratios, the formula alternative, and wall time.

-   :material-format-list-group: **[Language groups](language-groups.md)**

    Giving each language a limit that suits it.

-   :material-server-network: **[On the judge itself](remote.md)**

    Measuring on the judge park instead of your machine.

</div>
