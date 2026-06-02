# Live Timing-Table Preview During Group Selection — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render the resolved timing table live below the language list in the interactive `rbx time` group picker, updating as the user regroups languages.

**Architecture:** Reuse the single rich renderer `limits_info.build_limits_table()`. Add a generic `console.capture_ansi()` helper that renders any themed rich renderable to an ANSI string. `timing.py` builds a pure preview callback (assignment → ANSI table, or an inline error for invalid groupings) and passes it to the UI-only picker, which adds a content-sized Window below the list. prompt_toolkit repaints on every keystroke, so the preview is live without `rich.live`.

**Tech Stack:** Python, prompt_toolkit (`FormattedTextControl`, `ANSI`), rich (`Console`, `Table`), pytest (`create_pipe_input`/`DummyOutput`).

Design doc: `docs/plans/2026-06-02-timing-preview-design.md`.

---

### Task 1: `console.capture_ansi()` — render a themed renderable to ANSI

**Files:**
- Modify: `rbx/console.py`
- Test: `tests/rbx/test_console_capture.py` (create)

**Step 1: Write the failing test**

```python
import rich.table

from rbx import console


def test_capture_ansi_contains_text_and_escape_codes():
    table = rich.table.Table('Col')
    table.add_row('hello')
    out = console.capture_ansi(table, width=40)
    assert 'hello' in out
    assert '\x1b[' in out  # SGR / box-drawing escapes emitted


def test_capture_ansi_resolves_theme_markup():
    # 'warning' is a project theme style; markup must resolve, not error.
    out = console.capture_ansi('[warning]careful[/warning]', width=40)
    assert 'careful' in out
    assert '\x1b[' in out
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/test_console_capture.py -v`
Expected: FAIL with `AttributeError: module 'rbx.console' has no attribute 'capture_ansi'`

**Step 3: Write minimal implementation**

Add to `rbx/console.py` (it already defines `theme` and imports `Console`):

```python
def capture_ansi(renderable, width: Optional[int] = None) -> str:
    """Render a rich renderable (or markup string) to an ANSI string using the
    project theme, suitable for embedding in a prompt_toolkit ``ANSI`` fragment."""
    import io

    buf = io.StringIO()
    cap = Console(
        theme=theme,
        style='info',
        highlight=False,
        file=buf,
        force_terminal=True,
        color_system='standard',
        width=width,
    )
    cap.print(renderable)
    return buf.getvalue()
```

Add `from typing import Optional` if not already imported.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/test_console_capture.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/console.py tests/rbx/test_console_capture.py
git commit  # use the /commit skill: feat(console): add capture_ansi helper for embedding rich output
```

---

### Task 2: Preview callback factory in `timing.py`

The callback maps a picker assignment to an `ANSI` renderable: the resolved limits table on success, or an inline themed error for an invalid grouping. It is pure (no solution re-runs) and memoized so cursor moves don't rebuild the profile.

**Files:**
- Modify: `rbx/box/timing.py`
- Test: `tests/rbx/box/test_timing_preview.py` (create)

**Step 1: Write the failing test**

```python
from prompt_toolkit.formatted_text import ANSI, to_formatted_text

from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.timing import build_preview_renderer


def _text(ansi: ANSI) -> str:
    return ''.join(t for _, t in to_formatted_text(ansi))


def test_preview_renders_estimated_table():
    render = build_preview_renderer(
        timing_per_solution_per_language={
            'cpp': {'a.cpp': 100, 'b.cpp': 200},
            'python': {'p.py': 900},
        },
        formula='slowest * 3',
        env_groups=[],
        all_languages=['cpp', 'python'],
        width=80,
    )
    out = _text(render({'cpp': 1, 'python': 2}))
    assert 'Time Limit' in out  # the table header
    assert 'cpp' in out and 'python' in out


def test_preview_reports_invalid_grouping_inline():
    # Two env groups whose whenEmpty rules reference each other -> cycle.
    env_groups = [
        LanguageGroup(
            languages=['a'],
            whenEmpty=LanguageGroupFallback(relativeTo='b', multiplier=2.0),
        ),
        LanguageGroup(
            languages=['b'],
            whenEmpty=LanguageGroupFallback(relativeTo='a', multiplier=2.0),
        ),
    ]
    render = build_preview_renderer(
        timing_per_solution_per_language={},  # both groups empty -> resolve via cycle
        formula='slowest * 3',
        env_groups=env_groups,
        all_languages=['a', 'b'],
        width=80,
    )
    # assignment reproduces the two env groups exactly, carrying their whenEmpty
    out = _text(render({'a': 1, 'b': 2}))
    assert 'Invalid grouping' in out


