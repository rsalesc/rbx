# Running on the judge itself

`rbx run` runs your solutions in the sandbox on your machine. With `--runner`, it runs them
**on the judge park** instead, through the judge's own CLI, and reports back the verdicts and
timings the judge produced.

```bash
# Run every solution on MOJ instead of locally
rbx run --runner moj
```

## Why run there

Your machine is not the judge. The CPU, the compiler flags and the background load can all differ,
and a solution that finishes in `0.8s` here can take `1.4s` on the park. A local run tells you
whether a solution passes under your limits on your laptop. What matters when you ship is
whether it passes under those limits on the machine that will judge it.

`--runner` checks that directly. The verdicts are the judge's own, the times
are measured by the judge, and the time limits enforced are the ones from the limits profile
in effect — the same ones your local run would use, per language group. So with `--runner`:

- A borderline accepted solution can be **confirmed** where it matters, instead of on a proxy.
- A solution expected to be too slow can be **confirmed slow** on the hardware that has to
  reject it.

If what you want is a *time limit* rather than a verdict, use [`rbx time
--runner`](/setters/profiling/remote/) instead: it feeds the same remote timings into the
estimation.

## Running on MOJ

Everything below is specific to MOJ. `rbx run --runner moj` and [`rbx time --runner
moj`](/setters/profiling/remote/) share all of it.

<!-- TODO(record): rbx run --runner moj cast -- needs a live moj login, so it cannot be recorded from CI or from a machine without judge access -->

### What it needs, and what it cannot tell you

{% include "_partials/moj-backend.md" %}

The problem `rbx run` uploads to is named `<your-login>#rbxt-<slug>-run`, from the same
`.rbx-id` slug.

[Failing fast](/setters/running/#failing-fast) does work, because MOJ enforces it itself: it
stops a solution at its first non-accepted verdict, and the remaining testcases are reported
as skipped, exactly as they are locally.

### What it costs

The first run uploads the package and waits for the judge to calibrate it. After that, the
package is stable and finished testruns are cached, so re-running costs no judge time.

Changing anything that goes into the package invalidates that cache, and so does toggling
`--fail-fast`, since it changes MOJ's stop rule and therefore the package. Either one costs an
upload and a calibration on the next run.

`rbx run` and each phase of `rbx time` upload to a problem of their own (`…-run` for `rbx run`,
`…` and `…-slow` for `rbx time`), so alternating between the commands never costs a re-upload.

## Running on DOMjudge

```bash
rbx run --runner domjudge
```

### What it needs, and what it cannot tell you

{% include "_partials/domjudge-backend.md" %}

The problem `rbx run` uploads to is named `rbxt-<slug>-run`, so it never collides with
either phase of `rbx time`.

[Failing fast](/setters/running/#failing-fast) is **not** available here. DOMjudge has already
judged the whole submission by the time {{rbx}} reads the result, so there is nothing left to
stop; the run is reported in full instead.
