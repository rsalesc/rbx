# VS Code stress testing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Run `rbx stress` from a VS Code "Stress" view and an editor-tab launcher, watch it live, open findings, and promote them into the testset (issue #908).

**Architecture:** rbx publishes `.rbx/runs/.stress/stress.yml` (versioned, atomic) plus per-finding directories; the extension watches them (design D2) and dispatches `rbx stress` / `rbx testcases add-finding` as visible tasks (D3). Script-group promotions are proposed as an editable diff computed by a read-only `--dry-run --json`. Design: `docs/plans/2026-10-15-vscode-stress-design.md`.

**Tech Stack:** Python (Typer, Pydantic v2, pytest), TypeScript VS Code extension (esbuild, `node --test`), webviews with no framework.

---

## Conventions (read before any task)

- Python: single quotes, absolute imports, `uv run pytest <file>` (never the full suite), `uv run ruff check --fix . && uv run ruff format .`.
- Extension (`vscode/`): pure logic in `src/rbx/*.ts` with `*.test.ts` beside it, no `vscode` import there; host glue in `src/*.ts`; webview clients in `src/webview/*` bundled by `esbuild.mjs`. Run `npm run typecheck && npm test && npm run lint` inside `vscode/`. Match the comment density of the neighbouring files: they explain *why*.
- Findings are numbered **from 1** everywhere: directories, manifest `index`, CLI argument, UI `#1`.
- Commit after each task with a Conventional Commit message (`feat(stress): ...`, `feat(vscode): ...`).

## Python

### Task 1: The stress manifest module

**Files:** Create `rbx/box/stress_manifest.py`; Test `tests/rbx/box/stress_manifest_test.py`.

Pydantic models and IO, nothing else:

```python
STRESS_MANIFEST_VERSION = 1
class StressState(str, Enum): RUNNING='running'; DONE='done'; INTERRUPTED='interrupted'; FAILED='failed'
class StressSpec(BaseModel):  # what was asked
    name: Optional[str]; generator: Optional[str]; finder: str
    fuzz: Optional[List[str]] = None   # [] == all groups, None == no fuzz
    slowest: bool = False; timeout: int; findingsLimit: int
    timelimit: Optional[int] = None; doubleTL: bool = False
class StressSolutionResult(BaseModel):
    solution: int  # index into StressManifest.solutions
    outcome: str   # Outcome enum *name*, e.g. 'WRONG_ANSWER' (match run_report.py's convention)
    time: Optional[float] = None  # seconds
    memory: Optional[int] = None  # bytes
class StressFindingEntry(BaseModel):
    index: int                      # from 1; also the directory name
    generator: GeneratorCall        # expanded, with the seed
    duration: Optional[int] = None  # ms
    results: List[StressSolutionResult] = []
class StressManifest(BaseModel):
    version: int = STRESS_MANIFEST_VERSION
    state: StressState; spec: StressSpec
    startedAt: datetime; elapsed: float = 0; executed: int = 0; skipped: int = 0
    solutions: List[str]            # solution paths, ordered; <sol> dirs use the index
    findings: List[StressFindingEntry] = []
```

Helpers: `stress_dir() -> Path` (`package.get_problem_runs_dir() / '.stress'`), `manifest_path()`, `finding_dir(k)`, `finding_input_path(k)` (`findings/<k>/input.in`), `write_manifest(m)` (yaml dump of `model_dump(mode='json')` to a temp file in the same dir, then `os.replace`), `read_manifest() -> Optional[StressManifest]` (None when missing or a different version). Model the yaml dump on `rbx/box/run_report.py`.

Tests (TDD): round-trip; atomic write leaves no temp file; `read_manifest` returns None for missing file and for `version: 99`.

### Task 2: Publish the manifest and keep finding outputs from `run_stress`

**Files:** Modify `rbx/box/stresses.py`; Test `tests/rbx/box/stresses_test.py` (check for an existing stress test file and fixtures under `tests/rbx/box/` first, reuse them).

