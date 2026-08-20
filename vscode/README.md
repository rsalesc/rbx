# rbx for VS Code

Browse the results of an `rbx run` without leaving the editor: solution →
group → testcase, with verdicts, timings and a diff of what a solution printed
against the expected answer.

Execution stays in the terminal. You type `rbx run`; the extension watches
`.rbx/runs/` and renders whatever lands there. It never invokes `rbx` itself --
every `rbx` invocation has side effects on the package cache and could race a
run already in flight.

## The run view

Three different things can be true of a solution at once, and the view keeps
them in three separate places so they cannot be mistaken for one another:

| Channel | Says |
|---|---|
| the **name**, coloured and weighted | what `problem.rbx.yml` *declared* -- green for `ACCEPTED`, red for `WRONG_ANSWER`, yellow for a slow one, exactly as `rbx run` colours the same name |
| the **chip on the right** | what the run actually *produced*, with one icon per verdict |
| the **gutter on the left** | whether those two agree -- blank when nothing was declared, a tick when the declaration was met, a warning when it was missed |

That separation is the whole reason this is a webview rather than a tree: a
`TreeItem` offers one icon and one line of dim grey text, so a solution declared
`WRONG_ANSWER` that answers wrongly drew the same red icon as the main solution
breaking, and a solution that *missed* its declaration said so in the same grey
as every row's timing. Now a miss is the only thing in the view with a
background colour, and `sols/wa.cpp` failing on purpose is a calm row.

A missed solution also opens onto a card naming which groups missed and what was
declared, in words; a met one opens onto its verdict histogram and its worst
time and memory.

Every solution and every group carries its own summary: the verdict underneath
it, the points it earned, and the **max** time and memory across its testcases
-- the slowest test being the one the time limit is judged against.

### Warnings on a run that passed

A **yellow triangle in the gutter** -- where a met declaration draws a green tick
and a missed one draws a red triangle -- is a run rbx warned about even though it
passed. `status` is `OK` and `matchesExpectation` is `true` on exactly these
solutions, so nothing else in the view has anything to say about them: the chip
draws its verdict, the label draws its declaration, and `sols/slow.cpp` reads
green while `rbx run` prints a WARNING about it in the terminal.

The row is ruled and washed to match, the way a missed one is -- yellow at a
slightly lighter mix than the miss's red, because yellow is the lighter hue and
an equal mix would read louder than the more serious row it ranks below. Those
two washes and the selection and hover fills are the only backgrounds in the
stylesheet; the scarcity is what lets either be found by scanning.

The gutter is therefore a severity column, not a match column: tick, yellow
triangle, red triangle. A row that both missed its declaration and carries a
warning draws the miss, because there is one glyph to spend and the miss is the
more serious of the two -- the warning is still spelled out in the card below.
Warnings tried living in a mark of their own at the far end of the row first,
which failed for a reason worth recording: a double-TL warning lands only on a
TLE row, and `watch` is already the TLE chip's icon, so the mark vanished beside
an identical yellow clock.

Today the mark carries the two double-TL facts. `rbx run` defaults to `-v4`,
which judges at **twice** the time limit and rewrites an over-limit run to TLE,
so a solution declared `TLE` can be caught two ways while still matching what it
declared:

| Warning | What it means |
|---|---|
| *Still passed in double TL* | It timed out, but fit inside 2x the limit -- borderline slow, not decisively so |
| *Still finished in double TL, but failed with WA* | It fit inside 2x the limit and was **wrong** underneath: slow is not why it fails |

The two are independent and each names the groups it came from, because both are
unions over the pooled layer and every group and two groups can each raise one.
Warned solutions are counted in the header strip separately from mismatched
ones, so a run where every declaration held still reports what rbx warned about.

Which run deserves a warning is rbx's decision, published in `report.yml` as
`runUnderDoubleTl` and `doubleTlVerdicts`; the only thing decided here is which
words and which glyph carry it.

#### The verdict a soft TLE hid

A testcase judged at 2x the limit is reported `TLE` the moment it crosses 1x,
but the checker still saw its output -- so `TLE` on a leaf can mean *too slow*
or *wrong, and too slow got there first*. Those are different bugs. When they
differ, the row spells both:

