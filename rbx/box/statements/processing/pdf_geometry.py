"""The size of a one-page PDF figure, read without a PDF library.

What the export needs is the natural size of an externalized TikZ figure, so
an inline one can be given its height (``texsoup_utils.size_inline_figures``)
and MOJ can show every figure at the size it has in the PDF
(``texsoup_utils.size_figures``). pdfTeX
writes the page size as a ``/MediaBox``, which is the figure's bounding box --
TikZ's externalization crops the page to the picture. Since PDF 1.5 the page
dictionary usually sits in a compressed object stream, so the streams are
inflated and searched too.

A best effort by design: anything unexpected returns ``None``, and the figure
is simply left without a height.

A leaf module: the standard library only.
"""

import pathlib
import re
import zlib
from typing import Iterator, Optional, Tuple

_MEDIABOX_RE = re.compile(
    rb'/MediaBox\s*\[\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\]'
)
_STREAM_RE = re.compile(rb'stream\r?\n')


def _inflated_streams(data: bytes) -> Iterator[bytes]:
    for match in _STREAM_RE.finditer(data):
        end = data.find(b'endstream', match.end())
        if end < 0:
            return
        try:
            yield zlib.decompressobj().decompress(data[match.end() : end])
        except zlib.error:
            continue


def media_box(data: bytes) -> Optional[Tuple[float, float]]:
    """``(width, height)`` of the first ``/MediaBox`` in a PDF, in big points."""
    for chunk in (data, *_inflated_streams(data)):
        match = _MEDIABOX_RE.search(chunk)
        if match is None:
            continue
        try:
            x0, y0, x1, y1 = (float(value) for value in match.groups())
        except ValueError:
            continue
        return abs(x1 - x0), abs(y1 - y0)
    return None


def page_size_bp(path: pathlib.Path) -> Optional[Tuple[float, float]]:
    """``(width, height)`` of a one-page PDF in big points (1/72 in, PDF's unit
    and CSS's ``pt``); ``None`` when it cannot be read or is degenerate. Only
    the first page box is read: an externalized figure has one page."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    box = media_box(data)
    if box is None or box[0] <= 0 or box[1] <= 0:
        return None
    return box


def page_height_bp(path: pathlib.Path) -> Optional[float]:
    """The height of a one-page PDF in big points; ``None`` when it cannot be
    read. See :func:`page_size_bp`."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    box = media_box(data)
    if box is None or box[1] <= 0:
        return None
    return box[1]
