# VS Code: stress testing from the editor

Issue: [#908](https://github.com/rsalesc/rbx/issues/908). Builds on dispatch
([#906](https://github.com/rsalesc/rbx/issues/906),
[design](2026-10-15-vscode-dispatch-design.md)).

## Goal

Start a stress test from VS Code, watch it run, open each finding as a
testcase (input, every involved solution's output, verdicts), and promote a
finding into the testset -- reviewing the change before it lands.

## Decisions

- **S1 -- The artifact layout is the contract (approach A).** `rbx stress`
  publishes a versioned manifest and keeps each finding's outputs on disk, in
  the same shapes the run artifacts use. The extension never parses `rbx
  stress` output. Rejected: writing findings as a fake run (stress-only facts
  have no home there and would clobber the last real run), and an NDJSON
  stdout stream (violates D2/D3, loses state on reload).
- **S2 -- Latest session only.** Like today, a new stress replaces
  `.rbx/runs/.stress`. No history, no session index.
- **S3 -- A third sidebar view, "Stress"**, next to Run and Tests: declared
  stresses, progress, findings.
- **S4 -- The launcher is an editor-tab form**, not inline in the sidebar and
  not a QuickPick wizard: it needs room for the finder builder and a live
  command preview.
- **S5 -- The finder is built from rows only.** There is no "edit as text"
  mode; anything the rows cannot express is a job for the terminal.
- **S6 -- Promote offers both kinds of group.** Script groups get the
  reproducible generator call, proposed as a reviewable, editable diff; manual
  groups get a copy of the input.

## Python

### The stress manifest

```
.rbx/runs/.stress/
  stress.yml                          # versioned, written atomically
  findings/<k>/input.in
  findings/<k>/<sol>.out|.err|.eval   # same shapes as runs/<i>/<group>/
```

`stress.yml` (version 1):

- `state`: `running | done | interrupted | failed`;
- `spec`: stress name (if declared), generator expression, finder, fuzz
  groups, `slowest`, timeout, findings limit, time limit mode;
- `startedAt`, `elapsed`, `executed`, `skipped`;
- `solutions`: the solutions involved, in order -- `<sol>` above is the index
  into this list;
- `findings`: `[{index, generator: {name, args}, duration, results}]`, where
  `results` holds each finder-evaluated solution's worst outcome (enum value),
  time and memory;
- `pid`, `host`: the rbx process running the session, so a reader on the same
  host can tell a live `running` session from a dead one.

It is rewritten immediately when a finding lands and at most once a second
for the counters. The final state is always written: Ctrl-C finishes the
current test and ends `interrupted`; SIGTERM/SIGHUP (a terminated task) stamp
`interrupted` and exit at once; any other exception ends `failed`. Only
findings keep their outputs (plus `input.ans` when a reference answer was
produced): they are copied out of the scratch area before the next iteration.
`--slowest` renumbering moves whole finding directories.

### CLI

- `rbx stress ... --no-promote` skips the end-of-run promotion prompt. The
  extension always passes it, so the dispatched task ends cleanly.
- `rbx testcases add-finding [K...] --group G`, or `--new-script PATH`, or
  `--new-manual NAME --glob GLOB`: promotes findings of the latest session,
  read from `stress.yml`, reusing `rbx/box/promotion.py`. It lives under
  `testcases` because `rbx stress promote` would collide with `rbx stress`'s
  positional stress name. Re-adding a finding a group already has is skipped.
- `--dry-run --json` (script groups only) is read-only (allowed headless,
  like `rbx vars --json`) and prints `{file, before, after}`;
  `--list-groups --json` lists the eligible groups. Under `--json` everything
  else goes to stderr.

Phase 2 (not in the first PR): `rbx stress --sample N` to preview generator
calls in the launcher, and `rbx stress declare NAME ... --dry-run --json` for
"Save as declared stress".

## Extension

### Dispatch and watching

- `RbxCommand` gains `stress`; `rbxArgs` builds the argv. It runs through the
  existing `Dispatcher` (one task at a time, visible terminal), with its
  arguments strong-quoted. Stop terminates the task (SIGHUP); rbx then stamps
  the manifest `interrupted`. Stop is offered only for sessions the extension
  dispatched.
- New watch on `.stress/stress.yml` (findings' files are copied before the
  manifest names them, so the manifest alone is enough) and a `stress` kind in
  `classifyCachePath`, feeding a stress store with a versioned reader. A
  `running` manifest whose `pid` is dead on this host shows as stale; without a
  pid, the extension falls back to whether it has a stress task running.

### Sidebar view

Declared stresses (from `problem.rbx.yml`) with Run and Edit, and "New
stress"; a progress line; one row per finding with its generator call,
duration and a verdict chip per solution, and Open, Copy call and Promote.

### Launcher (editor tab)

Three sections compile to one `rbx stress` command, shown live in the footer:

1. **Inputs** -- declared stress, generator expression (completion for
   generator names and variables; insert chips for `@`, `[a..b]`, `(a|b)`), or
   fuzz testgroups.
2. **Find** -- rows joined by an All of / Any of toggle: *Break*
   (`[sol] ~ OUTCOME`, preselecting the solution's declared outcome),
   *Disagree* (`[a] != [b]`), *Slowest* (`--slowest`). Editing a declared
   stress whose finder the rows cannot express shows it as a read-only chip
   with "Replace with rows".
3. **Budget** -- time, findings, time limit mode; Advanced: sanitized, skip
   invalid, validate, reference solution.

The last ad-hoc configuration is kept per workspace.

### Open a finding

The input plus each solution's output and stderr open in the read-only
`rbx:` tabs; Compare diffs two of the reference answer and the outputs.
Visualize is not in the first PR.

### Promote

- Script group: run the dry-run headless, open `vscode.diff` of the real file
  against a writable `rbx-proposed:` document. The user edits the right side,
  then Accept (applies and saves) or Discard. Accept refuses if the file
  changed since the dry-run.
- Manual group, new script group, new manual group: dispatch
  `rbx testcases add-finding` in the terminal; the badge appears when the task
  exits 0.
- Promote is disabled while the session is still running.
- The finding row then shows "in `<group>`", tracked by the extension for the
  current session.

## Testing

- Python: manifest lifecycle (running, done, interrupted), atomic writes,
  kept outputs, slowest renumbering; `promote` into each group kind and
  `--dry-run --json`.
- Extension unit tests: `rbxArgs('stress')`, finder rows to expression and
  back, the `stress.yml` reader's version gate, `classifyCachePath`.
