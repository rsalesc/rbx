# Design: Surface compilation warnings in Compilation LiveTasks (#397)

## Problem

When `rbx` compiles solutions or generators, the live progress display
(`LiveTasks` of `CompilationTask`) shows `SUCCESS` for a compilable even when the
compiler emitted warnings. There is no way to tell, from the live view, that a
file compiled with warnings. The issue asks for a `WARNINGS` status to be shown
instead of `SUCCESS` in that case.

## Background: how Compilation LiveTasks work today

- `rbx/box/parallel/live_tasks.py` defines the display layer. `LiveTasks` wraps a
  `rich.live.Live`; callers `append()` `LiveTask` objects and call `update()`.
  Each task's `render()` returns a `TaskRenderable` (columns + optional panel),
  laid out by `TaskGrid`.
- `CompilationTask(LiveTask)` holds a `CodeItem`, a `CompilationStatus`, and an
  optional `exception`. `render()` returns `None` when status is `PENDING` or
  `SUCCESS` (so finished-OK rows disappear), otherwise renders
  `Compiling <href>...` plus the status markup, plus a cropped error panel if
  there is an exception. `is_finished()` is true unless `PENDING`/`RUNNING`.
- `CompilationStatus` **already has a `WARNINGS` member** with markup
  `[warning]WARNINGS[/warning]` — it was stubbed but is never set anywhere.
- Producers of compilation LiveTasks:
  - `rbx/box/solutions.py::compile_solutions()` builds a `LiveTasks` of
    `SolutionCompilationTask`, submits `compile_item` per solution through an
    `AsyncStreamer`. Streamer callbacks set status: `scheduled→RUNNING`,
    `succeeded→SUCCESS`, `failed→SKIPPED` (or `FAILED` when it should hard-fail).
  - `rbx/box/generators.py::GeneratorCompilationTask` follows the same pattern.
  - These two are the **only** LiveTasks consumers of compilation. Checker /
    validator / interactor / visualizer also call `compile_item` but not via
    LiveTasks — out of scope here.
- `rbx/box/code.py::compile_item()` already detects warnings: after
  `steps_with_caching.compile`, it inspects `artifacts.logs.preprocess[].warnings`
  (set by `steps.py::_check_for_compilation_warnings()`, which greps compiler
  stderr for warning lines). When `cfg.warnings.enabled or force_warnings` and any
  preprocess log has warnings, it calls
  `warning_stack.get_warning_stack().add_warning(code)`. That stack feeds the
  end-of-run `print_warning_stack_report()`.
- `compile_item` returns only the compiled digest (`str`); callers learn nothing
  about warnings. It has ~12 call sites, so changing the return type is invasive.
- The async executor used by the streamers is a `ThreadPoolExecutor` (same
  process), so module-level state (`@functools.cache`, `WarningStack`) is shared
  with the streamer callbacks — no process-boundary concerns.

## Decisions

- **Trigger**: show `WARNINGS` only when warning tracking is on
  (`cfg.warnings.enabled` or `force_warnings`) — the same gate that feeds the
  existing warning-stack report. This keeps the live view and the report
  consistent.
- **Detail shown**: the row shows `WARNINGS`, optionally followed by a short line
  produced by a **pluggable, language-keyed summarizer**. The base summarizer
  returns `None` (nothing extra shown for now). A C++ summarizer is deferred to a
  separate issue (to be brainstormed: extracting concise lines from GCC/clang
  output).
- **Scope**: solutions + generators compilation LiveTasks only.
- **Summarizer location**: its own module — `rbx/box/sanitizers/compilation_warnings.py`
  (co-located with `warning_stack.py`, which already handles compilation- and
  sanitizer-warning bookkeeping). Not in `live_tasks.py`.

## Changes

