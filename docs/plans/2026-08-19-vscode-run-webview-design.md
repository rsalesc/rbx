# VS Code run view: replacing the tree with a webview

Follow-up to #664, which gave every verdict its own icon. That settled how the
Run view shows **what happened**. It did not — and a `TreeView` cannot — settle
how the same row shows **what the package asked for** and **whether it got it**.

## The problem: a TreeItem is out of channels

Everything a `TreeItem` can render:

| channel | capacity |
| --- | --- |
| `iconPath` | one codicon, one `ThemeColor`, left edge |
| `label` | plain text; `TreeItemLabel.highlights` is a single hardcoded "find match" style |
| `description` | one dim string, one color, no per-substring styling |
| `FileDecoration` | right edge, at most two characters of **plain text**, one color, one winning provider, and it leaks into the Explorer and editor tabs |
| children | more rows — the only meaning "expand" can have |
| `tooltip` | markdown, hover-only |

Against what the Run view needs to say:

- expected outcome, identifiable by color and font style the way the CLI does it — **unreachable**
- verdict of each testcase, group and solution, as a colored icon on the right — **unreachable** (`FileDecoration.badge` is text, and capped at two characters)
- mismatch-or-OK, as an icon on the left — the left slot is already spent on the verdict
- independent coloring per channel, down to substrings of a description — **unreachable**
- useful detail when a row is expanded — child rows only, and a detail row is
  indistinguishable from a testcase row, which is itself a source of confusion

Four of five are unreachable. Any encoding that fits has to fold at least two
facts into one channel, and folding them is exactly the confusion being fixed:
a solution declared `WRONG_ANSWER` that answers wrongly draws the same red
`close` icon as the main solution breaking.

There is a shape argument underneath the channel argument. `rbx run` lays the
same data out as a *matrix* — `_render_detailed_group_table` puts solutions in
columns headed by `solution.href()` (hued by `ExpectedOutcome.full_style()`) and
outcomes in the cells. A tree linearizes that matrix onto one path, which is
*why* the two axes end up competing for one row's worth of pixels.

## D1. A webview view in the sidebar, replacing the tree

The Run view becomes a `WebviewViewProvider` in the existing `rbx` view
container, in the same slot the tree occupies today. Rejected alternatives:

- **Keep the tree, add an editor-tab report.** Cheaper, but leaves the sidebar
  — the surface actually looked at during a run — exactly as confusing as it is
  now.
- **Editor tab only.** Same objection, plus it costs a deliberate open.

A lower-density editor-tab report is still wanted, and is designed *for* here
(D2) but shipped separately. See "Follow-ups".

What is knowingly given up, and re-implemented: keyboard navigation and
selection, right-click menus, expansion and scroll state across hide/show,
type-ahead filtering, ARIA tree semantics, and the `viewsWelcome` empty state
(which does not apply to webview views). All four behaviors are required, not
optional — a sidebar that navigates worse than the tree it replaced is not an
improvement, however well it colors.

Also given up: `FileDecoration`. A webview cannot decorate Explorer entries or
editor tabs. That surface is worth having and is tracked separately; it is
orthogonal to this design and this design does not depend on it.

## D2. `viewModel.ts`: a pure transform, and the seam the editor tab reuses

The data layer does not move. `layout.ts`, `wire.ts`, `model.ts`, `store.ts`,
`report.ts`, `summary.ts` and `outcome.ts` are untouched, and the webview never
sees the disk.

One new module sits between the store and any renderer:

```
PackageRun[]  ->  viewModel.ts  ->  RunViewModel
```

`RunViewModel` is a flat, serializable array of rows, each carrying its display
channels **explicitly resolved**:

```ts
interface Row {
  id: string;              // `<root>::<solIdx>::<group>::<stem>`, as TreeItem.id is today
  depth: number;
  kind: 'package' | 'solution' | 'group' | 'testcase';
  gutter: 'none' | 'met' | 'missed';
  label: string;
  labelHue?: Hue;          // from the expectation
  labelBold: boolean;
  meta: Span[];            // [{text, hue?}, ...] — substrings carry their own color
  verdict?: { icon: string; hue: Hue; short: string };
  mismatch: boolean;
  detail?: Detail;
}
```

