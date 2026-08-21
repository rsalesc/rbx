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

### One problem at a time

The view shows **one package**, and a dropdown in its header picks which. The
dropdown is hidden when the workspace holds a single package, so a one-problem
workspace reads exactly as it did before. The header strip's mismatch and
warning counts are that one problem's -- a count summed over a ten-problem
contest named none of them and said nothing about the one on screen.

Problems are named by the **contest letter** `contest.rbx.yml` gives them, in
the order the contest declares them and with its declared colour as a dot,
rather than by directory name in path order. The dot shows the **selected**
problem's colour only, not one per entry: a native `<select>` cannot be relied
on to colour its options, so an open dropdown is a plain list of letters. The nearest `contest.rbx.yml`
above a package is the one that names it, a dispatcher's variants included. A
package no contest claims keeps its directory name and sorts after the ones a
contest does claim; with more than one contest open, the dropdown groups by
contest.

The view also **follows the problem that is running**. rbx writes a new
skeleton when a run *begins*, so the selection moves to the problem now being
run rather than to one that has already finished -- during `rbx contest each
run` it walks the contest in step. Left alone, the selection is remembered per
workspace, so reopening the window returns to the problem you were reading.

For the keyboard, `rbx: Select Problem` offers the same list as a quick pick.
`rbx: Reveal Problem in Explorer` reveals whichever problem is selected.

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
| testcase | **two panes** -- the input, and the output diffed against the expected answer |
| group | nothing; it is a heading over testcases, with no file behind it |

A solution row both expands and opens, so the two gestures are kept apart: a
single click expands it, as a click on any parent row does, and opening it takes
<kbd>Enter</kbd> or a double click. A double click always leaves the row
**expanded**, whichever way it started -- the second click is not a second
toggle, because a gesture that opens a file should not also shut the row it was
opened from.

### What a testcase opens

A testcase used to open one tab: the diff if it failed, the input otherwise. One
artifact at a time is the wrong number -- the input is what produced the output,
and reading a wrong answer without it is reading half the story. So a testcase
opens **two editor panes**, the way `rbx ui`'s run explorer shows them:

```
+- input.in ------------------------------+
| 5 3                                     |
| 1 2 3 4 5                               |
+- output.out <-> answer.out -------------+
| 12                  | 14                |
+-----------------------------------------+
```

Real editors and not a webview, because testcases are large: a `TextDocument`
streams a multi-megabyte input, highlights it, and gives you find and
go-to-line, none of which a webview gets without rebuilding it.

**The second pane is a channel**, and it switches -- `alt+1` output, `alt+2`
stderr, `alt+3` the run log, mirroring `rbx ui`'s `1`/`2`/`3`, and reachable
from the buttons on the card below. `out` is the *diff*, output beside what it
should have been, which is what `rbx ui`'s output box is in two-sided mode; a
hard TLE with no output falls back to whichever half exists. The channel is
**sticky**: reading stderr and arrowing down a group keeps reading stderr,
because comparing one channel across several tests is the thing a switch is for.

There is deliberately no `in` button. The input already lives in the first pane,
and a button pointing it at the second would put the same file on screen twice.

#### The layout is yours

Both panes are `preview` tabs in **separate editor groups**, and a preview tab
is per group -- so arrowing down the list swaps the documents in place and never
piles up tabs.

The first time a testcase is opened, the extension lays out two groups:
`rbx.testcaseLayout` picks `below` (default) or `beside`. **That is a seed and
nothing more.** Afterwards it finds its own panes -- every artifact travels on
the `rbx:` scheme, so a tab carrying one is recognisably ours -- and reuses
whichever groups they are sitting in, without touching the layout again.

Even the seed holds back when you have already split the editor yourself: with
more than one group open it joins them instead, putting the input in the active
group and the channel beside it, rather than collapsing your arrangement to two.