1. **`rbx/box/sanitizers/warning_stack.py`** — also stash the compiler logs that
   triggered each warning:
   - Add `warning_logs: Dict[pathlib.Path, List[PreprocessLog]]` to `WarningStack`.
   - `add_warning(code, logs: Optional[List[PreprocessLog]] = None)` stores the
     subset of preprocess logs with `.warnings == True`.
   - `clear()` clears `warning_logs` too.
   - Import `PreprocessLog` from `rbx.grading.steps`.

2. **`rbx/box/code.py::compile_item()`** — at the existing warning-detection site,
   pass the warning-bearing preprocess logs into `add_warning(code, logs=...)`. No
   signature/return-type change; all existing callers untouched.

3. **`rbx/box/sanitizers/compilation_warnings.py`** (new):
   ```python
   class CompilationWarningSummarizer:
       """Given the compiler logs that produced warnings, return a short line
       to show next to 'WARNINGS' in the live view, or None."""

       def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
           return None

   _DEFAULT_SUMMARIZER = CompilationWarningSummarizer()
   # Per-language summarizers register here. C++ summarizer is deferred to a
   # separate issue (extracting concise lines from GCC/clang output).
   _SUMMARIZERS: Dict[str, CompilationWarningSummarizer] = {}

   def get_compilation_warning_summarizer(language: str) -> CompilationWarningSummarizer:
       return _SUMMARIZERS.get(language, _DEFAULT_SUMMARIZER)
   ```

4. **`rbx/box/parallel/live_tasks.py::CompilationTask`** — add
   `warning_summary: Optional[str] = None`. In `render()`, when `status ==
   WARNINGS` and `warning_summary` is set, append ` ({warning_summary})` (warning
   style) to the status text. `CompilationStatus.markup()` is unchanged.

5. **Streamer callbacks** — `solutions.py::SolutionCompilationStreamer.succeeded`
   and the equivalent in `generators.py`:
   - After a successful compile, if `code.path in
     warning_stack.get_warning_stack().warnings`:
     - `key.status = CompilationStatus.WARNINGS`
     - `language = find_language_name(key.item)`
     - `logs = warning_stack.get_warning_stack().warning_logs.get(code.path, [])`
     - `key.warning_summary = get_compilation_warning_summarizer(language).summarize(logs)`
   - Otherwise `key.status = CompilationStatus.SUCCESS` as before.
   - `SolutionCompilationTask.render()`'s existing `SKIPPED` override is kept;
     `WARNINGS` flows through the base `render()`.

6. **Follow-up issue** — file a new GitHub issue: "Implement C++ compilation-warning
   summarizer — extract concise lines from GCC/clang output", and reference it in a
   comment near `_SUMMARIZERS` / `_DEFAULT_SUMMARIZER`.

## Data flow

`compile_item` → `steps_with_caching.compile` populates
`artifacts.logs.preprocess[].warnings` → if tracking on,
`WarningStack.add_warning(code, logs)` → streamer `succeeded()` reads the stack →
sets task status `WARNINGS` + summary → `LiveTasks.update()` re-renders the row.

## Known limitation (out of scope)

If a compilation is served from the dependency cache, `artifacts.logs.preprocess`
may be absent, so warnings won't be re-detected on cached runs — pre-existing for
the warning-stack report too. A future option is to persist `has_warnings` (and a
summary) in `CompilationMetadata`. Not part of this change.

## Testing

- Add a fixture compilable that triggers a real compiler warning (e.g. an unused
  variable) and a setter config with `warnings.enabled: true`.
- `compile_solutions()` over that fixture → task status is `WARNINGS`. With
  `warnings.enabled: false` → `SUCCESS`.
- Same for the generator compilation path.
- `WarningStack.add_warning` records logs; `clear()` resets `warning_logs`.
- `CompilationWarningSummarizer` base returns `None`;
  `get_compilation_warning_summarizer("cpp")` returns the default for now.
- `CompilationTask.render()`: plain `WARNINGS` when `warning_summary is None`,
  `WARNINGS (...)` when set.
- Reuse `cleandir_with_testdata` / existing compilation fixtures; add a small
  `testdata/` compilable with an unused-variable warning if needed.
