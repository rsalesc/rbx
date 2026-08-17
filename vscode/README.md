# rbx for VS Code

Browse the results of an `rbx run` without leaving the editor: solution →
group → testcase, with verdicts, timings and a diff of what a solution printed
against the expected answer.

Execution stays in the terminal. You type `rbx run`; the extension watches
`.rbx/runs/` and renders whatever lands there. It never invokes `rbx` itself --
every `rbx` invocation has side effects on the package cache and could race a
run already in flight.

## The run tree

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

## Status

Milestone 1 of the [v1 design](../docs/plans/2026-08-11-vscode-extension-design.md):
package discovery, the run tree, read-only artifact editors, and diff.

The build tree (browsing generated testcases without a run) needs rbx to persist
its entry list first, and is not here yet.

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

The tests cover the pure logic only -- summarising a run, formatting a verdict
-- which is why it lives in modules that never import `vscode` (`src/rbx/`).
Anything touching the extension host is left to the F5 development host.

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
- A missing `.eval` means *pending*, not *failed*. That is what gives the tree
  live progress during a run for free.
- A missing `report.yml` means *no solution has finished yet*, never *stale*:
  rbx deletes it when it writes a new skeleton. A `version` it does not
  recognise is ignored outright, because rendering a run without aggregates is
  recoverable and rendering the wrong verdict is not.
