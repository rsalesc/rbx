# UI Module (`rbx/box/ui/`)

Textual-based TUI for exploring test cases and run results.

## Architecture

Three Textual `App` classes in `main.py`:
- **`rbxApp`** -- Main UI launched by `rbx ui`. Shows a menu to explore tests or past run results.
- **`rbxDifferApp`** -- Standalone diff viewer launched by hidden `rbx diff` command.
- **`rbxReviewApp`** (in `review_app.py`) -- Confirmation dialog for remote file expansion (`remote.py`). Returns `app.confirmed` bool synchronously.

## Screen Navigation

```
rbxApp (main menu: OptionList)
  |-- [1] TestExplorerScreen -- browse built testcases
  |        |-- (select testcase) -> updates FileLog + TestBoxWidget inline
  |        |-- [v] -> opens external visualizer
  |
  |-- [2] RunExplorerScreen -- browse past `rbx run` results
           |-- (select solution) -> RunTestExplorerScreen
           |        |-- (select testcase) -> updates FileLog + TwoSidedTestBoxWidget
           |        |-- [s] -> toggle side-by-side comparison
           |        |-- [m] -> toggle docked testcase-metadata footer
           |        |-- [r] -> toggle run/eval metadata box
           |        |-- [v/V] -> input/output visualizer
           |
           |-- [s] "Compare with" -> SelectorScreen (modal) -> side-by-side mode
```

## Key Screens (`screens/`)

| Screen | File | Purpose |
|--------|------|---------|
| `CommandScreen` | `command.py` | Runs a shell command, shows output in `LogDisplay` |
| `BuildScreen` | `build.py` | Subclass of `CommandScreen` running `rbx build` |
| `RunScreen` | `run.py` | Solution/testgroup selection UI + runs `rbx run` |
| `SolutionReportScreen` | `run.py` | DataTable grid showing verdicts per solution |
| `TestExplorerScreen` | `test_explorer.py` | Browse testcases built by `rbx build` |
| `RunExplorerScreen` | `run_explorer.py` | Browse past run results, select solutions |
| `RunTestExplorerScreen` | `run_test_explorer.py` | Deep-dive into testcase results (most complex screen, 227 lines) |
| `DifferScreen` | `differ.py` | Side-by-side file diff |
| `ReviewScreen` | `review.py` | Code review confirm/reject (y/n keybindings) |
| `SelectorScreen` | `selector.py` | Generic modal list selector, returns index |
| `ErrorScreen` | `error.py` | Simple full-screen text display (used for empty-states like "No runs found") |
| `ErrorModal` | `error_modal.py` | Dismissible, scrollable modal showing a formatted `RbxException` (compile/runtime output); opened via `rbxBaseApp.show_error`. `q`/`esc` close |

## Key Widgets (`widgets/`)

| Widget | File | Purpose |
|--------|------|---------|
| `TestBoxWidget` | `test_output_box.py` | Multi-tab viewer (output/stderr/log/interaction/metadata) using `ContentSwitcher` |
| `TwoSidedTestBoxWidget` | `two_sided_test_output_box.py` | Two `TestBoxWidget`s side-by-side for comparison |
| `FileLog` | `file_log.py` | Async file content viewer using `aiofiles`, reads in 1024-line batches |
| `CodeBox` | `code_box.py` | Syntax-highlighted code viewer via Rich Markdown. Auto-detects language from extension or sidecar `.json` metadata |
| `DiffBox` | `diff_box.py` | Computes unified diff via `difflib.ndiff()` |
| `InteractionBox` | `interaction_box.py` | Parses pipe-based interaction data for communication tasks via `testcase_utils.parse_interaction()` |
| `RichLogBox` | `rich_log_box.py` | Unfocusable `RichLog` wrapper |

## Terminal Emulator (`captured_log.py`)

`LogDisplay(ScrollView)` -- a full terminal emulator using **pyte**. Used by `CommandScreen` to capture and render output from shell commands (`rbx build`, `rbx run`).

Key internals:
- Uses `pty.fork()` to create a pseudo-terminal
- `capture(argv)` forks a child process and sets up PTY communication
- Converts pyte character attributes to `rich.Segment` objects for rendering
- `export()`/`load()` for serializing terminal state as `LogDisplayState`

## Data Loading (`utils/run_ui.py`)

Helper functions that load run results from disk:
- `has_run()` / `get_skeleton()` -- check for and load `skeleton.yml`
- `get_solution_eval()` / `get_solution_evals()` -- load `.eval` YAML files
- `get_solution_markup()` / `get_run_testcase_markup()` -- generate Rich markup for display

## Important Patterns

