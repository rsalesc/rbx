# Shareable run & time reports Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `--share[=FORMAT]` flag to `rbx run` and `rbx time` that captures the rendered report and copies it to the clipboard as a PNG image or plain text (#388).

**Architecture:** A new `rbx/box/sharing.py` module owns three concerns: (1) *capture* — re-render a report into a `rich.console.Console(record=True)` and export it as text or SVG; (2) *convert* — turn SVG into PNG by shelling out to a runtime-detected converter; (3) *clipboard* — copy text/image via platform-specific CLI tools, falling back to writing a file. The two CLI commands re-render their final report into a recording console after the normal live output, then hand off to `sharing`.

**Tech Stack:** Python, Rich (`Console(record=True)`, `export_text`/`export_svg`), `subprocess`/`shutil.which`, Typer, pytest + `unittest.mock`.

**Key insight:** `rich.live.Live` only animates when `console.is_terminal` is true. A recording `Console` built without `force_terminal` is **not** a terminal, so re-rendering the existing report functions into it yields a clean final frame — no reporter rewrite needed.

---

### Background: design

Read `docs/plans/2026-06-03-shareable-reports-design.md` first. It defines exactly what each command shares. Summary:
- `rbx run --share` → limits header + verdict view (+ `-d` detailed tables) + timing summary.
- `rbx time --share` → the "Run report (for time estimation)" + the final per-language-group limits table (`build_limits_table`). (Optional: the fastest/slowest/formula estimation lines.)

Key existing symbols:
- `rbx/console.py`: `theme`, `console.console` (global), `new_console()`, `capture_ansi()`.
- `rbx/box/solutions.py`: `async print_run_report(result, console, verification, detailed=False, timing=True, skip_printing_limits=False)`.
- `rbx/box/limits_info.py`: `build_limits_table(profile, title=...) -> rich.table.Table`, `render_limits_table(profile, title=...)`.
- `rbx/box/cli.py`: the `run` command (~line 303) and `time` command (~line 463).

Run tests with `uv run pytest <path> -v`. Lint with `uv run ruff check rbx/box/sharing.py`.

---

### Task 1: Converter detection + SVG→PNG

**Files:**
- Create: `rbx/box/sharing.py`
- Test: `tests/rbx/box/test_sharing.py`

**Step 1: Write the failing test**

```python
# tests/rbx/box/test_sharing.py
from unittest import mock

from rbx.box import sharing


def test_detect_png_converter_prefers_rsvg(monkeypatch):
    monkeypatch.setattr(
        sharing.shutil, 'which',
        lambda name: f'/usr/bin/{name}' if name == 'rsvg-convert' else None,
    )
    conv = sharing.detect_png_converter()
    assert conv is not None
    assert conv.tool == 'rsvg-convert'


def test_detect_png_converter_none_available(monkeypatch):
    monkeypatch.setattr(sharing.shutil, 'which', lambda name: None)
    assert sharing.detect_png_converter() is None


def test_svg_to_png_invokes_converter(monkeypatch, tmp_path):
    monkeypatch.setattr(
        sharing.shutil, 'which',
        lambda name: f'/usr/bin/{name}' if name == 'magick' else None,
    )
    calls = []
    monkeypatch.setattr(
        sharing.subprocess, 'run',
        lambda *a, **k: calls.append((a, k)) or mock.Mock(returncode=0),
    )
    out = sharing.svg_to_png('<svg/>', tmp_path / 'r.png')
    assert out == tmp_path / 'r.png'
    assert calls, 'converter should have been invoked'
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/test_sharing.py -v`
Expected: FAIL — `ModuleNotFoundError: rbx.box.sharing`.

**Step 3: Write minimal implementation**

