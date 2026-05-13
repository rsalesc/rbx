# Compilation Warnings in LiveTasks — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show `WARNINGS` (instead of `SUCCESS`) for a solution/generator row in the compilation LiveTasks display when the compiler emitted warnings and warning tracking is enabled, with an optional pluggable language-specific summary line.

**Architecture:** `compile_item` already detects compiler warnings via `artifacts.logs.preprocess[].warnings` and records them in `WarningStack` when `cfg.warnings.enabled`. We (1) extend `WarningStack` to also keep the warning-bearing `PreprocessLog`s per path, (2) add a tiny pluggable `CompilationWarningSummarizer` registry in a new module, (3) add a `warning_summary` field to `CompilationTask` and render it next to `WARNINGS`, and (4) flip the streamer callbacks in `solutions.py`/`generators.py` to set `WARNINGS` + the summary when the path is in the warning stack. `compile_item`'s signature/return type does not change.

**Tech Stack:** Python 3, Pydantic v2, `rich`, pytest. Project commands: `uv run pytest ...`, `uv run ruff check . && uv run ruff format .`. Commits MUST follow conventional commits — use the `/commit` skill (`.claude/skills/commit.md`); every commit message ends with the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

**Reference docs to skim first:** `docs/plans/2026-05-12-compilation-warnings-livetasks-design.md`, `rbx/box/CLAUDE.md` (sections "Code Compilation", "Global State" — note the test-isolation rule for `@functools.cache`), `rbx/box/parallel/live_tasks.py`, `rbx/box/sanitizers/warning_stack.py`, `rbx/box/code.py` (around line 710).

---

## Task 1: Stash warning-bearing logs in `WarningStack`

**Files:**
- Modify: `rbx/box/sanitizers/warning_stack.py`
- Test: `tests/rbx/box/sanitizers/warning_stack_test.py` (create; check whether `tests/rbx/box/sanitizers/` already has test files and match the existing naming convention — `*_test.py` vs `test_*.py`)

**Context:** `WarningStack` currently holds `self.warnings: set` (paths of code items that compiled with warnings) and `self.sanitizer_warnings: dict`. `add_warning(self, code: CodeItem)` does `self.warnings.add(code.path)`. `clear()` clears both. We add a parallel dict mapping `code.path -> List[PreprocessLog]`.

**Step 1: Write the failing test**

```python
# tests/rbx/box/sanitizers/warning_stack_test.py
import pathlib

from rbx.box.schema import CodeItem
from rbx.box.sanitizers.warning_stack import WarningStack
from rbx.grading.steps import PreprocessLog


def _log(warnings: bool) -> PreprocessLog:
    return PreprocessLog(cmd=['g++', 'a.cpp'], log='some warning text', warnings=warnings)


def test_add_warning_records_path_and_logs(tmp_path: pathlib.Path):
    stack = WarningStack(tmp_path)
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')
    logs = [_log(True)]

    stack.add_warning(code, logs=logs)

    assert code.path in stack.warnings
    assert stack.warning_logs[code.path] == logs


def test_add_warning_without_logs_still_records_path(tmp_path: pathlib.Path):
    stack = WarningStack(tmp_path)
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')

    stack.add_warning(code)

    assert code.path in stack.warnings
    assert stack.warning_logs.get(code.path) in (None, [])


def test_clear_resets_warning_logs(tmp_path: pathlib.Path):
    stack = WarningStack(tmp_path)
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')
    stack.add_warning(code, logs=[_log(True)])

    stack.clear()

    assert not stack.warnings
    assert not stack.warning_logs
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/sanitizers/warning_stack_test.py -v`
Expected: FAIL — `WarningStack` has no `warning_logs` attribute / `add_warning()` got an unexpected keyword argument `logs`.

**Step 3: Implement**