No `vscode` import and no DOM, so it is unit-tested under `node --test` exactly
as `summary.ts` is. It is also the seam that makes the future editor tab cheap:
same view model, a different renderer at a different density.

Row `id` is the id the tree already assigns, kept verbatim. It is the key for
selection, for expansion state, and for every message crossing the webview
boundary.

## D3. Row anatomy: one CSS grid, four channels that align down the tree

```
[gutter][twisty][label ......................][meta][verdict]
```

- **gutter** — the *match* axis, and nothing else. Blank when nothing was
  declared, a quiet tick when the declaration was met, a loud warning when it
  was missed.
- **label** — hued by the *expectation*, porting `ExpectedOutcome.full_style()`
  (`rbx/box/schema.py:228`) as-is: bold green for `ACCEPTED`, red for
  `WRONG_ANSWER` and `INCORRECT`, yellow for TLE/MLE, blue for RTE/CE, magenta
  otherwise, bold plain for `ANY`. Mapped onto `charts.*` theme variables so it
  follows the user's theme rather than hardcoding hex.
- **meta** — dim `0.94s · 58 MiB`, as a list of spans so any substring can take
  its own color.
- **verdict** — right-aligned colored codicon plus short name, read straight
  from the existing `outcomeIcon()` table. #664 is preserved exactly: a TLE
  keeps the same yellow shape it has in the terminal beside it.
- **mismatch** — a red left border and a faint wash on the row. This is the
  only background color anywhere in the view, so it is the only thing that can
  catch the eye without being read.

By level: solutions get gutter, expectation hue and verdict; groups get gutter
(from `outcomePerGroup`) and verdict; testcases get verdict only — a testcase
has no expectation of its own to report.

> **Superseded by D9.** Giving a group the gutter but no expectation channel
> left it unable to say *what* it had wanted, which is the one thing a reader
> of a missed group needs. Groups now carry the expectation in both channels,
> and both levels gained a spelled-out chip beside the verdict.

The verdict and the expectation now live in genuinely separate channels with
separate alphabets, so neither has to be inferred from the other. That is the
whole point of the change.

### Expectation hues

The extension does not model `ExpectedOutcome` today. This design adds that
mapping itself, from `full_style()`. PR #666 introduces an overlapping
`expectation.ts` for a different purpose; whichever lands first owns the table
and the other reconciles onto it. The mapping is small and the source of truth
is `rbx/box/schema.py` either way.

## D4. Detail card on an expanded solution

Expanding a solution renders a card **above** its group children. Testcases stay
leaves: clicking one opens the diff, as it does today.

The card always carries a verdict histogram (`12 AC · 3 WA · 1 TLE` as a bar),
max time, max memory, and score.

**No limit denominators in v1.** Showing `0.94s / 1.00s` would mean reading
`problem.rbx.yml`, and the extension is deliberately a pure reader of `.rbx`
artifacts (`layout.ts`, D2 of the M1 design). Bare maxima it is.

When the solution missed its declaration, a second card above the histogram
states declared-versus-observed in words and **names the failing groups**. It
reuses the `summary.ts` logic that already avoids naming an expectation that was
in fact met — a pooled `INCORRECT` on a solution that does fail is met, and only
the per-group layer sees the miss.

> **Superseded by D9.** The intent above was right and the implementation did
> not achieve it: the card named the pooled declaration *and* listed the failing
> groups in one sentence, which reads as those groups having missed that
> declaration. The layers are now separated in the model, not only in the prose.

## D5. A pinned header strip

Non-scrolling, at the top of the view, and **hidden entirely when nothing
mismatched** — no chrome when there is nothing wrong. Otherwise:

```
⚠ 2 of 9 did not match                    [next ›]
```

