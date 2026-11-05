"""The size of a one-page PDF figure, read without a PDF library.

What the export needs is the natural height of an externalized TikZ figure, so
an inline one can be given it (``texsoup_utils.size_inline_figures``). pdfTeX
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

# PDF user space is in big points (1/72 in); TeX's `pt` is 1/72.27 in.
_PT_PER_BP = 72.27 / 72


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


def page_height_pt(path: pathlib.Path) -> Optional[float]:
    """The height of a one-page PDF, in TeX points; ``None`` when it cannot be
    read."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    box = media_box(data)
    if box is None or box[1] <= 0:
        return None
    return box[1] * _PT_PER_BP
