# Surfacing invalid-by-nature time limits in the timing table

## Problem

A timing group whose limit is *derived* -- from a reference group (`whenEmpty`
or a picker-forced relative) or from the base estimate -- is never checked
against its own accepted solutions. `timing.compute_bounds` takes the derived
limit as the lower bound and discards `measured.lower` entirely, so the group's
own evidence bounds nothing.

The result is a limit that no good solution of the group can meet, rendered in
the table as an ordinary row:

    java | 1 | 200 ms | x1.0 of cpp

with `sol.java` taking 900 ms. Nothing in the table says the row is impossible.

Two further gaps share the root cause:

* In **formula mode** `build_timing_profile` passes `derive_fn=None`, so a
  derived group is checked from neither side -- not even the upper bound.
* The invariant is not specific to derived groups. A formula is arbitrary, so an
  `ESTIMATED` row can also land below its own slowest accepted solution.

## The invariant

Every group carries the smallest limit its own accepted solutions allow:

* multipliers mode: `ceil(slowest_ac * acToTimeLimit)` -- the setter's own margin;
* formula mode: `slowest_ac` -- a solution taking `T` ms passes at a limit of `T`.

A group violates it when its resolved limit is below that value. On the
estimated path the limit is *built* from this bound and rounded up, so the
invariant holds by construction; only derived limits can break it.

## Design

`TimingGroupReport` gains `lowerViolation: Optional[TimingBound]`, recorded only
when the invariant is broken -- `value` is the smallest limit the group's own
accepted solutions allow and `solution` is the one that sets it. Following
`upperValidation`, the field stays unset when there is nothing to record, so an
untroubled group does not emit a meaningless key.

`compute_bounds` computes that bound from `measured.lower` on every path,
derived or not, and `_as_eval_result` stamps the violation. Formula mode gains
`make_formula_derive`, which runs the same check without inventing bounds a
formula does not have.

Severity is a **warning, not an error**. The upper-bound path raises
`TimingRangeError`, which the interactive picker renders *instead of* the table
-- acceptable for a grouping that is wholly unsatisfiable, wrong here: the
setter cycling groupings needs to see which row is broken, in the table, beside
the rows that are fine.

`limits_info` renders a violating row in the error style and appends the bound
to its Source cell, with a caption distinguishing the two severities:

* `slowest_ac > timeLimit` -- the accepted solutions do not pass at all;
* otherwise -- they pass, but below the margin `acToTimeLimit` asks for.

Because `build_limits_table` is the single rendering path, this reaches
`rbx time`, the group picker preview and shared reports alike.

## Out of scope

Deliberately not surfaced (raised, considered, dropped): skipped upper
validation, zero-evidence multiplier rows, and reference-chain provenance.