`next` cycles selection through mismatched solutions. It counts *misses*, not
failures: badging a solution that fails on purpose would report the package's
own test suite as a problem.

The strip also hosts the filter box (D6).

## D6. Filter

A text box narrowing by solution path and testcase stem, plus verdict tokens
(`wa`, `tle`) and the literal `mismatch`. Ancestors of a match stay visible so
the hierarchy still reads. This replaces the tree's built-in `Ctrl+F`, and does
more than it did.

## D7. Parity mechanics

- **Keyboard** — `role="tree"` with a roving tabindex. Up/Down move, Right/Left
  expand and collapse, Enter runs the row's primary command, Home/End jump.
  `aria-expanded`, `aria-level`, `aria-setsize`, `aria-posinset` on every row.
- **Context menus** — `data-vscode-context` per row with
  `preventDefaultContextMenuItems: true`. The `package.json` menu items move
  from `view/item/context` to `webview/context`, keyed on
  `webviewSection == 'rbx.solution' | 'rbx.group' | 'rbx.testcase'`. Explicit
  sections replace matching on a `contextValue` string.
- **Commands** — unchanged. The webview posts `{type: 'invoke', commandId,
  nodeId}`; the host resolves `nodeId` back to a `RunNode` and calls into
  `commands.ts` with the signature it already has.
- **State** — `getState()/setState()` holds the expansion set, scroll offset and
  selection, restored on every re-show. Not `retainContextWhenHidden`: the state
  is small and the host re-posts the model on visibility, so paying memory to
  keep a hidden view alive buys nothing.
- **Empty state** — rendered inside the webview, in the words `viewsWelcome`
  uses today.

## D8. Build and bundling

A second esbuild entry (`iife`, `platform: browser`, into `dist/webview/`)
alongside the existing extension bundle. `@vscode/codicons`' font file ships
under `resources/` and is served through `localResourceRoots`; the HTML carries
a nonce CSP with no remote origins.

## Testing

- `viewModel.ts` — unit tests under `node --test`, as `summary.ts` has.
- The renderer stays a pure `RunViewModel -> HTML string` function, so it is
  snapshot-tested the same way.
- Event wiring is untested, which is where the vscode-facing glue already sits.

## Risks

- **Accessibility is now ours.** Screen-reader quality depends on D7 being done
  properly rather than on VS Code doing it for us.
- **Width.** The row sheds channels in priority order as the sidebar narrows
  (D10); the detail card stays single-column.
- **Virtualization is deferred.** Rendered rows are solutions plus groups, plus
  testcases only under an expanded solution — and only a solo run expands one by
  default. Revisit past ~2000 rendered rows.

## D9. The two declaration layers, kept apart (follow-up to #672)

`sols/mislabeled-groups.cpp` declares `outcome: incorrect` with
`outcomePerGroup: {'*': tle}`. It *is* incorrect, so the pooled layer holds; it
is caught only by the per-group layer, which every group missed. The view as
shipped said, of that solution:

```
Declared INCORRECT, but samples, main, edge, big did not match.
```

Both halves are true and the sentence is false: those groups missed `TLE`, not
`INCORRECT`. And nothing anywhere in the view said `TLE` at all -- the group
rows read as four ordinary rows with a warning beside them.

Three changes, one per layer of the problem.

**The report publishes which layer failed.** `matchesExpectation` is the
aggregate of both, and the aggregate cannot say which one to blame.
`RunSolutionReport` gains `pooledMatchesExpectation`, read straight off the
`pooledStatus` that `get_verdict_markup` was already using for exactly this
decision in the console and nowhere else. `expectedScore` comes with it, so the
third failure mode -- a score outside its declared range -- has something to say
beyond "wrong". Both fields are optional, so the version does not bump: an older
reader drops them and reads the rest unchanged, where a bump would make every
existing reader ignore the whole file. An extension meeting a report without
them infers the pooled layer from "no group failed, so nothing else can have",
which is exact except when both layers failed at once, where it under-reports
rather than accusing a layer that held.

