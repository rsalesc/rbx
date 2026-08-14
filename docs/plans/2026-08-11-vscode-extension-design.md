# VS Code extension — v1 design

Issue: [#25](https://github.com/rsalesc/rbx/issues/25)
Date: 2026-08-11
Status: design approved, not implemented

## Goal

Bring the two most useful `rbx ui` screens — **build** (browse generated
testcases) and **run** (browse solution verdicts per testcase) — into VS Code,
so a setter who just typed `rbx run` in the integrated terminal can inspect what
happened without scrolling terminal output or launching the TUI.

Execution stays in the terminal. The extension only *observes and renders*.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | The extension lives in this repo, under `vscode/` | Contract changes and the reader that depends on them land atomically |
| D2 | **The contract is the on-disk artifact layout.** The extension is a pure reader — it parses `.box/` and never invokes `rbx` | Every `rbx` invocation has side effects: `package.get_problem_cache_dir()` mkdirs `.box/` and writes a `fingerprint` file; `get_problem_runs_dir()` mkdirs. A query command could corrupt or race a concurrently running `rbx` |
| D3 | Terminal-first. The user runs `rbx build` / `rbx run`; the extension watches `.box/` | rbx keeps sole ownership of execution. Nothing is hidden from the user, and the terminal output stays the source of truth |
| D4 | Custom `TreeView` in an rbx sidebar, **not** the VS Code Testing API | Full control over MAIN badges, POINTS scores, expected-vs-actual mismatch styling, group headers. The Testing API is shaped for *running* tests, which we deliberately do not do |
| D5 | Testcase content opens as **read-only editor windows**; comparisons use the native diff editor. No webview in v1 | Every artifact the TUI shows is already a real file on disk. Editors give syntax highlighting, search, large-file handling and familiar keybindings for free |
| D6 | `rbx build` persists its entry list to `.box/tests/entries.yml` | The one piece of state the TUI shows that is *not* on disk after a build (see [Build provenance](#the-one-gap-build-provenance)) |

### Why not a JSON manifest emitted by rbx

An earlier draft had `rbx run` emit a denormalized `ui.json` for the extension
to read. Rejected, because reading the existing artifacts is strictly better:

- The manifest could only be written **at the end of a run**. The raw artifacts
  give **live progress for free** (see below).
- It duplicates state that `skeleton.yml` already carries.
- It is another schema to version, dump and guard.

The escape hatch remains: if the extension ever needs something genuinely not
derivable from disk, rbx persists it — as D6 does — rather than growing a query
command.

## Architecture

```
VS Code window
├─ Integrated terminal ── user types `rbx run` ──┐
│                                                 │ rbx writes:
│                                                 │   .box/tests/<group>/<stem>.in|.ans
│                                                 │   .box/tests/entries.yml        (D6)
│                                                 │   .box/runs/skeleton.yml
│                                                 └─ .box/runs/<i>/<group>/<stem>.eval|.out|.err|.log|.pio
│
├─ Extension (pure reader — never spawns rbx)
│   ├─ PackageDiscovery      scan workspace folders for problem.rbx.yml
│   ├─ ArtifactWatcher       FileSystemWatcher on .box/runs/** and .box/tests/**
│   ├─ ArtifactStore         parse YAML → typed model, cached + invalidated by the watcher
│   ├─ RunTreeProvider       solution → group → testcase (verdict, time, memory)
│   ├─ BuildTreeProvider     group → testcase (provenance)
│   └─ RbxFileSystemProvider scheme `rbx:`, isReadonly, maps URIs to real paths
│
└─ Editors: read-only documents + vscode.diff(output, answer)
```

## What is on disk, and what the extension reads

### After `rbx run`

`rbx.box.solutions.run_solutions()` rmtree's the runs dir, recreates it, writes
`skeleton.yml`, then drops one `.eval` per (solution, testcase) as evaluations
resolve.

| Path | Contents |
|---|---|
| `.box/runs/skeleton.yml` | `SolutionReportSkeleton` — solutions, groups, `entries` (with full provenance), per-language limits, verification level |
| `.box/runs/<i>/<group>/<stem>.eval` | `Evaluation` — verdict, time, memory, checker message, **absolute paths** to stdout/stderr/log |
| `.box/runs/<i>/<group>/<stem>.out` | solution stdout |
| `.box/runs/<i>/<group>/<stem>.pio` | interaction capture (communication tasks) |

`<i>` is the solution's index in `skeleton.solutions`; `SolutionSkeleton.runs_dir`
records it.

### After `rbx build`

| Path | Contents |
|---|---|
| `.box/tests/<group>/<stem>.in` | generated input |
| `.box/tests/<group>/<stem>.ans` | expected answer |
| `.box/tests/entries.yml` | `List[GenerationTestcaseEntry]` — **new, see D6** |

## Live progress, for free

Because artifacts land incrementally, the watcher yields a full run lifecycle
without any streaming protocol:

| Filesystem event | Extension reaction |
|---|---|
| `.box/runs/` emptied | previous run invalidated; tree greys out |
| `skeleton.yml` appears | populate the whole tree, every test `pending` |
| each `<stem>.eval` appears | fill in that test's verdict, time, memory; roll up group/solution status |
| all evals present | notification: *"Run finished: 2 of 4 solutions failed"* |

This is the main reason D2 beats the manifest approach.

## Models to mirror in TypeScript

Three Pydantic models, all serialized as YAML:

- `rbx.box.solutions.SolutionReportSkeleton` (+ `SolutionSkeleton`, `GroupSkeleton`)
- `rbx.box.generation_schema.GenerationTestcaseEntry` (embedded in the skeleton and in `entries.yml`)
- `rbx.grading.steps.Evaluation` (+ `CheckerResult`, `TestcaseIO`, `TestcaseLog`)

### The stem quirk — get this right or the UI lies

`.eval` / `.out` filenames are **not** `{index:03d}`. `SolutionReportSkeleton.get_entry_stem()`
resolves the real stem through `entry.metadata.copied_to.inputPath.stem` — a
subgroup-generated test is e.g. `1-gen-000`, not `003`. The zero-padded form is
only a legacy fallback for old packages.

Mirror `get_entry_stem()` and `get_solution_entry_prefix()` faithfully. Getting
this wrong silently displays another testcase's output; it was a real rbx bug
once (#418 / #429).

## The one gap: build provenance

After a run, `skeleton.yml` carries `entries` with full provenance. After a
*build alone*, the `.in` / `.ans` files exist but the provenance the TUI's test
explorer shows — which generator call produced a test, its copied-from path,
inline `@input` content — is computed in-process by
`rbx.box.testcase_extractors.extract_generation_testcases_from_groups()` from
`problem.rbx.yml` plus Lark-parsed generator scripts. It is never persisted.

**D6:** `rbx build` dumps the list it already computed to `.box/tests/entries.yml`,
reusing the existing `GenerationTestcaseEntry` model. No new schema — just
persisting what `skeleton.yml` already carries.

```yaml
- group_entry: {group: main, index: 0}
  metadata:
    copied_to: {inputPath: .box/tests/main/000.in}
    generator_call: {name: gen, args: "5 3"}
- group_entry: {group: main, index: 1}
  metadata:
    copied_to: {inputPath: .box/tests/main/001.in}
    copied_from: {inputPath: tests/manual/big.in}
```

## Read-only editors

Register a `FileSystemProvider` for scheme `rbx:` with `isReadonly: true`,
mapping URIs onto real paths under `.box/`.

Chosen over `TextDocumentContentProvider` because it streams large testcases
lazily instead of holding them in memory, and because the URI's last path
segment becomes the editor tab title:

- `rbx:/sols/wa.cpp/main/3/output.out` → tab reads `output.out`, C++/text
  highlighting intact, file never accidentally editable
- `⇄` on a failing test → `vscode.diff(outputUri, answerUri, 'wa.cpp · main/3')`

Reading the real path directly would also work, but risks the user editing a
generated artifact, and gives useless tab titles (`003.out` five times over).

## Tree shape

```
RBX
└─ RUN                                   2 of 4 solutions failed · 12s ago
   ├─ sols/main.cpp          MAIN   OK
   │  └─ main                       30 / 30
   │     ├─ 0   AC   12ms  3MB
   │     └─ 1   AC   10ms  3MB
   └─ sols/wa.cpp     expected WA, got AC   ⚠ UNEXPECTED_VERDICTS
      └─ main                        0 / 30
         └─ 3   WA    8ms  3MB   wrong answer 3rd number

RBX
└─ BUILD                                 24 testcases in 3 groups
   └─ main
      ├─ 0    gen 5 3
      └─ 1    tests/manual/big.in
```

Context menu / inline actions per testcase: open input, open output, open
expected answer, open stderr, open interaction, diff output ↔ answer, reveal in
explorer, copy path.

## Repository layout and tooling

```
vscode/
  package.json          extension manifest, contributes views/commands/menus
  src/                   TypeScript
  test/                  @vscode/test-cli
  esbuild.mjs
```

- Own `package.json`; the Python toolchain is untouched.
- `mise run vscode:build` / `vscode:test` / `vscode:package` tasks.
- A separate GitHub workflow — the extension's CI must not gate Python CI.
- Published to the Marketplace independently of the PyPI release cadence.

## Version skew

Users can pair any extension version with any installed `rbx-cp`. The extension
checks the `fingerprint` file / package cache version and degrades gracefully:
unknown fields are ignored, missing files produce empty-state views rather than
errors, and an unreadable skeleton produces one actionable notification
("this run was produced by a newer rbx; update the extension") rather than a
stack trace.

## Milestones

| # | Scope |
|---|---|
| M0 | **rbx:** persist `.box/tests/entries.yml` during build (D6); document the artifact layout in `docs/internal/`; e2e tests pinning the layout |
| M1 | Extension skeleton, package discovery, run tree from `skeleton.yml` + `.eval`, read-only editors, diff |
| M2 | Build tree from `entries.yml`, live progress via the watcher, "run finished" notification, status bar item |
| M3 | Polish: failed-only filter, fuzzy search, POINTS totals, MAIN badge, keybindings, interaction view for communication tasks |

M1 can start immediately against today's rbx — only the build tree depends on M0.

## Non-goals for v1

- Running `rbx` from the extension (D3)
- `problem.rbx.yml` authoring support — the versioned JSON schemas (#617) already give completion and validation
- Stress testing, statements, packaging, `irun` / interactive mode, visualizers
- The VS Code Testing API (D4)

## Risks

- **Multi-problem workspaces.** A contest workspace holds N problem directories,
  plus `-C` variant selection (`contest.rbx.yml` dispatcher mode). v1 shows one
  root node per discovered `problem.rbx.yml`, flattening when there is only one.
  Variant selection is out of scope for v1.
- **Absolute paths in `.eval`.** `TestcaseLog.stdout_absolute_path` and friends
  are absolute. They resolve correctly whenever rbx and the extension host share
  a filesystem (including Dev Containers and WSL, where the extension host runs
  inside the container). They break for a local UI against a remote-executed
  rbx — out of scope, but the extension should prefer paths derived from
  `skeleton.runs_dir` + `get_entry_stem()` and treat the absolute ones as a
  fallback.
- **Layout drift.** D2 makes the on-disk layout a public contract. M0's e2e
  tests exist to make a breaking change loud on the rbx side.
- **Interrupted runs.** A Ctrl-C'd run leaves a skeleton with a partial set of
  `.eval` files, indistinguishable from a run in progress. v1 treats missing
  evals as `pending` and lets the user re-run; a timestamp-based staleness hint
  can come later.
