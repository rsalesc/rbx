r"""Monospace TeX groups holding math, rewritten as a single math span.

``\texttt{A $a_i$ $t_i$}`` -> ``$\texttt{A}~a_i~t_i$``.

**The defect this exists for.** pandoc's LaTeX reader maps ``\texttt{...}`` to a
``Code`` inline, and a pandoc ``Code`` holds a *string*: it cannot contain
another inline. Given math inside the group pandoc has no node to build, so it
splits the group into siblings instead::

    \texttt{A $a_i$ $t_i$}  ->  Code "A ", Math a_i, Code " ", Math t_i

The math loses its monospace, and the ``Code " "`` separators collapse to an
empty ``<code></code>`` in HTML -- so a reader of the rendered statement sees
the fields glued together as ``Aa_it_i``. Rewriting the group into one math span
gives pandoc a single ``Math`` inline, which reaches MathML intact: monospace
``A`` included, with real spacing between the fields.

**Why a scanner and not TexSoup**, which rbx uses everywhere else it touches
TeX. Three measured reasons, all of them about this transform being whitespace-
and adjacency-sensitive in a way TexSoup's node list is not:

- ``find_all('texttt')`` descends INTO ``\verb|...|`` (the ``verbatim``
  environment is skipped, ``\verb`` is not), so the literal-region skip has to
  be rebuilt by hand anyway -- and getting it wrong rewrites literal text.
- ``.contents`` drops the adjacency this needs. ``\texttt{100\% $n$}`` comes
  back as ``'100'``, ``'\%'``, ``$n$`` -- indistinguishable from ``100 \%``
  except by re-reading the raw token's trailing space, which is the position
  arithmetic ``polygon_utils.convert_to_polygon_tex`` already carries
  ``_fill_gap`` for.
- A ``{\tt ...}`` switch is not a node at all; it runs to the end of its
  enclosing group, which is the ``FONT_SWITCHES``/``BARRIERS`` problem
  ``polygon_utils`` spends ~40 lines on.

The tree would be the right tool if this ever had to *descend* into nested
markup instead of bailing on it. It does not. It also cannot be done on pandoc's
AST, where the ``Code`` a ``\texttt`` left is indistinguishable from the one a
``\verb`` left (same empty attr triple) and the group boundary is already gone.

**Conservative by construction.** Every uncertain case is returned untouched:
rendering a group imperfectly is a much smaller failure than mangling it. The
module is pure text in, text out, with no rbx imports -- so it is testable, and
reusable by any other consumer that has to hand TeX to pandoc.
"""

import re
from typing import List, Optional, Tuple

# The monospace wrappers pandoc reads into a `Code` inline, in both spellings:
# the command and the font switch. `convert_to_polygon_tex` does NOT fold the
# switches into `\texttt`, so both really do reach pandoc.
#
# Every OTHER command in the Polygon TeX subset is fine and must be left alone:
# `\textbf`/`\textit`/`\emph`/`\underline`/`\sout`/`\textsc`/`\textsubscript`/
# `\textsuperscript`, the size switches and `\href` all read into container
# nodes (Strong, Emph, Span, Link, ...) that nest `Math` correctly.
MONOSPACE_COMMANDS = ('texttt',)
MONOSPACE_SWITCHES = ('tt', 'ttfamily')

# Regions whose content is literal, where a `$` is a dollar sign rather than
# math and a `\texttt` is nine characters of text. Rewriting inside one would be
# a corruption, not a fix, so the scanner skips over them wholesale.
LITERAL_ENVIRONMENTS = ('verbatim', 'lstlisting')

_COMMAND = r'\\(?:%s)[ \t]*(?=\{)' % '|'.join(MONOSPACE_COMMANDS)
_SWITCH = r'\{[ \t]*\\(?:%s)(?![A-Za-z])[ \t]*' % '|'.join(MONOSPACE_SWITCHES)
_VERB = r'\\verb\*?(?P<delim>[^*\sA-Za-z])'
_VERBATIM_ENV = r'\\begin\{(?P<env>%s)\}' % '|'.join(LITERAL_ENVIRONMENTS)

_SCAN = re.compile(
    f'(?P<verb>{_VERB})'
    f'|(?P<env_open>{_VERBATIM_ENV})'
    f'|(?P<cmd>{_COMMAND})'
    f'|(?P<switch>{_SWITCH})'
)

# A control word (`\alpha`, `\textbf`) in the text part of a monospace group.
# Only escaped specials (`\%`, `\_` -- backslash then a NON-letter) survive the
# move into math mode unchanged, so anything else bails out.
_CONTROL_WORD = re.compile(r'\\[A-Za-z]')

# An escape sequence, dropped before the unsafe-character check below so that an
# escaped `\%` is not mistaken for the bare `%` it protects.
_ESCAPE = re.compile(r'\\.')

# Bare characters that mean something different inside math than they did in the
# text-mode group they came from. Braces are in the set because they open a
# group or a command argument, which is the nested-markup case.
_UNSAFE_IN_MATH = frozenset('_^%&#{}~')

