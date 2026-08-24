# Profiling

In {{rbx}}, **profiling** is the process of measuring how long your solutions take and turning
those measurements into a time limit for the problem.

Picking that number by hand is guessing. Too generous and the quadratic solution you wrote the
problem to reject sneaks through; too tight and a correct solution in Python fails on a judge
whose machine is slower than yours. And it is not one number: the same problem deserves a
different answer on your laptop and on each judge it ships to.

{{rbx}} measures instead. You run one command, it times your solutions, applies the rules your
environment configures, and writes the result to a **limits profile** — a file you can keep one
of per judge you ship to.

## Motivational problem

Everything in this section is the same problem, growing. It asks for the number of pairs of
values in a list that add up to `K`:

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

Notice that nothing here mentions Java, and no solution is written in it. That is deliberate,
and [Language groups](language-groups.md) is about what {{rbx}} does with it.

## Estimating a limit

Run `rbx time`:

```bash
rbx time
```

It builds the problem, times the accepted solutions, asks you how to bucket the languages, and
then checks the limit it arrived at against the solutions you said were too slow:

{{ asciinema("time-estimate") }}

The table at the end is the answer. `cpp` gets `100 ms` from its own measurements, `py` gets
`200 ms` from its own, and `java` — which nothing solves — gets `×2.0 of cpp`, because the
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

    What a profile is, and every command that reads one.

-   :material-timer-outline: **[Estimating a time limit](estimating.md)**

    `rbx time` in full: strategies, the estimation cap, and the upper-bound check.

-   :material-calculator: **[How the limit is computed](computing.md)**

    The ratios, the formula alternative, and wall time.

-   :material-format-list-group: **[Language groups](language-groups.md)**

    Giving each language a limit that suits it.

-   :material-server-network: **[On the judge itself](remote.md)**

    Measuring on the judge park instead of your machine.

</div>
