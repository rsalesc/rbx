# Checksumming what a time limit was estimated from

Closes [#823](https://github.com/rsalesc/rbx/issues/823).

## The problem

`.limits/<profile>.yml` records the time limit `rbx time` computed. It records nothing about
what that number was computed *from*. Edit the accepted solution, add a slow one, rewrite a
generator, and the limit stays where it is, indistinguishable from one measured five minutes
ago. The setter has no way to tell a current estimate from a stale one, and neither does a
teammate who just cloned the repo.

## The shape of the answer

A checksum of the inputs that can move an estimate, written into the profile beside the limit,
and recomputed by the commands that consume it.

Two levels, because the inputs are not equally available:

* **Light** — the solutions alone. Always computable, from `problem.rbx.yml` and the sources.
* **Heavy** — light, plus the interactor and a digest of every built test input. Needs a
  finished build to read them from.

A consumer computes whichever level it can and compares only the segments both sides carry, so
a heavy record checked on a clean checkout still gets its solutions compared.

## What goes in

### Solutions

Every solution carrying an **inference role** — `LOWER` or `UPPER`, as
`solutions.inference_role_of` decides — labelled by that role. A `lower` solution sets the base
estimate and an `upper` one validates the bound; everything else (`inference: false`,
`accepted-or-tle`) is measured for the report and never feeds the number.

Deriving the set this way, rather than storing the roster of paths that actually ran, is what
lets the estimator and the checker agree without extra state: both ask the package the same
question. It also means `--run-all` does not change the checksum, which is correct — the extra
solutions it runs are reported, not estimated from.

Per solution: the package-relative path, the role, the language, and the digest of the whole
transitive source closure via `dependencies.graph.expand`. The closure matters: a C++ solution
whose hot loop lives in an included header changes its timing without a byte of the solution
itself moving.

### Interactor

Its source and closure, when the package has one. Timing on an interactive problem depends on
it directly. In the heavy level only.

### Tests

The digest of every built test input, keyed by group and index. These already exist: generation
computes them to detect duplicates and non-determinism, and used to throw them away. They are
now persisted into `build/testset.yml` and read back, so the check costs nothing at consumption
time.

Digests of the built inputs, deliberately, rather than a hash of the testplan declarations. The
inputs are the ground truth the declarations were only trying to produce — a generator rewrite
that happens to emit identical bytes is genuinely not a change worth warning about.

### Not the checker

Checker time is not part of a solution's measured runtime, so a checker change cannot make a
limit stale.

## The encoding

One string, segmented:

```
v1.h.9f3a1c22.4b7e0d81.c1a8f930
│  │ solutions  interactor  tests
│  └ level: `l` or `h`
└ format version
```

Light is `v1.l.9f3a1c22`. One field to store and one to compare, but the segment that differs
names the bucket that moved — which is the whole reason for structuring it rather than rolling
everything into a single opaque hash.

The version prefix is what lets the recipe change later. An unknown version compares as "cannot
tell", never as a mismatch, so a new rbx does not greet an old package with a warning about a
format it does not speak. The same rule covers an unparseable string: the field is
hand-editable YAML, and a garbled one should cost a missing warning, never a failed build.

`-` stands in for a segment whose subject the package does not have, so positions stay fixed
and a package that later gains an interactor reads as a change rather than as a different
format.

## When the heavy level is refused

`_tests_segment` returns nothing — silently downgrading to light — on any of:

* **No manifest, or one from a different manifest version.** Nothing to read.
* **A build that did not check determinism.** `generators.generate_testcases` only verifies
  generator determinism at `VerificationLevel.VALIDATE` or above, where a generator emitting
  different bytes on two runs fails the build outright. Below that, an unseeded generator would
  mismatch on every single build and turn the warning into noise nobody reads.
* **A build restricted to a subset of the groups.** `--samples-only` leaves a manifest
  describing one group; comparing it against an estimate taken over the whole testset would
  flag every such build.

## Consumers

| Command | Where | Why there |
| --- | --- | --- |
| `rbx package build` | after `builder.verify`, in `run_packager` | The heavy level reads the manifest, and only the build that just ran leaves one describing the tests actually being packaged. |
| `rbx run -p <profile>` | `_set_timing_profile` | Naming a profile is asking to be judged by its limits. Nothing is built yet, so this is usually a light check. |
| `rbx time` | beside the "Current limits" table | Informational: the command exists to replace the estimate, so staleness is context, not a warning to act on. |

All three go through `warn_if_stale`, so the message is identical everywhere. It is a warning
in every case — never an error, and never a reason to refuse a package. Only the setter can say
whether an edited solution was one whose timing mattered.

Writers other than an estimation write no checksum at all: `inherit_time_limits` and
`set_time_limit` construct a fresh `LimitsProfile`, so an inherited or hand-set limit is simply
never checked.

## Changes

* `rbx/box/estimation_checksum.py` — new. Computation, encoding, comparison, the warning.
* `rbx/box/schema.py` — `LimitsProfile.estimationChecksum`, in the presentation-only group
  beside `groups` and `baseEstimate`.
* `rbx/box/timing.py` — `TimingProfile.estimationChecksum`, carried by `to_limits()` and
  stamped in `compute_time_limits` once the estimation has settled.
* `rbx/box/testset_manifest.py` — `TestsetTest.input_digest`, `TestsetManifest.deterministic`,
  a `read_manifest` reader, `MANIFEST_VERSION` 1 → 2.
* `rbx/box/generators.py` — `generate_testcases` returns the input digests it already computed.
* `rbx/box/builder.py` — plumbs them, and the determinism flag, into the manifest.
* `rbx/box/packaging/packager.py`, `rbx/box/cli/commands/run.py`,
  `rbx/box/cli/commands/time_cmd.py` — the three consumers.
* `docs/setters/profiling/profiles.md` — "When an estimate goes stale".

The manifest becomes load-bearing for rbx itself here, for the first time: it was written
purely for external readers (the VS Code extension). That is the deliberate cost of making the
tests segment free at check time. `write_manifest_or_warn` still downgrades every failure to a
warning — a missing manifest costs the checksum its heavy level and nothing else.