**A row spells its declaration.** The expectation gets a channel of its own,
between the meta and the verdict, on solutions and groups alike:

```
[gutter][twisty][label .............][meta][expectation][verdict]

  ⚠  edge      [0/30 pts] · 9 ms · 10 MiB    TLE → ✗ WA
```

It grows leftwards from the verdict instead of taking a fixed column: the pair
is what has to be read together, and reserving the width of `TLE or RTE` on
every row costs more than a ragged left edge does. Groups take the label hue
too, by the same rule solutions already used. `ANY` still draws nothing --
it is how a setter declares nothing, and the gutter already treats it that way.
Under a container query the declaration drops **first** -- see D10.

**The card speaks per layer.** `MismatchDetail` becomes a set of optional
clauses -- a pooled `declared → got` pair, a list of groups each with its own
pair, a score range -- and the renderer prints only the clauses that are set. A
group-only miss now reads:

```
⚠ INCORRECT held for the solution as a whole; 4 groups missed their
  outcomePerGroup declaration:
     samples   TLE → AC
     main      TLE → AC
     edge      TLE → WA
     big       TLE → WA
```

Naming the pooled layer as *held* is deliberate rather than redundant: the
reader is looking at a row labelled `INCORRECT`, and saying which declaration
was fine is what stops them chasing it.

## D10. What a narrowing sidebar gives up, and in what order

A row has more to say than a narrow sidebar can show. The first cut at this
hid the meta line whole at 260px and the declaration at 200px, which got both
halves wrong: it took the score away along with the memory figure -- one blob,
one switch -- and it kept the *declaration* alive longer than the measurements,
when the declaration is the least urgent thing on a cramped row.

The order is by how much each would be missed, not by how much room each frees:

| # | dropped | at | why it goes when it does |
|---|---|---|---|
| 1 | the declaration | 400px | the gutter still answers *was it met*, which is the part needed at a glance; the card says what it was |
| 2 | memory | 330px | the measurement least often being looked for |
| 3 | time | 280px | wanted often, but a solution is opened to study its timings, and the card carries the maxima |
| 4a | the verdict's *name* | 240px | the colour and shape carry most of what the name says, at a tenth of the width |
| 4b | the verdict's icon | 190px | below this a row is a path and a score, the least it can be and still be worth drawing |
| 5 | the score | never | on a points problem it is the answer to the question the view exists to answer, and the cheapest thing on the row |

Everything above the score is recoverable by widening the sidebar or opening the
row. The breakpoints are set where the label -- a path, the one thing that
cannot be recovered from anywhere else -- would otherwise be squeezed past
legibility.

Two mechanics make it work.

**Spans are named.** `Span` gains a `role` (`progress`/`score`/`time`/`memory`)
and the renderer turns it into a `span-*` class. An anonymous list of strings
can only be shown or hidden whole, which is what forced the original all-or-
nothing switch.

**Separators belong to the span that follows them.** `metaCell` emits nothing
between spans; the stylesheet draws a `·` as a `::before` on every span but the
first. A separator written as its own element would outlive the span it divides
and leave `[30/100] ·` trailing off a narrowed row. This is correct only while
hiding removes a *suffix* of the line -- so the meta line is built in priority
order, and a `render.test.ts` case asserts the breakpoints are strictly
descending and that the score is named by none of them. Reorder the ladder and
that test fails rather than the separators quietly going wrong.

`formatScore` also drops the ` pts` the console uses. In a terminal the unit
earns its place; in a sidebar it is four characters of the one span that has to
survive everything else, and the brackets already say what the number is.

## Follow-ups

1. **Editor-tab report.** A lower-density report in the editor area, reusing
   `viewModel.ts` with its own renderer. The matrix shape the CLI uses belongs
   here, where there is width for it.
2. **Expected outcome in the Explorer and on editor tabs.** The
   `FileDecorationProvider` from PR #666 — the one surface a webview cannot
   reach, and worth having on its own terms. Tracked separately; this design
   neither depends on it nor conflicts with it.
