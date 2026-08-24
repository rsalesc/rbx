# Language groups

A **language group** is a set of languages that share one estimated time limit. Grouping them is
how a problem ends up with a limit that suits C++ *and* a limit that suits Python, from one run
of [`rbx time`](estimating.md).

## Why group languages

Estimate a single limit from every accepted solution pooled together and two things go wrong at
once. The limit is too generous for C++, because Python dragged it up. And it is too tight for
any language nothing was written in.

That second one is the real trap, and our problem has it. It is solved in C++ and Python, and
nothing stops a contestant submitting Java — which is not represented in the measurements at
all, and would inherit whatever the pooled estimate happened to be.

## Bucketing languages

After timing your solutions, `rbx time` shows every language the environment knows, with a
preview of the limits your current bucketing would produce. The preview updates as you move:

{{ asciinema("time-language-groups") }}

Each language sits in one of three states:

- **Grouped** `[N]` — in numbered group `N`. Languages in a group are estimated together from
  their pooled timings. Put `c` with `cpp`, and `java` with `kt`.
- **Singleton** `[X]` — a bucket of its own, toggled with ++space++.
- **Unbucketed** `[ ]` — the default. Every unbucketed language joins one **leftover pool**,
  estimated together. Its row is listed first and marked with a `*`.

The leftover pool is what stops an unrepresented language from falling back to the base limit:
it inherits the pool's estimate, which is drawn from languages that *were* measured.

Press ++enter++ to accept, or pass `--auto` to take the environment's groups without being
asked.

!!! warning "A language on its own with nothing to measure"

    Watch what happens in the recording above when `java` is pulled into a bucket of its own. It
    has no solutions and it is no longer covered by a rule, so there is nothing to estimate from
    and it lands on the base limit, flagged `DEFAULTED`. `kt` in the row beneath still derives
    from `cpp`. Splitting a language out is only an improvement if something in its new bucket
    was actually measured.

## Forcing a relative limit

Sometimes you want a group's limit derived from another group rather than from its own
measurements — the Java solutions you have are unrepresentative, say, but you know Java should
get twice what C++ gets.

Press ++r++ on a language to open an inline editor and define its group's limit as
`multiplier × reference + increment`. The reference can be another group or the base estimate,
and the increment is a constant in milliseconds. ++tab++ moves between the fields, ++enter++
commits, ++esc++ cancels, and ++c++ clears the rule. ++shift+r++ resets the whole grouping back
to what the environment defines.

!!! danger "A derived limit can be one the group's own solutions cannot meet"

    A forced rule **overrides** the measurements completely. Derive `java` from `cpp` at `×1.0`
    and Java gets C++'s limit however slow the Java solutions actually are.

    {{rbx}} checks every derived limit against the group's own measurements and flags the row
    when they disagree — red when the group's accepted solutions would not pass at all, yellow
    when they pass without the margin the ratios ask for. It is a warning, not an error: the
    limit is written as you asked, so regroup or drop the reference if it was not what you
    meant.

## Configuring groups in the environment

The picker is prepopulated from `env.rbx.yml`, so the grouping you want by default belongs
there:

```yaml title="env.rbx.yml"
timing:
  groups:
    - languages: ["py"]
      whenEmpty: {relativeTo: "cpp", multiplier: 3.0}   # (1)!
    - languages: ["java", "kt"]
      whenEmpty: {relativeTo: "cpp", multiplier: 2.0}
```

1. What to do when this group has **no** accepted solutions to measure: follow `cpp` at three
   times its limit. This is the rule that gave `java` its limit in our problem.

`whenEmpty` and a forced relative rule are not the same thing. `whenEmpty` applies *only* when
the group has nothing to measure; a forced rule always wins. The [Environment
reference](../reference/environment/#language-groups) has the full schema.
