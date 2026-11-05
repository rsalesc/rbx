r"""Text-mode symbol and spacing commands, translated before pandoc reads them.

pandoc's LaTeX reader **drops** a long tail of ordinary text commands --
``\textbar``, ``\space``, ``\quad``, ``\textrightarrow`` -- with nothing but an
INFO line nobody sees, so a statement exported to Markdown (MOJ) silently loses
them. This module is the one table of what rbx puts in their place, and the
scanner that applies it.

**Adding a symbol is one row in** ``TEXT_SYMBOLS`` (plus one row in the
parametrized test). A row names the command, what replaces it on the Markdown
path, and how many arguments it takes. The replacement is *TeX text that pandoc
reads back as the intended character* -- almost always the Unicode character
itself, which pandoc passes through untouched, and ``\_`` / ``\{`` where the raw
character would mean something to TeX.

``PANDOC_NATIVE`` is the other half: the text commands pandoc already converts
on its own. Nothing here touches them; the list exists so the statement
validator can count them as supported, and so a test notices the day a pandoc
upgrade stops converting one.

TeX's rules are respected:

- A control word swallows the blanks after it (and one line break): ``\textbar
  b`` is ``|b``. A following empty group is swallowed too, so ``\textbar{}``
  and ``\textbar{} b`` keep their meaning; ``\textbar\ b`` keeps its control
  space, which pandoc reads. A control symbol (``\:``) swallows nothing.
- Only **text mode** is translated. Math (``$…$``, ``$$…$$``, ``\(…\)``,
  ``\[…\]``, the display-math environments) is copied untouched -- MathJax and
  MathML handle ``\mid`` and friends there, and ``\textbar`` inside math is not
  this module's business.
- Nothing inside ``\verb``, a verbatim environment, a comment, or the URL / file
  argument of ``\url``, ``\href`` and ``\includegraphics`` is touched.

A leaf module: the standard library and ``tex_scan`` only.
"""

import dataclasses
import math
import re
from typing import Callable, Dict, FrozenSet, Optional, Union

from rbx.box.statements.processing import tex_scan

EM_SPACE = ' '
EN_SPACE = ' '
THIN_SPACE = ' '

# A replacement is literal TeX text, or -- for a command taking an argument --
# a function of that argument's text.
Replacement = Union[str, Callable[[str], str]]


@dataclasses.dataclass(frozen=True)
class TextSymbol:
    """One translatable command.

    ``markdown`` is what replaces it in the TeX handed to pandoc on the Markdown
    path. ``arguments`` is 0 for a symbol, or 1 for a command such as
    ``\\hspace{<len>}``, whose ``markdown`` is then a function of the argument.
    ``star`` accepts the ``\\name*`` form as well.
    """

    name: str
    markdown: Replacement
    arguments: int = 0
    star: bool = False

    def replace(self, argument: Optional[str] = None) -> str:
        if callable(self.markdown):
            return self.markdown(argument or '')
        return self.markdown


# Points per unit, at TeX's definitions (`1in = 72.27pt`).
_POINTS = {
    'pt': 1.0,
    'bp': 72.27 / 72,
    'pc': 12.0,
    'in': 72.27,
    'cm': 72.27 / 2.54,
    'mm': 72.27 / 25.4,
    'sp': 1 / 65536,
}
# A statement's body font: 11pt is the default preset's, and the em and ex of
# a 11pt Computer Modern are close enough for picking Unicode spaces.
_FONT_PT = 11.0
_EX_IN_EM = 0.43
# Beyond this an `\hspace` is layout, not spacing between words.
_MAX_EMS = 8
_LENGTH_RE = re.compile(r'^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*([a-z]{2})\s*$')


def length_in_em(length: str) -> Optional[float]:
    """A TeX length in ems, or ``None`` when it is not a plain dimension
    (``\\fill``, ``\\stretch{1}``, ``0.5\\linewidth``, an unknown unit)."""
    match = _LENGTH_RE.match(length)
    if match is None:
        return None
    value, unit = float(match.group(1)), match.group(2)
    if unit == 'em':
        return value
    if unit == 'ex':
        return value * _EX_IN_EM
    if unit in _POINTS:
        return value * _POINTS[unit] / _FONT_PT
    return None


def hspace_to_spaces(length: str) -> str:
    """The closest run of em, en and thin spaces to a ``\\hspace``.

    A length that is no plain dimension (``\\fill``, ``\\stretch``) becomes one
    space: flowing Markdown has no horizontal fill. A zero or negative one
    becomes nothing.
    """
    ems = length_in_em(length)
    if ems is None:
        return ' '
    if ems <= 0:
        return ''
    ems = min(ems, _MAX_EMS)
    whole = math.floor(ems)
    rest = ems - whole
    spaces = EM_SPACE * whole
    if rest >= 0.75:
        spaces += EM_SPACE
    elif rest >= 0.375:
        spaces += EN_SPACE
    elif rest >= 0.1 or not spaces:
        spaces += THIN_SPACE
    return spaces


