# Measuring on the judge itself

[`rbx time`](estimating.md) measures wherever {{rbx}} runs, so the straightforward way to get
limits for a judge is to run it *on* that judge's hardware. `--runner` is the other way: it
measures your solutions **on the judge park**, through the judge's own CLI, and feeds those
timings into the same estimation you would get locally.

```bash
rbx time -p moj --runner moj
```

## Why measure there

A time limit is a claim about hardware. Estimate on your laptop and you have a limit that is
correct for your laptop — different CPU, different compiler flags, none of the neighbouring load
a judge machine carries. The margin you thought you left may not be there.

Measuring on the park removes the guess: the timings are the judge's own, so the limit is
derived from the machine that will enforce it.

If what you want is a *verdict* rather than a limit, reach for [`rbx run
--runner`](../running/remote.md) instead. The two commands share everything below.

## Timing on MOJ

MOJ is the only backend today.

<!-- TODO(record): rbx time --runner moj cast -- needs a live moj login, so it cannot be recorded from CI or from a machine without judge access -->

{% include "_partials/moj-backend.md" %}

## The two phases, and the two uploads

MOJ enforces the time limit from inside the package, so the limit {{rbx}} is measuring under has
to be *in* what it uploads. The two phases of a run measure under different limits, and
therefore need different packages:

1. **Estimating** runs the accepted solutions under the [estimation
   cap](estimating.md#the-estimation-cap) — one limit for every language.
2. **[Checking the upper bound](estimating.md#checking-the-upper-bound)** runs the too-slow
   solutions at the bound the estimate demands of them, which differs per language group.

So a full run uploads twice, and the second upload usually costs a calibration wait as well.
Each trip through the language-group picker that *changes* a limit costs another one.

Finished testruns are cached, so re-running `rbx time`, or regrouping back onto limits already
probed, costs no judge time at all. And `--skip-slow` stops after the estimate, which is the
one-upload path:

```bash
rbx time -p moj --runner moj --skip-slow
```

Each command uploads to a throwaway problem of its own — `…-run` for `rbx run`, `…` and
`…-slow` for the two phases of `rbx time` — so alternating between the commands never costs a
re-upload.