In `rbx/box/sanitizers/warning_stack.py`:
- Add import: `from typing import Dict, List, Optional` (merge with existing imports) and `from rbx.grading.steps import GradingFileOutput, PreprocessLog` (extend the existing `from rbx.grading.steps import GradingFileOutput`).
- In `__init__`: add `self.warning_logs: Dict[pathlib.Path, List[PreprocessLog]] = {}`.
- Change signature/body of `add_warning`:
  ```python
  def add_warning(
      self, code: CodeItem, logs: Optional[List[PreprocessLog]] = None
  ):
      self.warnings.add(code.path)
      if logs:
          self.warning_logs[code.path] = logs
  ```
- In `clear()`: add `self.warning_logs.clear()`.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/sanitizers/warning_stack_test.py -v`
Expected: PASS (3 tests).

Also run: `uv run ruff check rbx/box/sanitizers/warning_stack.py` — Expected: clean.

**Step 5: Commit** (use the `/commit` skill)

```
feat(sanitizers): stash warning logs in WarningStack
```

---

## Task 2: New `CompilationWarningSummarizer` module

**Files:**
- Create: `rbx/box/sanitizers/compilation_warnings.py`
- Test: `tests/rbx/box/sanitizers/compilation_warnings_test.py`

**Context:** A pluggable, language-keyed object that turns the warning-bearing `PreprocessLog`s into one short string shown next to `WARNINGS`. For now the base returns `None` and the registry is empty (so every language gets the base). A C++ implementation is intentionally deferred to a follow-up issue (see Task 6).

**Step 1: Write the failing test**

```python
# tests/rbx/box/sanitizers/compilation_warnings_test.py
from rbx.box.sanitizers.compilation_warnings import (
    CompilationWarningSummarizer,
    get_compilation_warning_summarizer,
)
from rbx.grading.steps import PreprocessLog


def _log() -> PreprocessLog:
    return PreprocessLog(cmd=['g++', 'a.cpp'], log='a.cpp:1:1: warning: x', warnings=True)


def test_base_summarizer_returns_none():
    assert CompilationWarningSummarizer().summarize([_log()]) is None


def test_get_summarizer_returns_base_for_unknown_language():
    summarizer = get_compilation_warning_summarizer('cpp')
    assert isinstance(summarizer, CompilationWarningSummarizer)
    assert summarizer.summarize([_log()]) is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/sanitizers/compilation_warnings_test.py -v`
Expected: FAIL — `ModuleNotFoundError: rbx.box.sanitizers.compilation_warnings`.

**Step 3: Implement**

```python
# rbx/box/sanitizers/compilation_warnings.py
from typing import Dict, List, Optional

from rbx.grading.steps import PreprocessLog


class CompilationWarningSummarizer:
    """Turns the compiler logs that produced warnings into a short, single-line
    summary to show next to the ``WARNINGS`` status in the compilation live view.

    The base implementation returns ``None`` (no extra line). Language-specific
    subclasses register themselves in ``_SUMMARIZERS``.
    """

    def summarize(self, logs: List[PreprocessLog]) -> Optional[str]:
        return None


_DEFAULT_SUMMARIZER = CompilationWarningSummarizer()

# Per-language summarizers register here, keyed by the language name returned by
# ``rbx.box.code.find_language_name``. A C++ summarizer that extracts concise
# lines from GCC/clang output is deferred to a separate issue (see the plan /
# the linked GitHub issue) and should be brainstormed before implementing.
_SUMMARIZERS: Dict[str, CompilationWarningSummarizer] = {}


