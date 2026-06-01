# Language groups for time-limit estimation (issue #497)

Date: 2026-06-01
Issue: https://github.com/rsalesc/rbx/issues/497

## Problem

When `rbx time` estimates per-language time limits, it stores overrides in
`.limits/{profile}.yml` `modifiers` for languages that *have* solutions, while the
base `timeLimit` reflects only the represented languages. Any language **without a
solution** (Java, Kotlin, Go, …) silently falls back to that base TL, which can be
unreasonably tight. The change is invisible — setting specific limits masks the
fallback — so it surfaces as a contest surprise.

## Goals

The issue's three proposals, all in scope:

1. **Language grouping** — related languages (C/C++, Java/Kotlin) share an estimated
   TL bucket so an unrepresented language inherits a sibling's limit instead of the
   global base.
2. **Visibility after `rbx time`** — a detailed per-group table showing resolved TL
   and its origin (estimated / multiplier / defaulted).
3. **Visibility at BOCA package build** — the *same* table, printed last, so what
   ships is unambiguous.

We are **not** changing the global fallback default; instead groups + clear
visibility address the risk.

## Approach (A): groups are an estimation-time abstraction

Groups live only in `env.rbx.yml` and in `timing.py`. At the end of estimation they
**compile down** to the existing per-language `modifiers[lang].time` entries that the
rest of the system (`timelimit_for_language()`, the BOCA packager) already consumes.
No consumer changes, no resolution-path changes, fully backward-compatible. The
`.limits` file additionally carries *metadata* describing the grouping for later
presentation, but that metadata is never used for resolution.

