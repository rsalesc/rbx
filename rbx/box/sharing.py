import dataclasses
import os
import shutil
import subprocess
import sys
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
