# VS Code: dispatching `rbx build` / `rbx run` from the editor

Issue: [#906](https://github.com/rsalesc/rbx/issues/906).

## The decision

Design decision D3 of the [extension design](2026-08-11-vscode-extension-design.md)
said the user runs `rbx build` and `rbx run` in a terminal and the extension
only watches. It now reads:

> **D3** -- Terminal-first. The extension may **dispatch** `rbx` commands to a
> visible terminal, as VS Code tasks, but never runs them headless and never
> parses their output. Results still come from the on-disk artifacts.

The rationale is unchanged. rbx still owns execution: the task runs the real
`rbx` in a terminal the user can see and stop with Ctrl-C. The terminal output
is still the source of truth, and the views still read only `.rbx/`, so a
dispatched run is followed live by the watchers that already follow one typed
by hand.

## Dispatch mechanism: VS Code tasks

Every entry point builds a `vscode.Task` with a `ShellExecution` of the
resolved `rbx` (`resolveRbx`, so `rbx.executable` and venvs apply), the argv as
an array (VS Code quotes it for the shell), and `cwd` at the package root -- or
the contest root, for a contest-wide run. The task has no problem matchers.

Tasks were chosen over typing into a terminal with `Terminal.sendText`:

- `sendText` cannot tell whether the terminal is busy without shell
  integration, which is stable only from VS Code 1.93 and can be missing even
  then. A task's lifetime is known exactly: `vscode.tasks.taskExecutions`,
  `onDidStartTask`, `onDidEndTask`.
- Tasks need no engine bump (the extension targets `^1.90`).

The cost is that the task terminal is not the user's interactive shell, so
there is no up-arrow to edit the command. *Re-run Last Command* covers the
common case.

Entry points: a **Run** CodeLens next to a solution's declaration lens, an
editor-title button on solution files, *Run All Solutions* / *Re-run Last
Command* / *Build Tests* in the view titles, *Run This Solution* on a Run view solution row,
buttons in both views' empty states, and *Run All Problems in the Contest*
(`rbx contest each --inline run`; `--inline` because the default opens the
contest TUI). Each is a command, so keybindings need no task provider.

## The busy policy

**A dispatch never interleaves with an rbx command already running where it
would run.** Two commands *collide* when one runs in the other's directory or
above it:

- Any two commands in the same package -- not only identical ones. VS Code's
  own "task already active" guard catches only an identical task, so it would
  let `rbx build` start under a running `rbx run sols/a.cpp`. A second `rbx
  run` writes a fresh skeleton, which clears the report the first is still
  writing; an `rbx build` regenerates the tests the run is reading. The cache
  would survive (rbx's session lock allows concurrent processes), but the
  results would not.
- A contest-wide run and any package under the contest, in both directions.

Two different packages never collide.

The policy is kept in two layers, because a task can start without passing
through the extension's code:

1. **Before.** Every extension entry point goes through one queue, so two
   quick clicks cannot both pass the check. A collision opens a modal: *Stop
   and Run* terminates the colliding tasks and waits (up to 10 s) for them to
   end; *Cancel* does nothing.
2. **After.** VS Code's *Rerun Last Task* re-executes a task directly.
   `onDidStartTask` checks every rbx task the extension did not approve; one
   that collides is terminated at once, with a message naming the command it
   ran into. rbx spends its first moments importing before it writes anything,
   so in practice the task is stopped before it touches the run it collided
   with. This is a race the extension wins by a wide margin, not a guarantee.

There is no task provider, so `tasks.json` cannot declare an rbx task (VS Code
ignores an entry of a custom type no provider resolves). The `taskDefinitions`
contribution only describes the tasks the extension itself starts.

Commands typed by hand in an ordinary terminal are outside both layers: the
extension cannot see them without reading the terminal, which D3 rules out.

The collision rule is a pure function (`collides` in
`vscode/src/rbx/dispatch.ts`) and is unit-tested.

## Contest variants

A command's *candidates* are the contests it could run under:

| Scope | Candidates |
|---|---|
| Problem (`rbx run`, `rbx build`) | every contest file in the contest root whose `problems:` names the package |
| Contest (`rbx contest each run`) | every contest file that is a real contest, not a `use_variants` dispatcher |

With no candidates nothing is passed, and rbx resolves the contest as it would
for a command typed by hand. With one, it is used without asking. With several,
the extension uses the choice remembered for that contest root
(`workspaceState`) or asks with a quick pick and remembers the answer. A
remembered choice that is no longer a candidate is dropped and asked again.

This is stricter than rbx's own fallback. With no selection, rbx uses the
canonical `contest.rbx.yml` whenever one exists, even when the problem is listed
only in a sibling, and the variant changes what a run uses (for example, the
contest's `languages:`). So once the extension has resolved a contest it always
says so: a variant as `-C <id>`, and the canonical by clearing `RBX_CONTEST` in
the task's environment, so an inherited variant cannot override the choice.

The resolved contest appears in the task name (`run sols/a.cpp [div1]`) and,
while the selected problem has more than one candidate, in a status-bar item
that opens *Change Contest for Dispatched Commands*.

## Settings

- `rbx.dispatch.enabled` (default `true`): `false` removes every dispatch
  entry point. The extension goes back to only watching what the user runs;
  the read-only spawns it already had (visualizers, `rbx vars`) are unaffected.
- `rbx.run.extraArgs` (default `[]`): arguments added to every dispatched
  `rbx run`, one per item, including each problem's run in a contest-wide run.

## Out of scope

- Running one solution on one test, or on custom input: #907 (`rbx irun`).
- Parsing terminal output.
- A task provider listing rbx tasks in *Run Task*. Keybindings bind the
  commands, and every command goes through the busy policy's first layer.
