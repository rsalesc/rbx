# Three-state language bucketing in `rbx time` (refines #497 / PR #499)

Date: 2026-06-01
Refines: `docs/plans/2026-06-01-language-groups-timing-design.md`
PR: https://github.com/rsalesc/rbx/pull/499

## Motivation

The original language-groups design gave every language exactly two fates: a member
of an explicit env group, or an **implicit singleton** (its own pool). Languages not
listed in any env group therefore each became a singleton.

That collapses two genuinely different intents into one:

- "Estimate this language on its own" (a deliberate, isolated bucket), and
- "I didn't configure this language; lump it with the other leftovers."

We split them into **three** states, and change the default for unconfigured
languages from *singleton* to *unbucketed (leftover pool)*.

## The three states

Every language in scope is in exactly one state:

| State | Box | Meaning at resolution |
|-------|-----|-----------------------|
| (a) Explicit group | `[N]` | Pools with all other `[N]` languages. `whenEmpty` carries over iff membership exactly matches an env group. |
| (b) Singleton | `[X]` | Its own pool. Has solutions → own estimate; empty → DEFAULTED to base + warning. "Isolate this language; don't let it ride the leftover pool." |
| (c) Unbucketed | `[ ]` | Joins the single shared **leftover pool**. Pool has any solutions → all members inherit that pooled estimate; pool empty → all DEFAULTED to base + one warning. **New default for unconfigured languages.** |

### Why a leftover pool (and not base TL directly)

When the unbucketed set has **no** accepted solutions (the common #497 case:
java/go/etc. with no solution), an empty leftover pool DEFAULTs to *exactly* the base
TL anyway — so there is no numerical change, only better visibility (one grouped
DEFAULTED row + warning instead of an invisible base fallback).

The leftover pool only changes the *number* when the unbucketed set itself contains
solutions: then its TL is `formula(fastest, slowest)` over **only** those languages'
timings, and unrepresented members inherit that sibling estimate instead of the global
base. This is the intended win.

## Scope change: all env languages participate

`relevant_languages_for_estimation()` previously returned only languages that had
solutions, were in an env group, or were a `whenEmpty.relativeTo` target. An env
language with no solution and no group never entered the picker and silently rode the
base TL — the #497 symptom, just narrowed.

It now returns **all env languages** (still unioning in `whenEmpty` refs and any stray
timing languages), ordered by the environment's language order. This is what places
unrepresented languages into the picker and into the leftover pool / DEFAULTED warning.

Consequence: `--auto` output changes slightly for problems that declare languages with
no solutions — they now appear as one DEFAULTED leftover row instead of being absent.

## Picker UX

Single-screen picker, one row per language, each row showing its box.

Keybindings:

- `1`–`9` — assign group `[N]`
- `Space` / `Tab` — toggle the current language between singleton `[X]` and unbucketed
  `[ ]` (from a numbered `[N]`, the first press goes to `[X]`)
- `Enter` — submit
- `q` / `Ctrl-C` — cancel

Prepopulation:

- Env-grouped languages → their group number `[N]` (single-member env groups stay
  `[N]`, preserving `whenEmpty`).
- All other env languages → unbucketed `[ ]`.
- `[X]` is never a default; reachable only via toggle.

## Data model

Each language's state is an int in the assignment map:

- `N ≥ 1` → group N
- `0` → unbucketed (leftover pool)
- `-1` → singleton

This redefines today's `0` (was "singleton") to mean "unbucketed", so the existing
`{lang: 0}` prepopulation default flips to the new default for free.

## Partition building

- `partition_from_assignment(assignment, env_groups)`:
  - `N ≥ 1` → shared buckets; carry an env group's `whenEmpty` only on exact-membership
    match (unchanged rule).
  - each `-1` → its own singleton group.
  - all `0` → **one** leftover-pool group (no `whenEmpty`). Omitted if empty.
- `build_partition(env_groups, all_languages)` (the `--auto` / non-interactive path):
  env groups verbatim, then **one** leftover group of all remaining languages, instead
  of N implicit singletons.

## Unchanged

`resolve_groups` and the limits-table renderer need no changes: both already handle
multi-language groups, the ESTIMATED / MULTIPLIER / DEFAULTED origins, and DEFAULTED
highlighting. The leftover pool flows through as one ordinary group / row.

## Tests

- `test_timing_group_picker.py` — toggle to `[X]`, toggle back to `[ ]`, number → group,
  prepopulation defaults (env-grouped → `[N]`, others → `[ ]`), Enter submits.
- `test_timing_groups.py` — `partition_from_assignment` with all three states (one
  leftover pool group, singletons separate); `build_partition` yields a single leftover
  group.
- `test_timing_estimation.py` — unrepresented languages inherit a non-empty leftover
  pool; an empty leftover pool DEFAULTs and the warning lists all of them.
- Update existing assertions that depend on the old "0 = singleton" / implicit-singleton
  behavior.

## Out of scope

Unchanged from the original design: memory/output limit grouping, the global fallback
default mechanism itself (we change *which* languages are visibly bucketed, not the
DEFAULTED-to-base resolution), and Approach B (groups as a first-class resolution
concept).
