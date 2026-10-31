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

<!-- TODO(record): rbx time --runner moj cast -- needs a live moj login, so it cannot be recorded from CI or from a machine without judge access -->

{% include "_partials/moj-backend.md" %}

How `rbx time` measures on MOJ depends on how the problem estimates its limit.

### Estimating with time limit ratios

When the problem estimates with [time limit ratios](computing.md#time-limit-ratios), {{rbx}}
doesn't run any testruns. The ratios are the same rule MOJ calls its Kattis method, so {{rbx}}
hands the whole estimate to the judge:

1. It uploads one package to `<your login>#rbxt-<slug>-kattis`, holding the solutions that
   [bound the limit](estimating.md#which-solutions-bound-which-side): the accepted ones, and the
   ones expected to be too slow when `timeLimitToTle` is set.
2. It asks every judge in the park to calibrate that package by the Kattis rule, with your
   `acToTimeLimit`, `timeLimitToTle` and `timeResolution`. If MOJ refuses to queue it on every
   judge, {{rbx}} warns and asks for one calibration instead.
3. It waits for every judge it queued, then reads the calibration back: the time of every
   solution on every judge, and the limit MOJ computed from them.

The language-group picker and the profile it writes work as they do locally, including the record
of what [the upper-bound check](estimating.md#checking-the-upper-bound) found. A language that is
its own group gets exactly the limit MOJ computed.

A few things differ from a local run:

- **One wait, then one table.** Instead of a live report per solution, one table lists each
  solution with its time and verdict once the calibration finishes. If MOJ hasn't finished after
  the polling window, {{rbx}} stops waiting, and running `rbx time` again picks up the same
  calibration.
- **The upper bound is checked once, against MOJ's own limit.** MOJ judges the too-slow
  solutions against the limit it computed, and stops a timed-out test at that limit plus
  2.2 seconds. That confirms the bound whenever the limit is at most 2.2 seconds divided by
  (`timeLimitToTle` − 1): 4.4 seconds at a `timeLimitToTle` of 1.5. A group that pools several
  languages can end up above MOJ's limit and need more. When the calibration can't confirm it,
  {{rbx}} records that solution's upper bound as **skipped** in the profile and warns. It doesn't
  run the solution again.
- **Your ratios must be ones MOJ accepts.** `acToTimeLimit` and `timeLimitToTle` must be between
  1 and 100, and `timeResolution` at most 10000 ms. {{rbx}} refuses anything else before it
  uploads.

The calibration can take several minutes. Re-running `rbx time` on this machine with an
unchanged package reads the same calibration again, without uploading or calibrating anything.

### Estimating with a formula

A [formula](computing.md#time-limit-formulas) has no MOJ counterpart, so {{rbx}} measures it
with testruns instead.

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
`…-slow` for the two phases of `rbx time`, `…-kattis` for a calibration — so alternating between
the commands never costs a re-upload.

## Timing on DOMjudge

```bash
rbx time -p domjudge --runner domjudge
```

### What it needs, and what it cannot tell you

{% include "_partials/domjudge-backend.md" %}

### The two phases, and the two uploads

DOMjudge enforces the time limit from inside the package, so — exactly as on MOJ — the two
phases measure under different limits and therefore need different packages. Each phase uploads
to a problem of its own, `rbxt-…-estimation` and `rbxt-…-validation`, so alternating between
them never costs a re-upload.

The estimation package pins a deliberately generous limit. DOMjudge kills a run at the limit,
so a package pinned near the answer you are looking for would truncate exactly the measurements
that matter most.

Finished judgings are cached, and so is the upload: re-running `rbx time`, or regrouping back
onto limits already probed, re-submits only the solutions whose source changed, and re-uploads
the package only when the package itself changed. A judging {{rbx}} could not read — a compile
error above all — is never cached, so fixing it and running again really does try again.

`--skip-slow` stops after the estimate, which is the one-upload path:

```bash
rbx time -p domjudge --runner domjudge --skip-slow
```
