# "Adding a custom checker" walkthrough — design

**Status:** approved 2026-05-24. Implements issue #443, step 2 of the *Authoring a problem*
track from the [Walkthrough restructure](2026-05-07-walkthrough-restructure-design.md).

## Goal

Add a new narrative walkthrough page that picks up where
[`first-steps.md`](../setters/first-steps.md) leaves off and gives the reader a real
motivation to write a {{testlib}} checker.

Scope is **checker-only**: the page keeps the spotlight on the checker. The surrounding
package (validator, generator, statement) is changed in a single sentence with a link back
to step 1 — it is *not* re-walked. Rationale: re-walking those would duplicate `first-steps.md`
and bury the lesson. The trade-off is that the page is not strictly copy-paste runnable on its
own; it assumes the reader adapts the rest as they learned in step 1.

## The narrative mutation

Step 1 ends on *"compute the sum of N integers"* — a problem with a **unique** answer, where
the default `wcmp` token-diff checker works fine.

We mutate it into a variant with **many valid answers**:

> Given an integer `N` (`2 ≤ N ≤ 1e9`), print any two integers `a b` such that
> `a + b = N` and `1 ≤ a, b`.

For `N = 10`, both `5 5` and `3 7` are correct. Comparing the participant's tokens against the
model answer therefore produces spurious wrong-answer verdicts — which is exactly why a checker
is needed.

## File & nav

- **File:** `docs/setters/custom-checker-walkthrough.md` (flat, matching the `-walkthrough`
  suffix of `packaging-walkthrough.md`).
- **Nav (`mkdocs.yml`):** under `Walkthrough → Authoring a problem`, a new
  `"Adding a custom checker"` entry directly after `"First steps"`.
- **No "Step N" framing.** A plain prerequisite callout linking back to `first-steps.md`,
  matching that page's current style. (Step-marker retrofitting of `first-steps.md` is out of
  scope; tracked separately by #435.)

## Page outline

1. **Recap & motivation.** Recall the sum-of-N problem from step 1, introduce the pair variant,
   and show concretely how the default `wcmp` checker wrongly rejects a valid-but-different
   output.
2. **New solutions.** `sols/main.cpp` (prints `1 N-1`) and `sols/wa-offbyone.cpp` (prints
   `2 N-1`, i.e. sum `N+1` — both values stay in range so it survives the bound-reads and trips
   the *sum* check, cleanly demonstrating a custom WA message). One line + link: "adapt the
   validator, generator and statement as you learned in step 1."
3. **Writing the checker** (`checker.cpp`, the focus):
   - `#include "testlib.h"`, `registerTestlibCmd(argc, argv)`.
   - Read `N` from `inf`.
   - Read `a`, `b` from `ouf` with bounds, e.g. `ouf.readInt(1, n - 1, "a")` — bound-reads
     auto-fail out-of-range output with a presentation-style message.
   - `quitf(_ok, "%d + %d = %d", …)` vs `quitf(_wa, "a + b = %d, expected %d", …)`.
   - Note that the `ans` stream (jury answer) exists but is unused here; link to the
     feature-guide *output + answer* case for problems that must consult it.
   - Uses the same `(1)!` annotation style as the existing docs.
4. **Wiring it in.** Replace `checker: {path: "wcmp.cpp"}` with `checker: {path: "checker.cpp"}`
   in `problem.rbx.yml`. Single-object form (see schema note below).
5. **`rbx run` again.** The AC solution now passes (any valid pair accepted); the WA solution
   fails with the *custom message* instead of a token diff. `<!-- TODO(record): rbx run cast -->`
   marker — no `{{ asciinema(...) }}` macro until recorded.
6. **Testing the checker with `rbx unit`** (brief). `unitTests.checker` with `ac*`/`wa*` globs;
   create `unit/checker/ac_BASIC.{in,out}` and `wa_BAD_SUM.{in,out}`; run `rbx unit`.
   `<!-- TODO(record): rbx unit cast -->` marker. Link to `verification/unit-tests.md` for test
   plans and deeper coverage.
7. **Next steps.** Grid cards linking to step 3 (stress-testing) and the feature-guide checker
   reference.

## Schema note (drives a side fix)

The real schema is `checker: Optional[Checker]` — a **single object**. The default preset uses
`checker: {path: "wcmp.cpp"}`. However, `docs/setters/grading/checkers.md` currently documents
`checker:` as a YAML **list** (`checker:\n  - path:`) in 3 places. That is a documentation bug.

This PR uses the correct single-object form on the new page **and** fixes the 3 occurrences in
`grading/checkers.md` so the docs do not contradict each other.

## Recordings

Two asciinema casts are required but can only be recorded and uploaded by a human:

- `rbx run` showing custom verdicts / messages.
- a short `rbx unit` cast.

The draft leaves an HTML-comment marker at each spot (no macro call, to avoid a broken-ID
build). Real `{{ asciinema(...) }}` macros are added when the casts are recorded.

## Out of scope

- Interactors (separate walkthrough / feature-guide content).
- Deep dive on the testlib API — linked to `setters/grading/checkers.md`.
- Re-walking the validator/generator/statement for the pair problem.
- Retrofitting "Step N" framing onto `first-steps.md` (#435).
