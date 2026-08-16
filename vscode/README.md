# rbx for VS Code

Browse the results of an `rbx run` without leaving the editor: solution →
group → testcase, with verdicts, timings and a diff of what a solution printed
against the expected answer.

Execution stays in the terminal. You type `rbx run`; the extension watches
`.rbx/runs/` and renders whatever lands there. It never invokes `rbx` itself --
every `rbx` invocation has side effects on the package cache and could race a
run already in flight.

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
npm run package    # production bundle
```

From the repository root, the same via mise:

```bash
mise run vscode:build
mise run vscode:typecheck
mise run vscode:package
```

## What it reads

Everything comes from files rbx already writes. The layout is a contract, and
`src/rbx/layout.ts` is the single place that encodes it:

| Path | Contents |
|---|---|
| `<pkg>/.rbx/runs/skeleton.yml` | solutions, groups, testcase entries with provenance |
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
