# `rbx ui` quality-of-life improvements — design & issue fan-out

**Source issue:** [#326 — Add quality of life improvements to `rbx ui`](https://github.com/rsalesc/rbx/issues/326)
**Date:** 2026-06-08
**Status:** Child issues created — #547 (A), #548 (B), #549 (C), #550 (D).

## Summary

Issue #326 lists 7 quality-of-life ideas for the Textual TUI (`rbx ui`). This doc
groups them into **4 themed child issues**, each with a high-level design. #326
stays as the tracking umbrella.

The current run-explorer flow is **solution-first**: pick a solution
(`RunExplorerScreen`) → browse that solution's tests (`RunTestExplorerScreen`).
The detail screen shows input/output, a side-by-side compare, and (since #404) a
toggleable testcase-metadata footer.

Mapping of the 7 ideas to the 4 issues:

| # | Idea | Issue |
|---|------|-------|
| 1 | Show which solution was used as main | **A** |
| 2 | Show the actual testplan line (content, not just `path:line`) | **A** |
| 3 | Filter to show only failing tests | **B** |
| 5 | Fuzzy test search (number / generator / testplan line) | **B** |
| 6 | Goto command to jump to a test | **B** (folded into the search box) |
| 7 | Faster navigation (jump multiple) | **C** |
| 4 | Test-first ("inverted") explorer showing every solution's verdict | **D** |

## Decisions taken during brainstorming

- **D is a primary test-first navigation screen** (not a transposed matrix grid).
  Matches the issue wording: "navigate across tests first, and show verdicts of
  each solution."
- **Goto (#6) is folded into the fancy search box (#5)**, not a separate
  numeric-only command. Typing in the box filters; committing (Enter) jumps to the
  match. So Issue C is purely #7.
- **Failing-only (#3) means "not AC"** (the common debugging case), not "not
  matching the solution's expected outcome". May be refined later.

## Cross-cutting concern: the test-list machinery

Issues **B**, **C**, and **D** all touch the same fragile code: `get_entries_options`
(`rbx/box/ui/utils/run_ui.py:73`) builds **two parallel lists** — `options`
(renderables, including disabled group-header rows and `None` dividers) and
`expanded_entries` (the `GenerationTestcaseEntry` per real row). A `None` divider
is deliberately *not* given a slot in `expanded_entries`, because Textual's
`OptionList` doesn't allocate an index for it; getting this wrong drifts the two
lists out of sync once a divider is crossed (the bug fixed in #464).

**Sequencing:** Implement **A → B → C**. Issue **B** introduces a reusable
filter/index model for the test list (a predicate + a clean
`option_index → entry` mapping that survives filtering); Issue **C** builds
navigation on top of it. Issue **D** is largely independent but reuses A's MAIN
badge helper and the per-(solution, test) eval/verdict helpers.

---

## Issue A (#547) — Display polish: main-solution badge + inline testplan line

**Ideas:** #1, #2. **Effort:** Small (~½ day). **Risk:** Low. **Depends on:** nothing.

Two small, independent display enhancements. No new screens.

### #1 — Surface the MAIN solution

The "main" solution is the first solution with `outcome: accepted`
(`package.get_main_solution()`, `rbx/box/package.py:462`). A `MAIN` badge is
**already** rendered in `RunScreen`/`SolutionReportScreen` by
`_build_solution_selection_label` (`rbx/box/ui/screens/run.py:27`) but is **not**
surfaced in the run-explorer flow.

- Extract the badge-styling logic into a shared helper (e.g.
  `run_ui.get_main_badge(solution)` → markup or empty string).
- `RunExplorerScreen`: have `get_solution_markup` (`run_ui.py:161`) append the
  badge so the solution list marks the main solution.
- `RunTestExplorerScreen`: prefix `self.title` (`run_test_explorer.py:77`) with a
  `[MAIN]` marker when `self.solution.path == get_main_solution().path`.

### #2 — Inline testplan line content

Today `get_generation_metadata_markup` (`rbx/box/testcase_extractors.py:132`)
renders `metadata.generator_script` as just `path:line` (the `__str__` of
`GeneratorScriptEntry`, `generation_schema.py:18`). The *content* of that line is
never read.

- When `metadata.generator_script` is set, read line `entry.line` from
  `entry.path` and render it alongside the location, e.g.
  `Gen. script: gen.txt:42 → gen_random 1000 50`.
- **Edge cases:**
  - File edited since build → line content may be stale: render anyway, but read
    from the current file (a small dim caveat is acceptable; do not error).
  - `@input { … }` block syntax spans multiple lines — `line` points at the start;
    show the first line + `…`.
  - File missing / line out of range → fall back to today's `path:line`-only
    rendering.
  - Read once per entry and cache (avoid re-opening the file on every footer
    repaint).

### Tests

- Unit test `get_main_badge` / `get_solution_markup` marks the main solution and
  no other.
- Unit test the metadata markup: line content rendered; graceful fallback when the
  file/line is missing.

---

## Issue B (#548) — Test-list filtering & fancy search box

**Ideas:** #3, #5, #6. **Effort:** Medium (~2–3 days). **Risk:** Medium (the
filtered rebuild + index sync). **Depends on:** A (#2 for searching by line content).

Make the test list in `RunTestExplorerScreen` filterable and searchable, and let
the search box double as goto.

### Reusable filter/index model (the foundational piece)

- Add an optional `predicate: Callable[[GenerationTestcaseEntry], bool]` (and/or a
  query string) to `get_entries_options` (`run_ui.py:73`) so it emits a **filtered**
  option list while keeping `options` and `expanded_entries` in sync.
- When filtering empties a group, **drop that group's header row** and recompute
  the POINTS score totals over visible entries only.
- Carefully preserve the divider/index invariant (#464): dividers never get an
  `expanded_entries` slot. Cover with a regression test that filters across group
  boundaries and asserts `highlighted → entry` stays correct.

### #3 — Failing-only toggle

- New binding (e.g. `f`) toggles a `reactive[bool]` on `RunTestExplorerScreen`.
- Predicate keeps entries whose eval outcome ≠ `ACCEPTED` (decision above).
- Reflect state in the `#test-list` border title (e.g. `Tests (failing only)`).
- Re-apply the active search query + failing filter together when either changes.

### #5 / #6 — Fancy search box (filter + goto)

- A dockable `Input` toggled by `/`, docked above or below `#test-list`.
- **Fuzzy-matches** across: test number (`group/index`), generator call
  (`metadata.generator_call` / `full_repr()`), and the testplan line — both
  `metadata.generator_script` location and the **line content** read in Issue A.
- Live-filters the OptionList as the user types; the first/best match becomes
  `highlighted`.
- **Goto (#6):** pressing Enter commits the jump — focus returns to the list with
  the matched test selected. A purely numeric query (`42`) behaves like a direct
  jump to that test index. `Esc` clears the query and restores the full list.
- Fuzzy matcher: reuse a vendored matcher if one exists; otherwise a simple
  subsequence/score function is enough for these short strings.
- Respect existing input-focus guards: `vim_nav` and the `?` help panel already
  disable their keys while an `Input` is focused (`vim_nav.py`, `help_panel.py`),
  so typing in the box is never hijacked.

### Tests

- Predicate-based filtering keeps `options`/`expanded_entries` aligned across
  group boundaries (regression for #464).
- Failing-only filter hides AC tests and empty group headers.
- Fuzzy search matches by number, generator, and line content; Enter selects the
  match; numeric query jumps directly; Esc restores.

---

## Issue C (#549) — Faster navigation: jump-multiple

**Idea:** #7. **Effort:** Medium (~1.5–2 days). **Risk:** Medium (count-prefix
state machine). **Depends on:** B (operates on the filtered list).

Add fast keyboard movement over the (now filterable) test list and any cursor
widget.

- Extend `VimNavMixin` (`rbx/box/ui/vim_nav.py`, mixed into `rbxBaseApp`) with:
  - `Ctrl-D` / `Ctrl-U` — half-page down/up.
  - `PageDown` / `PageUp` — full page (where not already provided by the widget).
  - **Vim count prefixes**: typing `5j` moves down 5. Needs a small pending-count
    state in the mixin, reset on any non-digit / on timeout / on motion. This is
    the trickiest part and the main risk — it must not interfere with the `?` help
    toggle, the `/` search, or digit input inside `Input`/`TextArea` (the mixin
    already disables itself there via `check_action`).
- Jumps must **skip disabled rows** (group headers) and dividers so a "down 5"
  lands on the 5th *real* test, consistent with goto in Issue B.
- Surface the new bindings in the help panel under the existing `Global` group.

### Tests

- Count prefix: `5j` moves 5, `G`/`gg` honored, non-digit resets the count.
- Half-page / page jumps clamp at list ends and skip headers/dividers.
- Count state does not leak into `Input`/`TextArea` typing.

---

## Issue D (#550) — Inverted (test-first) explorer

**Idea:** #4. **Effort:** Large (~4–6 days). **Risk:** Medium-high (new screen +
navigation + CSS + interaction with compare/metadata). **Depends on:** A (MAIN
badge), reuses B/D-shared verdict helpers; otherwise standalone.

Add a **test-first** flow complementing today's solution-first flow.

### Flow

- New `TestCentricExplorerScreen` (`rbx/box/ui/screens/`), reachable from the main
  menu (new option) and/or via an `i` (invert) toggle on `RunExplorerScreen`.
- **Left pane:** the list of all tests across groups (same renderer as the
  solution-first list, minus a single solution's verdict column).
- **Right pane:** for the highlighted test, a compact table/list of **every
  solution → its verdict** (outcome badge + time + memory), with the MAIN solution
  marked (Issue A badge). Selecting a solution row drills into the existing
  per-(solution, test) detail widgets (`TwoSidedTestBoxWidget`, input `FileLog`,
  metadata footer) — reuse, don't duplicate.

### Data assembly

- The per-(solution, test) evals already live on disk; `get_solution_eval`
  (`run_ui.py:33`) loads one. Add a **transpose helper**: for a given test entry,
  iterate `skeleton.solutions` and collect each solution's `Evaluation` (the dual
  of `get_solution_evals`, which today fixes a solution and iterates entries).
- Verdict markup reuses `solutions.get_testcase_markup_verdict` /
  `get_full_outcome_markup_verdict`.

### Open sub-decisions (resolve during planning)

- Whether the inverted screen reuses the side-by-side compare semantics (compare a
  test's output between two solutions) or defers that to v2.
- Whether to keep both menu entry **and** the `i` toggle, or pick one entry point.
- Sample-vs-hidden / POINTS group score display in the test-first list.

### Tests

- Transpose helper returns the right verdict per solution for a test, tolerating
  missing `.eval` files (incomplete runs).
- Screen renders the verdict-per-solution panel and drills into the detail view.

---

## Rollout

1. Child issues created: **A → #547**, **B → #548**, **C → #549**, **D → #550**,
   each referencing #326.
2. #326 stays the umbrella (check off ideas as child issues land).
3. Each child issue gets its own implementation plan (`writing-plans`) when picked
   up — they are independent PRs, with the B-before-C ordering noted above.