```python
# rbx/box/sharing.py
import dataclasses
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

# Ordered preference of SVG->PNG converters. Each entry builds the argv given
# (svg_path, png_path).
_CONVERTERS = [
    ('rsvg-convert', lambda svg, png: ['rsvg-convert', str(svg), '-o', str(png)]),
    ('magick', lambda svg, png: ['magick', str(svg), str(png)]),
    ('convert', lambda svg, png: ['convert', str(svg), str(png)]),
    ('qlmanage', lambda svg, png: ['qlmanage', '-t', '-o', str(png.parent), str(svg)]),
]


@dataclasses.dataclass
class PngConverter:
    tool: str
    build_argv: object  # Callable[[Path, Path], List[str]]


def detect_png_converter() -> Optional[PngConverter]:
    for tool, build in _CONVERTERS:
        if shutil.which(tool) is not None:
            return PngConverter(tool=tool, build_argv=build)
    return None


def svg_to_png(svg: str, png_path: Path) -> Optional[Path]:
    """Convert SVG text to a PNG file. Returns the path on success, None if no
    converter is available."""
    converter = detect_png_converter()
    if converter is None:
        return None
    with tempfile.NamedTemporaryFile('w', suffix='.svg', delete=False) as f:
        f.write(svg)
        svg_path = Path(f.name)
    try:
        argv = converter.build_argv(svg_path, png_path)
        subprocess.run(argv, check=True, capture_output=True)
    finally:
        svg_path.unlink(missing_ok=True)
    return png_path
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/test_sharing.py -v`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add rbx/box/sharing.py tests/rbx/box/test_sharing.py
git commit -m "feat(sharing): detect svg-to-png converter and convert"
```

> Note: `qlmanage` names its output `<svg-stem>.png` in the target dir, not the exact `png_path`. Handle in Task 1b if you choose to support it; otherwise the `rsvg-convert`/`magick` paths are primary. Keep `qlmanage` last.

---

### Task 2: Clipboard dispatch with file fallback

**Files:**
- Modify: `rbx/box/sharing.py`
- Test: `tests/rbx/box/test_sharing.py`

**Step 1: Write the failing tests**

```python
def test_copy_text_macos_uses_pbcopy(monkeypatch):
    monkeypatch.setattr(sharing.sys, 'platform', 'darwin')
    captured = {}
    def fake_run(argv, input=None, **k):
        captured['argv'] = argv
        captured['input'] = input
        return mock.Mock(returncode=0)
    monkeypatch.setattr(sharing.subprocess, 'run', fake_run)
    monkeypatch.setattr(sharing.shutil, 'which', lambda n: '/usr/bin/pbcopy')
    assert sharing.copy_text_to_clipboard('hello') is True
    assert captured['argv'] == ['pbcopy']
    assert captured['input'] == b'hello'


def test_copy_text_linux_wayland_uses_wl_copy(monkeypatch):
    monkeypatch.setattr(sharing.sys, 'platform', 'linux')
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
    monkeypatch.setattr(sharing.shutil, 'which',
                        lambda n: '/usr/bin/wl-copy' if n == 'wl-copy' else None)
    seen = {}
    monkeypatch.setattr(sharing.subprocess, 'run',
                        lambda argv, input=None, **k: seen.update(argv=argv) or mock.Mock(returncode=0))
    assert sharing.copy_text_to_clipboard('x') is True
    assert seen['argv'][0] == 'wl-copy'


def test_copy_image_unsupported_returns_false(monkeypatch):
    monkeypatch.setattr(sharing.sys, 'platform', 'win32')
    assert sharing.copy_image_to_clipboard(sharing.Path('/tmp/x.png')) is False
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_sharing.py -v`
Expected: FAIL — functions not defined.

**Step 3: Implement**

```python
import os
import sys


def _linux_clipboard_tool() -> Optional[str]:
    if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wl-copy'):
        return 'wl-copy'
    if shutil.which('xclip'):
        return 'xclip'
    if shutil.which('wl-copy'):
        return 'wl-copy'
    return None


def copy_text_to_clipboard(text: str) -> bool:
    data = text.encode('utf-8')
    if sys.platform == 'darwin' and shutil.which('pbcopy'):
        argv: Optional[List[str]] = ['pbcopy']
    elif sys.platform.startswith('linux'):
        tool = _linux_clipboard_tool()
        if tool == 'xclip':
            argv = ['xclip', '-selection', 'clipboard']
        elif tool == 'wl-copy':
            argv = ['wl-copy']
        else:
            argv = None
    else:
        argv = None
    if argv is None:
        return False
    result = subprocess.run(argv, input=data, capture_output=True)
    return result.returncode == 0


