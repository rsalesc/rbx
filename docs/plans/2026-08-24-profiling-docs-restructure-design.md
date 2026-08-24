# Profiling docs restructure — design

**Status:** approved 2026-08-24 (brainstorm).
**Scope:** the **Feature Guide → Profiling** section, plus two additions to the cast pipeline
(`casts/`, `scripts/casts/`) and one new rule in the docs writing-style guide.
**Style authority:** [`docs/plans/docs-writing-style-guide.md`](docs-writing-style-guide.md).
**Pipeline authority:** `casts/README.md` and
[`docs/plans/2026-08-08-asciinema-recording-pipeline-design.md`](2026-08-08-asciinema-recording-pipeline-design.md).

## 1. Motivation

`docs/setters/profiling/index.md` is a single 649-line page, the longest hand-written guide in
the docs and the only Feature Guide section that never got split. Profiling is a crucial part
of rbx — it is what turns a package into something a judge can actually run — and the page is
currently the hardest one to read.

Three concrete problems:

1. **Three unrelated concepts in one page.** The `rbx time` flow, the knobs that shape the
   number it computes (ratios, formulas, language groups, wall time), and profiles as a
   storage-and-consumption mechanism (`.limits/*.yml`, who reads one, the TUI, `--integrate`)
   are interleaved rather than separated. A reader who came because BOCA packaging demanded a
   `boca` profile has to scroll past the whole estimation theory to find out what a profile is.
2. **No running example.** The style guide's central rule for the feature-guide register is a
   single motivational problem carried down the page. This page has none — every snippet is a
   different toy, so the reader re-orients at each section.
3. **Extras are sprinkled, not sectioned.** `--runs`, `inference:`, `RBX_TIME_MULTIPLIER` and
   `--skip-slow` all appear mid-narrative instead of each owning a `##` below the happy path,
   which is the rule §10 of the style guide calls the most valuable and most easily broken.

Only one cast covers the whole feature, and the two behaviours readers most need to *see* — the
upper-bound check failing and reopening the picker, and the language-group picker itself — are
prose-only.

## 2. Decisions

1. **Six pages** (§3), each answering one reader question.
2. **`profiling/remote.md` is a sibling of `running/remote.md`**, not a merge and not a link-out.
   The two-phase / two-upload story is genuinely about estimation and would be off-topic under
   "Running"; a profiling reader should not have to leave the section for a core capability.
3. **The shared MOJ contract is deduplicated with a snippet.** `pymdownx.snippets` is already
   enabled. The backend contract — the `moj` CLI login, the committed `.moj-id`, the throwaway
   problem that is refused rather than overwritten, and what a judge cannot report — moves to
   `docs/_partials/moj-backend.md` and is included by both pages. `running/remote.md` is
   rewritten to consume it, so the two stop drifting. Wording that genuinely differs (`…-run`
   vs `…-slow`, one upload vs two) stays in each page's own prose.
4. **One running example across all six pages**, backed by a new `timing-problem` fixture (§5).
5. **Five casts, up from one** (§6), using the two new pipeline knobs (§7).
6. **No internal detail that is prone to change** (§8) — a new style-guide rule, applied to
   every rewritten page.

## 3. Target nav

```
Feature Guide → Profiling
├── Profiling                  setters/profiling/index.md            (keep path, rewrite)   ~80
├── Limits profiles            setters/profiling/profiles.md         (new)                 ~150
├── Estimating a time limit    setters/profiling/estimating.md       (new)                 ~150
├── How the limit is computed  setters/profiling/computing.md        (new)                 ~130
├── Language groups            setters/profiling/language-groups.md  (new)                 ~110
└── On the judge itself        setters/profiling/remote.md           (new)                  ~80
```

`mkdocs.yml` gains the five entries under the existing `Profiling` group, matching the shape
already used by `Running`, `Grading` and `Verification` (bare `index.md` first, then titled
siblings).

## 4. Page breakdowns

Section names below are the intended headings: sentence case, gerunds and honest questions, per
style guide §10.

### 4.1 Profiling — `index.md` (rewrite, 649 → ~80 lines)

