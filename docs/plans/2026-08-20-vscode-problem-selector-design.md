# VS Code extension — one problem at a time

Date: 2026-08-20
Status: design approved

## Problem

The Run view renders every problem package in the workspace at once.
`discoverPackages` (`vscode/src/discovery.ts:16`) globs `**/problem.rbx.yml`
across all workspace folders, and `flattenNodes` (`vscode/src/rbx/nodes.ts:85`)
emits one package section per hit, each with all of its solutions, groups and
testcases. For a ten-problem contest that is one long scrollable list whose only
narrowing tool is the filter box.

Three things make it worse than mere length:

- **No contest awareness.** `contest.rbx.yml` appears nowhere under `vscode/`.
  Packages sort lexicographically by absolute path (`discovery.ts:19`) and are
  labelled by directory name, so the `short_name` (the A/B/C letter), the
  contest's declared order and the per-problem `color` are all unused. A
  contest reads as N unrelated directories that happen to be nearby.
- **The header summary leaks across packages.** `buildViewModel` computes
  `mismatches` and `empty` over every row of every package
  (`vscode/src/rbx/viewModel.ts:642`), so the strip reports a workspace-wide
  number rather than one about the problem being read.
- **Every package is parsed on every event.** `loadAll` (`vscode/src/runData.ts:104`)
  re-reads all packages whenever any one of them changes. The per-package
  `ArtifactStore` cache absorbs most of the cost, but the work is O(packages)
  per watcher event regardless.

## Goal

The Run view shows **exactly one problem**, chosen from a dropdown, and follows
whichever problem is currently running.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | An `ActiveProblem` service in the extension host owns the problem list, the selection and the auto-switch rule | Single source of truth. The webview renders a selection it is told about rather than deciding one, so the quick pick, the watcher and the dropdown cannot disagree |
| D2 | The host posts `{problems, selected, run}` — a light list plus **one** package's run | Only the selected package's artifacts are parsed and serialized. A ten-problem contest stops paying for nine of them on every event |
| D3 | The package row is **removed**, not kept as a section header for the selected problem | With one package on screen the row is a permanent parent of everything, one indent level deep, naming what the dropdown already names |
| D4 | Contest identity resolves by walking up to the nearest `contest.rbx.yml` | Mirrors `find_contest_root` (`rbx/box/contest/contest_package.py:103`). Nothing new on the wire; the file is already there |
| D5 | Auto-switch is unconditional: newest skeleton wins | `rbx/box/solutions.py:719` — "A new skeleton is what marks a new run". It is written at run *start*, so this makes the view follow the running problem rather than jump to finished ones |
| D6 | `rbx.packageSearchDepth` is **removed** | Contributed in `package.json` with a default of 3 and never read anywhere in `src/`; discovery globs at unbounded depth. It has never done anything |

### Why not a seen/unseen marker

An earlier draft marked problems in the dropdown with a dot when a run finished
while the user was elsewhere. Dropped: because the skeleton lands at run *start*
and the view follows it, the user is auto-switched *to* each problem as it runs,
so a seen-marker would be cleared by the auto-switch itself and mark almost
nothing. It also needed run-completion detection and `workspaceState`
bookkeeping that nothing else wanted.

## Architecture

```
ActiveProblem (host)
├─ problems: ProblemChoice[]   root + label + shortName + color, in contest order
├─ selected: string            package root; persisted in workspaceState
└─ watcher on **/.rbx/runs/skeleton.yml → select that package

RunViewProvider posts { problems, selected, run } ── webview renders <select> + rows
                 ◄── { type: 'select', root } ──────
`rbx: Select Problem` quick pick ──► ActiveProblem
```

### Contest identity

`src/rbx/contest.ts`, pure logic with no `vscode` import so it stays testable
under plain `node --test` like its neighbours.

For each discovered root, walk up to the nearest `contest.rbx.yml`, parse its
`problems`, and match each entry's resolved path (`path`, defaulting to
`./{short_name}/`) against the root. That yields `short_name`, declared order
and `color`.

The dropdown shows `A`, `B`, `C` in contest order with the declared colour as a
dot. Packages in no contest keep today's `packageLabel` and sort after. Two
contests in one workspace become two `<optgroup>`s.

**Variants.** A `contest.rbx.yml` with `use_variants: true` declares no problems
of its own. Rather than teach the extension variant selection, gather problems
from the canonical file plus every `contest.*.rbx.yml` sibling, first file
naming a given root wins. Mislabelling across variants is possible in principle,
but the letters are near-always shared and the fallback is today's directory
name.

## What this deletes

- `showPackages` and the package branch of `flattenNodes` (`nodes.ts:85`), and
  the depth-offset recomputation it forced (`viewModel.ts:612`).
- `PackageNode`, `packageRow` (`viewModel.ts:457`) and the `rbx.package`
  webview section. `rbx.revealInExplorer` re-attaches to the header.
- Per-package solution-label trimming (`viewModel.ts:585`) collapses to the
  single-package case.
- The `mismatches`/`empty` cross-package leak, fixed by construction.
- The `rbx.packageSearchDepth` setting (D6), and `IGNORED_DIRS`
  (`layout.ts:114`) — exported, unused, and already drifted from the real
  exclusion glob in `discovery.ts:12`, which does not exclude `out`/`dist`.
  One list, used by discovery.

## Edge cases

| Case | Behaviour |
|---|---|
| One package | Dropdown hidden; the view looks exactly as it does today |
| Zero packages | Existing empty state, unchanged |
| Selected package disappears | Fall back to the first problem in order |
| Reload | Selected root persisted in `context.workspaceState`, so a reopened window does not land on A every time |

## Testing

Contest resolution, problem ordering and the reduced `flattenNodes`/`viewModel`
are pure functions under `src/rbx/`, tested with `node --test` alongside the
existing `nodes.test.ts` and `viewModel.test.ts`. `ActiveProblem` holds only the
vscode-facing glue — watcher subscription, `workspaceState`, quick pick —
mirroring how `runData.ts` is already split from `nodes.ts`.
