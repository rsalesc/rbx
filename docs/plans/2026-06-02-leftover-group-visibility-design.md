# Leftover-group visibility: table marker + picker legend (PR #499 follow-up)

Date: 2026-06-02
Builds on: `docs/plans/2026-06-01-three-state-language-bucketing-design.md`
PR: https://github.com/rsalesc/rbx/pull/499

## Motivation

The three-state bucketing landed, but the **leftover pool** is invisible in two places:

1. In the rendered time-limits table it looks like any other multi-language group —
   you can't tell which row is the catch-all default, and it renders **last**.
2. The interactive picker has only a terse one-line key hint; new users don't learn
   what "grouped / singleton / leftover" actually mean.

This change makes the leftover group obvious in the table (asterisk + footer, moved to
first position) and teaches the three states in the picker (a static legend).

Locked terminology (used in legend, key hint, table footer, docs):
**`[N]` grouped · `[X]` singleton · `[ ]` leftover.**

## Section 1 — Persist a leftover marker

The table is rebuilt from saved `.limits/*.yml` metadata, so "which group is the
leftover" must be persisted, not inferred.

- `ResolvedGroup` (`timing_groups.py`) gains `is_leftover: bool = False`. Both
  `build_partition` and `partition_from_assignment` set it `True` on the single
  leftover group they create.
- `TimingGroupReport` (`schema.py`) gains `isLeftover: bool = False`. `resolve_groups`
  copies it from the group into the report. It serializes into `.limits/*.yml`.
- Old saved files have no `isLeftover` → defaults `False` → no row is treated as
  leftover → table renders exactly as before (graceful degradation).

## Section 2 — Table (`limits_info.py`)

- `LimitsTableRow` gains `is_leftover: bool = False`.
- `build_limits_table_rows`: when `profile.groups` is present, emit the leftover
  report **first**, then the remaining reports in their existing order. (Render-time
  reorder only; resolution and saved order are untouched.)
- The leftover row's Languages cell gets a **leading asterisk**: `* go, java`
  (still warning-highlighted when DEFAULTED).
- `build_limits_table` sets a rich `caption` (footer) **only when a leftover row is
  present**:
  `* leftover: languages not assigned to a group, estimated together (default).`
- Degraded view (no `groups` metadata) is unchanged — no leftover concept applies.

Example:

| Languages    | Solutions | Time Limit  | Source                          |
|--------------|-----------|-------------|---------------------------------|
| * go, java   | 0         | **2000 ms** | ⚠ DEFAULTED to base             |
| c, cpp       | 2         | 1000 ms     | estimated (fastest 280 / 600)   |
| python       | 1         | 5000 ms     | estimated (1600 / 1600)         |

`* leftover: languages not assigned to a group, estimated together (default).`

## Section 3 — Picker static legend (`timing_group_picker.py`)

Replace the current 2-line header (title + key hint) with a static legend block
(~7 lines), explaining each state once:

```
Assign each language to a time-limit bucket:

  [N] grouped    shares one estimated limit with same-numbered langs
  [X] singleton  its own estimated limit
  [ ] leftover   pooled with all other unmarked langs (default)

1-9 group · space/tab [X]/[ ] · 0 clear · enter confirm · q cancel
```

- Legend lines extracted to a module-level constant (e.g. `LEGEND_LINES` or a
  `legend_text()` helper) so the wording is unit-testable and reused by the header
  control.
- The header `Window` height grows to the legend's line count.
- Body (per-language `[N]`/`[X]`/`[ ]` rows) unchanged. Picker row order stays env
  order — only the *table* reorders the leftover to the top.

## Section 4 — Docs

Update `docs/setters/reference/environment/index.md`: note that the per-group table
lists the leftover group first, marked with an asterisk and explained in a footer.
Terminology is already "leftover".

## Section 5 — Tests

- `test_timing_groups.py` — `is_leftover` is `True` on the leftover group from both
  `build_partition` and `partition_from_assignment`, and `False` on grouped/singleton
  groups.
- `test_timing_estimation.py` (or resolve tests) — `isLeftover` propagates from group
  into the resolved `TimingGroupReport`.
- `test_limits_table.py` — leftover row is first; Languages cell starts with `* `;
  `build_limits_table` caption is set when a leftover row exists and absent otherwise;
  degraded view unaffected; existing ordering tests updated for the new first-position
  rule.
- `test_timing_group_picker.py` — the legend constant/text contains all three state
  descriptions (grouped / singleton / leftover).

## Out of scope

- Reordering the leftover group in the *saved* metadata or in the *picker* (only the
  rendered table reorders).
- Marking singleton rows specially (only the leftover is marked).
- Any change to resolution, `whenEmpty`, or the DEFAULTED warning logic.