def get_compilation_warning_summarizer(language: str) -> CompilationWarningSummarizer:
    return _SUMMARIZERS.get(language, _DEFAULT_SUMMARIZER)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/sanitizers/compilation_warnings_test.py -v` — Expected: PASS (2 tests).
Run: `uv run ruff check rbx/box/sanitizers/compilation_warnings.py` — Expected: clean.

**Step 5: Commit** (use the `/commit` skill)

```
feat(sanitizers): add pluggable compilation warning summarizer
```

---

## Task 3: Render `warning_summary` on `CompilationTask`

**Files:**
- Modify: `rbx/box/parallel/live_tasks.py` (`CompilationTask`, ~lines 155-187)
- Test: `tests/rbx/box/parallel/live_tasks_test.py` (create; if `tests/rbx/box/parallel/` does not exist, create it with an empty `__init__.py` only if sibling test dirs have one — check `tests/rbx/box/sanitizers/`)

**Context:** `CompilationTask` has fields `item`, `status`, `exception`. `render()` returns `None` for `PENDING`/`SUCCESS`, otherwise a `TaskRenderable` with `columns=[Text("Compiling <href>..."), Text(status.markup())]` plus an optional exception panel. `CompilationStatus.WARNINGS.markup()` is `'[warning]WARNINGS[/warning]'`. We add an optional `warning_summary` and, when present and status is `WARNINGS`, append ` (<summary>)` to the status column text.

**Step 1: Write the failing test**

```python
# tests/rbx/box/parallel/live_tasks_test.py
from rbx.box.parallel import live_tasks
from rbx.box.schema import CodeItem


def _task(status: live_tasks.CompilationStatus, summary=None) -> live_tasks.CompilationTask:
    task = live_tasks.CompilationTask(CodeItem(path='sols/a.cpp', language='cpp'))
    task.status = status
    task.warning_summary = summary
    return task


def test_success_renders_nothing():
    assert _task(live_tasks.CompilationStatus.SUCCESS).render() is None


def test_warnings_without_summary_shows_plain_label():
    rendered = _task(live_tasks.CompilationStatus.WARNINGS).render()
    assert rendered is not None
    assert rendered.columns[1].plain == 'WARNINGS'


def test_warnings_with_summary_appends_it():
    rendered = _task(
        live_tasks.CompilationStatus.WARNINGS, summary='3 warnings'
    ).render()
    assert rendered is not None
    assert rendered.columns[1].plain == 'WARNINGS (3 warnings)'


def test_warning_summary_ignored_when_not_warnings_status():
    rendered = _task(live_tasks.CompilationStatus.FAILED, summary='x').render()
    assert rendered is not None
    assert rendered.columns[1].plain == 'FAILED'
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/parallel/live_tasks_test.py -v`
Expected: FAIL — `CompilationTask` has no attribute `warning_summary` (and/or the summary assertion fails).

**Step 3: Implement**

In `rbx/box/parallel/live_tasks.py`, `CompilationTask`:
- Add class attribute `warning_summary: Optional[str] = None` next to `exception`.
- In `render()`, build the status column with the optional suffix:
  ```python
  status_text = Text.from_markup(self.status.markup())
  if self.status is CompilationStatus.WARNINGS and self.warning_summary:
      status_text.append(f' ({self.warning_summary})', style='warning')
  return TaskRenderable(
      columns=[
          Text.from_markup(f'[info]Compiling {self.item.href()}...[/info]'),
          status_text,
      ],
      panel=...,  # unchanged
  )
  ```
  (`Text` is already imported in this module.)

Note: `SolutionCompilationTask.render()` in `solutions.py` calls `super().render()` then, only for `SKIPPED`, replaces `columns[1]`. Leave that as-is — `WARNINGS` flows through unchanged.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/parallel/live_tasks_test.py -v` — Expected: PASS (4 tests).
Run: `uv run ruff check rbx/box/parallel/live_tasks.py` — Expected: clean.

**Step 5: Commit** (use the `/commit` skill)

```
feat(parallel): render compilation warning summary in LiveTasks
```

---

## Task 4: `compile_item` passes warning logs to the stack

**Files:**
- Modify: `rbx/box/code.py` (the "Write compiler warnings." block, ~lines 710-719)
- Test: `tests/rbx/box/code_compile_test.py` (add a test to the existing `TestCompileItem` class, or a new test module if cleaner)