`below` is the default because of the **diff**, not the input. VS Code ships
`diffEditor.useInlineViewWhenSpaceIsLimited` turned on, which quietly drops a
narrow diff to an inline view -- and `beside` hands the channel pane a fraction
of an editor area that has already lost width to the sidebar. On a laptop that
renders the output against the answer inline, with nothing on screen saying why.
Stacked, the diff spans the full width and side-by-side holds at any window
size. `beside` is roomier for a long testcase; pair it with
`"diffEditor.useInlineViewWhenSpaceIsLimited": false` if you want side-by-side
kept regardless.

#### The diff is VS Code's own

Nothing about how the diff *renders* is the extension's, deliberately -- the
diff editor already has all of it, and a second knob here would only fight the
built-in one:

| Want | Use |
|---|---|
| side-by-side or inline, as a setting | `diffEditor.renderSideBySide` |
| switch it live | the diff editor's **More Actions** (`...`) menu |
| a key for it | bind `toggle.diff.renderSideBySide` |
| ignore whitespace | `diffEditor.ignoreTrimWhitespace`, or `toggle.diff.ignoreTrimWhitespace` |

`vscode.diff` takes a `TextDocumentShowOptions` -- which column, preview,
focus -- and nothing about rendering, so these are window-wide preferences
rather than something a testcase pane could set for itself even if it wanted to.

That distinction is the whole design. Laying out editor groups is global and
destructive: it rearranges the entire editor area, the solution source you were
editing included. Doing it on every <kbd>Enter</kbd> would undo your own
arrangement every time you picked a different testcase. Drag the panes where you
want them and they stay there.

### The testcase card

Under the tree, a card describes the **selected** testcase -- and carries only
what its row cannot.

```
+- 1-gen-002 ---------------+
| wrong answer, expected    |
| 14, found 12              |
| gen_random 5 3 --seed=7   |
| [out] [err] [log]         |
+---------------------------+
```

Not the verdict, not the time, not the memory: the row has all three, eight
pixels above. What the card adds is the two facts the extension has been reading
out of every run and showing nowhere.

- **The checker's own message**, wrapped and whole. It is the answer to *why*
  a solution answered wrongly, and it is free-form output from the package's own
  checker -- as long as that checker felt like being, which is exactly why it
  could never fit a 22px row. Absent on a hard TLE, where the checker never saw
  the output; that absence is informative and is not filled with a placeholder.
- **Where the test came from** -- copied-from, the generator call, the generator
  script, in the order rbx's own metadata prints them. The script and the
  copied-from **open** where they point, since rbx records a script entry as a
  real `path:line`. A generator *call* is text: it names a generator declared in
  `problem.rbx.yml` rather than a file, and a button that went nowhere would
  promise a destination the view does not have.

The card fills on **selection**, not on open, so a whole failing group can be
scanned for checker messages without opening a single editor. It is absent
entirely whenever the selection is not a testcase -- the same rule the findings
panel follows.

None of the three channel buttons is ever disabled. Whether a testcase has
stderr is a fact about the disk, and the view reads a run's metadata rather than
statting artifacts on every watcher tick; a button with nothing behind it says
so, in words, when pressed. The upside is that the button row is the one control
in the card that never moves as the highlight travels down a group.

### Compilation findings

Everything above is about *running* a solution. A solution that did not compile
never ran, and until now it was not in the view at all: rbx filters it out of
`skeleton.yml`'s `solutions` before the run starts, so the row simply went
missing, with nothing anywhere saying which solution had gone or why. Compiler
warnings were invisible in the plainer sense -- nothing on disk mentioned them,
so the sidebar was silent while the terminal was not.

A **Compilation Findings** panel sits under the tree, with one compact row per
solution the compile phase had something to say about. It is absent entirely
when there is nothing to say, the same way the header strip is: the panel being
on screen is itself the news.

- The **badge** on its header counts the rows, and is **red** the moment one
  solution failed to compile, **yellow** while everything merely warned. A
  coloured badge is the reason the panel lives inside this webview rather than
  in a second view of the container: a `ViewBadge` is a plain count on the
  activity-bar icon and cannot be coloured, and here the colour is the message.
