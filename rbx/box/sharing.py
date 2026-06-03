import dataclasses
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

import rich.console

from rbx import console as _console  # for the shared theme

# Ordered preference of SVG->PNG converters. Each entry builds the argv given
# (svg_path, png_path). Only converters that render an SVG faithfully to the
# requested output path belong here (e.g. macOS `qlmanage` is excluded: it is a
# thumbnailer that writes `<name>.png` into a directory, not a real renderer).
_CONVERTERS = [
    ('rsvg-convert', lambda svg, png: ['rsvg-convert', str(svg), '-o', str(png)]),
    ('magick', lambda svg, png: ['magick', str(svg), str(png)]),
    ('convert', lambda svg, png: ['convert', str(svg), str(png)]),
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
    """Convert SVG text to a PNG file. Returns the path on success, or None if no
    converter is available or the conversion failed."""
    converter = detect_png_converter()
    if converter is None:
        return None
    with tempfile.NamedTemporaryFile('w', suffix='.svg', delete=False) as f:
        f.write(svg)
        svg_path = Path(f.name)
    try:
        argv = converter.build_argv(svg_path, png_path)
        subprocess.run(argv, check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    finally:
        svg_path.unlink(missing_ok=True)
    # A zero exit code is not enough: a converter can succeed yet write nothing
    # (or an empty file) to the requested path. Only report success if a usable
    # PNG actually exists.
    try:
        if png_path.stat().st_size == 0:
            return None
    except OSError:
        return None
    return png_path


def _linux_clipboard_tool() -> Optional[str]:
    if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wl-copy'):
        return 'wl-copy'
    if shutil.which('xclip'):
        return 'xclip'
    if shutil.which('wl-copy'):
        return 'wl-copy'
    return None


def _run_clipboard(argv: List[str], input: Optional[bytes] = None) -> bool:
    """Run a clipboard subprocess. Returns True on a zero exit code, False if the
    command fails to launch (OSError) or exits non-zero."""
    try:
        result = subprocess.run(argv, input=input, capture_output=True)
    except OSError:
        return False
    return result.returncode == 0


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
    return _run_clipboard(argv, input=data)


def copy_image_to_clipboard(png_path: Path) -> bool:
    if sys.platform == 'darwin':
        escaped = str(png_path).replace('\\', '\\\\').replace('"', '\\"')
        script = f'set the clipboard to (read (POSIX file "{escaped}") as «class PNGf»)'
        return _run_clipboard(['osascript', '-e', script])
    if sys.platform.startswith('linux'):
        tool = _linux_clipboard_tool()
        if tool == 'xclip':
            argv = ['xclip', '-selection', 'clipboard', '-t', 'image/png']
        elif tool == 'wl-copy':
            argv = ['wl-copy', '--type', 'image/png']
        else:
            return False
        try:
            data = png_path.read_bytes()
        except OSError:
            return False
        return _run_clipboard(argv, input=data)
    return False


def recording_console(width: int = 120) -> rich.console.Console:
    return rich.console.Console(
        theme=_console.theme,
        style='info',
        highlight=False,
        record=True,
        width=width,
        # force_terminal=False keeps is_terminal False so rich.live.Live renders
        # a single final frame instead of animating when we re-render reports.
        force_terminal=False,
        # A non-terminal console would otherwise drop colors from the recording;
        # force truecolor so the exported SVG keeps the report's styling.
        color_system='truecolor',
        # Discard the visible output: we only want the recorded buffer. Without
        # this the re-rendered report would be printed to the real stdout a
        # second time.
        file=io.StringIO(),
    )


def export_text(rec: rich.console.Console) -> str:
    return rec.export_text()


def export_svg(rec: rich.console.Console, title: str) -> str:
    svg = rec.export_svg(title=title)
    # Rich places the spaces that separate styled spans at the start/end of a
    # <text> run. Some SVG rasterizers (e.g. rsvg-convert) trim that leading and
    # trailing whitespace when laying out each run, which drops the separators
    # (`AC solution` -> `ACsolution`). Mark every run as whitespace-preserving so
    # those spaces survive conversion to PNG.
    return svg.replace('<text ', '<text xml:space="preserve" ')


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
    converted = svg_to_png(svg, png_path)
    if converted is not None:
        # PNG was produced this run; try to copy it.
        if copy_image_to_clipboard(png_path):
            return ShareResult(fmt='png', copied=True, file_path=png_path)
        return ShareResult(fmt='png', copied=False, file_path=png_path)
    # No converter available: persist the SVG so the user still has an artifact.
    svg_path = out_dir / 'report.svg'
    svg_path.write_text(svg)
    return ShareResult(fmt='png', copied=False, file_path=svg_path)


def print_share_result(console: rich.console.Console, result: ShareResult) -> None:
    if result.copied:
        console.print(
            f'[success]✓ Report copied to clipboard ({result.fmt.upper()}).[/success]'
        )
    elif result.file_path is not None:
        console.print(
            f'[warning]Could not copy to clipboard; wrote report to '
            f'[item]{result.file_path}[/item].[/warning]'
        )
    else:
        console.print('[error]Failed to share report.[/error]')


def capture_and_share(
    rec: rich.console.Console, *, fmt: str, title: str
) -> ShareResult:
    """Share an already-recorded report: write fallbacks into the package build
    dir, copy to the clipboard, and print the outcome.

    Sharing is a convenience side-effect that runs after the report has already
    been shown, so any failure here (e.g. an unwritable build dir) degrades to a
    warning instead of crashing the command."""
    from rbx.box import package

    try:
        out_dir = package.get_build_path()
        out_dir.mkdir(parents=True, exist_ok=True)
        result = share_report(rec, fmt=fmt, title=title, out_dir=out_dir)
    except OSError as e:
        _console.console.print(f'[warning]Could not share report: {e}.[/warning]')
        return ShareResult(fmt=fmt, copied=False)
    print_share_result(_console.console, result)
    return result