```
1-gen-001        1306 ms · 10 MiB   ⌚ TLE (WA)
```

Only on leaves, and only when it matters. A solution declared `incorrect` that
answers wrongly under a soft TLE says nothing new, and neither does a correct
answer underneath -- that one is the `runUnderDoubleTl` warning, reported once,
on the row above. Deciding which is which is an `ExpectedOutcome.match` against
both the group's declaration and the solution's, so rbx decides it and publishes
the answer per group as `unexpectedNoTleVerdicts`; the extension shows a
testcase's `no_tle_outcome` when it appears in that list and never otherwise.

**None of that is computed here.** rbx decides it and publishes it to
`.rbx/runs/report.yml`; the extension reads it and renders it. That is
deliberate: outcome ranking, expectation matching and dependency-gated scoring
are subtle, they live in `rbx/box/run_report.py`, and a second implementation in
TypeScript is a second implementation to keep in step. See
[the design](../docs/plans/2026-08-16-run-report-artifact-design.md).

The visible consequence is that rbx writes the report as each solution
*finishes*, so a solution still running shows how far it has got (`12/40`) and
no verdict. Individual testcase rows fill in live, from their own `.eval` files.

A run of a single solution opens expanded, the way `rbx run` prints per-testcase
lines only when there is one solution to print them for. A run of several opens
with the solutions collapsed; expanding one reveals its groups already open.

### Opening what a row names

Every row that names a file opens it, and always the same way: <kbd>Enter</kbd>
on the keyboard, a click on a leaf, a double click on anything that also
expands.

| Row | Opens |
|---|---|
| solution | its source file, for editing -- `sols/wa.cpp` is a file you wrote |
| testcase | the diff against the expected answer if it failed, the input otherwise |
| group | nothing; it is a heading over testcases, with no file behind it |

A solution row both expands and opens, so the two gestures are kept apart: a
single click expands it, as a click on any parent row does, and opening it takes
<kbd>Enter</kbd> or a double click. The second click of a double click takes the
first one's expansion back, so the tree is left where it was -- the same net
effect a double click has on a folder in the Explorer.

### Naming solutions

Nearly every package keeps its solutions under one directory, so the path rbx
records repeats that directory on every row and spends the sidebar's narrowest
column saying nothing. `rbx.solutionLabel` chooses how much of it to keep:

| Value | `sols/main.cpp`, `sols/slow/tle.cpp` |
|---|---|
| `full` | `sols/main.cpp`, `sols/slow/tle.cpp` |
| `trimmed` (default) | `main.cpp`, `slow/tle.cpp` |
| `basename` | `main.cpp`, `tle.cpp` |

`trimmed` drops the longest directory prefix *that package's* solutions all
share, so one package that stores its solutions somewhere unusual does not cost
the others their trimming. It works in whole path segments and never touches a
file name: `main.cpp` beside `mai_x.cpp` stays both.

Whatever is shown, the filter box still matches the full path, and a shortened
name carries the whole one as its tooltip.

## Explorer badges

The run view is only useful while you are looking at it. A solution promises
something the moment it is written down, and the Explorer says so before any
run exists: every file `problem.rbx.yml` names is badged, and solutions are
badged with the outcome they were declared to have.

A `FileDecoration` gives two characters, one colour tinting both the badge and
the file name, and a tooltip -- and nothing else. Twelve `ExpectedOutcome`
members have to fit in that, and two pairs of them share a colour. So the badge
column is generated by two rules rather than picked row by row:

1. **The first character is the glyph `rbx run` already prints** -- `✓` when the
   expectation admits AC, `⧖` when it is slow, `?` for `any`, `✗` otherwise. A
   badge can never contradict the terminal.
2. **A second character appears only when the expectation is not the canonical
   member of that glyph's family**, and says how it differs: `⧖` "or slow", `!`
   "or crashing", `?` "unspecified which failure", or a letter naming a rarer
   specific verdict.