def copy_image_to_clipboard(png_path: Path) -> bool:
    if sys.platform == 'darwin':
        script = (
            f'set the clipboard to '
            f'(read (POSIX file "{png_path}") as «class PNGf»)'
        )
        result = subprocess.run(['osascript', '-e', script], capture_output=True)
        return result.returncode == 0
    if sys.platform.startswith('linux'):
        tool = _linux_clipboard_tool()
        data = png_path.read_bytes()
        if tool == 'xclip':
            argv = ['xclip', '-selection', 'clipboard', '-t', 'image/png']
        elif tool == 'wl-copy':
            argv = ['wl-copy', '--type', 'image/png']
        else:
            return False
        result = subprocess.run(argv, input=data, capture_output=True)
        return result.returncode == 0
    return False
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_sharing.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/sharing.py tests/rbx/box/test_sharing.py
git commit -m "feat(sharing): copy text and image to clipboard with fallback"
```

---

### Task 3: Capture a report into a recording console + top-level `share_report`

**Files:**
- Modify: `rbx/box/sharing.py`
- Test: `tests/rbx/box/test_sharing.py`

This task adds (a) a recording-console factory, (b) export helpers, and (c) the orchestrator `share_report` that picks format → convert → clipboard → file fallback, returning a small result object so callers can print a confirmation.

**Step 1: Write the failing tests**

```python
import rich.text

from rbx.box import sharing


def test_recording_console_is_not_a_terminal():
    rec = sharing.recording_console(width=80)
    assert rec.record is True
    assert rec.is_terminal is False  # so rich.live.Live won't animate


def test_export_text_captures_rendered_content():
    rec = sharing.recording_console(width=80)
    rec.print(rich.text.Text('Timing summary: 123 ms'))
    text = sharing.export_text(rec)
    assert 'Timing summary: 123 ms' in text


def test_share_report_text_copies_to_clipboard(monkeypatch, tmp_path):
    rec = sharing.recording_console(width=80)
    rec.print('hello world')
    monkeypatch.setattr(sharing, 'copy_text_to_clipboard', lambda t: True)
    result = sharing.share_report(rec, fmt='text', title='t', out_dir=tmp_path)
    assert result.copied is True
    assert result.fmt == 'text'
    assert result.file_path is None


def test_share_report_text_falls_back_to_file(monkeypatch, tmp_path):
    rec = sharing.recording_console(width=80)
    rec.print('hello world')
    monkeypatch.setattr(sharing, 'copy_text_to_clipboard', lambda t: False)
    result = sharing.share_report(rec, fmt='text', title='t', out_dir=tmp_path)
    assert result.copied is False
    assert result.file_path is not None and result.file_path.exists()
    assert 'hello world' in result.file_path.read_text()
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/test_sharing.py -v`
Expected: FAIL.

**Step 3: Implement**

```python
import rich.console

from rbx import console as _console  # for the shared theme


def recording_console(width: int = 120) -> rich.console.Console:
    return rich.console.Console(
        theme=_console.theme,
        style='info',
        highlight=False,
        record=True,
        width=width,
        # No force_terminal: keeps is_terminal False so Live renders final frame.
    )


def export_text(rec: rich.console.Console) -> str:
    return rec.export_text()


def export_svg(rec: rich.console.Console, title: str) -> str:
    return rec.export_svg(title=title)


@dataclasses.dataclass
class ShareResult:
    fmt: str
    copied: bool
    file_path: Optional[Path] = None


def share_report(
    rec: rich.console.Console,
    fmt: str,
    title: str,
    out_dir: Path,
) -> ShareResult:
    """Convert a recorded report to `fmt` ('png'|'text') and copy to clipboard.
    Falls back to writing a file under out_dir if clipboard/convert is
    unavailable."""
    if fmt == 'text':
        text = export_text(rec)
        if copy_text_to_clipboard(text):
            return ShareResult(fmt='text', copied=True)
        path = out_dir / 'report.txt'
        path.write_text(text)
        return ShareResult(fmt='text', copied=False, file_path=path)

    # fmt == 'png'
    svg = export_svg(rec, title=title)
    png_path = out_dir / 'report.png'
    if svg_to_png(svg, png_path) is not None and copy_image_to_clipboard(png_path):
        return ShareResult(fmt='png', copied=True, file_path=png_path)
    # Could not convert and/or copy: persist whichever artifact we have.
    if png_path.exists():
        return ShareResult(fmt='png', copied=False, file_path=png_path)
    svg_path = out_dir / 'report.svg'
    svg_path.write_text(svg)
    return ShareResult(fmt='png', copied=False, file_path=svg_path)