- After `.stress` is wiped, write a `RUNNING` manifest (spec from the arguments; `solutions` = `[str(s.path) for s in solutions]` from the finder).
- On each finding: create `findings/<k>/`, copy `input` to `input.in`, and copy each involved solution's artifacts from the scratch run (`output_dir=input_path.parent`, `filestem=f'{index}'` -- check which of `.out/.err/.log/.eval` `tasks.run_solution_on_testcase` writes in stress mode; if no `.eval` is written, dump the `Evaluation` the same way `solutions.py` does for runs) to `findings/<k>/<index>.<ext>`. Append a `StressFindingEntry` with `results` from `finder_outcome.results` (dedupe by solution) and rewrite the manifest immediately.
- Rewrite the counters (`executed`, `skipped`, `elapsed`) at most once a second.
- Wrap the loop so the final state is `DONE` on normal exit, `INTERRUPTED` on `KeyboardInterrupt`, `FAILED` on any other exception (re-raise it) or `typer.Exit` with nonzero code.
- `--slowest`: keep candidates as directories; `_renumber_slowest_findings` moves directories, and the manifest's findings are rewritten in the final order (1..n). A finding evicted from the heap deletes its directory and its manifest entry.
- `StressReport`/`print_stress_report` keep working; the findings path printed stays `findings/`.

Tests: a stress with a WA solution produces `stress.yml` with `state: done`, N findings, `findings/1/input.in` and the involved solutions' outputs; `KeyboardInterrupt` raised from inside the loop (patch a generator step) leaves `state: interrupted`; slowest mode renumbers directories contiguously.

### Task 3: `--no-promote` and the interactive prompt on the new layout

**Files:** Modify `rbx/box/cli/commands/stress.py`; Test the existing stress CLI test if any (else skip CLI test, rely on Task 4 tests).

- Add `--no-promote` (help: 'Do not offer to add the findings to a test group when the stress ends.'). When set, return after `print_stress_report`.
- The manual-group branch reads `stress_manifest.finding_input_path(k)` instead of `findings/<i>.in`.
- Move the "append generator calls to a script group" and "copy into a manual group" bodies into `rbx/box/promotion.py` functions so Task 4 reuses them:
  - `propose_script_append(group, calls, comment) -> tuple[Path, str, str]` (file, before, after) -- uses `generator_script_handlers` exactly as today, does **not** write.
  - `append_to_script_group(group, calls, comment) -> Path` -- propose + write.

### Task 4: `rbx testcases add-finding`

**Files:** Modify `rbx/box/testcases/main.py`; Test `tests/rbx/box/testcases/add_finding_test.py` (look at existing promote tests in that folder for fixtures).

```
rbx testcases add-finding [K...] (--group G | --new-script PATH | --new-manual NAME --glob GLOB)
                          [--dry-run] [--json]
rbx testcases add-finding --list-groups --json
```

- `K` are finding indices of the latest session (read via `stress_manifest.read_manifest()`; error clearly if no manifest or an index is unknown). No K means all findings.
- `--group G`: G must be a `.txt` generatorScript group (append calls; comment `Found by rbx stress <spec summary>`) or a manual group (copy `input.in` with `promotion.promote_input_to_group`). Anything else errors naming the two kinds.
- `--new-script PATH` -> `promotion.create_script_group`, then append. `--new-manual NAME --glob GLOB` -> `promotion.create_manual_group`, then copy.
- `--dry-run --json` (script groups and `--new-script` only): print `{"file": <abs path>, "before": str, "after": str}` and write nothing. For `--new-script` `before` is `""` and nothing is registered in `problem.rbx.yml` (the extension dispatches the real command after accept... see Task 12; simplest: dry-run is only allowed with `--group`).
- `--list-groups --json`: print `[{"name", "kind": "script"|"manual", "path"}]` (script path = generatorScript path, manual path = glob), reusing the same filters as the interactive prompt.
- JSON goes to stdout via plain `print(json.dumps(...))`, nothing else on stdout.

Tests: each mode; dry-run writes nothing; list-groups output; unknown index errors.

## Extension

### Task 5: Read the stress manifest; watch it

**Files:** Create `vscode/src/rbx/stress.ts` (+ test); Modify `vscode/src/rbx/layout.ts` (+ test), `vscode/src/rbx/artifactEvents.ts` (+ test), `vscode/src/extension.ts`.

