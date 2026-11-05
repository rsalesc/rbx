"""The size a figure file has in the PDF, read without an imaging library.

pdfTeX lays an ``\\includegraphics`` with no size options out at the file's
*natural* size, and that is the size an HTML renderer needs to be told, since
it would otherwise show a raster at its pixel size:

- a **PDF** at its ``/MediaBox`` (``pdf_geometry``);
- a **PNG** or **JPEG** at its pixel size over its resolution: the PNG
  ``pHYs`` chunk, or the JPEG JFIF density. A file that records none is laid
  out at 72 DPI -- pdfTeX's ``\\pdfimageresolution`` default -- so one pixel
  is one big point, exactly as the PDF shows it.

Anything else (SVG, GIF, a JPEG whose resolution lives only in EXIF, a file
that cannot be read) is ``None``: the figure is left to the renderer.

A leaf module: the standard library and ``pdf_geometry`` only.
"""

import pathlib
import struct
from typing import Optional, Tuple

from rbx.box.statements.processing import pdf_geometry

# pdfTeX's `\pdfimageresolution` default, used for a raster that records none.
DEFAULT_DPI = 72.0

_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
_METERS_PER_INCH = 0.0254
_CM_PER_INCH = 2.54

# The JPEG start-of-frame markers, which carry the pixel size: every SOFn but
# DHT (C4), JPG (C8) and DAC (CC).
_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}

Size = Tuple[float, float]


def _bp(pixels: Tuple[int, int], dpi: Tuple[float, float]) -> Optional[Size]:
    width, height = pixels
    if width <= 0 or height <= 0:
        return None
    return width * 72.0 / dpi[0], height * 72.0 / dpi[1]


def png_size_bp(data: bytes) -> Optional[Size]:
    """``(width, height)`` of a PNG in big points; see the module docstring."""
    if not data.startswith(_PNG_SIGNATURE):
        return None
    pixels: Optional[Tuple[int, int]] = None
    dpi = (DEFAULT_DPI, DEFAULT_DPI)
    i = len(_PNG_SIGNATURE)
    while i + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[i : i + 8])
        body = data[i + 8 : i + 8 + length]
        if len(body) < length:
            break
        if kind == b'IHDR' and length >= 8:
            pixels = struct.unpack('>II', body[:8])
        elif kind == b'pHYs' and length >= 9:
            x, y, unit = struct.unpack('>IIB', body[:9])
            # Unit 0 is an aspect ratio, not a resolution.
            if unit == 1 and x > 0 and y > 0:
                dpi = (x * _METERS_PER_INCH, y * _METERS_PER_INCH)
        elif kind in (b'IDAT', b'IEND'):
            break
        i += 12 + length
    if pixels is None:
        return None
    return _bp(pixels, dpi)


def jpeg_size_bp(data: bytes) -> Optional[Size]:
    """``(width, height)`` of a JPEG in big points; see the module docstring."""
    if not data.startswith(b'\xff\xd8'):
        return None
    dpi = (DEFAULT_DPI, DEFAULT_DPI)
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no length
            i += 2
            continue
        (length,) = struct.unpack('>H', data[i + 2 : i + 4])
        body = data[i + 4 : i + 2 + length]
        if marker == 0xE0 and body.startswith(b'JFIF\x00') and len(body) >= 12:
            unit = body[7]
            x, y = struct.unpack('>HH', body[8:12])
            if x > 0 and y > 0 and unit in (1, 2):
                factor = 1.0 if unit == 1 else _CM_PER_INCH
                dpi = (x * factor, y * factor)
        elif marker in _SOF_MARKERS and len(body) >= 5:
            height, width = struct.unpack('>HH', body[1:5])
            return _bp((width, height), dpi)
        elif marker == 0xDA:  # start of scan, and no frame header yet
            return None
        i += 2 + length
    return None


def natural_size_bp(path: Optional[pathlib.Path]) -> Optional[Size]:
    """``(width, height)`` in big points of the figure at ``path`` as pdfTeX
    lays it out, or ``None`` when that cannot be told. Dispatches on the
    suffix, as ``\\includegraphics`` does."""
    if path is None:
        return None
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        return pdf_geometry.page_size_bp(path)
    readers = {'.png': png_size_bp, '.jpg': jpeg_size_bp, '.jpeg': jpeg_size_bp}
    reader = readers.get(suffix)
    if reader is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return reader(data)