```

> `out_dir` should be a stable, discoverable location — use the package build dir. The CLI tasks pass `package.get_problem_build_path()` (or the closest existing build-dir helper; confirm the exact name in `rbx/box/package.py`).

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/test_sharing.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/sharing.py tests/rbx/box/test_sharing.py
git commit -m "feat(sharing): record reports and orchestrate share with fallback"
```

---

### Task 4: Wire `--share` into `rbx run`

**Files:**
- Modify: `rbx/box/cli.py` (the `run` command, ~line 303; report print ~line 432)
- Test: `tests/rbx/box/test_sharing.py` (capture-content unit test) + manual

**Step 1: Add the flag.** In the `run` signature add:

```python
    share: Optional[str] = typer.Option(
        None,
        '--share',
        help='Capture the run report and copy it to the clipboard. '
        'Optionally specify a format: --share=png (default) or --share=text.',
    ),
```

Typer note: to allow both `--share` (flag-like, default png) and `--share=text`, declare it as `Optional[str]` with no value meaning "not requested". Treat the empty/sentinel case: if the user passes bare `--share`, Typer needs a value. To support a bare flag, add a separate boolean is overkill; instead accept `--share png|text` and document `--share png`. If a true bare flag is desired, use a custom callback — keep it simple: require an explicit value, default examples in help.

> Decision for this plan: `--share` takes an explicit value `png|text`. Validate it: if `share not in (None, 'png', 'text')`, print an error and `raise typer.Exit(1)`.

**Step 2: After the existing report print**, add the capture path. Replace the existing `await print_run_report(...)` tail with:

```python
    await print_run_report(
        solution_result,
        console.console,
        VerificationLevel(verification),
        detailed=detailed,
        skip_printing_limits=sanitized,
    )

    if share is not None:
        from rbx.box import sharing

        rec = sharing.recording_console()
        await print_run_report(
            solution_result,
            rec,
            VerificationLevel(verification),
            detailed=detailed,
            skip_printing_limits=sanitized,
        )
        result = sharing.share_report(
            rec, fmt=share, title='rbx run report',
            out_dir=package.get_problem_build_path(),
        )
        _print_share_result(result)  # small helper printing ✓/fallback line
```

Add `_print_share_result` near the command (or in `sharing.py` as `print_share_result(console, result)`):

```python
def print_share_result(console, result) -> None:
    if result.copied:
        console.print(f'[success]✓ Report copied to clipboard ({result.fmt.upper()}).[/success]')
    elif result.file_path is not None:
        console.print(
            f'[warning]Could not copy to clipboard; wrote report to '
            f'[item]{result.file_path}[/item].[/warning]'
        )
    else:
        console.print('[error]Failed to share report.[/error]')
```

**Step 3: Test (capture content).** Add a test that re-rendering produces expected text. Reuse a package fixture:

```python
# tests/rbx/box/test_sharing.py
import pytest

@pytest.mark.test_pkg('...')  # pick an existing fixture pkg with solutions
async def test_run_report_capture_contains_verdicts(pkg_from_testdata, ...):
    # Build solution_result via the existing run path, render into recording
    # console, assert export_text() contains a known solution name / 'Timing'.
    ...
```

> If wiring a full run in a unit test is heavy, rely on Task 3's unit tests for `sharing` and verify `run --share` manually (Step 4). Do not over-invest here.

**Step 4: Manual verification.**

Run inside a test package:
`uv run rbx run --share=text`
Expected: normal report, then `✓ Report copied to clipboard (TEXT).`; paste shows the report.
`uv run rbx run --share=png` (with `rsvg-convert`/ImageMagick installed): image on clipboard.

**Step 5: Commit**

```bash
git add rbx/box/cli.py rbx/box/sharing.py tests/rbx/box/test_sharing.py
git commit -m "feat(run): add --share to copy run report to clipboard"
```