def _rows(*rows: TextSymbol) -> Dict[str, TextSymbol]:
    table: Dict[str, TextSymbol] = {}
    for row in rows:
        assert row.name not in table, f'duplicate text symbol: {row.name}'
        table[row.name] = row
    return table


TEXT_SYMBOLS: Dict[str, TextSymbol] = _rows(
    # Punctuation and delimiters.
    TextSymbol('textbar', '|'),
    TextSymbol('textbardbl', '‖'),
    TextSymbol('textunderscore', r'\_'),
    TextSymbol('textbraceleft', r'\{'),
    TextSymbol('textbraceright', r'\}'),
    TextSymbol('textendash', '–'),
    TextSymbol('textemdash', '—'),
    TextSymbol('textellipsis', '…'),
    TextSymbol('textquotedbl', '"'),
    TextSymbol('textlangle', '⟨'),
    TextSymbol('textrangle', '⟩'),
    TextSymbol('textperiodcentered', '·'),
    TextSymbol('textvisiblespace', '␣'),
    TextSymbol('textexclamdown', '¡'),
    TextSymbol('textquestiondown', '¿'),
    TextSymbol('guillemotleft', '«'),
    TextSymbol('guillemotright', '»'),
    TextSymbol('textfractionsolidus', '⁄'),
    # Operators and arrows.
    TextSymbol('texttimes', '×'),
    TextSymbol('textdiv', '÷'),
    TextSymbol('textpm', '±'),
    TextSymbol('textminus', '−'),
    TextSymbol('textleftarrow', '←'),
    TextSymbol('textrightarrow', '→'),
    TextSymbol('textuparrow', '↑'),
    TextSymbol('textdownarrow', '↓'),
    # Marks and currency.
    TextSymbol('texteuro', '€'),
    TextSymbol('textcent', '¢'),
    TextSymbol('texttrademark', '™'),
    TextSymbol('textnumero', '№'),
    TextSymbol('textdaggerdbl', '‡'),
    TextSymbol('textasteriskcentered', '∗'),
    TextSymbol('textopenbullet', '◦'),
    TextSymbol('textreferencemark', '※'),
    TextSymbol('checkmark', '✓'),
    # Horizontal space.
    TextSymbol('space', ' '),
    TextSymbol('quad', EM_SPACE),
    TextSymbol('qquad', EM_SPACE * 2),
    TextSymbol('enspace', EN_SPACE),
    TextSymbol('thinspace', THIN_SPACE),
    TextSymbol('negthinspace', ''),
    TextSymbol('nobreakspace', ' '),
    TextSymbol('hfill', ' '),
    TextSymbol('hspace', hspace_to_spaces, arguments=1, star=True),
    # Text-mode control symbols (`\,` pandoc converts itself).
    TextSymbol(':', ' '),
    TextSymbol(';', ' '),
    TextSymbol('!', ''),
    # Vertical space and page layout: nothing to show in flowing Markdown, and
    # nothing lost by dropping them -- so they are dropped here, where it is a
    # decision, rather than by pandoc, which reports each one as lost content.
    TextSymbol('vspace', '', arguments=1, star=True),
    TextSymbol('smallskip', ''),
    TextSymbol('medskip', ''),
    TextSymbol('bigskip', ''),
    TextSymbol('vfill', ''),
    TextSymbol('noindent', ''),
    TextSymbol('indent', ''),
    TextSymbol('centering', ''),
    TextSymbol('newpage', ''),
    TextSymbol('clearpage', ''),
    TextSymbol('pagebreak', ''),
)

# Text commands pandoc 3.7 converts on its own (checked with `pandoc -f latex`).
# Kept so the validator counts them as supported; `test_text_symbols.py` runs
# each through the installed pandoc so a regression is noticed.
PANDOC_NATIVE: FrozenSet[str] = frozenset(
    {
        'textless',
        'textgreater',
        'textbackslash',
        'textasciitilde',
        'textasciicircum',
        'textdollar',
        'textquotesingle',
        'textquoteleft',
        'textquoteright',
        'textquotedblleft',
        'textquotedblright',
        'textbullet',
        'textdegree',
        'textmu',
        'textonehalf',
        'textonequarter',
        'textthreequarters',
        'textyen',
        'textsterling',
        'textcopyright',
        'textregistered',
        'textsection',
        'textparagraph',
        'textdagger',
        'S',
        'P',
        'ss',
        'slash',
        'dots',
        'ldots',
        'linebreak',
        'newline',
    }
)


def supported_names() -> FrozenSet[str]:
    """Every command name the Markdown path shows: translated or native. A
    starred row contributes ``name*`` too, as the validator spells it."""
    names = set(PANDOC_NATIVE)
    for row in TEXT_SYMBOLS.values():
        names.add(row.name)
        if row.star:
            names.add(row.name + '*')
    return frozenset(names)


