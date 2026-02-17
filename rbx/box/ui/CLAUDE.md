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
           |        |-- [g] -> RichLogModal (testcase metadata)
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
| `RichLogModal` | `rich_log_modal.py` | Modal popup for rich markup text |
| `ErrorScreen` | `error.py` | Simple error display |

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

## Core Dependencies

- `rbx.box.solutions` -- `SolutionReportSkeleton`, `SolutionSkeleton`, verdict formatting
- `rbx.box.testcase_extractors` -- `extract_generation_testcases_from_groups()`
- `rbx.box.testcase_utils` -- `parse_interaction()` for communication tasks
- `rbx.box.visualizers` -- input/output visualizer launching
- `rbx.box.remote` -- `expand_files()`, and `start_review()` is called FROM remote
- `rbx.grading.steps` -- `Evaluation` data model

Also reused by `rbx/box/tooling/boca/ui/app.py` which imports `CodeBox` and `DiffBox`.
