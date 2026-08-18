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
   solution breaking. The declaration is only in the hover tooltip.
2. **Mismatches do not stand out.** The interesting row -- outcome missed the
   declaration -- says `expected AC, got WA` in `TreeItem.description`, which is
   dim monochrome text sitting among every other row's `AC · 120 ms · 4 MiB`.

## What the CLI does

`_render_detailed_group_table` (`rbx/box/solutions.py:2362`) gives each solution
a **column**, headed by `solution.href()` and coloured by
`ExpectedOutcome.full_style()`. The expectation lives in the header -- the
identity of the thing -- and the outcomes live in the cells. Two facts, two
axes. The TUI does the same (`rbx/box/ui/screens/run.py:29-35`).

A tree row is not a table column; it has one line for both facts. So the split
has to be re-expressed in channels a `TreeItem` actually has.

## The channels, and what they can hold

This is worth stating precisely, because two of the design's decisions are
forced by it rather than chosen:

| channel | can hold |
| --- | --- |
| `TreeItem.iconPath` | one `ThemeIcon`, themeable via `ThemeColor` |
| `TreeItem.description` | plain text |
| `FileDecoration.badge` | a `string` of **at most two characters** -- no icon |
| `FileDecoration.color` | **one** `ThemeColor`, tinting badge and label together |
| `FileDecoration.tooltip` | plain text -- no markdown, no icon |

So: a codicon cannot appear in a decoration at all, a decoration cannot carry
two colours, and there is no bold/italic anywhere -- which rules out porting
rbx's own trick of separating `ACCEPTED` (`bold green`) from `ACCEPTED_OR_TLE`
(plain `green`) by weight.

## Design

**The decoration says what was declared. The icon says what happened, and
whether that was what was wanted.**

### Decoration: the declaration

- **Badge** -- the two-letter spelling rbx itself accepts in `problem.rbx.yml`:
  `AC`, `WA`, `TL`, `ML`, `OL`, `RE`, `JF`, `CE`. The mark on the row is the
  token the setter typed into their own file, so the view introduces no
  vocabulary of its own. Compound expectations keep rbx's `+` separator from its
  `ac+tle` and `tle+re` aliases: `A+` and `T+`, which is also the honest reading
  -- *accepted, and more is tolerated*. `INCORRECT` is `IN`.

  Letters rather than rbx's `✓ ⧖ ✗` glyphs for two reasons: the row already
  carries a codicon, and a second symbolic alphabet beside it reads as noise;
  and at the badge's ~11px a `⧖` is not distinguishable from a `✗`, where `TL`
  and `WA` are unambiguous. VS Code's own decorations are letters (`M`, `U`,
  `A`) for the same reason.

- **Colour** -- `ExpectedOutcome.style()` transposed onto the `charts.*` family,
  the same transposition #664 made for verdicts. A solution declared TLE is
  yellow here exactly as `rbx run` prints it yellow. Note `OUTPUT_LIMIT_EXCEEDED`
  is purple, not the orange an OLE *outcome* draws: `style()` has no branch for
  it and falls through to magenta. This colours a declaration, not a verdict.

- `ANY` gets no decoration at all. Nothing was declared, and marking every
  undeclared solution would put a mark carrying no information on most rows.

Both come from `problem.rbx.yml` by way of the skeleton, so neither is a claim
about the last run and **neither goes stale** when the solution is edited.

### Icon: the verdict, and whether it was the declared one

On a match, #664's table is untouched.

On a miss the icon switches to the same verdict's **mismatch variant** -- that
codicon with a small circled cross in its top-right corner -- and turns red. The
verdict stays legible (a solution that missed by timing out still shows a clock)
while the row stops claiming the run went to plan.

Red rather than the verdict's own hue is the one place this view departs from
the terminal palette. On a row that broke its promise the interesting fact is
the promise, not the verdict, and once colour moved to the declaration this is
the only channel left to say so.

**Consequence worth naming:** because the mark lives in the icon, and only the
Run view draws an icon, a mismatch is visible there and *not* on an Explorer
entry or an editor tab. Those still show what a solution was declared to be,
which is the more useful fact while editing it.

### The mismatch icons

No codicon exists for "this icon, but wrong", so the glyphs are generated:
`scripts/build-mismatch-font.py` builds `resources/rbx-mismatch.woff`, in which
each glyph is a TrueType **composite** of two codicon outlines -- the verdict
icon scaled down and anchored bottom-left, plus `error` scaled into the corner.
Components reference the base outlines rather than copying them, so every icon
gets an identical mark and the font is ~2.5 KB.

A contributed icon font rather than SVG files because icons declared through
`contributes.icons` are ordinary `ThemeIcon`s and so accept a `ThemeColor`; an
SVG referenced by `iconPath` is an image fixed at whatever colours are baked
into it, which would have cost the per-verdict palette this view shares with the
terminal.