---

### Task 5: Wire `--share` into `rbx time`

**Files:**
- Modify: `rbx/box/cli.py` (`time` command), `rbx/box/timing.py` (`compute_time_limits`)
- Test: `tests/rbx/box/test_sharing.py`

**Goal:** `time --share` captures the run report (for estimation) + the final per-language-group limits table. (Estimation fastest/slowest/formula lines are optional polish — include only if cheap.)

**Step 1:** Add the same `--share` option to the `time` command signature and validation as Task 4.

**Step 2:** Thread capture into `compute_time_limits`. It already holds `solution_result` and computes `estimated_tl` (a `LimitsProfile`). Add a `share: Optional[str] = None` parameter and, at the end (after `render_limits_table`), build a recording console and render the two pieces into it:

```python
    if share is not None:
        from rbx.box import sharing

        rec = sharing.recording_console()
        await print_run_report(
            solution_result, rec, VerificationLevel(verification),
            detailed=detailed, skip_printing_limits=True,
        )
        rec.print()
        rec.print(limits_info.build_limits_table(limits, title=f'Time limits ({profile})'))
        result = sharing.share_report(
            rec, fmt=share, title='rbx time report',
            out_dir=package.get_problem_build_path(),
        )
        sharing.print_share_result(console.console, result)
```

Pass `share` from the `time` CLI command into `compute_time_limits(... , share=share)`.

> `build_limits_table` returns a `rich.table.Table` (already used by `render_limits_table`). Reuse it — do not re-implement. Confirm `limits` here is the `LimitsProfile` that `render_limits_table` was called with.

**Step 3: Test.** Unit-test the assembly by rendering a known `LimitsProfile` table into a recording console and asserting `export_text` contains a group/time figure. Reuse Task 3 helpers; mock the clipboard.

**Step 4: Manual verification.**
`uv run rbx time -s estimate --share=text`
Expected: after estimation, `✓ Report copied to clipboard (TEXT).`; pasted text contains the run report **and** the language-group limits table.

**Step 5: Commit**

```bash
git add rbx/box/cli.py rbx/box/timing.py tests/rbx/box/test_sharing.py
git commit -m "feat(time): add --share to copy estimation report to clipboard"
```

---

### Task 6: Docs + lint + full test sweep

**Files:**
- Modify: relevant docs page for `rbx run` / `rbx time` (search `docs/` for the commands).
- Modify: `rbx/box/CLAUDE.md` if it documents the reporting flow.

**Steps:**
1. Document the `--share` flag (formats, clipboard behavior, required converters for PNG: install `rsvg-convert` or ImageMagick; Linux needs `xclip`/`wl-copy`). Run `mise run docs` or the project's docs check per CLAUDE.md (use non-strict build; ~9 pre-existing strict warnings are unrelated).
2. `uv run ruff check rbx/box/sharing.py rbx/box/cli.py rbx/box/timing.py && uv run ruff format rbx/box/sharing.py`
3. `uv run pytest tests/rbx/box/test_sharing.py -v`
4. `uv run pytest --ignore=tests/rbx/box/cli -n auto` (note pre-existing local C++/sandbox/docker failures per project memory — unrelated to this change).
5. Commit docs:

```bash
git add docs/ rbx/box/CLAUDE.md
git commit -m "docs(timing): document --share for run and time reports"
```

---

## Open items / risks to validate during execution

1. **Live final-frame capture.** Confirm `print_run_report` rendered into a non-terminal recording console produces the full final grid (not blank). If `LiveRunReporter` suppresses output entirely off-terminal, add a `static: bool` path to the reporter that prints the final table directly. Validate this **first** in Task 4 Step 4 before polishing.
2. **Re-evaluation cost/side-effects.** Re-calling `print_run_report` for capture re-invokes the deferred `await eval()`s. These should be cached; confirm no real re-execution happens. If they do re-run, capture from the first render instead (pass the recording console as a tee is not possible — instead render once into the recorder and replay its text to the live console, or have the reporter expose its final renderable).
3. **`qlmanage` output naming** differs; keep it last and treat its presence as best-effort.
4. **`out_dir` helper name** — confirm the exact build-path accessor in `rbx/box/package.py`.
