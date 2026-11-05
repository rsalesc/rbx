"""The size options an ``\\includegraphics`` needs for an HTML renderer.

A PDF lays a figure out at its natural size, or at the size its options ask
for. An HTML renderer shows an unsized image at its *pixel* size instead --
for a figure rasterized at 300 DPI, 3.125 times too large -- so a target
rendering to HTML (MOJ) has to spell the size out. ``figure_options`` turns
what the author wrote into that size, times a ``scale`` the target picks to
keep figures the same size relative to its text.

What it writes:

- **No size given**: the natural size (the PDF's ``/MediaBox``, a raster's
  pixels over its DPI), times ``scale=`` if there is one.
- **An absolute length** (``pt``, ``bp``, ``cm``, ``mm``, ``in``, ``pc``,
  ``dd``, ``cc``, ``sp``): that length.
- **A fraction of the line width** (``0.5\\textwidth``, ``\\linewidth``,
  ``\\columnwidth``, ``\\hsize``) for ``width``: the same fraction, as
  ``<f>\\textwidth``, which pandoc turns into ``width="50%"``. It is relative
  to the column already, so ``scale`` does not touch it.
- **A font-relative length** (``em``, ``ex``): left as written. It is relative
  to the text already, which is what ``scale`` is there to approximate.

Absolute sizes are multiplied by ``scale`` and written as ``pt`` holding the
big-point number: pandoc keeps ``pt`` (it drops ``bp``), and CSS's ``pt`` is
the big point.

A **display** figure gets a width only, so the renderer's ``max-width: 100%``
can still shrink it on a narrow screen without distorting it; an author's
height is converted into that width through the figure's aspect ratio when the
natural size is known. An **inline** figure, sitting in a line of text, gets a
height, the dimension that has to agree with the text around it.

Anything else is left exactly as the author wrote it (``None``): a key that
changes the geometry (``angle``, ``trim``, ``viewport``, ``bb``, ...), a
length that is an expression, a height relative to the page, or no size at
all with no natural size to fall back on.

A leaf module: the standard library only.
"""

import re
from typing import Dict, List, Optional, Tuple, Union

Size = Tuple[float, float]

# TeX's units, in big points.
_PT = 72.0 / 72.27
_UNITS_BP = {
    'pt': _PT,
    'bp': 1.0,
    'in': 72.0,
    'cm': 72.0 / 2.54,
    'mm': 72.0 / 25.4,
    'pc': 12.0 * _PT,
    'dd': 1238.0 / 1157.0 * _PT,
    'cc': 12.0 * 1238.0 / 1157.0 * _PT,
    'sp': _PT / 65536.0,
}
_FONT_UNITS = ('em', 'ex')
_LINE_WIDTHS = ('textwidth', 'linewidth', 'columnwidth', 'hsize')

_NUMBER = r'[+]?(?:\d+(?:\.\d*)?|\.\d+)'
_ABSOLUTE_RE = re.compile(rf'({_NUMBER})\s*({"|".join(_UNITS_BP)})')
_FONT_RE = re.compile(rf'({_NUMBER})\s*({"|".join(_FONT_UNITS)})')
_LINE_WIDTH_RE = re.compile(rf'({_NUMBER})?\s*\\({"|".join(_LINE_WIDTHS)})')
_SCALE_RE = re.compile(_NUMBER)

# The keys this module understands; any other leaves the figure alone.
_SIZE_KEYS = frozenset({'width', 'height', 'scale', 'keepaspectratio'})


class _Absolute(float):
    """A length in big points."""


class _Font(str):
    """A font-relative length, kept as written."""


class _LineWidth(float):
    """A fraction of the line width."""


_Length = Union[_Absolute, _Font, _LineWidth]


def _split_options(options: str) -> Optional[List[Tuple[str, Optional[str]]]]:
    """``key=value`` pairs (``value`` is ``None`` for a bare flag), split at
    the commas outside braces; ``None`` when the braces do not balance."""
    items: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in options:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                return None
        if ch == ',' and depth == 0:
            items.append(''.join(current))
            current = []
            continue
        current.append(ch)
    if depth != 0:
        return None
    items.append(''.join(current))

    pairs: List[Tuple[str, Optional[str]]] = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        key, sep, value = item.partition('=')
        value = value.strip()
        if sep and value.startswith('{') and value.endswith('}'):
            value = value[1:-1].strip()
        pairs.append((key.strip(), value if sep else None))
    return pairs


def _length(value: str) -> Optional[_Length]:
    value = value.strip()
    match = _ABSOLUTE_RE.fullmatch(value)
    if match is not None:
        return _Absolute(float(match.group(1)) * _UNITS_BP[match.group(2)])
    match = _LINE_WIDTH_RE.fullmatch(value)
    if match is not None:
        return _LineWidth(float(match.group(1) or 1))
    if _FONT_RE.fullmatch(value) is not None:
        return _Font(value)
    return None


def _format_number(value: float) -> str:
    return f'{value:.4f}'.rstrip('0').rstrip('.') or '0'


def _format_pt(value: float) -> str:
    return f'{value:.2f}'.rstrip('0').rstrip('.') + 'pt'


def _write(length: _Length, scale: float) -> str:
    if isinstance(length, _Absolute):
        return _format_pt(length * scale)
    if isinstance(length, _LineWidth):
        # A leading digit: pandoc reads `.5\textwidth` as raw text, not 50%.
        return f'{_format_number(length)}\\textwidth'
    return str(length)


def figure_options(
    options: Optional[str],
    natural: Optional[Size],
    *,
    scale: float,
    inline: bool,
) -> Optional[str]:
    """The ``\\includegraphics`` options (without brackets) that give the
    figure its size in HTML, or ``None`` to leave the figure as it is.

    ``options`` is what the author wrote between the brackets (``None`` for
    no brackets), ``natural`` the figure's natural size in big points,
    ``scale`` the target's figure scale and ``inline`` whether the figure sits
    in running text. See the module docstring for the rules."""
    pairs = _split_options(options or '')
    if pairs is None:
        return None
    if any(key not in _SIZE_KEYS for key, _ in pairs):
        return None
    if natural is not None and (natural[0] <= 0 or natural[1] <= 0):
        natural = None

    values: Dict[str, Optional[str]] = dict(pairs)
    width = height = None
    if values.get('width') is not None:
        width = _length(values['width'] or '')
        if width is None:
            return None
    if values.get('height') is not None:
        height = _length(values['height'] or '')
        # A height relative to the line width means nothing in HTML.
        if height is None or isinstance(height, _LineWidth):
            return None
    factor = 1.0
    if values.get('scale') is not None:
        match = _SCALE_RE.fullmatch((values['scale'] or '').strip())
        if match is None or float(match.group(0)) <= 0:
            return None
        factor = float(match.group(0))

    if isinstance(width, _LineWidth):
        # The renderer keeps the aspect ratio from the width alone.
        return f'width={_write(width, scale)}'

    if width is None and height is None:
        if natural is None:
            return None
        if inline:
            return f'height={_format_pt(natural[1] * factor * scale)}'
        return f'width={_format_pt(natural[0] * factor * scale)}'

    if (
        width is None
        and isinstance(height, _Absolute)
        and not inline
        and natural is not None
    ):
        return f'width={_format_pt(height * natural[0] / natural[1] * scale)}'

    parts = []
    if width is not None:
        parts.append(f'width={_write(width, scale)}')
    if height is not None:
        parts.append(f'height={_write(height, scale)}')
    return ','.join(parts)