- `layout.ts`: `stressDir(pkg)`, `stressManifestPath(pkg)`, `findingDir(pkg, k)`, `findingInputPath(pkg, k)`, `findingArtifactPath(pkg, k, solution, ext)`.
- `stress.ts`: `STRESS_SUPPORTED_VERSION = 1`, typed `StressManifest` mirroring Task 1, `parseStressManifest(raw: Wire)` using `wire.ts` helpers, returning undefined for unknown versions. Pattern: `report.ts`.
- `artifactEvents.ts`: a `{ kind: 'stress' }` event for `runs/.stress/stress.yml` only (outputs are opened on demand). Update the comment that says `.stress` is ignored. `planRefresh` must not treat it as a run change.
- `extension.ts`: add `**/.rbx/runs/.stress/stress.yml` to the watcher globs; expose an event the Stress view subscribes to (follow how `RunDataProvider.onDidChange` / `touchesTestset` gate the Tests view; add `touchesStress`).

### Task 6: Finder rows and the stress argv (pure)

**Files:** Create `vscode/src/rbx/finder.ts` (+ test), `vscode/src/rbx/stressSpec.ts` (+ test).

- `finder.ts`:
  ```ts
  type FinderRow = { kind: 'break'; solution: string; outcome: string }
                 | { kind: 'disagree'; a: string; b: string };
  type Join = 'all' | 'any';
  compileFinder(rows, join): string   // '[a] ~ WRONG_ANSWER && [b] != [c]'; quote paths with reserved chars (grammar in rbx/box/stressing/finder_parser.py)
  recognizeFinder(expr): { rows, join } | undefined  // only the shapes compileFinder emits, plus a bare `path` (== break INCORRECT); anything else undefined
  ```
  Outcomes offered: the `ExpectedOutcome` names (see `src/rbx/rbxEnums.json` if it carries them). `defaultOutcomeFor(declaredOutcome)` maps a solution's declared expectation to the preselected outcome (accepted -> INCORRECT).