**Context:** Today:
```python
# Write compiler warnings.
cfg = setter_config.get_setter_config()
if (
    (cfg.warnings.enabled or force_warnings)
    and artifacts.logs is not None
    and artifacts.logs.preprocess is not None
):
    any_warning = any(log.warnings for log in artifacts.logs.preprocess)
    if any_warning:
        warning_stack.get_warning_stack().add_warning(code)
```
We change the last two lines to also forward the warning-bearing logs.

**Step 1: Write the failing test**

The existing `TestCompileItem` mocks `rbx.box.code.steps_with_caching.compile`. Add a variant that also populates `artifacts.logs.preprocess`, force warnings on, and assert the stack got the logs. Sketch:

```python
async def test_compile_records_warning_logs_when_warnings_enabled(
    self, testing_pkg, monkeypatch
):
    from rbx.box import setter_config
    from rbx.box.sanitizers import warning_stack
    from rbx.grading import steps
    from rbx.grading.steps import GradingLogsHolder, PreprocessLog

    cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
    code_item = CodeItem(path=cpp_file, language='cpp')

    warning_log = PreprocessLog(
        cmd=['g++', 'solution.cpp'],
        log='solution.cpp:1:1: warning: unused variable',
        warnings=True,
    )

    async def compile_side_effect(commands, params, artifacts, sandbox, dependency_cache):
        for output in artifacts.outputs:
            if output.digest is not None:
                output.digest.value = await package.get_file_cacher().put_file_content(b'x')
        artifacts.logs = GradingLogsHolder(preprocess=[warning_log])
        return True

    monkeypatch.setattr('rbx.box.code.steps_with_caching.compile', mock.AsyncMock(side_effect=compile_side_effect))
    # Ensure warnings tracking is on regardless of repo setter config.
    cfg = setter_config.get_setter_config()
    monkeypatch.setattr(cfg.warnings, 'enabled', True)

    warning_stack.get_warning_stack().clear()
    await code.compile_item(code_item)

    stack = warning_stack.get_warning_stack()
    assert code_item.path in stack.warnings
    assert stack.warning_logs[code_item.path] == [warning_log]
```

