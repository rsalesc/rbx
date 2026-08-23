# `rbx run --runner`: running the solutions on a custom backend

Issue: [#702](https://github.com/rsalesc/rbx/issues/702).

`rbx time --runner moj` measures the solutions on the MOJ judge park by uploading a
throwaway *probe* package and driving `moj testrun`. `rbx run` should be able to do the
same: run the solutions where they will really be judged, and report the verdicts and
timings the judge produced.

Almost all of the machinery already exists. The `SolutionRunner` seam is per solution and
command-agnostic, `run_solutions` already accepts a backend, probe packages already ship
only the model solution and whitelist every testrunnable language, and `rbx run` already
closes the runner in a `finally`. Four things had to be designed.

## 1. The signal: `RunPurpose`, said out loud

`MojRunner` uploads a package per *application*, because MOJ's limits and its stop rules
live inside the package: two applications sharing one remote problem evict each other's
fingerprint and the fast path can never fire.

That application used to be **inferred** from the shape of `ctx.timelimit_override` -- an
`int` meant `rbx time`'s estimation phase, a per-language mapping meant its validation
phase. The inference worked only while `rbx time` was the sole command with a `--runner`
flag. `rbx run` passes no override at all, so it was indistinguishable from "neither
phase" and would have landed on the estimation problem.

So `RunContext` grows a `purpose: RunPurpose` (`RUN` / `ESTIMATION` / `VALIDATION`), set
by the calling command, and the shape-sniffing is deleted. The MOJ runner maps it to a
problem-id suffix:

| purpose | problem | `measuring` |
| :--- | :--- | :--- |
| `ESTIMATION` | `<login>#rbxt-<slug>` | accepted solutions |
| `VALIDATION` | `…-slow` | slow solutions |
| `RUN` | `…-run` | solutions |

Estimation keeps the bare id, so every committed `.moj-id` keeps working untouched.

`RUN` is the default: `run_solutions` is a general entry point, and a plain run is what a
caller that says nothing means. Getting it wrong costs an extra staging area, never a
wrong limit -- the limits come from somewhere else entirely, which is the next section.

## 2. The limits: pinned from `ctx.skeleton.limits`

`_probe_pin` stops reading `timelimit_override` and reads the skeleton's per-language
`Limits` instead. The skeleton is the one place that has already reconciled everything
that decides an enforced limit: the active limits profile, the verification level, and
any override the caller passed. Pinning from it is what makes `--runner moj` answer the
same question the local run answers, and it collapses three cases into one:

- `rbx run` passes no override, so the skeleton holds the profile's own per-language
  limits -- what a local run enforces, and now what MOJ enforces.
- `rbx time` estimating passes one `int`, so every language holds that `inferenceTimeout`.
- `rbx time` validating passes a mapping, so each language group holds its own
  `ceil(TL × timeLimitToTle)` -- and a language the mapping does *not* mention keeps the
  profile's own limit, which the override-shaped reading could only approximate with the
  loosest of the others.

The **expanded** limit (`get_expanded_tl`), not the declared one: a double-TL language
really runs at twice the number locally, and pinning the undoubled figure would TLE a
solution here that passes there. Neither `rbx time` phase is affected -- both run at
`ALL_SOLUTIONS`, which keeps `isDoubleTL` off.

Two refusals rather than guesses: a language whose enforced limit is `None` (MOJ always
enforces one, so "no limit" has no package that means it), and -- as a fallback rather
than a refusal -- an empty limits table falls back to the configured estimation cap, since
that is a run with nothing to pin rather than a run asking for something impossible.

## 3. `--fail-fast`: a halt rule on the package

rbx cannot gate a batch backend (`supports_abort=False`): a testrun has already run the
whole submission by the time rbx sees any of it. So the caller's abort predicate has to be
enforced *by the judge*, through `STOPWHEN_*`. `ProbePackage` grows `halt_on`, and the
runner translates:

| caller | `abort_on` | `STOPWHEN_*` |
| :--- | :--- | :--- |
| `rbx time`, either phase | `...outcome.is_slow()` | `TLE` |
| `rbx run --fail-fast` | any non-accepted verdict | `WA`, `TLE`, `RE` |
| `rbx run` | none | **none** |

The last row is the correctness-critical one. The probe used to hard-code
`STOPWHEN_TLE=y`; on a plain run that would turn the tests after the first timeout into
SKIPPED -- work the judge really did, reported as work it did not -- and a setter
comparing local against MOJ would read it as the judge losing tests.

Because the halt rule is in the package, it is in the fingerprint: toggling `--fail-fast`
costs an upload and a calibration. **One `-run` problem serves both modes** rather than
two. `--fail-fast` is documented as quick experimentation, the toggle is rare, and a
second persistent problem per flag is a worse trade than an occasional re-upload. The
existing `prepare` line already says "uploaded" versus "reused", so the cost is visible.

## 4. `--no-check`: refused by name

`rbx run --no-check` skips building outputs and running the checker. A judge decides the
verdict itself, and a probe package cannot even be built without the answers `--no-check`
skips. New capability `supports_unchecked`, refused in `_check_capabilities` alongside the
sanitizer and interactor refusals -- before anything is built or uploaded. Running it
checked anyway and warning was rejected for the reason those refusals exist: the report
would look like an answer to `--no-check` and be an answer to a different question.

## What came free

`--sanitized`, `--runs` and `communication` problems are already refused by the existing
capability checks. The report path is shared with `rbx time`, so the degraded surface (no
memory column, no `.out`/`.err`, no checker messages) is already exercised. Testrun
caching keys on the package fingerprint plus the solution content, so a repeated
`rbx run --runner moj` with no edits costs no judge time at all.

One cost worth stating: without `--fail-fast`, every wrong solution runs the full testset
on a shared park. That is what a local run does too, but on someone else's hardware.