# What the atoms of a rewritten group are joined with. Math mode discards the
# spaces the source had, so the tie is what keeps the fields of a token like
# `A a_i t_i` visibly apart.
_JOINER = '~'


def _read_group(tex: str, start: int) -> Optional[int]:
    """Index just past the balanced brace group opening at ``tex[start]``.

    ``None`` when the group never closes -- malformed input is passed through
    untouched rather than guessing where it ended.
    """
    depth = 0
    i = start
    while i < len(tex):
        char = tex[i]
        if char == '\\':
            i += 2
            continue
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _split_on_math(body: str) -> Optional[List[Tuple[bool, str]]]:
    r"""``[(is_math, text), ...]`` for a monospace body, or ``None`` to bail.

    Backslash escapes are consumed as a unit, so an escaped ``\$`` is text and
    never opens a math run. Display math and an unclosed ``$`` bail.
    """
    runs: List[Tuple[bool, str]] = []
    text: List[str] = []
    i = 0
    while i < len(body):
        char = body[i]
        if char == '\\':
            if i + 1 >= len(body):
                return None
            text.append(body[i : i + 2])
            i += 2
            continue
        if char != '$':
            text.append(char)
            i += 1
            continue
        if body.startswith('$$', i):
            return None
        runs.append((False, ''.join(text)))
        text = []
        math: List[str] = []
        i += 1
        while i < len(body) and body[i] != '$':
            if body[i] == '\\':
                if i + 1 >= len(body):
                    return None
                math.append(body[i : i + 2])
                i += 2
                continue
            math.append(body[i])
            i += 1
        if i >= len(body):
            return None
        runs.append((True, ''.join(math)))
        i += 1
    runs.append((False, ''.join(text)))
    return runs


def _rewrap_body(body: str) -> Optional[str]:
    r"""One monospace body as a single math span, or ``None`` to leave it alone.

    Each whitespace-separated text word becomes its own ``\texttt{}`` atom and
    each math run contributes its body bare.
    """
    runs = _split_on_math(body)
    if runs is None or not any(is_math for is_math, _ in runs):
        return None
    atoms = []
    for is_math, run in runs:
        if is_math:
            math = run.strip()
            if not math:
                return None
            atoms.append(math)
            continue
        if _CONTROL_WORD.search(run):
            return None
        for word in run.split():
            if _UNSAFE_IN_MATH.intersection(_ESCAPE.sub('', word)):
                return None
            atoms.append(f'\\texttt{{{word}}}')
    return '$' + _JOINER.join(atoms) + '$' if atoms else None


def _skip_literal(tex: str, hit: 're.Match') -> int:
    """Index just past the literal region ``hit`` opened.

    An unterminated region swallows the rest of the input, which is what LaTeX
    itself would do with it.
    """
    if hit.group('verb') is not None:
        closing = tex.find(hit.group('delim'), hit.end())
        return len(tex) if closing < 0 else closing + 1
    closer = f'\\end{{{hit.group("env")}}}'
    closing = tex.find(closer, hit.end())
    return len(tex) if closing < 0 else closing + len(closer)


def rewrap_monospace_math(tex: str) -> str:
    r"""Rewrite every monospace group that holds math into a single math span.

    ``\texttt{A $a_i$ $t_i$}`` -> ``$\texttt{A}~a_i~t_i$``. See the module
    docstring for why, and for why this is a scanner rather than a parse.

    Returned untouched: a group with no math at all (pandoc renders those
    perfectly), one with nested markup, display math, an unbalanced delimiter or
    a bare character that would change meaning in math mode -- and anything
    inside ``\verb`` or a verbatim environment. Text outside a monospace group
    is never modified, so this is a no-op on input that has none.
    """
    out = []
    i = 0
    while True:
        hit = _SCAN.search(tex, i)
        if hit is None:
            break
        out.append(tex[i : hit.start()])
        if hit.group('verb') is not None or hit.group('env_open') is not None:
            end = _skip_literal(tex, hit)
            out.append(tex[hit.start() : end])
            i = end
            continue
        if hit.group('cmd') is not None:
            # `\texttt{body}` -- the group opens after the command name.
            end = _read_group(tex, hit.end())
            body_start = hit.end() + 1
        else:
            # `{\tt body}` -- the group is what the switch is scoped by, so it
            # opened at the match itself.
            end = _read_group(tex, hit.start())
            body_start = hit.end()
        if end is None:
            # The group never closes. Everything from the command on is passed
            # through as-is -- and `i` must be rewound to it, since the text
            # before it has already been emitted and the tail below starts at
            # `i`. (Leaving `i` where it was duplicated that text.)
            i = hit.start()
            break
        rewrapped = _rewrap_body(tex[body_start : end - 1])
        out.append(tex[hit.start() : end] if rewrapped is None else rewrapped)
        i = end
    out.append(tex[i:])
    return ''.join(out)
