# On-demand visualizers in the VS Code extension

Date: 2026-08-24
Status: implemented

## Goal

Bring `rbx ui`'s `v` and `V` -- run a visualizer for *this* testcase, now --
into the VS Code extension, for both testset inputs and **solution outputs**.

The solution-output half is the one that matters. `rbx build --visualize`
already visualizes every testset input and expected answer eagerly, and the
testset panel already renders what it wrote. What nothing covers is a
*solution's* output: it lives per-solution under
`.rbx/runs/<i>/<group>/<stem>.out`, it is produced by `rbx run`, and no build
flag reaches it. Today the only way to see one is to launch the TUI.

| Trigger | Visualizer | Inputs | Artifact |
|---|---|---|---|
| Testset view, a testcase | input visualizer | `<build>/tests/<g>/<stem>.in` (+ `.out`) | `<build>/tests/<g>/visualization/<stem>.<ext>` |
| Run view, a (solution, testcase) | solution visualizer | `.in`, solution `.out`, expected `.out` | `<build>/visualizations/runs/<i>/<g>/<stem>.<ext>` (D7) |

Behaviour matches the TUI: `-i` is passed, exit 42 means "ran interactively,
produced no file", and the run is wrapped in `CacheLevel.CACHE_COMPILATION` so
compilation is cached but the visualizer itself always re-runs.

## D1. The extension may invoke rbx

This is the first time the extension spawns anything, and it reverses D2/D3 of
[the v1 design](2026-08-11-vscode-extension-design.md). That reversal is
deliberate and narrow.

The original rationale was that "every rbx invocation has side effects ... could
corrupt or race a concurrently running rbx". That is no longer accurate, and
`rbx/box/CLAUDE.md` now says so directly:

- **Concurrency is supported.** Every cache directory carries a reader/writer
  lock (`session.lock`), taken in *shared* mode by `get_problem_cache_dir()` and
  held until the process exits. "Any number of rbx processes may use the same
  cache at once."
- **Nothing is destroyed.** Emptying a cache goes through `clear_cache_dir()`,
  which takes that lock *exclusively* and so waits for -- or refuses, with
  `CacheBusyError` -- the processes still using it. And it empties in place via
  `wipe_cache_dir()`; `rmtree` on a cache directory is explicitly banned.

So a spawned rbx cannot corrupt a run in flight. The narrowed doctrine:

> The extension does not drive the build. It may invoke rbx for a read-only,
> idempotent, per-testcase artifact the user explicitly asked for.

`rbx build`, `rbx run` and a "Build" button remain out, unchanged.

### The residual risk, and the guard

One real hazard survives, and it is not corruption. An rbx whose
`CACHE_STEP_VERSION` differs from the one that built the package will
*legitimately* clear the cache -- by design -- forcing a full rebuild. Triggered
by a click the user believed was read-only, that is a nasty surprise.

`.rbx/fingerprint` is a plain text file holding exactly that number. So the
command compares its own fingerprint against the package's **before doing
anything**, and on mismatch refuses rather than clearing (D3, exit 3).

The guard lives in Python, not in the extension, so it cannot be bypassed and so
it protects a hand-typed invocation too.

**It has to live in the root app callback, not in the sub-command.** The
clear-on-mismatch happens in `cli.main()`, which Typer runs *before* any
sub-command -- so the first implementation of this guard, inside
`rbx/box/visualization.py`, never fired: by the time it ran, the cache and the
build tree were already gone. It is `cli._refuse_incompatible_cache`, reached
through `cli._is_readonly_command`, and `visualization.py` only owns the exit
code. Caught by running it, not by reading it.

## D2. `rbx visualize`, addressed by explicit paths

```
rbx visualize input  --input <path> [--output <path>] [--use-stderr]
rbx visualize output --input <path> --output <path> [--answer <path>] [--use-stderr]
```

Two subcommands, because the TUI's two paths differ in both *which* visualizer
is selected and *where* the artifact lands. Expressing that in the CLI grammar
makes the required arguments differ correctly (`output` needs `--output`; `input`
does not) and keeps each help text honest.

**Paths, not logical ids.** rbx resolves nothing, which is what lets one command
serve the testset view, the run view, and anything else -- a run artifact, a
built answer, a scratch file. It is also exactly what the TUI does today:
`run_test_explorer.py` builds `Testcase(inputPath=..., outputPath=...)` from
whatever the widget is showing, never from a group/index.

