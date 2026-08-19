# Surfacing a solution's expected outcome in the VS Code Run view

Follow-up to #664, which gave each verdict its own icon. That settled how the
extension shows **what happened**. This settles how it shows **what the package
asked for**, and whether it got it.

Scope is the Run view only. `rbx run` is unchanged and no field is added to the
run report: everything below is presentation over data already on the wire.

## The problem

1. **The expectation is invisible.** `sols/wa.cpp`, declared `WRONG_ANSWER`,
   answers wrongly and draws a red `close` icon -- pixel-identical to the main
   solution breaking. In the sample package, six of eleven rows draw a failure
   icon while doing exactly what was asked, so the tree reads as a wall of red
   when nothing is wrong.
2. **Mismatches do not stand out.** The one row that matters -- the run missed
   the declaration -- said `expected AC, got WA` in dim monochrome
   `description` text, sitting among every other row's `AC · 120 ms · 4 MiB`.

## What the CLI does

`_render_detailed_group_table` (`rbx/box/solutions.py:2362`) gives each solution
a **column**, headed by `solution.href()` and coloured by
`ExpectedOutcome.full_style()`; the verdicts go in the cells below. The
expectation is the column's *identity*; the outcome is its *content*. The TUI
does the same, appending the declared outcome to the solution's name
(`rbx/box/ui/screens/run.py:29-35`).

A tree row is not a column, but it has the same two slots.

## Design

**A solution row is a claim, not a result.** So:

| channel | carries |
| --- | --- |
| icon | the **declared expectation**, one icon per `ExpectedOutcome` |
| description | what the run actually produced |
| label colour | red **iff** the run missed the declaration |
| badge (right) | `✗` **iff** the run missed the declaration |
| tooltip | the full breakdown, including which groups missed |

Testcase rows are unaffected: a testcase has no expectation of its own, so it
keeps the verdict icons from #664. That is also what keeps the two vocabularies
rhyming -- an `ACCEPTED` solution row and an accepted testcase beneath it both
draw `pass`.

### One icon per expectation

The icon *is* the expectation, so two different promises must not share one.
Where an expectation names exactly one outcome it borrows that outcome's icon
from `DISPLAY`. The four that name no single outcome get their own:

| expectation | icon | | expectation | icon |
| --- | --- | --- | --- | --- |
| `ANY` | `dash` | | `TIME_LIMIT_EXCEEDED` | `watch` |
| `ACCEPTED` | `pass` | | `TLE_OR_RTE` | `flame` |
| `ACCEPTED_OR_TLE` | `pass-filled` | | `MEMORY_LIMIT_EXCEEDED` | `server` |
| `WRONG_ANSWER` | `close` | | `OUTPUT_LIMIT_EXCEEDED` | `arrow-both` |
| `INCORRECT` | `circle-slash` | | `JUDGE_FAILED` | `law` |
| `RUNTIME_ERROR` | `zap` | | `COMPILATION_ERROR` | `tools` |

`ACCEPTED` vs `ACCEPTED_OR_TLE` and `WRONG_ANSWER` vs `INCORRECT` are the pairs
a coarse pass/fail/slow set would have collapsed, and a test asserts all twelve
stay distinct. Every id was checked against the codicon table in an installed
VS Code build.

Colours are `ExpectedOutcome.style()` transposed onto `charts.*` -- exact
parity with the column header this icon replaces. Note it deliberately does not
match the *verdict* palette everywhere: a declared `OUTPUT_LIMIT_EXCEEDED` is
magenta while an OLE verdict is orange, because those are two different
functions in rbx, and copying one onto the other would invent a colour rbx
never prints.

### One vocabulary

The first cut drew a codicon on the left and one of rbx's `✓ ⧖ ✗` glyphs on the
right: two alphabets for the same kind of statement. The glyphs are gone. The
tree speaks codicons, and `MISMATCH_BADGE` (`✗`) is the single exception,
forced by `FileDecoration.badge` being a `string` -- it says nothing about
*which* expectation or *which* verdict, only that the two disagree.