- A run with a **compile error opens the panel by itself**, once, when it
  arrives. A warnings-only run never does -- the yellow badge is what carries
  it, and a panel that opened for every warning would be a panel nobody leaves
  open. Closing it sticks for the rest of that run, however many times the view
  refreshes underneath.
- Each row is ruled and washed in its severity, at the same two mixes the tree
  uses for a miss and for a warning. The **name keeps its declaration's colour**,
  exactly as it has in the tree above, so a row here and the same row up there
  are recognisably the same solution.
- The right of a row says `CE` or `3 warns`, and hovering it reveals two
  buttons: **open the source**, and **open the compiler output** -- the stderr
  verbatim, in a read-only `rbx:` tab.
- A row with warnings **expands** into one line per warning: its line number and
  its flag, nothing more -- `22 · -Wshadow`. The compiler's own sentence is the
  hover title, not a line of the panel: a third of a narrow sidebar has no room
  for `declaration of 'total' shadows a global declaration`. Clicking one goes
  to that line in the source.
- Clicking a row that failed to compile opens the compiler output, since there
  is nothing to expand and that is the only place the answer is.

Sanitizer and linter warnings are deliberately *not* here. Both live in rbx's
same console block, but one comes from running a solution rather than compiling
it and the other is not compiler output at all; a panel called Compilation
Findings that carried them would be lying about what it contains.

#### And in the Problems panel

The same findings are also published as diagnostics, so they reach you without
the sidebar being open at all:

```
PROBLEMS (3)
▾ sols/warns.cpp
  ⚠ 22  declaration of 'total' shadows a global declaration   rbx(-Wshadow)
  ⚠ 25  unused variable 'leftover'                            rbx(-Wunused-variable)
▾ sols/broken.cpp
  ⊗  1  This solution failed to compile, and was left out of the run.  rbx(compiler output)
```

The panel and the Problems list are the same facts on two surfaces, and which
one you want depends on what you are doing: the panel is a list of *solutions*
and sits beside the run it belongs to, while Problems is a list of *locations*
and belongs to the file you are editing. A warning there also draws in the
editor's own gutter and is reachable with `F8`.

- A **warning** lands on the line the compiler named, in the file **the compiler
  named** — which is not always the solution being compiled — and spends the
  `code` cell on its flag, the way every linter in the product does.
- A **failure** lands at the top of the solution, because rbx parses locations
  out of warnings only and a guessed line would underline the wrong code. Its
  message says the part that is otherwise invisible — the solution was left out
  of the run — and its `code` cell is a **link to the compiler output** instead
  of a flag, since a diagnostic's code is the one field that can carry a URI.
- The range is the whole line: rbx records which line a warning is on and not
  which column, and inventing a column would underline the wrong characters.
- Entries are cleared and rebuilt from the same `onDidChange` that feeds the run
  view, so the two surfaces can never describe different runs. Set
  `rbx.compilationDiagnostics` to `false` to turn them off.

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
[its own design](../docs/plans/2026-08-19-vscode-run-webview-design.md), and what
a testcase opens onto is
[a design of its own](../docs/plans/2026-08-21-vscode-testcase-detail-design.md).

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
| `<pkg>/.rbx/runs/skeleton.yml` | solutions, groups, testcase entries with provenance, each solution's resolved limits, and what the compile phase reported |
| `<pkg>/.rbx/runs/compilation/<i>.log` | one solution's compiler output, verbatim |
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
- `skeleton.yml`'s `compilation` lists **only** the solutions with something to
  report, and a solution that failed to compile appears there and nowhere else
  -- it is absent from `solutions` and from `compiled_solutions`, because it
  never entered the run. The compiler output is *not* inlined: it is unbounded,
  and the skeleton is parsed in full by every reader, so each record points at a
  file beside it instead. A skeleton written by an older rbx has no field at
  all, which reads as a clean compile and no panel.
- A missing `report.yml` means *no solution has finished yet*, never *stale*:
  rbx deletes it when it writes a new skeleton. A `version` it does not
  recognise is ignored outright, because rendering a run without aggregates is
  recoverable and rendering the wrong verdict is not.