| Badge | Declared | Colour |
|---|---|---|
| `✓` | `accepted` | green |
| `✓⧖` | `accepted-or-tle` | green |
| `✗` | `wrong-answer` | red |
| `✗?` | `incorrect` | red |
| `⧖` | `time-limit-exceeded` | yellow |
| `⧖!` | `tle-or-rte` | yellow |
| `✗!` | `runtime-error` | blue |
| `✗M` | `memory-limit-exceeded` | yellow |
| `✗O` | `output-limit-exceeded` | purple |
| `✗C` | `compilation-error` | blue |
| `✗J` | `judge-failed` | purple |
| `?` | `any` | neutral |

Rule 2 is the whole point: `accepted` and `accepted-or-tle` are both green,
`wrong-answer` and `incorrect` are both red, and colour alone cannot tell either
pair apart.

Everything else the manifest names is badged with **two letters in one neutral
colour** -- `Gn` generator, `Vl` validator, `Ck` checker, `It` interactor, `Vz`
visualizer, `St` statement. Deliberately a different kind of mark: a generator
makes no promise about how it will do, so giving it a hue that means one would
spend the verdict palette on something that can neither pass nor fail. A file
claimed by two roles takes the more specific one.

The colour means the **declaration, not the last run**. That costs the Explorer
any way of showing a solution that *missed* its declaration -- both badge
characters are already spent telling expectations apart -- and the miss is
surfaced in the run view instead, which has room for it. The upside is that the
badges are right with no run on disk at all, and stay right while one is in
flight.

Colours are contributed as `rbx.expected*` and default to the theme's own
`charts.*`, so a colour theme can restyle them and the run view agrees with the
Explorer either way. `rbx.decorateExplorer` turns the whole thing off.

Two caveats worth knowing:

- Expectations arrive here as the setter *spelled* them (`ac/tle`, `fail`,
  `Accepted`), not as the enum names `skeleton.yml` publishes, so
  `src/rbx/manifest.ts` mirrors `AutoEnum.from_str` to resolve them. A spelling
  it cannot resolve is passed through and rendered raw rather than dropped: the
  setter declared *something*, and rbx would refuse to run the package.
- `⧖` (U+29D6) renders in terminals because terminal fonts are picked for
  coverage; the Explorer draws badges in the UI font. If it comes out as tofu,
  `~` and `T` are the fallbacks that keep both rules intact.

## While you are editing a solution

The Explorer badge is two characters seen out of the corner of your eye. With
the solution itself open, the same declaration is spelled out in two more
places.

**A CodeLens, on its own line above line one:**

```
  ✓ accepted-or-tle · each group: accepted · group3: time-limit-exceeded · score 50..80
1 #include <bits/stdc++.h>
2 using namespace std;
```

**A language status item**, which is the half that survives scrolling: it
stays in the status bar for as long as that solution is the active editor, it
can be pinned so it is always on screen, and it carries the pooled outcome with
the per-group overrides on its detail line. Clicking either opens the Run view.

Both say the pooled `outcome` first, then every `outcomePerGroup` override in
the order it was written, then the expected `score` if the solution declares
one. All three are separate claims that rbx checks separately -- `outcome`
against the whole testset, each override against one group's tests alone, and
the score against the total -- and a solution fails if any of them misses. `*`
reads as **each group**, because it is not a group name. Outcomes are spelled
the way the manifest spells them (`accepted-or-tle`, not `AC or TLE`); the
hover says the same thing in the labels the run view and the terminal use.

A score reads the way `rbx run` prints it: `score 100` for an exact one,
`score 50..80` for a range, and `score 50..` for one with no ceiling -- an
omitted bound is rbx's `10^9`, and naming it would invent a maximum the setter
never wrote.

**The right-hand slot of the lens is reserved and ships empty.** That is where
the last run goes -- verdict, worst time against the limit, points, and the
fact of a miss. It is deliberately a separate issue, because it carries the
questions this one does not have to answer: which run, how stale is too stale,
and what it says when there has never been a run.

`rbx.solutionCodeLens` and `rbx.solutionStatus` turn the two off independently.

### Why a CodeLens, and not a banner

VS Code has no banner API. The substitute everyone reaches for first -- a
whole-line decoration whose `before` attachment is pushed onto its own line
with `display: block` -- **cannot work**, and it is worth writing down why, so
nobody spends an afternoon on it again:

- The extension host forwards a fixed set of properties to the editor
  (`contentText`, `margin`, `width`, `height`, colours, `textDecoration`).
  Nothing in it asks for a taller line.
