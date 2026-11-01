# Measuring on the judge itself

[`rbx time`](estimating.md) usually measures your solutions on the machine {{rbx}} runs on. It
can also measure them **on the judge**: your solutions run on the judge's own machines, and
{{rbx}} estimates the time limits from the running times the judge reports back.

## Why measure there

A time limit is a claim about hardware. Estimate on your laptop and you get a limit that's
correct for your laptop. The judge has another CPU and other compiler flags, and it shares its
machines with a contest's worth of submissions, so the margin you thought you left may not be
there.

Measuring on the judge removes the guess: the timings are the judge's own, so you derive the
limit from the machines that enforce it.

Only the timings change. The estimate itself is still computed by {{rbx}}, on your side, by the
same [rules](estimating.md) a local `rbx time` follows, and it ends in the same limits profile.

If what you want is a *verdict* rather than a limit, reach for [`rbx run
--runner`](../running/remote.md) instead.

## Timing on MOJ

<!-- TODO(record): rbx time --runner moj cast -- needs a live moj login, so it cannot be recorded from CI or from a machine without judge access -->

With the `moj` limits profile, `rbx time` measures on MOJ by default, so this is all it takes:

```bash
rbx time -p moj
```

{{rbx}} has MOJ run the solutions the estimate needs. MOJ reports how long each one took on its
machines, and {{rbx}} estimates the limit from those times, exactly as it would from a local
run.

To also check every other solution's verdict, add
[`--run-all`](estimating.md#checking-the-rest-of-the-package): MOJ runs those solutions
alongside the ones the estimate needs, and the report shows each of them at the limit {{rbx}}
estimated.

{{rbx}} remembers what it already asked MOJ to run, so running `rbx time` again on an unchanged
problem costs no judge time at all.

To estimate the `moj` profile on your own machine instead, pass `--runner local`.

### What it needs, and what it cannot tell you

{% include "_partials/moj-backend.md" %}

## Timing on DOMjudge

```bash
rbx time -p domjudge --runner domjudge
```

It works the same way: {{rbx}} runs your solutions on DOMjudge and estimates the limits from the
times DOMjudge reports. Running it again on an unchanged problem only re-submits the solutions
you changed.

### What it needs, and what it cannot tell you

{% include "_partials/domjudge-backend.md" %}