- **The UI shells out to CLI** -- `BuildScreen` runs `['rbx', 'build']` and `RunScreen` runs `['rbx', 'run']` via `LogDisplay.capture()`. It does NOT call build/run logic in-process.
- **Reactives with `recompose=True`** -- `RunExplorerScreen.skeleton` rebuilds the entire compose tree on change.
- **`@work(exclusive=True)`** -- `FileLog` and `InteractionBox` use this for cancellable async file loading.
- **`self.watch(widget, 'index', callback)`** -- Test explorer screens watch `ListView.index` to react to selection changes.
- **CSS** in `css/app.tcss` uses Textual's TCSS syntax with `$`-prefixed theme variables.
- **Surfacing exceptions** -- `rbxBaseApp.show_error(exc)` (`main.py`) pushes an `ErrorModal` rendering `exc.from_ansi()` (formatting preserved, scrollable, not truncated). Use it instead of `notify(e.plain(), severity='error')` for `RbxException`s that may carry long output; the visualizer actions in `test_explorer.py`/`run_test_explorer.py` do (#380). Short one-line validation messages ("No test selected") stay toasts. Screens call it as `self.app.show_error(e)  # type: ignore[attr-defined]`.
- **YAML/config error safety net** -- `rbxBaseApp._handle_exception` (`main.py`) intercepts `RbxException` (e.g. invalid `problem.rbx.yml`/`env.rbx.yml` from `load_yaml_model`): if the app is running it shows the error via `show_error` (ErrorModal) and keeps the TUI alive; otherwise it exits cleanly via `exit(return_code=1, message=exc.from_ansi())` (no Rich traceback, not re-raised, so the top-level CLI handler in `rbx/box/main.py` can't double-print). This recovers screen-entry crashes (`compose`/`on_mount` of a pushed screen — e.g. `RunScreen.compose`, `TestExplorerScreen.on_mount`). The explorer screens need no per-call guard: their loads run at mount and `find_problem_package` is `@functools.cache`d (later action loads hit the cache; a failed first load re-parses on retry since exceptions aren't cached). Loads whose *first* execution is in an action/watcher body cannot recover from `_handle_exception` (verified: the app goes half-dead), so they catch `RbxException` at the call site and call `self.app.show_error(e)` directly — currently only `limits_editor._load_profile_detail_from`.

## Keybindings

Vim navigation lives in `vim_nav.py` (`VimNavMixin`, mixed into `rbxBaseApp` in `main.py`, ahead of `App` in the MRO). It registers app-level `h/j/k/l` bindings that dispatch to the focused widget's existing `cursor_*` action, falling back to `scroll_*`: `j`/`k` move down/up everywhere; `h`/`l` move left/right only where horizontal movement exists (e.g. `DataTable` cells, scroll viewers). `check_action` disables the keys while an `Input`/`TextArea` is focused, so typing is never hijacked. The mixin subclasses `DOMNode` so Textual merges its `BINDINGS`.

The help panel lives in `help_panel.py` (`HelpPanelMixin`, also a `DOMNode` subclass, mixed into `rbxBaseApp` in `main.py` alongside `VimNavMixin`). `?` (`question_mark`) toggles `RbxHelpPanel` via `action_toggle_help_panel`, which mounts the panel on the active screen or removes it if already present. `RbxHelpPanel` is a thin `KeyPanel` subclass whose `_TitledBindingsTable` renders only binding groups that declare a `BINDING_GROUP_TITLE` — so the obvious built-in navigation Textual's stock panel would dump (the focused widget's arrow/page keys, the screen's tab/copy) is filtered out, leaving just our titled sections. `check_action` disables `?` while an `Input`/`TextArea` is focused, so it types literally. Primary screens keep `q` visible (a plain tuple) but set their other feature bindings to `Binding(..., show=False)`, so the footer stays slim (`? Help` + `q`) while the panel lists every active binding in that section (including the hidden vim `h/j/k/l`, which live under the app-level `Global` title set on `rbxBaseApp`). Each screen sets `BINDING_GROUP_TITLE` for a readable section header; a screen without one contributes nothing to the panel. Transient modals are intentionally left untouched. `rbxCommandApp` keeps its bespoke `HelpModal` and hides the inherited `?` footer entry (`show=False`) until #483 unifies them.

## Core Dependencies

- `rbx.box.solutions` -- `SolutionReportSkeleton`, `SolutionSkeleton`, verdict formatting
- `rbx.box.testcase_extractors` -- `extract_generation_testcases_from_groups()`
- `rbx.box.testcase_utils` -- `parse_interaction()` for communication tasks
- `rbx.box.visualizers` -- input/output visualizer launching
- `rbx.box.remote` -- `expand_files()`, and `start_review()` is called FROM remote
- `rbx.grading.steps` -- `Evaluation` data model

Also reused by `rbx/box/tooling/boca/ui/app.py` which imports `CodeBox` and `DiffBox`.
