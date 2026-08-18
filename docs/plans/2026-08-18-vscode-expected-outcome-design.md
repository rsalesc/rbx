# Surfacing a solution's expected outcome in VS Code

Follow-up to #664, which gave each verdict its own icon in the Run view. That
settled how the extension shows **what happened**. This settles how it shows
**what was supposed to happen**, and whether it did.

Scope is the VS Code extension only. `rbx run` is unchanged, and no field is
added to the run report: everything below is presentation over data already on
the wire.

## The problem

Two distinct failures of the current view:

1. **The expectation is invisible.** `sols/wa.cpp`, declared `WRONG_ANSWER`,
   answers wrongly and draws a red `close` icon -- pixel-identical to the main
   solution breaking. The declaration is only in the hover tooltip, so the tree
   reads as a wall of failures when nothing is wrong.
2. **Mismatches do not stand out.** The interesting row -- outcome missed the
   declaration -- says `expected AC, got WA` in `TreeItem.description`, which is
   dim monochrome text sitting among every other row's `AC · 120 ms · 4 MiB`.
   Nothing draws the eye.

## What the CLI does, and why we are not copying it directly

`_render_detailed_group_table` (`rbx/box/solutions.py:2362`) gives each solution
a **column**, headed by `solution.href()` and coloured by
`ExpectedOutcome.full_style()`. The expectation lives in the header -- the
identity of the thing -- and the outcomes live in the cells. Two facts, two
axes. The TUI does the same, appending the declared outcome to the solution's
name (`rbx/box/ui/screens/run.py:29-35`).

A tree row is not a table column; it has one line for both facts. So the split
has to be re-expressed in channels a `TreeItem` actually has. Taking inventory:

| channel | state |
| --- | --- |
| icon + icon colour | taken by the outcome (#664) |
| description | taken by verdict / score / time / memory |
| tooltip | already carries `Expected: AC` |
| **`FileDecoration` badge + colour** | **unused**; solution nodes already set `resourceUri` |
| **`contextValue`** | unused for expectation |
| **`TreeView.badge`** | unused |

## Design

**The icon says what happened. The decoration says what was wanted, and whether
it happened.** #664's icon table is untouched, so a TLE stays yellow in the tree
exactly as it is yellow in the terminal beside it.

### Badge: what was declared

The badge carries the declared expectation, using rbx's own glyph set from
`ExpectedOutcome.icon()` (`rbx/box/schema.py:212-218`):

| declared | badge |
| --- | --- |
| `ACCEPTED`, `ACCEPTED_OR_TLE` | `✓` |
| `TIME_LIMIT_EXCEEDED`, `TLE_OR_RTE` | `⧖` |
| `WRONG_ANSWER`, `INCORRECT`, `RUNTIME_ERROR`, `MEMORY_LIMIT_EXCEEDED`, `OUTPUT_LIMIT_EXCEEDED`, `COMPILATION_ERROR`, `JUDGE_FAILED` | `✗` |
| `ANY` | no decoration at all |

Coarse on purpose: these are the three glyphs the CLI shows, and the precise
name stays in the description and the tooltip. `ANY` is not badged because
nothing was declared -- badging it would put a mark on the majority of rows that
carries no information.

`FileDecoration.badge` is plain text, so it cannot be a codicon; the badge and
the icon are necessarily different pixels. They are chosen to rhyme: #664's
`pass` is a tick in a circle, `close` is a cross, `watch` is a clock. `✓` beside
a `pass` icon reads as one statement rather than two alphabets.

### Colour: whether the declaration held

The colour channel carries the **match axis and nothing else**:

- expectation met -> no colour; the row renders normally
- expectation missed -> `charts.red`, which tints the whole row **label**, so a
  mismatched solution's filename goes red while its TLE icon stays yellow
- not yet run -> no colour

This is a deliberate divergence from the CLI, where the header colour is the
expectation's own hue (`ExpectedOutcome.style()`). One channel cannot carry both
facts, and colouring by declaration means a mismatch has no colour of its own --
which is problem 2 unsolved. Mismatches pop here precisely because nothing else
on the row is coloured. The divergence gets a comment in the code, in the style
#664 used for its own colour choices.

Together this fixes problem 1: `sols/wa.cpp` failing as declared keeps its red
`close` icon (it *did* fail) but wears a calm `✗` badge and an uncoloured label
-- visibly doing its job.

### Consolidating the two vocabularies

`outcome.ts` opens by warning that `Outcome` and `ExpectedOutcome` are different
types that must not be conflated, and then conflates them at the bottom:

```ts
default:
  return shortName(expected.toLowerCase().replace(/_/g, '-'));
```

That assumes every `ExpectedOutcome` member name lowercases onto an `Outcome`
key. It holds today by coincidence, not contract -- the enums have genuinely
different members (`INCORRECT`, `ANY`, `TLE_OR_RTE` exist only in one;
`SKIPPED` only in the other). Hanging a badge off that mangle is what would make
the two vocabularies visibly disagree.

So: **two explicit tables, one shared symbol vocabulary, no string-guessing
between them.**

- `DISPLAY` (one record per `Outcome`, already there) gains a `glyph` field:
  `✓ ✗ ⧖ ⊘`, mirroring `get_outcome_markup_verdict`
  (`rbx/box/solutions.py:1326-1339`).
- A new `EXPECTED` table gets one record per `ExpectedOutcome` member, giving
  its short name and its glyph, mirroring `rbx/box/schema.py` the way `DISPLAY`
  mirrors `Outcome`.
- `expectedShortName` stops deriving and starts looking up.

The glyph must be stored per expectation rather than derived from the outcomes
an expectation matches, because the CLI's own mapping is not that derivation:
`ACCEPTED_OR_TLE` matches both `ACCEPTED` and `TLE` but shows `✓`, and
`INCORRECT` matches five outcomes but shows `✗`. A derivation would get both
wrong.

### The hover, and the two layers of expectation

The decoration's tooltip names both sides -- `Expected ✓ AC, got ⧖ TLE` -- a
port of `ExpectedOutcome.full_markup()` joined to
`get_full_outcome_markup_verdict`, minus the colour the decoration already
carries.

A solution declares expectations in two layers, pooled and per-group, and rbx
checks both, so a miss must say *which layer* caught it.
`sols/mislabeled.cpp` in the `outcome-per-group` fixture is the case that
matters: its pooled `INCORRECT` is satisfied -- it does fail -- and only its
`outcomePerGroup` catches it. Rendering that as "expected INCORRECT, but got
WA" would accuse an expectation that was in fact met. So when `failedGroups` is
non-empty the hover names the groups instead: `Declared ✗ INCORRECT, but small,
big did not match`. This is the same distinction `solutionVerdict`
(summary.ts) already draws, for the same reason.

### Where decorations attach

- **Solutions** -- the existing `resourceUri` (`runTree.ts:208`), the real file.
  Decorations are global per URI, so `sols/wa.cpp` carries its `✗` in the
  Explorer and on its editor tab too: the declared expectation is visible while
  you edit the solution, not only while you read a run. `propagate` must be
  `false`, or the badge climbs to the `sols/` folder.
- **Groups** -- no `resourceUri` today; they get a synthetic
  `rbx-run:/<root>/<index>/<group>`. Only groups covered by an `outcomePerGroup`
  entry are badged, which is exactly when `report.yml` sets
  `GroupReport.expectedOutcome`.
- **Testcases** -- nothing. A testcase has no expectation of its own, and leaf
  rows stay clean.

### Staleness

The badge is read from `problem.rbx.yml` via the skeleton, so it is never stale
-- it is a declaration, not a result. The colour is run-derived, and on an
editor tab it would go on claiming a mismatch after the solution was edited and
not re-run. So the colour is dropped when the solution file's mtime is newer
than `report.yml`; the badge stays. An edited solution shows what it promises
and says nothing about what it last did.

### Data flow

Nothing new is read. `report.yml` v1 already carries `expectedOutcome`,
`matchesExpectation` and `failedGroups` per solution and per group
(`rbx/box/run_report.py:42-78`), and `skeleton.yml` carries the declared
expectation before any run finishes (`model.ts:111`).

The provider serves from `ArtifactStore`'s already-loaded `PackageRun` and never
triggers a read -- `provideFileDecoration` is called often and must be cheap.
`onDidChangeFileDecorations` fires from `RunTreeProvider.invalidate()` and
`refresh()`, alongside the existing tree-change event.

### Smaller changes, same theme

- `pendingDescription` gains the expectation: `expects AC · 3/10` rather than
  `3/10`. It comes from the skeleton, so it is available before and during the
  run, not only after it.
- `contextValue` becomes `rbx.solution.mismatch` on a miss, so a `when` clause
  can hang a filter or a menu item off it later.
- `TreeView.badge` counts solutions that missed, visible on the activity-bar
  icon with the view collapsed.
- The solution tooltip leads with the miss instead of burying it under
  `Expected:`.

## Error handling

Unchanged in kind: an unknown `ExpectedOutcome` -- an extension older than the
`rbx-cp` that wrote the report -- misses the `EXPECTED` table and yields no
decoration, the same way an unknown `Outcome` already yields `XX`. Absent is the
correct rendering for "this extension does not know"; guessing a badge would be
the drift this design exists to remove.

## Testing

`expectationBadge()` and `expectationColor()` are pure functions in
`outcome.ts`, covered by `node --test` in `outcome.test.ts` beside the #664
table -- including a test asserting the `EXPECTED` table covers every member of
`ExpectedOutcome`, which is what makes the two tables provably parallel rather
than parallel by inspection. A new `decorations.ts` is a thin `vscode` wrapper
over them, the way `runTree.ts` is thin over `outcome.ts`, keeping the `vscode`
import out of the tested module.
