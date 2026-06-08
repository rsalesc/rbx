# Graceful YAML-error handling in `rbx ui` — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop `rbx ui` from crashing with a doubled traceback dump when a
`problem.rbx.yml` / `env.rbx.yml` is invalid; instead surface the error in the
existing scrollable `ErrorModal` and keep the TUI alive, with a clean
diagnostic-only exit as a fallback.

**Architecture:** Intercept `RbxException` in `rbxBaseApp._handle_exception`
(`rbx/box/ui/main.py`). If the app is running, push the existing `ErrorModal`
via `show_error` (app survives — verified for screen-entry `compose`/`on_mount`
crashes). Otherwise exit cleanly showing only `exc.from_ansi()` (no Rich
traceback, no re-raise, so the top-level CLI handler can't double-print). One
screen (`limits_editor`, in development) loads the package in a non-mount
callback; harden it with the proven `try/except RbxException: self.app.show_error(e)`
pattern.

**Tech Stack:** Python 3.14, Textual 8.0 (`ModalScreen`, `App._handle_exception`,
Pilot `run_test()`), Pydantic v2, pytest (`pytest-asyncio` — tests are `async def`).

**Design doc:** `docs/plans/2026-06-08-ui-yaml-error-handling-design.md`

**Background facts (verified empirically against Textual 8.0):**
- `load_yaml_model()` raises `YamlValidationError`/`YamlSyntaxError`, both
  `RbxException` subclasses carrying a pre-rendered caret diagnostic accessible
  via `exc.from_ansi()` (rich `Text`) / `exc.plain()` (str).
- A pushed screen's `compose`/`on_mount` raising an `RbxException` → handling it
  in `_handle_exception` by pushing a modal **keeps the app alive**.
- `find_problem_package` is `@functools.cache`d and does NOT cache exceptions:
  the main explorer screens load YAML at mount (safety-net-covered), later
  action loads hit the cache, and a failed load re-parses on retry. So no
  per-action wraps are needed there.
- `rbxDifferApp` and `rbxCommandApp` subclass `rbxBaseApp`, inheriting the fix.

**Test commands:**
- Single test: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py::<name> -v`
- File: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py -v`
- Existing modal tests still pass: `uv run pytest tests/rbx/box/ui/test_error_modal.py -v`

---

### Task 1: Keep-alive modal for `RbxException` in `_handle_exception`

Surface a recoverable `RbxException` in the `ErrorModal` instead of crashing,
when the app is running. Also DRY the modal-content fallback shared with the
existing `show_error`.

**Files:**
- Modify: `rbx/box/ui/main.py` (`rbxBaseApp.show_error` ~47-58, `_handle_exception` ~37-45)
- Create: `tests/rbx/box/ui/test_yaml_error_handling.py`

**Step 1: Write the failing test**

Create `tests/rbx/box/ui/test_yaml_error_handling.py`:

```python
"""rbx ui surfaces YAML/config RbxExceptions without crashing the TUI.

A YAML syntax/validation error (RbxException) raised while rbx ui is running
used to fall through rbxBaseApp._handle_exception into Textual's default
handler, dumping a Rich traceback AND re-printing the diagnostic from the
top-level CLI handler. It now opens the dismissible ErrorModal and keeps the
app alive, falling back to a clean diagnostic-only exit if the modal cannot be
shown.
"""

import rich.text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, RichLog

from rbx.box.exception import RbxException
from rbx.box.ui.main import rbxApp
from rbx.box.ui.screens.error_modal import ErrorModal


def _exc(text: str) -> RbxException:
    """Build an RbxException carrying ``text`` as its rendered diagnostic."""
    exc = RbxException()
    exc.print(text)
    return exc


def _rich_log_text(modal: ErrorModal) -> str:
    rich_log = modal.query_one(RichLog)
    return '\n'.join(strip.text for strip in rich_log.lines)


class _CrashOnMountScreen(Screen):
    """Mirrors a real screen that loads invalid YAML during on_mount."""

    def compose(self) -> ComposeResult:
        yield Label('loading')

    def on_mount(self) -> None:
        raise _exc('env.rbx.yml: 1 validation error\nlanguages: extra inputs')


async def test_yaml_error_on_screen_entry_opens_modal_and_keeps_app_alive():
    async with rbxApp().run_test() as pilot:
        app = pilot.app
        await app.push_screen(_CrashOnMountScreen())
        await pilot.pause()

        assert app.is_running
        assert isinstance(app.screen, ErrorModal)
        assert 'extra inputs' in _rich_log_text(app.screen)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py::test_yaml_error_on_screen_entry_opens_modal_and_keeps_app_alive -v`
Expected: FAIL — the app tears down / `app.screen` is not an `ErrorModal` (the
`RbxException` falls through to Textual's default handler).

**Step 3: Write minimal implementation**

In `rbx/box/ui/main.py`, refactor `show_error` to share a content helper and add
the keep-alive branch to `_handle_exception`. Replace the existing
`_handle_exception` and `show_error` with:

```python
    def _handle_exception(self, error: Exception) -> None:
        if isinstance(error, typer.Exit):
            self._exit_renderables.clear()
            self._exit_renderables.append(Segments(console.console._buffer))  # noqa: SLF001
            self.exit(error.exit_code)
            return

        if isinstance(error, RbxException):
            # Recoverable user-config error (e.g. invalid problem/env YAML).
            # Keep the TUI alive and show it in a dismissible modal. Verified:
            # screen-entry crashes (a pushed screen's compose/on_mount) recover
            # here; the few action-body loads are guarded at the call site.
            if self.is_running:
                try:
                    self.show_error(error)
                    return
                except Exception:
                    pass  # fall through to the clean exit below
            # Clean fallback: show ONLY the pretty diagnostic -- never a Python
            # traceback, and never re-raised (so the top-level CLI handler in
            # rbx/box/main.py cannot double-print it).
            self._exit_renderables.clear()
            self._exit_renderables.append(self._error_content(error))
            self.exit(1)
            return

        # Default behavior (Rich traceback + return code 1)
        return super()._handle_exception(error)

    def _error_content(self, exc: RbxException) -> rich.text.Text:
        content = exc.from_ansi()
        if not content.plain.strip():
            content = rich.text.Text('An unexpected error occurred.')
        return content

    def show_error(self, exc: RbxException) -> None:
        """Surface an RbxException in a dismissible, scrollable modal.

        Preferred over a toast notification for errors that carry long,
        formatted output (e.g. a visualizer's compile/runtime failure, or an
        invalid problem/env YAML).
        """
        self.push_screen(ErrorModal(self._error_content(exc), title='Error'))
```

(`rich.text`, `typer`, `Segments`, `console`, `RbxException`, and `ErrorModal`
are already imported in this file.)

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py::test_yaml_error_on_screen_entry_opens_modal_and_keeps_app_alive -v`
Expected: PASS

Also confirm no regression in the existing modal tests:
Run: `uv run pytest tests/rbx/box/ui/test_error_modal.py -v`
Expected: PASS (all)

**Step 5: Commit**

```bash
git add rbx/box/ui/main.py tests/rbx/box/ui/test_yaml_error_handling.py
git commit -m "$(cat <<'EOF'
fix(ui): surface RbxException in a modal instead of crashing rbx ui

Catch RbxException (e.g. invalid problem/env YAML) in
rbxBaseApp._handle_exception and show it in the existing ErrorModal,
keeping the TUI alive instead of dumping a Rich traceback.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Clean diagnostic-only fallback when the modal can't be shown

If `show_error` itself fails (or the app is not running), exit cleanly showing
only the rendered diagnostic — never a traceback, never re-raised. The code for
this already landed in Task 1's `_handle_exception`; this task adds the test
that locks the behavior.

**Files:**
- Modify: `tests/rbx/box/ui/test_yaml_error_handling.py`
- (No production change unless the test reveals a gap.)

**Step 1: Write the failing test**

Append to `tests/rbx/box/ui/test_yaml_error_handling.py`:

```python
async def test_clean_fallback_shows_diagnostic_without_traceback():
    async with rbxApp().run_test() as pilot:
        app = pilot.app

        # Force the modal path to fail so the clean-exit fallback runs.
        def _boom(_exc):
            raise RuntimeError('cannot push modal')

        app.show_error = _boom  # type: ignore[method-assign]

        app._handle_exception(_exc('problem.rbx.yml: bad value at line 12'))
        await pilot.pause()

        # The sole exit renderable is the pretty diagnostic as plain rich Text,
        # NOT a Rich Traceback / Segments dump.
        assert app._exit_renderables
        rendered = app._exit_renderables[-1]
        assert isinstance(rendered, rich.text.Text)
        assert 'bad value at line 12' in rendered.plain
        # App is exiting with code 1 rather than crashing.
        assert app._return_code == 1
```

**Step 2: Run test to verify it fails (or passes if Task 1 already covers it)**

Run: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py::test_clean_fallback_shows_diagnostic_without_traceback -v`
Expected: PASS if Task 1's implementation is correct. If it FAILS (e.g.
`_exit_renderables` empty or holds `Segments`), fix `_handle_exception` so the
fallback clears `_exit_renderables` and appends `self._error_content(error)`
before `self.exit(1)`, then re-run.

**Step 3: (Only if Step 2 failed) adjust implementation**

Ensure the `RbxException` fallback branch in `rbx/box/ui/main.py` matches the
code in Task 1 Step 3 exactly.

**Step 4: Run the full file**

Run: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add tests/rbx/box/ui/test_yaml_error_handling.py
git commit -m "$(cat <<'EOF'
test(ui): lock clean diagnostic-only fallback for RbxException

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Harden `limits_editor`'s non-mount package/env load

`LimitsEditorScreen._render_detail_form` (reached from the profile-selection
watcher `_on_profile_selected`, not from mount) calls
`package.find_problem_package_or_die()` (~line 192) and
`environment.get_environment()` (~line 264). These are the only package/env
loads in `rbx ui` whose *first* execution is not in a pushed screen's
`compose`/`on_mount`. Catch `RbxException` there and route to the modal — the
proven pattern (catching before the exception escapes always keeps the app
alive). Both loads live in one method, so one `except` clause covers both.

**Files:**
- Modify: `rbx/box/ui/screens/limits_editor.py` (imports; `_render_detail_form`)
- Modify: `tests/rbx/box/ui/test_yaml_error_handling.py`

**Step 1: Inspect the method**

Read `rbx/box/ui/screens/limits_editor.py` around `_render_detail_form`
(it begins ~line 184 with `self._is_rendering = True` then a body that mounts
form widgets). Confirm the package load (~192) and env load (~264) are both
inside this method, and note its existing `try`/`finally` structure (it sets
`self._is_rendering = True` and resets it in `finally`).

**Step 2: Write the failing test**

Append to `tests/rbx/box/ui/test_yaml_error_handling.py`:

```python
async def test_limits_editor_profile_load_error_opens_modal():
    from rbx.box.ui.screens import limits_editor

    async def _no_profiles():
        return None

    with mock.patch.object(
        limits_editor.package,
        'find_problem_package_or_die',
        side_effect=_exc('problem.rbx.yml: invalid limits'),
    ):
        async with rbxApp().run_test() as pilot:
            app = pilot.app
            screen = limits_editor.LimitsEditorScreen()
            await app.push_screen(screen)
            await pilot.pause()

            # Render a profile detail form, which triggers the package load.
            await screen._render_detail_form(_profile_stub())
            await pilot.pause()

            assert app.is_running
            assert isinstance(app.screen, ErrorModal)
            assert 'invalid limits' in _rich_log_text(app.screen)
```

Add `from unittest import mock` to the imports, plus a `_profile_stub()` helper
near the top of the file that returns a minimal object satisfying
`_render_detail_form`'s attribute access up to the package-load line — inspect
the method to see what it reads (e.g. a `mock.Mock()` with the needed
attributes, or a real minimal `LimitsProfile`). Keep the stub as small as the
method demands; if the method reads many attributes before the load, prefer
`mock.Mock()`.

> If mounting `LimitsEditorScreen` pulls in heavy dependencies, mirror the
> patching already used in `tests/rbx/box/ui/test_error_modal.py`
> (`test_visualizer_error_routes_to_error_modal`) and the help-panel tests.

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py::test_limits_editor_profile_load_error_opens_modal -v`
Expected: FAIL — the `RbxException` escapes `_render_detail_form` and the app
does not show an `ErrorModal` (and may tear down).

**Step 4: Write minimal implementation**

In `rbx/box/ui/screens/limits_editor.py`:

1. Add the import near the other `rbx.box` imports:
   ```python
   from rbx.box.exception import RbxException
   ```
2. Wrap the body of `_render_detail_form` so a config-load failure surfaces in
   the modal and aborts the render. Add this `except` to the method's existing
   `try` (the one paired with the `finally` that resets `self._is_rendering`):
   ```python
           except RbxException as e:
               self.app.show_error(e)  # type: ignore[attr-defined]
               return
   ```
   If the load lines are not already inside that `try`, widen the `try` to
   enclose them (keep the `finally: self._is_rendering = False` intact). Place
   the new `except RbxException` BEFORE any broader `except`.

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py::test_limits_editor_profile_load_error_opens_modal -v`
Expected: PASS

Run the whole file + the existing modal tests:
Run: `uv run pytest tests/rbx/box/ui/test_yaml_error_handling.py tests/rbx/box/ui/test_error_modal.py -v`
Expected: PASS (all)

**Step 6: Commit**

```bash
git add rbx/box/ui/screens/limits_editor.py tests/rbx/box/ui/test_yaml_error_handling.py
git commit -m "$(cat <<'EOF'
fix(ui): show config errors in limits editor instead of crashing

The limits editor loads the package/env in a profile-selection callback
(not at mount), so a bad problem/env YAML there escapes the keep-alive
safety net. Catch RbxException and route it to the error modal.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Document the safety-net pattern

**Files:**
- Modify: `rbx/box/ui/CLAUDE.md` ("Important Patterns" section, near the existing
  "Surfacing exceptions" bullet ~line 83)

**Step 1: Add a bullet**

Under "Important Patterns", after the "Surfacing exceptions" bullet, add:

```markdown
- **YAML/config error safety net** -- `rbxBaseApp._handle_exception` (`main.py`)
  intercepts `RbxException` (e.g. invalid `problem.rbx.yml`/`env.rbx.yml` from
  `load_yaml_model`): if the app is running it shows the error via `show_error`
  (ErrorModal) and keeps the TUI alive; otherwise it exits cleanly printing only
  `exc.from_ansi()` (no Rich traceback, not re-raised, so the top-level CLI
  handler can't double-print). This recovers screen-entry crashes
  (`compose`/`on_mount` of a pushed screen). Loads whose *first* execution is in
  an action/watcher body (e.g. `limits_editor._render_detail_form`) cannot
  recover from `_handle_exception`, so they catch `RbxException` at the call
  site and call `self.app.show_error(e)` directly.
```

**Step 2: Verify it renders (no build needed — Markdown)**

Run: `uv run python -c "import pathlib; print('ok' if 'safety net' in pathlib.Path('rbx/box/ui/CLAUDE.md').read_text() else 'missing')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add rbx/box/ui/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(ui): document the RbxException safety net in _handle_exception

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Final verification

Run the UI test suite (excluded from default CI per CLAUDE.md, so run explicitly):

```bash
uv run pytest tests/rbx/box/ui/ -v
```
Expected: PASS (new + existing). If pre-existing failures appear unrelated to
these files (e.g. sandbox/docker/C++ env issues noted in project memory), note
them but do not treat them as regressions.

Lint/format:
```bash
uv run ruff check rbx/box/ui/ tests/rbx/box/ui/
uv run ruff format rbx/box/ui/ tests/rbx/box/ui/
```
Expected: clean.

### Notes / out of scope
- The deprecation warnings in the original screenshot ("languages as list…",
  "removed in v3") are separate parser output, not the crash — not addressed
  here.
- `BocaRunsApp` (`rbx/box/tooling/boca/ui/app.py`) subclasses `App`, not
  `rbxBaseApp`; outside `rbx ui` scope.
- Auto-popping a broken screen after the modal is dismissed is intentionally not
  done; `q` returns the user to the menu, and a failed load re-parses on retry
  (exceptions aren't cached by `@functools.cache`).
```