- `stressSpec.ts`:
  ```ts
  interface StressLaunch {
    source: { kind: 'declared'; name: string } | { kind: 'generator'; expression: string } | { kind: 'fuzz'; groups: string[] };
    finder?: { rows: FinderRow[]; join: Join } | { declared: true };  // declared: keep the stress's own finder
    slowest: boolean; timeout: number; findings: number;
    tl: { kind: 'normal' } | { kind: 'double' } | { kind: 'custom'; ms: number };
    sanitized: boolean; skipInvalid: boolean; validate: boolean; reference?: string;
  }
  stressArgv(launch): string[]           // args after `rbx`, always ending with --no-promote
  validateLaunch(launch): string | undefined  // human message, e.g. 'A generator stress needs a target.'
  ```
  A declared stress whose finder was replaced by rows is passed as `-g <its generator> -f <rows>` (the CLI cannot override a declared stress's finder by name).

### Task 7: Dispatch `stress` and `add-finding`

**Files:** Modify `vscode/src/rbx/dispatch.ts` (+ test), `vscode/src/dispatch.ts`.

- `RbxCommand` += `'stress' | 'add-finding'`; `Invocation.args?: readonly string[]` carries the argv tail; `rbxArgs` emits `['stress', ...args]` / `['testcases', 'add-finding', ...args]`; `taskName` -> `stress <name|generator>` / `add finding`.
- `DispatchRequest.args` passed through `dispatchNow`.
- `Dispatcher` exposes `isRunning(root, command)` (from `runningRbxTasks()` + definition.command) for stale detection, and `stop(root, command)` to terminate a running stress.

### Task 8: Declarations the launcher needs

**Files:** Create `vscode/src/rbx/stressDeclarations.ts` (+ test).

`parseStressDeclarations(raw: Wire)` -> `{ stresses: {name, generator: {name, args?}, finder}[], generators: string[], solutions: {path, outcome?}[], groups: string[] }` from `problem.rbx.yml` (reuse `manifest.ts`'s outcome normalisation for solutions). Read with `readYamlFile(manifestPath(pkg))` in the host.

### Task 9: The Stress sidebar view

**Files:** Create `vscode/src/rbx/stressViewModel.ts` (+ test), `vscode/src/stressView.ts`, `vscode/src/webview/stressMain.ts`, `vscode/src/webview/stressRender.ts` (+ test); Modify `vscode/package.json` (view `rbx.stress`, activation `onView:rbx.stress`, commands, `view/title` actions), `vscode/esbuild.mjs` (entry), `vscode/src/extension.ts` (register).

- Copy the `testsetView.ts` shape (html shell with CSP + nonce, `ready`/`state` messages, `Latest` guard, no `retainContextWhenHidden`).
- View model: declared stresses (Run, Edit), `New stress…`; status line (`running`/`done`/`interrupted`/`failed`/`stale` + executed/skipped/findings + elapsed vs timeout); findings rows (`#k`, `gen args`, duration, chips `solution basename: OUTCOME`, promoted badge).
- Messages from client: `run-declared {name}`, `edit-declared {name}`, `new`, `stop`, `open {k}`, `copy {k}`, `promote {k}`, `compare {k}`.
- Stale: `state === 'running'` and `!dispatcher.isRunning(root, 'stress')`.
- Reuse `style.css` tokens/codicons; keep markup minimal.

### Task 10: The launcher editor tab

**Files:** Create `vscode/src/stressLauncher.ts`, `vscode/src/webview/launcherMain.ts`, `vscode/src/webview/launcherRender.ts` (+ test for pure render/state helpers), `vscode/src/webview/launcherStyle.css`; Modify `esbuild.mjs`.

- One panel (`createWebviewPanel`, reveal if open). Opened blank (`New stress`), or pre-filled from a declared stress (`Edit`): if `recognizeFinder` fails, show the finder as a read-only chip with `Replace with rows`.
- Sections: Inputs (Declared / Generator / Fuzz; generator text input with a `<datalist>` of generator names and insert buttons `@`, `[1..10]`, `<var>`), Find (rows + All of/Any of + Slowest checkbox), Budget (timeout, findings, TL mode, Advanced: sanitized, skip invalid, validate, reference solution select).
- Footer: live `rbx …` preview (`stressArgv`), validation message, Run / Copy. Run posts the launch to the host, which dispatches `stress` with `stressArgv` and focuses the Stress view.
- Persist the last launch in `context.workspaceState` (`rbx.stress.lastLaunch:<root>`).

### Task 11: Open and compare findings

**Files:** Modify `vscode/src/stressView.ts` (or a small `vscode/src/stressCommands.ts`).

- Open: `findingInputPath` and each solution's `.out` via `artifactUri(real, label)` (read-only `rbx:` scheme) in a column layout like `testcasePanes.ts` (reuse it if its API accepts arbitrary input/output paths; else open with `vscode.window.showTextDocument` beside). Stderr through a QuickPick when non-empty.
- Compare: QuickPick two solutions -> `vscode.diff`.
- Copy: `gen args` to clipboard.

### Task 12: Promote

**Files:** Create `vscode/src/proposedFs.ts`, `vscode/src/stressPromote.ts`; Modify `package.json` (commands `rbx.proposal.accept` / `rbx.proposal.discard` in `editor/title` when `resourceScheme == rbx-proposed`), `extension.ts`.

- Groups: run `rbx testcases add-finding --list-groups --json` headless via `rbxProcess.ts` (read-only, like `rbx vars --json`); QuickPick with separators "Script groups (adds the generator call)" / "Manual groups (copies the input)" + "New script group…" / "New manual group…".
- Script group: headless `add-finding K --group G --dry-run --json`; store `after` in an in-memory writable `FileSystemProvider` at `rbx-proposed:/<file>`; `vscode.diff(fileUri, proposedUri, 'Promote finding #K → G (edit the right side)')`. Accept: re-read the real file, refuse with a message if it differs from `before`, else write the proposed document's current text to the real file via `WorkspaceEdit` + save, close the diff. Discard: close it.
- Manual group, new script, new manual: dispatch `add-finding` with the args in the terminal (new names via `showInputBox`).
- Record `{sessionStartedAt, k} -> group` in memory so the view shows the badge.

### Task 13: Docs, changelog, PR

- `vscode/CHANGELOG.md` + `vscode/README.md` feature list.
- `docs/setters/stress-testing.md`: a short section on `rbx testcases add-finding` and `--no-promote` (use the `docs-style` skill).
- Push the branch, open a draft PR closing #908.