Rejected alternatives:
- **B (groups first-class in `LimitsProfile`)** — invasive; touches the schema and
  every consumer, adds a second indirection over the BOCA `cc`→`cpp` mapping (#493).
- **C (hybrid: store groups *and* expanded values redundantly)** — over-engineered.

## Section 1 — Schema (`env.rbx.yml`)

Groups are **anonymous**. They are referenced (only by `whenEmpty.relativeTo`) via any
language they contain.

```yaml
timing:
  formula: "step_up(max(fastest * 3, slowest * 1.5), 100)"
  groups:
    - languages: [c, cpp]
    - languages: [java, kotlin]
      whenEmpty:                 # used ONLY if this group has no solutions
        relativeTo: cpp          # any language; resolves to the group containing it.
        multiplier: 2.0          #   omit relativeTo -> multiply the base estimate
    - languages: [python]
```

New models in `rbx/box/environment.py`:

```python
class LanguageGroupFallback(BaseModel):
    relativeTo: Optional[str] = None   # a language name; None = base estimate
    multiplier: float

class LanguageGroup(BaseModel):
    languages: List[str]               # rbx language names
    whenEmpty: Optional[LanguageGroupFallback] = None

class TimingConfig(BaseModel):
    formula: str = ...
    groups: List[LanguageGroup] = Field(default_factory=list)
```

Load-time validation:
- A language may appear in **at most one** group (disjoint partition); duplicates error.
- Env languages not listed → their own **implicit singleton** group.
- `relativeTo` must be a known language resolving to a *different* group; `whenEmpty`
  reference chains must be acyclic.

## Section 2 — Estimation flow (`rbx/box/timing.py`)

`estimate_time_limit()` becomes group-aware:

1. **Build the partition** — every env language → its group (explicit + implicit
   singletons).
2. **Pool timings per group** — run all ACCEPTED solutions unlimited (as today),
   attribute each solution's timings to its language's group, pooling members together.
3. **Estimate per non-empty group** — `fastest`/`slowest` over pooled timings → formula
   → group TL.
4. **Base `timeLimit`** = overall estimate across *all* accepted solutions pooled
   (unchanged from today). This is the fallback for empty-no-`whenEmpty` groups.
5. **Resolve empty groups** in dependency order (acyclic):
   - `whenEmpty` present → `referenced_group_TL * multiplier` (or `base * multiplier`
     when `relativeTo` omitted).
   - `whenEmpty` absent → base TL, **emit a loud warning** naming affected languages.
6. **Expand** every group's TL into per-language `modifiers[lang].time`.

### Interactive repartitioning (only when not `--auto`)

A checkbox-style prompt where **each language carries a group number**:

- Numbers prepopulated from `env.rbx.yml`: env group #1 → `1`, #2 → `2`, …; languages
  in no env group start at `0`.
- User edits per language: `0` = unassigned (own implicit singleton); `N ≥ 1` =
  member of group `N`. Same number = same bucket.
- Groups are reconstructed from the final numbers. This replaces today's "checkbox of
  which languages get a specific TL" prompt.

**`whenEmpty` preservation rule:** for each resulting group, if its membership is
*identical* to an env-defined group (same languages, no more/less), that env group's
`whenEmpty` carries over. If membership changed at all, `whenEmpty` is dropped and the
group uses defaults (base TL + loud warning if empty).

`--auto` uses env groups verbatim, no prompt; DEFAULTED warnings still print.

## Section 3 — Storage & metadata (`.limits/{profile}.yml`)

Per Approach A, per-language TLs expand into `modifiers` so all consumers are
untouched. Additionally, store **thorough** grouping metadata so the table is fully
reconstructable from a saved profile.

```python
class TimingGroupOrigin(str, Enum):
    ESTIMATED  = 'estimated'    # group had solutions; TL from the formula
    MULTIPLIER = 'multiplier'   # empty group resolved via whenEmpty
    DEFAULTED  = 'defaulted'    # empty group, no whenEmpty -> base TL (warned)

class TimingGroupReport(BaseModel):
    languages: List[str]
    timeLimit: int                              # resolved TL, ms
    origin: TimingGroupOrigin
    solutionCount: int = 0                      # contributing ACCEPTED solutions
    fastest: Optional[int] = None               # ms; ESTIMATED only
    slowest: Optional[int] = None               # ms; ESTIMATED only
    relativeToLanguage: Optional[str] = None    # MULTIPLIER only; None = base estimate
    multiplier: Optional[float] = None          # MULTIPLIER only

class LimitsProfile(BaseModel):
    ...
    groups: Optional[List[TimingGroupReport]] = None   # metadata only; never resolution
```

`groups` is **optional**: pre-existing files and the `inherit`/`custom` strategies
leave it `None`, and presentation degrades gracefully (per-language rows from
`modifiers` + base, without origin/solution-count annotations). Group TLs are not
duplicated into the table renderer beyond `timeLimit`; per-member TLs remain in
`modifiers`.

Example:

```yaml
timeLimit: 2000
modifiers:
  c: {time: 1000}
  cpp: {time: 1000}
  java: {time: 4000}
  kotlin: {time: 4000}
  python: {time: 5000}
groups:
  - languages: [c, cpp]
    timeLimit: 1000
    origin: estimated
    solutionCount: 2
    fastest: 280
    slowest: 600
  - languages: [java, kotlin]
    timeLimit: 4000
    origin: multiplier
    relativeToLanguage: cpp
    multiplier: 4.0
  - languages: [python]
    timeLimit: 5000
    origin: estimated
    solutionCount: 1
    fastest: 1600
    slowest: 1600
```

## Section 4 — Presentation tables

A **shared renderer** (e.g. `timing.render_limits_table(limits_profile)`) used by both
`rbx time` and the BOCA packager so the table is identical. One row per group when
`groups` metadata is present; otherwise one row per `modifiers` language plus a base row.

| Languages    | Solutions | Time Limit  | Source                          |
|--------------|-----------|-------------|---------------------------------|
| c, cpp       | 2         | 1000 ms     | estimated (fastest 280 / 600)   |
| python       | 1         | 5000 ms     | estimated (1600 / 1600)         |
| java, kotlin | 0         | 4000 ms     | ×4.0 of cpp                     |
| go           | 0         | **2000 ms** | ⚠ DEFAULTED to base             |

- `rbx time`: rendered **always** at the end of estimation (not gated by `--detailed`;
  `--detailed` continues to gate the per-solution breakdown).
- BOCA package build: rendered from `.limits/boca.yml` and printed **last** in the
  packaging command, so DEFAULTED warnings are the final visible output. **No error.**
- DEFAULTED rows are highlighted (warning color) and also emit the loud log warning.

## Section 5 — Edge cases

- **No groups configured anywhere** → all languages implicit singletons; behaves ≈
  today, now with the table.
- **`relativeTo` target also empty** → resolves transitively (acyclic guarantee); if the
  chain bottoms out at a DEFAULTED group, the multiplier applies to base.
- **`--auto`** → env groups verbatim, no prompt; DEFAULTED warnings still print.
- **`inherit`/`custom` strategies** → `groups` left `None`; degraded table view.
- **Language in `modifiers` but no group metadata** (older files) → degraded view.

## Out of scope

- Memory/output limit grouping (issue is time-only).
- Changing the global fallback default.
- Persisting groups as a first-class resolution concept (Approach B).
