# Graceful YAML-error handling in `rbx ui`

Date: 2026-06-08

## Problem

When a `problem.rbx.yml` / `env.rbx.yml` file is invalid while `rbx ui` is
running, the Textual app crashes and dumps a mangled mix of a Python/Rich
traceback **and** the pretty caret diagnostic to the restored terminal (see
issue screenshot). The error is recoverable — the user just needs to fix the
file — yet today it tears down the whole TUI with an ugly, doubled message.

### Root cause

- `rbx ui` loads the package/env YAML **lazily**, inside screens, via
  `package.find_problem_package_or_die()` → `load_yaml_model()`.
- `load_yaml_model()` raises `YamlValidationError` / `YamlSyntaxError`, both
  subclasses of `RbxException`, each carrying a **pre-rendered** caret
  diagnostic (file:line, snippet, carets) as an ANSI string in `self.msg`
  (accessible via `exc.from_ansi()` / `exc.plain()`).
- `rbxBaseApp._handle_exception` (`rbx/box/ui/main.py`) only special-cases
  `typer.Exit`. An `RbxException` falls through to Textual's default
  `App._handle_exception` → `_fatal_error()`, which appends a **Rich
  traceback** to `_exit_renderables` and closes the app. Textual's default
  also sets `self._exception`, which is re-raised out of `app.run()`; the
  top-level `rbx/box/main.py:app()` catches `RbxException` and **re-prints**
  `str(e)`. Hence the doubled/mangled output.

## Empirical findings (Textual 8.0)

Verified with throwaway Pilot experiments:

| Where the `RbxException` fires | `_handle_exception` → `show_error` (push modal) keeps app alive? |
|---|---|
| Pushed screen's `compose` / `on_mount` (screen entry — the screenshot case) | **Yes** (`alive=True`, modal shown) |
| Directly in an action/handler body (e.g. `_is_interactive()` from `action_show_output`) | **No** — `is_running` flips to `False`; must catch at the call site |

The realistic navigation path (an `OptionList`/selection handler that calls
`push_screen(SomeScreen())`, whose `compose`/`on_mount` then loads YAML) falls
in the **first** row: the exception surfaces in the child screen's mount
pipeline, not in the selection handler's own body, so the safety net recovers.

The existing visualizer actions already prove that catching an `RbxException`
**inside an action's `except` block** and calling `self.app.show_error(e)`
keeps the app alive (`test_visualizer_error_routes_to_error_modal`).

## Reused infrastructure

Commit `e5912a7` (#541) added exactly the presentation layer we need:

- `rbx/box/ui/screens/error_modal.py` — `ErrorModal(ModalScreen[None])`: a
  dismissible (`q`/`esc`), scrollable `RichLog` that renders a `rich.text.Text`
  with formatting preserved and no truncation.
- `rbxBaseApp.show_error(exc: RbxException)` — renders `exc.from_ansi()` (with
  a non-blank fallback) and pushes an `ErrorModal`.

This design only wires those into the error path; it does **not** build a new
modal.

## Design

Two parts.

### 1. Safety net in `rbxBaseApp._handle_exception` (covers the reported case)

Add an `RbxException` branch ahead of the `super()` fall-through:

```python
def _handle_exception(self, error: Exception) -> None:
    if isinstance(error, typer.Exit):
        ...  # unchanged
        return
    if isinstance(error, RbxException):
        if self.is_running:
            try:
                self.show_error(error)   # push ErrorModal, app stays alive
                return
            except Exception:
                pass  # fall through to clean exit
        # Clean fallback: diagnostic only, no traceback, no doubling.
        self._exit_renderables.clear()
        self._exit_renderables.append(_exit_renderable_for(error))
        self.exit(1)
        return
    return super()._handle_exception(error)
```

- **Keep-alive path:** handles screen-entry crashes (`compose`/`on_mount` of a
  pushed screen — e.g. `RunScreen.compose`, `TestExplorerScreen.on_mount` →
  `_is_interactive`). App survives; user reads the modal, fixes the file, and
  retries.
- **Clean fallback:** if the app cannot show the modal (not running yet, or
  `push_screen` raises mid-teardown), exit cleanly showing only
  `error.from_ansi()` (non-blank fallback text if empty). Because we never call
  `_fatal_error()` and never set `self._exception`, there is no Rich traceback
  and the top-level handler does not re-print → the doubling is gone.

`rbxDifferApp` and `rbxCommandApp` subclass `rbxBaseApp`, so they inherit this.

### 2. Local hardening for the "dies" case

An `RbxException` raised **directly in an action body** is unrecoverable from
`_handle_exception` (verified). The relevant sites are the lazy package loads
reachable from a key action mid-session — chiefly the `_is_interactive()`
helpers and the limits-editor callbacks. Wrap each so the exception is caught
before it escapes, mirroring the visualizer pattern:

```python
def _is_interactive(self) -> bool:
    try:
        return package.find_problem_package_or_die().type == TaskType.COMMUNICATION
    except RbxException as e:
        self.app.show_error(e)  # type: ignore[attr-defined]
        return False
```

Sites to harden (verify exact set during implementation):
- `rbx/box/ui/screens/test_explorer.py` — `_is_interactive()` and the package
  load in `_update_selected_test`/metadata paths reached from actions.
- `rbx/box/ui/screens/run_test_explorer.py` — `_is_interactive()` and the
  action-reachable package load.
- `rbx/box/ui/screens/limits_editor.py` — the `find_problem_package_or_die()` /
  `environment.get_environment()` loads in `_on_profile_selected` / save / mount
  callbacks.

Loads that live in `compose`/`on_mount` (e.g. `run.py:116`) need **no** wrap —
the safety net covers them — but wrapping is harmless where ergonomic.

## Testing

Pilot-based, following `tests/rbx/box/ui/test_error_modal.py`:

1. **Screen-entry crash → modal, app alive.** Push a screen whose `compose`
   (or `on_mount`) raises an `RbxException` (patch `find_problem_package_or_die`
   to raise); assert `app.is_running` and `isinstance(app.screen, ErrorModal)`
   and the diagnostic text is present.
2. **Mid-session action crash → modal, app alive.** With a mounted screen,
   patch the load to raise and invoke the action; assert app alive + modal.
3. **Clean fallback → diagnostic only, no traceback.** Force `show_error` to
   raise (or app not running) and assert `_exit_renderables` holds the
   diagnostic (not a `Traceback`) and the app exits with code 1; assert the
   exception does not propagate out of `run()` (no doubling).

## Out of scope

- The deprecation warnings visible in the screenshot ("languages as list…",
  "removed in v3") — separate output emitted during parsing, not the crash.
- `BocaRunsApp` (`rbx/box/tooling/boca/ui/app.py`) — subclasses `App`, not
  `rbxBaseApp`; not part of `rbx ui`.
- Auto-popping a broken screen after the modal is dismissed — minor; `q`
  returns the user to the menu.