The cost is that rbx cannot know which *group* a path came from, which matters
for D4.

### Why `--use-stderr` is a shorthand, not the mechanism

`use_stderr` in `run_ui_solution_visualizer_for_testcase` is not a property of a
visualizer -- the declared property is `Visualizer.answer_from`, which may be
`'stderr'` or a program. `use_stderr` is a call-site override forcing
`answer_from = 'stderr'`, which `run_visualizer` turns into
`ref_path.with_suffix('.err')`.

That substitution is wrong on the task type where stderr visualization is most
useful: a **communication** task writes the solution's stderr to
`<stem>.sol.err`, and `<stem>.err` is the *interactor's*.

Explicit paths dissolve the problem. "Visualize the stderr" becomes "pass the
`.err` file as `--output`": it mounts to the same `output.txt` and occupies the
same argv position, so it is behaviourally identical, with no suffix guessing.
The extension already models this as `Channel = 'out' | 'err' | 'log'` and so
passes the right file for both task types.

`--use-stderr` is kept as a documented shorthand for hand-typed use. The
extension never sends it.

## D3. Protocol: exit codes and one line of stdout

| Exit | Meaning | stdout |
|---|---|---|
| 0 | artifact produced | absolute path |
| 42 | interactive, produced no file | empty |
| 3 | cache-format skew; refused, nothing touched | empty |
| 1 | failure | empty; rich message on stderr |

No `--json`. The caller needs exactly one datum, there is no JSON output
anywhere in the rbx CLI today, and adding `--json` later breaks nothing.

42 is `visualizers.SPECIAL_CODE` promoted to the command's own exit code, so the
visualizer's contract and the command's contract are the same number.

## D4. All four visualizers, reachable

Visualizers are declared at two levels, not one:

| Level | Fields |
|---|---|
| `Package` (`schema.py:1331,1336`) | `visualizer`, `solutionVisualizer` |
| `TestcaseGroup` | inherited from `TestcaseSubgroup` |
| `TestcaseSubgroup` (`schema.py:567,573`) | `visualizer`, `solutionVisualizer` -- *"has priority over the visualizer specified in the package"* |

Three levels, not two: `TestcaseGroup` extends `TestcaseSubgroup`, so a group
declares the same fields. `testcase_extractors.py:368-374` folds the whole chain
into each entry, innermost winning.

**The TUI reaches only the two package-level ones.** `run_ui_*_visualizer_for_testcase`
reads `pkg.visualizer` directly, so a subgroup that declares its own visualizer
is silently visualized with the wrong one from `rbx ui` -- while
`rbx build --visualize`, which goes through `GenerationTestcaseEntry.visualizer`,
gets it right. That is a pre-existing bug, not one this design introduces.

Explicit-path addressing can still resolve it: `entry.metadata.copied_to.inputPath`
*is* the built input path, so the command matches `--input` back to its
generation entry and uses `entry.visualizer or pkg.visualizer`, falling back to
package level when no entry matches (a scratch input).

The TUI is routed through the same resolution, fixing its gap in one place:
`resolve_visualizers_for_input` in `visualizers.py` is what both call.

Verified end to end on a two-group package: the group declaring its own
visualizer got it, the group that did not got the package's.

## D5. Locating `rbx`

Resolved per **package root**, cached per package root, and validated before
being cached.

1. `rbx.executable` setting (`resource`-scoped, so it can be set per folder)
2. `rbx` on the extension host's inherited `PATH`
3. `$SHELL -lic 'command -v rbx'`, run with `cwd` set to the package root

Step 2 is a fast path, not a commitment: a candidate is cached only once it has
validated (see below). A stale binary therefore falls through to step 3 instead
of being locked in.

**Why step 3 exists.** The extension host's `PATH` is inherited from whatever
launched VS Code. Launched via `code .` it is the user's shell `PATH`; launched
from Dock, Finder or Spotlight on macOS it is a minimal
`/usr/bin:/bin:/usr/sbin:/sbin` that does **not** contain `~/.local/bin` -- where
both `uv tool install` and `pipx` put rbx, and which
[`docs/intro/installation.md`](../intro/installation.md) recommends. Without
step 3 the feature works or fails depending on how the editor was opened.

Note that the Python extension's virtualenv activation does not help here: it
injects environment into *terminal* creation and has no effect on
`child_process.spawn` from an extension host.