# Display-math environments, copied untouched.
_MATH_ENVIRONMENTS = frozenset(
    {
        'math',
        'displaymath',
        'equation',
        'equation*',
        'align',
        'align*',
        'gather',
        'gather*',
        'multline',
        'multline*',
        'eqnarray',
        'eqnarray*',
    }
)

# Commands whose arguments are a URL or a file name: copied untouched, so a `~`
# or a `\_` inside one keeps meaning what it meant.
_OPAQUE_ARGUMENTS = {'url': 1, 'href': 1, 'includegraphics': 1}


def _skip_math(text: str, i: int) -> int:
    """``text[i]`` is ``$``: the index past the math it opens (``$…$`` or
    ``$$…$$``), or the end of the text when it never closes."""
    delimiter = '$$' if text.startswith('$$', i) else '$'
    j = i + len(delimiter)
    n = len(text)
    while j < n:
        ch = text[j]
        if ch == '\\':
            _, j = tex_scan.read_control_sequence(text, j)
            continue
        if ch == '%':
            j = tex_scan.skip_comment(text, j)
            continue
        if text.startswith(delimiter, j):
            return j + len(delimiter)
        j += 1
    return n


def _skip_until(text: str, i: int, closing: str) -> int:
    """The index past the control symbol ``closing`` (``\\)`` or ``\\]``)."""
    j = i
    n = len(text)
    while j < n:
        if text[j] == '\\':
            name, k = tex_scan.read_control_sequence(text, j)
            if name == closing:
                return k
            j = k
            continue
        if text[j] == '%':
            j = tex_scan.skip_comment(text, j)
            continue
        j += 1
    return n


def _swallow_after_control_word(text: str, i: int) -> int:
    """What a control word swallows after itself: blanks, at most one line
    break (two would be a paragraph), and then one empty ``{}``."""
    j = tex_scan.skip_blanks(text, i, newlines=False)
    if j < len(text) and text[j] in '\r\n':
        k = tex_scan.skip_blanks(text, j + 1, newlines=False)
        if k < len(text) and text[k] in '\r\n':
            return j
        j = k
    if text.startswith('{}', j):
        return j + 2
    return j


def _skip_opaque_arguments(text: str, i: int, count: int) -> int:
    """Past an optional ``[...]`` and ``count`` mandatory arguments."""
    j = tex_scan.skip_blanks(text, i, newlines=False)
    if j < len(text) and text[j] == '[':
        end = tex_scan.read_group(text, j, '[')
        if end is None:
            return i
        j = end
    for _ in range(count):
        argument = tex_scan.read_argument(text, j)
        if argument is None:
            return j
        j = argument[2]
    return j


def translate_text_symbols(
    tex: str, table: Optional[Dict[str, TextSymbol]] = None
) -> str:
    """Replace every ``TEXT_SYMBOLS`` command in ``tex``'s text mode.

    Text in, text out; anything the table does not name is copied byte for
    byte, so an input with nothing to translate comes back unchanged.
    """
    if table is None:
        table = TEXT_SYMBOLS
    out = []
    i = 0
    n = len(tex)
    copied = 0

    def flush(upto: int) -> None:
        nonlocal copied
        out.append(tex[copied:upto])
        copied = upto

    while i < n:
        ch = tex[i]
        if ch == '%':
            i = tex_scan.skip_comment(tex, i)
            continue
        if ch == '$':
            i = _skip_math(tex, i)
            continue
        if ch != '\\':
            i += 1
            continue

        name, j = tex_scan.read_control_sequence(tex, i)
        verbatim_end = tex_scan.skip_verbatim(tex, name, j)
        if verbatim_end is not None:
            i = verbatim_end
            continue
        if name == '(':
            i = _skip_until(tex, j, ')')
            continue
        if name == '[':
            i = _skip_until(tex, j, ']')
            continue
        if name == 'begin':
            parsed = tex_scan.read_environment_name(tex, j)
            if parsed is not None and parsed[0] in _MATH_ENVIRONMENTS:
                end = tex_scan.find_environment_end(tex, parsed[1], parsed[0])
                i = n if end is None else end
                continue
        if name in _OPAQUE_ARGUMENTS:
            i = _skip_opaque_arguments(tex, j, _OPAQUE_ARGUMENTS[name])
            continue

        row = table.get(name)
        if row is None:
            i = j
            continue

        is_word = bool(name) and tex_scan.is_letter(name[0])
        end = j
        if row.star and end < n and tex[end] == '*':
            end += 1
        argument = None
        if row.arguments:
            parsed_argument = tex_scan.read_argument(tex, end)
            if parsed_argument is None:
                # A malformed use: leave it for pandoc (and the warnings).
                i = j
                continue
            argument, _, end = parsed_argument
        elif is_word:
            end = _swallow_after_control_word(tex, end)

        flush(i)
        out.append(row.replace(argument))
        copied = end
        i = end

    flush(n)
    return ''.join(out)
