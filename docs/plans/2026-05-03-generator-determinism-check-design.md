# Generator Determinism Check — Design

## Problem

Generators in rbx are expected to produce identical output whenever called
with the same `argv`. A generator that seeds itself from a non-`argv` source
(`time(NULL)`, `/dev/urandom`, an unseeded `rand()`, etc.) will silently
produce different testcases on different builds, breaking reproducibility and
masking subtle bugs in problem packages.

We want a cheap, opportunistic check that catches the obvious cases: run each
generator twice and compare digests. A non-deterministic generator may still
slip through if both runs happen to coincide, but the check raises the cost
of being undetected.

## Trigger

The check runs whenever `VerificationLevel >= VALIDATE` (i.e. anytime
validation is on). At `VerificationLevel.NONE` the check is skipped, keeping
plain `rbx build -v0` cheap.

## Behavior on mismatch

Hard error: raise `GenerationError` with a message naming the generator and
the offending args, and noting the likely cause (generator not seeded from
`argv`). The build aborts.

Mirrors the strictness of validator failures rather than the warning-only
hash-duplicate detection, because non-determinism breaks reproducibility
across builds, which is worse than a duplicate test.

## Scope

Only generator-call testcases get the second run. `copied_from` and inline
`content` testcases are deterministic by construction — skipped.

## Where the change lives

`rbx/box/generators.py`, inside `BuildTestcaseVisitor._visit` (the existing
build-pipeline call site that already digests outputs for hash-duplicate
detection). `generate_standalone` is left untouched — it has other callers
(stress testing) where doubling generator cost is unwanted.

## Mechanism

Inside `_visit`, when the entry is a generator call, run two coroutines
concurrently with `asyncio.gather`:

1. The existing `generate_standalone(...)` call, which writes the test to
   `spec.copied_to.inputPath` on disk.
2. A new helper `_run_generator_to_digest(call, generator_digest, holder)`
   that wraps `run_item` with `stdout=DigestOrDest.create(holder)`. The
   stdout streams straight into the file cacher; no temp file is
   materialized on disk.

The two runs write to disjoint sinks (disk path vs. `DigestHolder`), so they
are safe to run in parallel.

After `gather` returns:

- Compute the disk digest with `digest_file(...)` (this is already what
  `_visit` does today).
- If the determinism check is enabled, compare against `holder.value`. On
  mismatch raise `GenerationError`.
- Return the disk digest as before so the existing duplicate-detection logic
  is unchanged.

## Plumbing the trigger

`generate_testcases` currently takes no verification parameter. Three small
changes:

1. **`generators.generate_testcases`** — add
   `verification: VerificationLevel = VerificationLevel.NONE`. Default to
   `NONE` so other callers stay opt-out.
2. **`BuildTestcaseVisitor`** — store a single boolean
   `check_determinism: bool`. The visitor stays decoupled from
   `VerificationLevel`; translation happens in `generate_testcases`:
   `check_determinism = verification.value >= VerificationLevel.VALIDATE.value`.
3. **`builder.build()`** — pass it through:
   `await generate_testcases(s, groups=groups, verification=VerificationLevel(verification))`.

`VerificationLevel` is already imported in `builder.py`; `generators.py`
gains an import from `rbx.box.environment`.

## Performance

Doubles generator wall time when validation is on. Acceptable: generator
runs are already parallelized via the visitor, the second run streams
straight into the cacher (no extra disk I/O), and validation-enabled builds
are not the hot inner loop.

## Testing

Unit tests in `tests/rbx/box/`. New testdata package containing two tiny
C++ generators:

- A deterministic generator that echoes its `argv`.
- A non-deterministic generator that prints a value derived from
  `time(NULL)` or `/dev/urandom` so the two runs reliably diverge.

Cases:

1. Deterministic generator at `VerificationLevel.VALIDATE` — `build` succeeds.
2. Non-deterministic generator at `VerificationLevel.VALIDATE` — `build`
   raises `GenerationError`; message references the generator name and args.
3. Non-deterministic generator at `VerificationLevel.NONE` — `build`
   succeeds (proves the gate is wired correctly).

Reuse existing fixtures (`cleandir_with_testdata`, `pkg_from_testdata`).