Definition, then the frustration: a limit that fits your laptop is too tight or too generous on
the judge, and picking one by hand is guessing. Introduces the running example (§5). Then the
happy path as three commands — `rbx time` writes `.limits/local.yml`, `rbx run -p boca` uses
one — with the reworked `time-estimate` cast right after the snippet that introduces it. Closes
by pointing at the five pages below in reading order.

Everything else moves out. This page should be readable in a minute.

### 4.2 Limits profiles — `profiles.md`

The storage-and-consumption side, which is what most readers actually arrive for.

`## What a profile is` (the `.limits/` layout and the schema, linking to `LimitsProfile.json`
rather than restating every field) · `## Per-language modifiers` · `## Using a profile when
running solutions` (`-p` on `rbx`/`rbx run`/`rbx irun`, and the precedence rule) · `## Using a
profile when building statements` · `## Profiles and packaging` (the BOCA requirement) ·
`## Inheriting from the package` · `## Integrating a profile back into the package` ·
`## Editing profiles in the TUI` (with the new `limits-editor` cast) · `## Editing a profile by
hand` · `## Scaling every limit at once` (`RBX_TIME_MULTIPLIER`, currently a footnote).

### 4.3 Estimating a time limit — `estimating.md`

`rbx time` end to end.

`## Running rbx time` (the flow, its phases) · `## Strategies` · `## Which solutions bound which
side` (`inference:`) · `## The estimation cap` (`inferenceTimeout`) · `## Checking the upper
bound` (with the new `time-upper-bound-violation` cast) · `## Skipping the upper-bound check`
(`--skip-slow`) · `## Running each solution several times` (`--runs`) · `## Sharing the report`
(`--share`, **currently undocumented**) · `## Flags`.

### 4.4 How the limit is computed — `computing.md`

The knobs, kept away from the flow.

`## Time limit ratios` (the default; bounds both sides) · `## Time limit formulas` (variables,
functions, providing one, examples) · `## Wall time limits` (short; defers to the environment
reference).

### 4.5 Language groups — `language-groups.md`

`## Why group languages` (the unrepresented-Java pain) · `## Bucketing languages` (the picker,
with the new `time-language-groups` cast) · `## Forcing a relative limit` (++r++, and the
warning about a derived limit its own solutions cannot meet) · `## Configuring groups in the
environment` (`whenEmpty`, deferring to the reference).

### 4.6 On the judge itself — `remote.md`

Mirrors `running/remote.md` beat for beat.

`## Why measure there` · `## Timing on MOJ` (includes `_partials/moj-backend.md`) · `## The two
phases, and the two uploads` (the part unique to `rbx time`: the calibration wait, the
per-regroup re-upload, caching, and `--skip-slow` as the one-upload path). Cross-links to
`running/remote.md` for the verdict-shaped question, as that page already links back.

## 5. The running example — a new `timing-problem` fixture

`ab-problem` cannot carry this section: it has one accepted C++ solution and one wrong-answer
solution, so it can show neither a language group nor an upper-bound check.

`casts/fixtures/timing-problem` is a new fixture shaped for teaching profiling:

- an accepted C++ solution and an accepted Python solution, so a per-language limit is real;
- Java present in the environment but **unsolved**, which is the exact pain language groups fix;
- a solution marked `tle` that is slow, and one tuned to sit *near* the bound so the
  upper-bound check can be shown failing;
- input sizes chosen so the whole flow records in a tolerable time.

The same package is the running example in the prose of all six pages, so a reader sees the
code they just read. Per `casts/README.md`, it must build standalone before use, and the
generated `build/`, `.rbx/` and `rbx.h` must not be committed.

## 6. Casts

| Cast | Page | Shows |
| --- | --- | --- |
| `time-estimate` (rework) | `index.md` | the happy path, on the new fixture, fast-forwarded |
| `time-upper-bound-violation` | `estimating.md` | a slow solution beating the bound; the picker reopening with the violated row flagged |
| `time-language-groups` | `language-groups.md` | bucketing Java, the preview table updating, ++r++ for a relative rule |
| `time-profiles` | `profiles.md` | `rbx time -p boca` then `rbx package boca` |
| `limits-editor` | `profiles.md` | the TUI limits editor |

