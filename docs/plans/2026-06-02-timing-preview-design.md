# Live timing-table preview during group selection

Issue: [#500](https://github.com/rsalesc/rbx/issues/500). Builds on the language-groups
estimation work from [#499](https://github.com/rsalesc/rbx/pull/499).

## Goal

While the user regroups languages in the interactive `rbx time` picker, render the
resolved timing table directly below the language list, updating as the grouping
changes. The final table after confirmation is already rendered by
`compute_time_limits`, so this work is purely the *live preview during selection*.

## Constraints / context

- The picker is a `prompt_toolkit.Application` (`timing_group_picker.prompt_group_assignment`)
  with its own redraw loop that repaints on every key event.
- The table is a single rich renderable built by `limits_info.build_limits_table()`.
- The issue suggests `rich.live`, but `rich.live` and prompt_toolkit both own the
  terminal screen and conflict. The clean path is to render the preview *inside* the
  existing prompt_toolkit app, which already repaints on every keystroke.

## Approach (chosen)

**Reuse the one rich renderer via ANSI.** prompt_toolkit's renderer cannot accept a
rich renderable directly, so we render the existing `build_limits_table()` Table to an
ANSI string and wrap it in `prompt_toolkit.formatted_text.ANSI`. There is exactly one
table renderer; the picker only captures its output. No second renderer, no drift.

### Keep the picker UI-only

`timing_group_picker` stays free of timing/estimation logic. It gains one optional
parameter:

```python
preview: Optional[Callable[[Dict[str, int]], AnyFormattedText]] = None
```

When provided, the layout adds a `Window` below the language-list body whose
`FormattedTextControl` calls `preview(state.assignment())`. Because prompt_toolkit
repaints on every key event, the preview is live for free.

### The preview callback (owned by `timing.py`)

`timing.py` already has everything needed *before* the prompt
(`timing_per_solution_per_language`, `formula`, `env_groups`, `all_languages`) — no
re-running solutions. The callback, given the current `assignment` dict:

1. `build_timing_profile(..., repartition=assignment)`, catching `GroupValidationError`.
2. On error → return a styled inline message (e.g. `⚠ Invalid grouping: <reason>`),
   so the user sees immediately why no table renders.
3. On success → `profile.to_limits()` → `build_limits_table(limits)` (the existing
   renderer) → capture to an ANSI string via a
   `rich.console.Console(file=StringIO, force_terminal=True, width=…)` → wrap in `ANSI`.

Memoize by assignment so pure cursor moves don't rebuild the profile.

## Testing

- The callback is pure and unit-testable: valid assignment → table text contains the
  expected per-group limits; cyclic/invalid grouping → inline error string.
- The picker gets a test feeding piped keystrokes (existing prompt_toolkit test
  pattern) and asserting the preview Window reflects the current assignment.

## Out of scope

- Final-table rendering after confirmation (already done in `compute_time_limits`).
- The `--auto` path (no prompt → no preview).
