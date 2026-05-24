# "Stress-testing your solutions" walkthrough — design

**Status:** approved 2026-05-24. Implements issue #437, part of the Walkthrough restructure (`docs/plans/2026-05-07-walkthrough-restructure-design.md`).

## Goal

Add a new narrative page under **Walkthrough → Authoring a problem** that tells the
story of finding a tiny counterexample for a wrong solution with `rbx stress`. It is
distinct from the existing `setters/stress-testing.md` page, which stays the reference
(operators, fuzzing, `--slowest`, saved stresses). This page is the story; the
reference page is the manual.

## Scope

Pure docs. No code changes.

- New page: `docs/setters/stress-testing-walkthrough.md`.
- `mkdocs.yml`: one nav entry under Walkthrough → Authoring a problem.
- `docs/setters/first-steps.md`: repoint the "Stress test" next-steps card to the new walkthrough.
- Issue #442: comment noting step 4 should be revised once the promote-to-`manual_tests/` affordance lands.

## The #442 dependency

Issue #437 frames step 4 as "promote the counterexample to a manual test under
`manual_tests/`", which depends on #442 (a one-command promote affordance). #442 is
not implemented.

Decision: do **not** block on #442. Instead, step 4 uses the persistence mechanism
that already exists today — the `rbx stress` post-run prompt *"Do you want to add the
tests that were found to a test group?"* (`rbx/box/cli.py:961`). Accepting it appends
the found generator calls to a `.txt` generator script (with a
`# Obtained by running rbx stress ...` comment); the next `rbx build` regenerates
them, so the counterexample sticks across builds.

When #442 lands, step 4 should be rewritten to use the cleaner one-command flow. This
is tracked by a comment on #442.

## Narrative spine

Continues the exact package from `first-steps.md` (sum of N integers; `sols/main.cpp`
correct, `sols/wa-overflow.cpp` uses `int32_t ans` that overflows). Frame: *"main
passes everything, but I think `wa-overflow.cpp` is wrong somewhere — find me a tiny
counterexample."*

1. **Define the finder.** Generator expression `gens/gen [1..5] <A.max> @`; finder
   `[sols/wa-overflow.cpp] ~ INCORRECT` (introduce the `sols/wa-overflow.cpp`
   shorthand). The small `[1..5]` range is the point: int32 overflows once the sum
   passes ~2.1×10⁹, so a handful of ~10⁹ values trips it — which is *why* the
   counterexample is tiny.
2. **Run it.** `rbx stress -g "gens/gen [1..5] <A.max> @" -f "sols/wa-overflow.cpp"`.
   asciinema cast here.
3. **Inspect the failing input.** Show the report, open the found input, point at the
   few large numbers and the overflowed sum.
4. **Make it stick.** Accept the add-to-test-group prompt, create a new `.txt` script
   (group `corner`, file `testplan/corner.txt`), show the appended line + comment, then
   `rbx build` to confirm regeneration.

Closes with "Next steps" cards linking to the stress-testing *reference* page (fuzzing,
`--slowest`, saved stresses) and onward.

## Structure & style

- **No rigid "Step 3 of 3" header.** Step 2 (#443) isn't built, so numbering would be
  wrong. Open with a one-line callout linking back to `first-steps.md` instead.
- Stays narrative — does not re-document the operator table, fuzzing, etc. Links to
  `setters/stress-testing.md` for depth.
- Tabbed code blocks (`=== "..."`) and admonitions matching `first-steps.md` house style.

## asciinema recording

The page includes the `{{ asciinema("...") }}` macro at beat 2 with a **placeholder
cast id** and an HTML comment marking it pending. The maintainer records the
`rbx stress` run (kickoff → counterexample) and substitutes the real id. Claude cannot
produce the cast.

## Out of scope

- Implementing #442 (separate issue).
- Adding "Step N of M" numbering across the authoring track (revisit when #443 lands).
- Touching the reference page `setters/stress-testing.md`.
