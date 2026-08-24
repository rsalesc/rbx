# Running on the judge itself

`rbx run` runs your solutions in the sandbox on your machine. `--runner` is the other way:
it runs them **on the judge park**, through the judge's own CLI, and reports back the
verdicts and timings the judge produced.

```bash
# Run every solution on MOJ instead of locally
rbx run --runner moj
```

## Why run there

Your machine is not the judge. Different CPU, different compiler flags, a different amount of
neighbouring load — and a solution that finishes in `0.8s` here can spend `1.4s` on the park.
A local run answers "does this solution pass under my limits, on my laptop". The question you
actually ship on is "does it pass under my limits, on the machine that will judge it".

`--runner` answers that second question directly. The verdicts are the judge's own, the times
are measured by the judge, and the time limits enforced are the ones from the limits profile
in effect — the same ones your local run would use, per language group. Two things follow:

- A borderline accepted solution can be **confirmed** where it matters, instead of on a proxy.
- A solution expected to be too slow can be **confirmed slow** on the hardware that has to
  reject it.

If what you want is a *time limit* rather than a verdict, reach for [`rbx time
--runner`](/setters/profiling/remote/) instead: it feeds the same remote timings into the
estimation.

## Running on MOJ

MOJ is the only backend today, and everything below is specific to it. `rbx run --runner moj`
and [`rbx time --runner moj`](/setters/profiling/remote/) share all of it.

<!-- TODO(record): rbx run --runner moj cast -- needs a live moj login, so it cannot be recorded from CI or from a machine without judge access -->

### What it needs, and what it cannot tell you

{% include "_partials/moj-backend.md" %}

The problem `rbx run` uploads to is named `<your-login>#rbxt-<problem-id>-run`.

[Failing fast](/setters/running/#failing-fast) does work, because MOJ enforces it itself: it
stops a solution at its first non-accepted verdict, and the testcases it never reached come
back as skipped, exactly as they do locally.

### What it costs

The first run uploads the package and waits for the judge to calibrate it. After that, the
package is stable and finished testruns are cached, so re-running costs no judge time at all.

Two things invalidate that: changing anything that goes into the package, and toggling
`--fail-fast`, which changes MOJ's stop rule and therefore the package. Either one pays for an
upload and a calibration on the next run.

`rbx run` and each phase of `rbx time` upload to a problem of their own (`…-run` for `rbx run`,
`…` and `…-slow` for `rbx time`), so alternating between the commands never costs a re-upload.
