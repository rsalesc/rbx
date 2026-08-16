# VS Code run tree: solo expansion and node summaries

Follow-up to the M1 extension skeleton (#25, PR #650). Two defects in the Run
view as shipped:

1. Every solution is expanded on load. With a dozen solutions the tree opens as
   a wall of testcases and the user has to collapse each one by hand.
2. A solution or group node carries almost no information — just a verdict
   short name, and a `done/total` counter while the run is in flight. The
   aggregate facts a setter actually looks for (how slow was the worst test,
   did this group score) are only visible by expanding to the testcases and
   reading them off one at a time.

## D1. Expand only a solo solution

`rbx` already draws this exact distinction. `print_run_report` picks its
reporter with `len(result.skeleton.solutions) == 1`
(`rbx/box/solutions.py:2870`), and only the resulting `SingleSolutionRunReporter`
prints a line per testcase; `LiveRunReporter` collapses each group to one line.
The tree adopts the same condition, so the two surfaces agree on what "focused
on one solution" means.

- A package whose report has exactly one solution renders that solution
  `Expanded`.
- Otherwise every solution renders `Collapsed`.
- Group nodes stay `Expanded` regardless. Collapsing them too would cost a
  second click to reach any testcase, and the group breakdown is the reason to
  open a solution at all.
- The rule is evaluated per package, so in a multi-package workspace a package
  with a single solution still opens.

VS Code persists expansion state per `TreeItem.id`, and the ids here are stable
(`<root>::<index>`). The collapsible state is therefore a *default*: once the
user expands a solution it stays expanded across refreshes, which is the
behaviour we want.

## D2. Aggregate summaries on solution and group nodes

A new `summary.ts` computes one `RunSummary` per solution and per group from
the testcases already loaded:

- `outcome` — worst outcome seen so far (existing `worstOutcome`).
- `time` / `memory` — **max** across evaluated testcases. Max, not sum or mean:
  the number that matters is the worst test, because that is what the time
  limit is judged against. This mirrors `get_capped_evals_formatted_time`
  (`solutions.py:1408`) and `get_evals_formatted_memory` (`solutions.py:1442`).
- `done` / `total` — evaluated vs. expected testcases.
- `counts` — testcases per outcome, for the tooltip.
- `score` / `maxScore` — see D3.

Formatting follows rbx rather than the extension's previous ad-hoc units:
`120 ms` with a space, and memory on rbx's `B` / `KiB` / `MiB` ladder
(`rbx/box/formatting.py:43`) instead of the old always-`MB` division. Two
surfaces reporting the same run should not disagree on units.

Descriptions, ` · `-separated:

| node | in progress | complete |
| --- | --- | --- |
| solution, as declared | `12/40 · WA · 340 ms` | `AC · 120 ms · 32 MiB` |
| solution, mismatched | — | `expected AC, got WA · 340 ms · 32 MiB` |
| group | `3/8 · AC · 90 ms` | `WA · 340 ms · 12 MiB` |

The mismatch spelling is kept from M1: an unexpected verdict is the headline
finding of a run and outranks the raw verdict in the description.

Tooltips carry what does not fit: expected outcome, verdict, max time and
memory, the per-outcome counts (`14 AC, 2 WA`), and for a solution the groups
that failed — the same detail `_group_failure_lines` (`solutions.py:1594`)
prints.

## D3. Scores, without dependency gating

Under POINTS scoring rbx awards a group its full `score` all-or-nothing, gated
on `_check_deps` (`solutions.py:1996`): a group scores zero if any group it
depends on failed. The skeleton the extension reads carries `group.score` but
not the dependency graph.

The tree awards `group.score` whenever the group's worst outcome passes, and
sums those for the solution, rendered rbx-style as `[70/100 pts]`. On a problem
with group dependencies this **over-reports** — a group that rbx would zero out
for a failed dependency still shows its points here. That is a deliberate
trade: dependencies would mean parsing `problem.rbx.yml`, and the extension is
otherwise a pure reader of `.rbx/runs` artifacts. The divergence only appears
on a run that already has a failing group, where the tree is showing red
anyway.

Scores are omitted entirely when the package's groups declare no points
(`maxScore == 0`), which is every BINARY-scored problem.

## D4. Tests

`vscode/` had no test setup. Everything in D2 and D3 is pure — outcomes in,
strings out — so it is covered by `node --test` over the TypeScript sources
compiled by esbuild, with no VS Code host. Run with `npm test` from `vscode/`.

The tree provider itself is not tested; it needs the `vscode` module, and the
logic worth protecting has been moved out of it into `summary.ts`.