**Why per package, with `cwd`.** Different packages may resolve different rbx
installs -- direnv, mise, a project-local `.venv`, a dev checkout. Resolving in
the package root makes each get its own, and a session-global cache would
otherwise pin whichever package was visualized first. The extension already
keys everything by package root (`packageRootOf`, `data.invalidate(root)`).

**Validation** is exit code 3: it is cheap, authoritative, and turns "silently
rebuilt your whole package" into a dismissable warning naming `rbx.executable`.

## D6. Extension surface

Two commands, `rbx.visualizeTest` and `rbx.visualizeSolutionOutput`, contributed
to the existing `webview/context` menus for `webviewSection` `rbx.testsetTestcase`
and `rbx.testcase`.

Wrapped in `withProgress` (Notification scope). One in-flight run per package
root; a second request supersedes the first, so holding a key down cannot fan
out into a queue of sandboxed compilations.

On exit 0 the returned path goes straight to the existing `openVisualization()`,
so HTML lands in `VisualizationPanel` and SVG/PNG in the native preview --
unchanged, and already correct since visualizations became real files rather
than symlinks ([design](2026-08-24-visualization-symlink-design.md)).

Exit 42 is silent: it is success.

## D7. Where the artifact lands, and why the watcher never sees it

Left to itself, `run_solution_visualizer_for_testcase` writes beside the output
it visualizes -- so a solution's output visualization would land in
`.rbx/runs/<i>/<g>/output_visualization/`. That is inside the cache directory,
which the extension watches with `**/.rbx/**` to follow a run live. **Every
visualize click would invalidate the run view** and redraw the tree for an
artifact that carries no verdict, no timing and no progress.

So the command grows `--dest`, a destination *stem* (the visualizer owns the
extension, and the final path comes back on stdout), and the extension passes
one under the build directory:

```
<build>/visualizations/runs/<solutionIndex>/<group>/<stem>.<ext>
```

Nothing watches the build tree except `**/testset.yml`, so this costs **zero
watcher events** rather than events that then have to be filtered out -- which
is why it beats the obvious alternative of teaching the watcher to ignore
`output_visualization/**`. It is also why input visualizations cause no churn
today: they already live there.

The solution index is in the path because two solutions have different outputs
for the same testcase and would otherwise overwrite each other.

The watcher filter is kept anyway, as cheap insurance for a *hand-typed*
`rbx visualize output`, which has no `--dest` and does land in the cache.

### Two fixes this uncovers

Not optional -- the first blocks the feature outright.

1. **`localResourceRoots` hardcodes `'build'`** in `visualizationPanel.ts:111`
   and `testsetPanel.ts:174`, while everywhere else the build directory comes
   from `resolveBuildDir()`. Any preset renaming `buildDir` already breaks the
   gallery today; putting artifacts under the build directory makes it
   load-bearing. Both now resolve through `buildPath(packageLayout(root))`.

   Note that keeping artifacts out of `.rbx/` also means the resource root does
   **not** need widening into the cache directory, which an earlier draft of
   this design called for. Narrower, not wider.

2. **The `.rbx` watcher ignores visualization directories**, per above.

## D8. Errors

The first real error surface in the extension, which today has zero
`showErrorMessage` call sites.

`showErrorMessage` with a **Show Output** action revealing rbx's stderr in the
existing `log.ts` channel -- a compile failure is multi-line and does not fit a
toast. A missing rbx gets an actionable message naming `rbx.executable`.

This deliberately does not reuse the Problems panel: a visualization failure is
tied to a user gesture, not to a file.

## D9. Testing

Follows the existing split -- no test may import `vscode`.

- `src/rbx/visualizeRun.ts` (argv, exit codes, stdout parsing, destinations) and
  `src/rbx/executable.ts` (the resolution ladder), pure, under `node --test`.
  The stdout parser is pinned against the **real bytes** rbx emits --
  `<path>\n\x1b[?25h ` -- because rbx restores the cursor as it exits even when
  nothing rendered a spinner, and a parser that trusted "stdout is the path"
  hands the panel a filename with an escape glued to it.
- The spawn wrapper (`src/visualize.ts`) stays thin and untested.
- Python: `resolve_visualizers_for_input` in `tests/rbx/box/test_visualizers.py`,
  covering the override, the no-entry fallback and the separate solution
  visualizer.

## Non-goals

- No build or run buttons. D3 of the v1 design stands for everything else.
- No batch "visualize all" -- that is `rbx build --visualize`.
- No `--json`.
- Widening `_maybe_check_integrity` to copied artifacts stays out, as it did in
  the symlink design.