The mark is `error` -- a circled cross -- rather than a bare `close` cross,
which is not a style preference: a tree row draws at 16px, and at that size the
cross alone thins to a hairline that disappears against the base glyph, while
the circle gives the mark a closed shape that survives rasterisation. Judging
this at 64px will mislead you; `--preview` renders the sizes that matter.

The outlines come from VS Code's codicons (CC BY 4.0);
`resources/CODICONS-LICENSE.md` carries the required attribution and ships with
the font.

### The hover, and the two layers of expectation

The tooltip names both sides -- `Expected AC, but got TLE`. Names rather than
marks because `FileDecoration.tooltip` is a plain string and can carry neither a
codicon nor a glyph it could explain.

A solution declares expectations in two layers, pooled and per-group, and rbx
checks both, so a miss must say *which layer* caught it. `sols/mislabeled.cpp`
in the `outcome-per-group` fixture is the case that matters: its pooled
`INCORRECT` is satisfied -- it does fail -- and only its `outcomePerGroup`
catches it. Rendering that as "expected INCORRECT, but got WA" would accuse an
expectation that was in fact met. So when `failedGroups` is non-empty the hover
names the groups instead: `Declared INCORRECT, but samples, main did not match`.
Same distinction `solutionVerdict` (summary.ts) already draws.

### Where decorations attach

- **Solutions** -- the existing `resourceUri` (`runTree.ts:208`), the real file.
  Decorations are global per URI, so the declaration also shows in the Explorer
  and on editor tabs. `propagate` must be `false`, or the badge climbs to the
  `sols/` folder.
- **Groups** -- no `resourceUri` today; they get a synthetic
  `rbx-run:/<index>/<group>`. Only groups covered by an `outcomePerGroup` entry
  are decorated, which is exactly when `report.yml` sets
  `GroupReport.expectedOutcome`.
- **Testcases** -- nothing. A testcase has no expectation of its own.

## Consolidating the two vocabularies

`outcome.ts` opens by warning that `Outcome` and `ExpectedOutcome` are different
types that must not be conflated, and then conflated them at the bottom:

```ts
default:
  return shortName(expected.toLowerCase().replace(/_/g, '-'));
```

That assumes every `ExpectedOutcome` member name lowercases onto an `Outcome`
key. It holds today by coincidence, not contract -- the enums have genuinely
different members (`INCORRECT`, `ANY`, `TLE_OR_RTE` exist only in one;
`SKIPPED` only in the other).

Now: two explicit tables, no string-guessing between them. `EXPECTED` has one
record per `ExpectedOutcome` member giving its name, badge and hue, mirroring
`schema.py` the way `DISPLAY` mirrors `Outcome`, with a test asserting every
member is covered.

## Data flow

Nothing new is read. `report.yml` v1 already carries `expectedOutcome`,
`matchesExpectation` and `failedGroups` per solution and per group
(`rbx/box/run_report.py:42-78`), and `skeleton.yml` carries the declared
expectation before any run finishes (`model.ts:111`).

The decoration provider serves from `ArtifactStore`'s already-loaded
`PackageRun` and never triggers a read. `onDidChangeFileDecorations` fires from
the tree's existing change event, since a decoration goes out of date under
exactly the conditions the tree already watches for.

## Smaller changes, same theme

- `pendingDescription` gains the expectation: `expects AC · 3/10`. It comes from
  the skeleton, so it is available before and during the run.
- `contextValue` becomes `rbx.solution.mismatch` on a miss -- suffixed, so the
  existing prefix-regex menu `when` clauses keep applying.
- `TreeView.badge` counts solutions that missed, visible with the view
  collapsed. Misses, not failures: badging a solution that fails on purpose
  would report the package's own test suite as a problem.

## Error handling

An unknown `ExpectedOutcome` -- an extension older than the `rbx-cp` that wrote
the report -- misses the `EXPECTED` table and yields no decoration, the same way
an unknown `Outcome` already yields `XX`. Absent is the correct rendering for
"this extension does not know"; guessing would be the drift this design exists
to remove.

An unknown *icon id* is the more dangerous case, because VS Code renders it as
**blank** rather than complaining. A test therefore asserts that every verdict
`outcomeIcon` can return has a matching entry in `contributes.icons`, so a
verdict added to `DISPLAY` without regenerating the font fails the suite instead
of silently blanking the row.

## Testing

The display logic is pure functions in `outcome.ts` and `expectation.ts`,
covered by `node --test` without a `vscode` import; `decorations.ts` and
`runTree.ts` stay thin wrappers over them. Beyond the per-function tests, three
guard the seams that types cannot:

- every `ExpectedOutcome` member has a record,
- every badge is at most two characters (`FileDecoration.validate` throws
  otherwise, which is a runtime failure in the view),
- every mismatch icon is contributed in package.json.