### Red means exactly one thing

Only a missed expectation colours a **label**. Verdict colour lives in the
icon, so the label channel is free to carry one fact, and a row whose text is
red is a row where the package disagrees with itself.

An expectation that is *itself* red (`WRONG_ANSWER`, `INCORRECT`) still draws a
red icon whether or not it was met -- that is the declaration's own hue, per
CLI parity. The mismatch signal is the label plus the `✗`, not the icon.

### Descriptions stay narrow

Since the icon carries the expectation, a mismatch never repeats it:

| case | description |
| --- | --- |
| met | `AC · [100/100 pts] · 12 ms · 10 MiB` |
| missed, pooled | `got WA · [30/100 pts] · 9 ms · 10 MiB` |
| missed, per group | `failed samples, main, edge, big · ...` |
| still running | `expects AC · 3/10` |

The per-group form matters: a solution can satisfy its pooled expectation and
still be caught per group. `sols/mislabeled-groups.cpp` declares `incorrect`
pooled -- which **holds**, it does fail -- and `tle` for every group, which it
misses. Naming the pooled expectation there would accuse one that was met.

### Groups

Identical treatment, driven by `GroupReport.expectedOutcome`, which rbx sets
exactly when `outcomePerGroup` covers the group. A group with no declaration of
its own falls back to its verdict icon, that being the only thing it has to
show.

### Why rows are not files

Every decorated row is addressed by a synthetic `rbx-run:` URI, **including
solutions**, which do have a real file. Decorations are global per URI, so
pointing at `sols/wa.cpp` would mark it in the Explorer and on its editor tab
too. That is a separate question with its own scoping and staleness problems
(see the channel inventory issue), and a private scheme keeps this change
inside the view it was designed for. Nothing else reads `resourceUri` -- the
commands all take the node -- so nothing else changes.

This also removes the need for the mtime-vs-report staleness rule an earlier
draft carried: its whole purpose was to stop an editor tab accusing a file the
user had already fixed, and no decoration leaves the Run view any more.

### Tooltips

Markdown with `supportThemeIcons`, leading with the miss and listing every
group that missed with both sides named -- the same lines
`_group_failure_lines` prints. Note the hover *delay* is not controllable from
an extension; it is the user-level `workbench.hover.delay` setting.

## Consolidating the vocabularies

`outcome.ts` opened by warning that `Outcome` and `ExpectedOutcome` must not be
conflated, then ended with `shortName(expected.toLowerCase().replace(/_/g,
'-'))`, reaching an `Outcome` key by lowercasing an `ExpectedOutcome` name. It
held by coincidence: the enums have different members (`INCORRECT`, `ANY`,
`TLE_OR_RTE` only in one; `SKIPPED` only in the other). It is now an explicit
`EXPECTED` table, one record per member, with a test that every member is
covered.

## Data flow

Nothing new is read. `report.yml` v1 already carries `expectedOutcome`,
`matchesExpectation` and `failedGroups` per solution and per group
(`rbx/box/run_report.py:42-78`), and `skeleton.yml` carries the declaration
before any run finishes (`model.ts:111`).

The decoration provider serves from `ArtifactStore`'s cached `PackageRun` and
rides `onDidChangeTreeData`, which already fires when artifacts land.

## Error handling

An `ExpectedOutcome` this extension is too old to know misses the table, draws
no expectation icon, and the row falls back to its verdict. Absent is the
correct rendering for "not known"; guessing would be the drift this design
exists to remove.

## Testing

`expectationIcon`, `expectationColor` and `expectedShortName` are pure and
covered in `outcome.test.ts`, including the twelve-way distinctness check and
the CLI colour table. Verified end to end against `rbx-vscode-sample`, whose
eleven solutions cover every expectation and all three mismatch shapes.