- So the line box stays one line high and the block lands *on top of* line one.
  Tuning the CSS moves the overlap around; it never removes it.

A CodeLens gets a line because the editor renders one by adding a **view zone**
above its range -- real reserved space, which is why it cannot overlap. What it
costs is colour: a lens is drawn in `editorCodeLens.foreground` with no
per-lens override, so the expectation's hue stays with the Explorer badge and
the editor tab, and the lens carries the glyph as a codicon instead. Language
status items have severity rather than colour for the same reason, and severity
is always `Information` here: severity means "something is wrong", and a
declaration never is -- a *miss* is, and that belongs to the run.

The one API that would give a real banner, `createWebviewTextEditorInset`, is
still proposed and cannot ship in a published extension.

## Status

Milestone 1 of the [v1 design](../docs/plans/2026-08-11-vscode-extension-design.md):
package discovery, the run view, read-only artifact editors, and diff. The view
itself is a webview, per
[its own design](../docs/plans/2026-08-19-vscode-run-webview-design.md).

The build tree (browsing generated testcases without a run) needs rbx to persist
its entry list first, and is not here yet. A lower-density report in an editor
tab, reusing the same view model, is issue #670.

## Developing

```bash
npm install
npm run watch      # esbuild, incremental
```

Then press <kbd>F5</kbd> to launch an Extension Development Host, and open a
folder containing a `problem.rbx.yml`.

```bash
npm run typecheck  # tsc --noEmit
npm test           # node --test, over esbuild-compiled sources
npm run package    # production bundle
```

The tests cover the pure logic only -- deciding what a row displays
(`src/rbx/viewModel.ts`), turning that into HTML (`src/webview/render.ts`) and
deciding what a click on a row means (`src/webview/gesture.ts`) -- which is why
all three are modules that never import `vscode` and never touch the DOM. The
extension host and the DOM plumbing around them are left to the F5 development
host.

From the repository root, the same via mise:

```bash
mise run vscode:build
mise run vscode:typecheck
mise run vscode:test
mise run vscode:package
```

## What it reads

Everything comes from files rbx already writes. The layout is a contract, and
`src/rbx/layout.ts` is the single place that encodes it:

| Path | Contents |
|---|---|
| `<pkg>/problem.rbx.yml` | what the package *declares*: solutions and their expected outcomes, and every other file it names |
| `<pkg>/.rbx/runs/skeleton.yml` | solutions, groups, testcase entries with provenance, and each solution's resolved limits |
| `<pkg>/.rbx/runs/report.yml` | **every aggregate**: verdicts, scores, max time/memory, per-group expectation results, double-TL warnings |
| `<pkg>/.rbx/runs/<i>/<group>/<stem>.eval` | verdict, time, memory, checker message, the verdict a soft TLE hid |
| `<pkg>/.rbx/runs/<i>/<group>/<stem>.out` | solution stdout |
| `<pkg>/.rbx/runs/<i>/<group>/<stem>.err` | solution stderr (`.sol.err` for communication tasks) |
| `<pkg>/build/tests/<group>/<stem>.in` | generated input |
| `<pkg>/build/tests/<group>/<stem>.out` | expected answer |

Two things are easy to get wrong here:

- `<stem>` is **not** the zero-padded testcase index. It comes from the basename
  of the generated input, so a subgroup-generated test is `1-gen-000`, not
  `003`. Reading it wrong silently shows another testcase's output -- it was a
  real rbx bug once (#418 / #429).
- A missing `.eval` means *pending*, not *failed*. That is what gives the view
  live progress during a run for free.
- `skeleton.yml` carries each solution's `limits` already resolved through its
  language. The table above it is keyed by language, and mapping a solution onto
  one of its entries needs rbx's own `find_language_name` -- so the resolved
  copy is the only one a reader here can use. Nothing renders it yet; it is
  written so that a time can one day be shown against the limit it was judged
  under.
- A missing `report.yml` means *no solution has finished yet*, never *stale*:
  rbx deletes it when it writes a new skeleton. A `version` it does not
  recognise is ignored outright, because rendering a run without aggregates is
  recoverable and rendering the wrong verdict is not.
