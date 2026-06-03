# `rbx time`: forced relative time limits in the interactive picker

**Issue:** [#512](https://github.com/rsalesc/rbx/issues/512)
**Date:** 2026-06-03

## Problem

After #499/#511, an env group may declare `whenEmpty` so that an *empty* group's
time limit is derived from another group as `A·t + B` (`multiplier *
reference + increment`). But this only works through `env.rbx.yml`, and only when
the group has no solutions.

Inside the `rbx time` interactive picker (`timing_group_picker.py`) the user can
re-bucket languages, but:

- They have **no way** to author or edit a relative spec.
- The relative spec from env survives only by accident: `partition_from_assignment`
  re-derives `whenEmpty` by matching the resulting group membership against the
  env groups. Any edit to a group silently drops its relative spec.

We want the user to be able to **force** a relative assignment on a group — and
to edit its `A` and `B` — directly in the picker, with the relative formula
**always** taking precedence over estimation (the user sees solution counts in the
live preview and decides informed).

## Design

### 1. Resolve layer — a *forced* relative spec

A group may carry a **forced** relative spec that **always** wins over estimation,
even when the group has measured solutions.

Resolution priority in `resolve_groups` (per group):

1. **forced relative** present → `A · reference + B`
2. else group has pooled timings → estimate from the formula
3. else env `whenEmpty` present (empty-only, unchanged) → relative
4. else → base time limit (`DEFAULTED`)

The forced spec lives **only on `ResolvedGroup`**, via a new field
`forced_relative: Optional[LanguageGroupFallback]`. The user-facing env schema
(`environment.LanguageGroupFallback` / `LanguageGroup`) is **untouched**, and the
existing empty-only `whenEmpty` behavior on the non-interactive (`auto`) path is
unchanged.

The two paths never collide:

- Non-interactive / `auto` path (`build_partition`, `repartition=None`) sets
  `whenEmpty` on `ResolvedGroup`; never sets `forced_relative`.
- Picker path (`partition_from_assignment`) sets `forced_relative`; never sets
  `whenEmpty`.

The emitted `TimingGroupReport.origin` for a forced group reuses `MULTIPLIER`, but
`solutionCount` is preserved so the table can convey "had N solutions, forced
relative." `relativeToLanguage` / `multiplier` / `increment` are populated as today.

### 2. Drop the env-crossing; bake `whenEmpty` at picker init

`partition_from_assignment` **loses** its `env_groups` whenEmpty-matching logic. It
just builds buckets from the `{language: state}` numbers and stamps any supplied
relative overrides as `forced_relative` on the matching `ResolvedGroup`.

The env `whenEmpty` specs are instead **baked into the picker state at
initialization**:

- For each env group that has **no measured solutions** at init time, seed the
  picker's `relatives` map with that group's `whenEmpty` (as a forced spec).
- Groups that have solutions are not seeded (matching today's empty-only semantics
  at the moment of init).

After init, the picker's `{numbers, relatives}` is the **single source of truth**.
No re-crossing with env. If the user later moves a solution-bearing language into a
baked-relative group, the forced spec now overrides that group's estimate — this is
the user's responsibility, and the live preview shows the solution counts so the
decision is informed.

### 3. Picker interaction (UX)

Entry point: press **`r`** on a language → an **inline editor** expands under that
row, scoped to *the group that language currently belongs to*:

```
  [1] cpp
❯ [2] python   relative-to: [cpp]  A:[2.0]  B:[100]
      editing: Tab cycles ref · type A/B · enter ok · esc cancel · c clear
  [ ] java
```

- **Tab** cycles the reference through the *other groups* (shown by a representative
  language) plus **`(base estimate)`** (`relativeTo: None`, relative to the base TL).
- Type to edit **A** (slope, must be `> 0`) and **B** (increment in ms, optional).
- **Enter** commits, **Esc** cancels the edit, **`c`** (or clearing the reference)
  removes the spec.

In the normal list view, a forced-relative group's rows show a persistent
annotation so the relationship is visible without opening the editor:

```
❯ [2] python  → cpp ×2.0 +100
  [1] cpp
  [ ] java
```

**Reset:** a **`R`** (capital, distinct from `r` = edit) hotkey restores the full
initial env-derived state — both `numbers` *and* `relatives` — from a snapshot the
picker stashes at init. The legend documents it.

The **live preview table** already re-renders on every change and surfaces
`GroupValidationError` (self-reference, cycles) inline. Forced specs flow through the
same `validate_partition`, so a bad reference shows an error immediately and blocks
confirm.

Legend (updated):

```
↑/↓ move · 1-9 group · space/tab [X]/[ ] · 0 clear · r relative · R reset env
· enter confirm · q cancel
```

### 4. Data flow

- `prompt_group_assignment` return type grows from `Dict[str, int]` to a small
  struct, e.g. `GroupAssignment{ numbers: Dict[str, int], relatives: Dict[GroupKey,
  ForcedRelative] }`.
- `relatives` is keyed per **group** — numbered bucket `1..9`, the leftover pool,
  and each singleton keyed by its language — so a spec survives membership edits and
  is pruned when its group disappears at confirm time.
- `default_assignment` (or a sibling helper) grows a **per-group solution presence**
  argument (derived from the already-collected `timing_per_solution_per_language`)
  so init can decide which env `whenEmpty` specs to seed.
- `partition_from_assignment` accepts the `relatives` overrides and stamps
  `forced_relative` onto matching `ResolvedGroup`s. Everything downstream
  (`resolve_groups`, `build_limits_table`, the written `timeLimitPerLanguage`) already
  handles relative limits — the resolved profile stores **concrete numbers**, so the
  forced spec is a one-shot computation that never round-trips to `env.rbx.yml`.

## Out of scope

- Persisting forced specs back to `env.rbx.yml` (the resolved profile holds concrete
  numbers; this is a one-shot estimation aid).
- Changing the env schema or the non-interactive `auto` resolution path.

## Testing

- `tests/rbx/box/test_timing_groups.py`: `partition_from_assignment` with relative
  overrides → `forced_relative` stamped; forced relative wins over pooled timings in
  `resolve_groups`; forced vs. empty-only `whenEmpty` priority; validation errors
  (self-reference, cycle) still raised through forced specs.
- New picker-state unit tests (mirroring `GroupPickerState`): `r` edit lifecycle,
  reference cycling incl. `(base estimate)`, A/B parsing/validation, clear, and `R`
  reset to the init snapshot.
- `tests/rbx/box/test_timing_preview.py`: preview reflects a forced relative and
  shows inline validation errors for bad references.
- Init seeding: env `whenEmpty` seeded only for empty groups; not seeded when the
  group has solutions.