Each goes immediately after the snippet that introduces its command, never as decoration, per
style guide §11. `expect_contains` on each must name strings that would genuinely disappear if
the command broke, and must match one uninterrupted run of plain text.

## 7. Cast pipeline additions

Two knobs. Both are honest — they describe something that really happened — and both keep a
cast's duration deterministic.

### 7.1 Fast-forward

Today `casts/time-estimate.yml` sits through a 45-second compute at 1×, and the page compensates
with a blanket `speed=2` on the embed, which also doubles the parts worth reading.

Add a **scoped time scale**:

- `speed: 8` on an instruction, scaling the cast clock for that command's real elapsed time.
- An `x8` token inside an `!Interactive` `keys` list, taking effect from that point until the
  next such token, so the 4-second "read the prompt" dwells stay at 1× while the 45-second
  compute compresses.

Implementation is a scale factor applied in the engine's `sync()` — the function that advances
the cast clock by real elapsed time — and *not* in `_type_command`, so typing animation keeps
its authored speed. Because key dwells are already authored as fixed durations, the resulting
cast length is deterministic, which also blunts the "re-record on an idle machine" hazard
documented in `casts/README.md` for those windows.

### 7.2 Cropping the view

Add per-instruction `width` / `height`. Each instruction already gets its own pty, so this is a
genuinely smaller terminal rather than a post-hoc crop, and rbx's Rich output renders to fit it.
The recorder emits an asciicast `r` (resize) event at the point the size changes; the vendored
`asciinema-player.min.js` handles `r` events, verified before this design was written.

### 7.3 Explicitly out of scope

**Content trimming** — dropping a command's output before some marker string. It desyncs Rich's
cursor state, and `!Command {hidden: true}` plus `!Clear` already covers the cases that matter.

`casts/README.md` gains both knobs in its instruction table and a short subsection each.

## 8. New style-guide rule: ration internal detail

Add to `docs-writing-style-guide.md` (as a DO/DON'T pair and a short section): **document the
contract, not the implementation.** Prefer the behaviour a setter can rely on over the mechanism
that currently produces it. Name a specific number, file name or internal step only when the
reader must act on it; otherwise describe the guarantee and link to the reference or the schema,
which are generated and cannot drift.

The existing precedent is the `default_timing_formula()` macro: the page reads the formula out
of `rbx/box/environment.py` at build time rather than restating it, because a reader following a
stale formula is worse off than one told nothing. Applied to this section, it means the profile
schema page links to `LimitsProfile.json` instead of duplicating the field list, and the
upper-bound and remote pages describe what is guaranteed rather than transcribing the internal
sequence.

## 9. Verify against code before writing prose

The page is old enough to have drifted; one omission is already confirmed. Check, against the
source rather than against the current page:

- **`rbx time` flags** — `rbx/box/cli.py:669`. The page's flag table is **missing `--share`**
  (`--share png|text`). Confirm every other flag, short form and default.
- **Strategy names** — `estimate`, `inherit`, `estimate_custom`, `custom`.
- **Profile schema** — the live `LimitsProfile` model, including `upperValidation` and
  `lowerViolation`.
- **Ratio semantics** — `acToTimeLimit`, `timeLimitToTle`, `timeResolution`, and the
  exit-non-zero-when-unsatisfiable behaviour.
- **The deprecated `timing.multipliers.inferenceTimeout` spelling** — decide whether the
  `!!! note "The old spelling"` still earns its place now that `migrating-to-v1.md` exists, or
  whether it should be dropped from the guide and left to that page.
- **Timing sections of `setters/reference/environment`** — reconcile with the rewritten guide;
  fix drift, keep changes minimal.

## 10. Out of scope

- The auto-generated Reference schema pages (mkdocstrings over the live models) — link, do not
  duplicate.
- Any change to `rbx` behaviour. If verification turns up an rbx bug rather than a docs bug,
  record it and leave the code alone.
- The narrative Walkthrough track. Profiling stays a feature guide.