Notes for the implementer:
- `simple.cpp` already exists under the testdata used by `code_compile_test.py` (it's referenced as `compile_test/simple.cpp`); reuse it. We do NOT need it to actually emit a warning — the mock injects the warning log.
- The autouse `mock_steps_with_caching` fixture in `TestCompileItem` already patches `compile`; you can instead override `artifacts.logs` inside that fixture's side effect for this test, or put this test outside `TestCompileItem` with its own mock. Pick whichever is least disruptive; don't fight the existing fixtures.
- `mock_precompile_header` autouse fixture handles `_precompile_header`.
- The `_isolate_global_state` autouse fixture clears `@functools.cache`d state between tests, so the warning stack starts empty — the explicit `.clear()` is belt-and-suspenders.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/code_compile_test.py -k warning_logs -v`
Expected: FAIL — `stack.warning_logs[code_item.path]` raises `KeyError` (Task 1 stores logs only when `add_warning` is *called with* `logs=`, which `compile_item` does not do yet).

**Step 3: Implement**

In `rbx/box/code.py`, change the warnings block to:
```python
if (
    (cfg.warnings.enabled or force_warnings)
    and artifacts.logs is not None
    and artifacts.logs.preprocess is not None
):
    warning_logs = [log for log in artifacts.logs.preprocess if log.warnings]
    if warning_logs:
        warning_stack.get_warning_stack().add_warning(code, logs=warning_logs)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/code_compile_test.py -k warning_logs -v` — Expected: PASS.
Run the whole compile test module to be safe: `uv run pytest tests/rbx/box/code_compile_test.py -v` — Expected: PASS.

**Step 5: Commit** (use the `/commit` skill)

```
feat(code): forward compiler warning logs to the warning stack
```

---

## Task 5: Set `WARNINGS` status in the compilation streamers

**Files:**
- Modify: `rbx/box/solutions.py` (`SolutionCompilationStreamer.succeeded`, ~lines 305-307; imports near top)
- Modify: `rbx/box/generators.py` (`GeneratorCompilationStreamer.succeeded`, ~lines 313-317; imports near top)
- Test: `tests/rbx/box/solutions_compile_warnings_test.py` (create) — and ideally a parallel one for generators, or extend `tests/rbx/box/generators_test.py`.

**Context:** Each streamer's `succeeded(self, key, value)` currently records the digest and sets `key.status = CompilationStatus.SUCCESS`. We add: if the compiled item's path is in the warning stack, set `WARNINGS` and compute the summary via the language summarizer fed with the stashed logs. Factor the shared logic into one helper to keep it DRY.

Add a helper (put it in `rbx/box/parallel/live_tasks.py` since it operates on a `CompilationTask`, OR — to avoid `live_tasks.py` importing `code.py`/`warning_stack` — put it in `rbx/box/sanitizers/compilation_warnings.py` and import `find_language_name` lazily inside it). Recommended: add to `compilation_warnings.py`:

```python
def apply_warning_status(task: 'CompilationTask') -> None:
    """If ``task.item`` compiled with warnings (per the warning stack), flip the
    task to WARNINGS and attach a language-specific summary line."""
    from rbx.box.code import find_language_name
    from rbx.box.parallel.live_tasks import CompilationStatus
    from rbx.box.sanitizers import warning_stack

    stack = warning_stack.get_warning_stack()
    if task.item.path not in stack.warnings:
        return
    task.status = CompilationStatus.WARNINGS
    logs = stack.warning_logs.get(task.item.path, [])
    language = find_language_name(task.item)
    task.warning_summary = get_compilation_warning_summarizer(language).summarize(logs)
```

(Use a `TYPE_CHECKING` import or string annotation for `CompilationTask` to avoid a real import cycle; the runtime imports inside the function body are deliberate.)

Then in `solutions.py::SolutionCompilationStreamer.succeeded`:
```python
async def succeeded(self, key: SolutionCompilationTask, value: str) -> None:
    compiled_solutions[key.solution.path] = value
    key.status = live_tasks.CompilationStatus.SUCCESS
    compilation_warnings.apply_warning_status(key)
```
and the analogous change in `generators.py::GeneratorCompilationStreamer.succeeded` (after `key.status = live_tasks.CompilationStatus.SUCCESS`). Add `from rbx.box.sanitizers import compilation_warnings` imports to both modules.

**Step 1: Write the failing test**

```python
# tests/rbx/box/solutions_compile_warnings_test.py
from unittest import mock

import pytest

from rbx.box import code, package, solutions
from rbx.box.parallel import live_tasks
from rbx.box.sanitizers import warning_stack
from rbx.box.testing import testing_package
from rbx.grading.steps import GradingLogsHolder, PreprocessLog


async def _compile_with(testing_pkg, *, emit_warning: bool, warnings_enabled: bool):
    from rbx.box import setter_config

    testing_pkg.add_solution('sol.cpp', src='compile_test/simple.cpp', outcome='accepted')
    testing_pkg.save()  # adjust to the actual TestingPackage API used elsewhere

    warning_log = PreprocessLog(
        cmd=['g++', 'sol.cpp'], log='sol.cpp:1:1: warning: x', warnings=True
    )

    async def compile_side_effect(commands, params, artifacts, sandbox, dependency_cache):
        for output in artifacts.outputs:
            if output.digest is not None:
                output.digest.value = await package.get_file_cacher().put_file_content(b'x')
        artifacts.logs = GradingLogsHolder(
            preprocess=[warning_log] if emit_warning else []
        )
        return True

    cfg = setter_config.get_setter_config()
    with mock.patch('rbx.box.code.steps_with_caching.compile', mock.AsyncMock(side_effect=compile_side_effect)), \
         mock.patch('rbx.box.code._precompile_header'), \
         mock.patch.object(cfg.warnings, 'enabled', warnings_enabled):
        warning_stack.get_warning_stack().clear()
        # Capture the task by patching SolutionCompilationTask, or re-create
        # compile_solutions to expose tasks. Simplest: call compile_solutions and
        # then inspect... it does not return tasks. Instead, drive the streamer
        # directly OR add a small seam. Recommended approach: assert via the
        # warning stack + a direct call to compilation_warnings.apply_warning_status
        # on a fresh SolutionCompilationTask.
        ...
```

Practical guidance for the implementer: `compile_solutions()` does not return the `LiveTask` objects, so the cleanest test is two-layered:
1. **Unit test `compilation_warnings.apply_warning_status`** directly: seed `warning_stack.get_warning_stack().add_warning(code, logs=[...])`, build a `SolutionCompilationTask(solution)`, call `apply_warning_status(task)`, assert `task.status is CompilationStatus.WARNINGS` and `task.warning_summary is None` (base summarizer). Also assert that when the path is *not* in the stack, status is left untouched.
2. **Integration smoke test**: run `compile_solutions([...])` end to end with the mocked `compile` that injects a warning log + `warnings.enabled=True`, and assert it returns normally and the warning stack contains the solution path (this proves `compile_item` → stack wiring works inside the streamer flow). You generally cannot easily assert the task status from outside without a seam — don't add one unless trivial; the unit test in (1) covers the status logic.

Match `tests/rbx/box/conftest.py` fixtures (`testing_pkg`, `testing_pkg_from_testdata`) and the `TestingPackage` API used in `solutions_test.py` / `code_compile_test.py` for adding solutions — mirror an existing test rather than guessing the API.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/solutions_compile_warnings_test.py -v`
Expected: FAIL — `compilation_warnings.apply_warning_status` does not exist / `compilation_warnings` not importable from streamers.

**Step 3: Implement** — as described in Context above (helper in `compilation_warnings.py`; call it from both streamers' `succeeded`; add imports).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/solutions_compile_warnings_test.py tests/rbx/box/generators_test.py -v` — Expected: PASS.
Run the broader suite touched by this change:
`uv run pytest tests/rbx/box/code_compile_test.py tests/rbx/box/solutions_test.py tests/rbx/box/generators_test.py tests/rbx/box/sanitizers tests/rbx/box/parallel -v` — Expected: PASS.
Run: `uv run ruff check . && uv run ruff format --check .` — Expected: clean.

**Step 5: Commit** (use the `/commit` skill)

```
feat(box): show WARNINGS in compilation LiveTasks (#397)
```

---

## Task 6: File the C++ summarizer follow-up issue

**Not a code change.** Create a GitHub issue in `rsalesc/rbx` titled roughly:

> Implement C++ compilation-warning summarizer (extract concise lines from GCC/clang output)

Body: link issue #397 and `docs/plans/2026-05-12-compilation-warnings-livetasks.md`; note that `rbx/box/sanitizers/compilation_warnings.py` has a pluggable `CompilationWarningSummarizer` registry (`_SUMMARIZERS`) with only the no-op base implementation, and that designing how to distill GCC/clang warning output into a one-line summary deserves its own brainstorm. Use:

```bash
gh issue create --repo rsalesc/rbx --title "..." --body "..."
```

Then update the comment near `_SUMMARIZERS` in `compilation_warnings.py` to reference the new issue number, and commit (`docs(sanitizers): link C++ warning summarizer follow-up issue` — use the `/commit` skill).

---

## Final verification

- `uv run pytest --ignore=tests/rbx/box/cli` — full suite green.
- `uv run ruff check . && uv run ruff format --check .` — clean.
- Manual smoke (optional): in a sample package, add `-Wall`-triggering code to a solution, set `warnings.enabled: true` in the setter config, run `rbx build` / `rbx run`, and confirm the solution row shows `WARNINGS` and stays visible; with `warnings.enabled: false` it shows `SUCCESS` (row disappears) as before.
- Confirm `git log` shows conventional-commit messages each ending with the `Co-Authored-By:` trailer.
