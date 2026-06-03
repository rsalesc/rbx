import dataclasses
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

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
