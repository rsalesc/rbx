# `rbx ui` test-list filtering + fancy search box — design (#548)

**Source issue:** [#548 — rbx ui: test-list filtering + fancy search box](https://github.com/rsalesc/rbx/issues/548)
**Umbrella:** [#326](https://github.com/rsalesc/rbx/issues/326) · **Sibling A:** #547 (merged as #551)
**Date:** 2026-06-08
**Status:** Design approved; implementation in progress.

## Summary

Make the test list in `RunTestExplorerScreen` (`rbx/box/ui/screens/run_test_explorer.py`)
**filterable** and **searchable**, and let the search box double as a **goto**.
Introduces a reusable predicate-based filter/index model in
`get_entries_options` that the sibling navigation issues (#549, #550) build on.

Covers umbrella ideas **#3** (failing-only filter), **#5** (fuzzy search),
**#6** (goto, folded into the search box).

## Dependency note (resolved)

The issue originally listed a dependency on Issue A's "#2 line content" for
searching by testplan line. That feature was **reverted** before #547 merged
(PR #551 is MAIN-badge only; see commit `32b4d58`). The reason also resolves our
dependency: the generator-script parser already populates **`generator_call`**,
**`copied_from`**, and **`content`** on `GenerationMetadata` alongside
`generator_script` (`rbx/box/testcase_extractors.py`). So the testplan line
*content* is already in memory for every entry — we search those fields directly,
**with no file read and no dependency on unmerged work**. Built directly on
`main` (which has #551).

## Cross-cutting: the test-list machinery (#464 invariant)

`get_entries_options` (`rbx/box/ui/utils/run_ui.py:73`) builds **two parallel
lists**: `options` (renderables — disabled group-header rows, real test rows, and
`None` dividers) and `expanded_entries` (the `GenerationTestcaseEntry` per real
row, `None` for a header row). A `None` divider is deliberately **not** given an
`expanded_entries` slot, because Textual's `OptionList` does not allocate an index
for a separator (it only flags the preceding option). This keeps
`expanded_entries[i]` aligned with `OptionList.highlighted` (#464). **Filtering
must preserve this invariant.**

## A. Reusable filter/index model (`get_entries_options`)

Add one optional parameter:

```python
def get_entries_options(
    entries,
    skeleton=None,
    solution=None,
    predicate: Optional[Callable[[GenerationTestcaseEntry], bool]] = None,
) -> Tuple[List[...], List[Optional[GenerationTestcaseEntry]]]:
```

Behaviour when `predicate` is set (default `None` = today's behaviour, unchanged):

- Filter each group's entries by `predicate`.
- A group with **zero** surviving entries drops **both** its header `Option`
  **and** its trailing `None` divider (no empty headers).
- **POINTS totals**: accumulate `max_score` / `got_score` only over groups that
  still have ≥1 visible entry. A *partially* filtered group keeps its full group
  score (subtask scores are per-group, not per-test). The `TOTAL` row appears only
  if some visible group carries a score.
- The divider/header invariant is preserved exactly via the existing `_add`
  helper: dividers never get an `expanded_entries` slot; headers get a `None` slot.

This is the only signature change. The screen owns predicate construction,
OptionList rebuild, and highlight restoration.

## B. Screen state & rebuild (`RunTestExplorerScreen`)

- **Precompute evals once** on mount (`get_solution_evals(skeleton, solution)`,
  aligned with `skeleton.entries`) into an `entry-id → Outcome` map, so neither the
  failing filter nor per-keystroke search re-reads `.eval` files.
- Reactives: `failing_only: reactive[bool] = reactive(False)`; the search query is
  driven by the `Input` widget (a `search_query: str` attribute, not necessarily a
  reactive).
- One private `_rebuild_options()`:
  1. Build the combined predicate (failing-only AND fuzzy-match-or-numeric).
  2. Call `get_entries_options(..., predicate=...)`.
  3. `clear_options()` + `add_options(...)`, store `_option_entries`.
  4. Update `#test-list` border title (see below).
  5. Set `highlighted` to the best match (search) or the first real row.
- The existing `self.watch(option_list, 'highlighted', self._update_selected_test)`
  re-fires on rebuild and refreshes the detail panes for free. `_update_selected_test`
  already guards `entry is None` (header rows) and an out-of-range/None index.

## C. Failing-only toggle (#3)

- New binding `f` → `action_toggle_failing_only` flips `failing_only`; a
  `watch_failing_only` calls `_rebuild_options()`.
- Predicate keeps entries whose precomputed outcome **≠ `Outcome.ACCEPTED`**.
  A **missing eval** (incomplete run) is treated as "not AC" and **kept**, so an
  unfinished run never hides rows.
- Border title reflects state: `Tests` → `Tests (failing only)`; combined with an
  active search it reads e.g. `Tests (failing only, search)`.
- Binding declared `show=False` (footer stays slim; help panel lists it under the
  screen group).

## D. Fuzzy search box + goto (#5/#6)

- A hidden, dockable `Input` (`#test-search`) inside `#test-list-container`, docked
  at the **top** of the list. `/` → `action_focus_search` makes it visible and
  focuses it (binding `show=False`).
- **Search corpus** per entry (all already in memory — no I/O):
  `f'{group}/{index}'` + `str(metadata.generator_call)` +
  `str(metadata.copied_from.inputPath)` + `metadata.content` +
  `str(metadata.generator_script)` (location). Joined into one candidate string.
- **Matcher:** `textual.fuzzy.Matcher(query)` (Textual 8.0, already a dependency).
  `match(candidate)` returns a float; `> 0` ⇒ visible, the **max** ⇒ highlighted.
  No reordering of rows (keeps the group structure intact).
- **Numeric query** `N` (`query.strip().isdigit()`): per decision, **match group
  index** — keep entries whose `group_entry.index == N`; highlight the first such
  entry (first group that has it). (Predicate, not fuzzy, for numeric queries.)
- **Live filter:** `Input.Changed` → set `search_query`, `_rebuild_options()`,
  highlight best match. Empty query ⇒ no search constraint.
- **Goto / Enter** (`Input.Submitted`): commit the jump — clear the search
  constraint, restore the list to its non-search state (full, or failing-only if
  that toggle is on), keep the matched (best) test **highlighted**, hide the box,
  and move focus back to the `OptionList`. (`/` is a transient locator; `f` is the
  persistent filter.)
- **Esc** while the box is focused: clear the query, restore the list, hide the
  box, focus the list — **no** jump.
- **Focus guards:** `vim_nav` and the help panel already disable `h/j/k/l` and `?`
  while an `Input` is focused (`check_action`). The screen's own `f` / `/` bindings
  do not fire while the `Input` has focus because Textual routes the key to the
  focused `Input`, which consumes printable characters. Esc is handled by the
  `Input`'s own key handler / a screen binding scoped to the focused input.

## CSS

Add rules in `rbx/box/ui/css/app.tcss` for `#test-search`: hidden by default
(`display: none`), full width docked at the top of `#test-list-container`, with a
border title like `Search` so it reads as a filter bar when shown. Toggling
`display` shows/hides it without disturbing the OptionList layout.

## Edge cases

- Empty result set (predicate filters everything): OptionList shows no rows;
  `highlighted` is `None`; `_update_selected_test(None)` clears the detail panes
  ("No test selected"). Border title still reflects the active filter.
- Single-solution vs. compare mode: filtering operates on `skeleton.entries`
  independent of `diff_solution`; the existing per-entry rendering is unchanged.
- Interactive (`make_interactive`) entries have no `generator_*` metadata; their
  search corpus is just `group/index` — still searchable by number.

## Testing

`tests/rbx/box/ui/test_run_ui.py` (pure helper, no Textual app):
- Predicate filtering keeps `options` / `expanded_entries` index-aligned across
  group boundaries — regression for #464 (assert `expanded_entries[i]` matches the
  intended entry after a group is partially/fully filtered).
- A predicate that empties a group drops that group's header **and** divider.
- POINTS `TOTAL` is recomputed over visible groups only; a fully-filtered scored
  group is excluded from the total.

`tests/rbx/box/ui/test_run_test_explorer.py` (Textual `run_test` pilot):
- Failing-only (`f`) hides AC rows and now-empty group headers; border title
  updates; toggling again restores.
- `/` opens the search box and focuses it; typing fuzzy-filters by number,
  generator call, copied-from path, inline content, and script location; the best
  match is highlighted.
- Numeric query matches the group index.
- Enter commits the goto (list restored, matched test highlighted, focus on list);
  Esc restores the full list with no jump.
- Search + failing-only compose (both constraints applied).

Reuse fixtures from `tests/rbx/box/ui/conftest.py` / the existing run-explorer
tests; build a small package with multiple groups and a mix of AC / non-AC evals.

## Out of scope

- Faster navigation / count prefixes (#549, Issue C — builds on this filter model).
- Inverted test-first explorer (#550, Issue D).
- Persisting the last filter/search across screen entries.
