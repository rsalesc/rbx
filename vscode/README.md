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
(`src/rbx/viewModel.ts`) and turning that into HTML (`src/webview/render.ts`) --
which is why both are modules that never import `vscode` and never touch the
DOM. Interaction and the extension host are left to the F5 development host.

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
| `<pkg>/.rbx/runs/skeleton.yml` | solutions, groups, testcase entries with provenance |
| `<pkg>/.rbx/runs/report.yml` | **every aggregate**: verdicts, scores, max time/memory, per-group expectation results |
| `<pkg>/.rbx/runs/<i>/<group>/<stem>.eval` | verdict, time, memory, checker message |
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
- A missing `report.yml` means *no solution has finished yet*, never *stale*:
  rbx deletes it when it writes a new skeleton. A `version` it does not
  recognise is ignored outright, because rendering a run without aggregates is
  recoverable and rendering the wrong verdict is not.