def test_preview_memoizes_by_assignment():
    calls = {'n': 0}
    real = build_preview_renderer(
        timing_per_solution_per_language={'cpp': {'a.cpp': 100}},
        formula='slowest * 3',
        env_groups=[],
        all_languages=['cpp'],
        width=80,
    )

    # Same assignment dict (different identity) must hit the cache.
    first = real({'cpp': 1})
    second = real({'cpp': 1})
    assert first is second
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_preview.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_preview_renderer'`

**Step 3: Write minimal implementation**

Add to `rbx/box/timing.py`. Add imports at top:

```python
import functools

from prompt_toolkit.formatted_text import ANSI

from rbx.box.environment import LanguageGroup
```

(`environment`, `limits_info`, `timing_groups`, `console` are already imported.)

Then:

```python
def build_preview_renderer(
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    formula: str,
    env_groups: List[LanguageGroup],
    all_languages: List[str],
    width: Optional[int] = None,
) -> Callable[[Dict[str, int]], ANSI]:
    """Return a memoized callback mapping a picker assignment to an ``ANSI``
    preview: the resolved limits table, or an inline error for invalid groupings.
    Pure — reuses the already-collected timings, never re-runs solutions."""

    @functools.lru_cache(maxsize=None)
    def _render(assignment_items: tuple) -> ANSI:
        assignment = dict(assignment_items)
        try:
            profile = build_timing_profile(
                timing_per_solution_per_language=timing_per_solution_per_language,
                formula=formula,
                env_groups=env_groups,
                all_languages=all_languages,
                repartition=assignment,
            )
        except timing_groups.GroupValidationError as e:
            return ANSI(console.capture_ansi(f'[warning]⚠ Invalid grouping: {e}[/warning]', width=width))
        table = limits_info.build_limits_table(profile.to_limits(), title='Preview')
        return ANSI(console.capture_ansi(table, width=width))

    def render(assignment: Dict[str, int]) -> ANSI:
        return _render(tuple(sorted(assignment.items())))

    return render
```

Add `Callable` to the `typing` import line at the top of the file.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_preview.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/box/timing.py tests/rbx/box/test_timing_preview.py
git commit  # /commit skill: feat(timing): add memoized preview renderer for the group picker
```

---

### Task 3: Render the preview Window in the picker

**Files:**
- Modify: `rbx/box/timing_group_picker.py`
- Test: `tests/rbx/box/test_timing_group_picker.py:` (append)

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_timing_group_picker.py`:

```python
async def test_picker_invokes_preview_with_current_assignment():
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    seen = []

    def preview(assignment):
        seen.append(dict(assignment))
        return ANSI('preview')

    with create_pipe_input() as inp:
        inp.send_text('1')  # cpp -> group 1
        inp.send_text('\r')  # confirm
        result = await prompt_group_assignment(
            ['cpp', 'java'],
            {'cpp': 0, 'java': 0},
            input=inp,
            output=DummyOutput(),
            preview=preview,
        )
    assert result == {'cpp': 1, 'java': 0}
    # The picker rendered at least once and the final state reached the preview.
    assert seen
    assert {'cpp': 1, 'java': 0} in seen
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py::test_picker_invokes_preview_with_current_assignment -v`
Expected: FAIL with `TypeError: prompt_group_assignment() got an unexpected keyword argument 'preview'`

**Step 3: Write minimal implementation**

In `rbx/box/timing_group_picker.py`:

1. Update imports at top of file:

```python
from typing import Callable, Dict, List, Optional

from prompt_toolkit.formatted_text import AnyFormattedText
```

2. Extend the signature:

```python
async def prompt_group_assignment(
    languages: List[str],
    default_number: Dict[str, int],
    input=None,
    output=None,
    preview: Optional[Callable[[Dict[str, int]], AnyFormattedText]] = None,
) -> Optional[Dict[str, int]]:
```

3. Build the layout's window list and conditionally append the preview window. Replace the existing `layout = Layout(HSplit([...]))` block with:

```python
windows = [
    Window(content=header, height=len(LEGEND_LINES), always_hide_cursor=True),
    Window(content=body, height=len(state.languages), always_hide_cursor=True),
]
if preview is not None:

    def _preview_fragments():
        return preview(state.assignment())

    windows.append(
        Window(
            content=FormattedTextControl(_preview_fragments),
            always_hide_cursor=True,
            dont_extend_height=True,
        )
    )
layout = Layout(HSplit(windows))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_group_picker.py -v`
Expected: PASS (new test plus all existing picker tests)

**Step 5: Commit**

```bash
git add rbx/box/timing_group_picker.py tests/rbx/box/test_timing_group_picker.py
git commit  # /commit skill: feat(timing): render live preview window in the group picker
```

---

### Task 4: Wire the preview into `_prompt_repartition`

**Files:**
- Modify: `rbx/box/timing.py` (`_prompt_repartition`, `estimate_time_limit` call site)
- Test: `tests/rbx/box/test_timing_preview.py` (append)

**Step 1: Write the failing test**

Append to `tests/rbx/box/test_timing_preview.py`:

```python
import inspect

from rbx.box import timing


def test_prompt_repartition_passes_preview_to_picker():
    # _prompt_repartition must accept the timing data needed to build a preview.
    sig = inspect.signature(timing._prompt_repartition)
    assert 'timing_per_solution_per_language' in sig.parameters
    assert 'formula' in sig.parameters
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_timing_preview.py::test_prompt_repartition_passes_preview_to_picker -v`
Expected: FAIL on the missing-parameter assertions.

**Step 3: Write minimal implementation**

In `rbx/box/timing.py`, replace `_prompt_repartition`:

```python
async def _prompt_repartition(
    all_languages: List[str],
    env_groups: List[environment.LanguageGroup],
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    formula: str,
) -> Optional[Dict[str, int]]:
    preview = build_preview_renderer(
        timing_per_solution_per_language=timing_per_solution_per_language,
        formula=formula,
        env_groups=env_groups,
        all_languages=all_languages,
        width=console.console.size.width,
    )
    return await timing_group_picker.prompt_group_assignment(
        all_languages,
        default_assignment(all_languages, env_groups),
        preview=preview,
    )
```

Update the call site in `estimate_time_limit` (currently around line 216). Note `formula` is resolved just above the call (lines 205-206), so pass it:

```python
    repartition = None
    if not auto and len(all_languages) > 1:
        repartition = await _prompt_repartition(
            all_languages,
            env_groups,
            timing_per_solution_per_language,
            formula,
        )
        if repartition is None:
            console.print('[error]Time limit estimation cancelled.[/error]')
            return None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_timing_preview.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add rbx/box/timing.py tests/rbx/box/test_timing_preview.py
git commit  # /commit skill: feat(timing): wire live preview into the repartition prompt
```

---

### Task 5: Full verification

**Step 1: Run the directly-related suites**

Run:
```bash
uv run pytest tests/rbx/test_console_capture.py tests/rbx/box/test_timing_preview.py \
  tests/rbx/box/test_timing_group_picker.py tests/rbx/box/test_timing_groups.py \
  tests/rbx/box/test_timing_estimation.py tests/rbx/box/test_timing.py -v
```
Expected: all PASS.

**Step 2: Lint & format**

Run: `uv run ruff check rbx/box/timing.py rbx/box/timing_group_picker.py rbx/console.py && uv run ruff format --check .`
Expected: clean.

**Step 3: Manual smoke (optional, needs a multi-language package)**

Run `rbx time -p boca` in a package with ≥2 languages; confirm the table renders below the picker and updates as groups change. (Skip if no sandbox/toolchain available locally.)

**Step 4: Final commit if any fixups were needed.**

---

## Notes for the implementer

- **Why ANSI, not `rich.live`:** the picker is already a `prompt_toolkit.Application` that repaints every keystroke; a second screen-owner (`rich.live`) would conflict. Capturing the existing table to ANSI keeps one renderer.
- **Memoization key** is `tuple(sorted(assignment.items()))` — cursor-only moves don't change the assignment, so they reuse the cached `ANSI`.
- **Width** is captured once from `console.console.size.width`; the table is compact, so static width is acceptable.
- Keep `timing_group_picker.py` free of timing/rich-theme knowledge — it only invokes the opaque `preview` callback.
