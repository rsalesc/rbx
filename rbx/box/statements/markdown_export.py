"""Polygon-TeX statement blocks, converted to pandoc-flavored Markdown.

The input is not arbitrary LaTeX: ``get_processed_statement_blocks`` has already
reduced it to the **Polygon TeX subset** (``polygon_utils.PolygonTeXConfig``), a
closed set of ~25 commands and 6 environments with unrestricted MathJax inside
``$…$``.

The converter is **pandoc**, and that is a target choice rather than a
compromise: MOJ renders statements by running pandoc over them
(``mojtools/render-statement.sh``), so pandoc-flavored Markdown is the dialect
the consumer reads back. Fenced divs, grid tables and attribute spans all
round-trip, and ``$…$`` survives to MathML untouched.

The conversion goes through pandoc's **JSON AST** rather than straight to
Markdown, because one defect has to be corrected on the way: pandoc's LaTeX
reader gives every ``\\includegraphics`` the alt text ``image``, and non-empty
alt text triggers ``implicit_figures`` on MOJ's side, captioning every figure
"image". Clearing it on the AST is robust against captions, attributes and
nested contexts in a way a regex over ``![image](`` is not, and it gives any
later fix a home.

A second defect has to be corrected *before* pandoc runs, on the TeX --
monospace wrappers holding math (see ``rewrap_monospace_math``). So the output
here is deliberately **not** what a plain ``pandoc -f latex -t markdown`` would
produce.

**The goldens in ``tests/.../testdata/markdown_export`` are pandoc-version
sensitive.** They record what a specific pandoc emits; a diff there means pandoc
changed its Markdown writer, not that the expectation was wrong.
"""

import json
import re
from typing import Any, Callable, Optional

from rbx import tooling


class MojGateError(ValueError):
    """A converted block would trip MOJ's statement release gate.

    A ``ValueError`` subclass, matching ``StatementExportError``: a consumer that
    already catches ``ValueError`` keeps working, and a CLI boundary can turn
    exactly these setter mistakes into a clean message.
    """


def _fix_images(node: Any, rewrite_url: Optional[Callable[[str], str]]) -> None:
    """Normalize every ``Image`` in a pandoc AST, in place.

    A pandoc ``Image`` is ``{'t': 'Image', 'c': [attr, [inlines], [url, title]]}``:
    the alt inlines are that middle element, and the url is the first of the last.
    The alt is always cleared; ``rewrite_url``, when given, replaces the url --
    which is how a consumer that ships no image files at all (MOJ, inlining
    base64) gets one.
    """
    if isinstance(node, list):
        for child in node:
            _fix_images(child, rewrite_url)
        return
    if not isinstance(node, dict):
        return
    if node.get('t') == 'Image' and isinstance(node.get('c'), list):
        node['c'][1] = []
        if rewrite_url is not None:
            target = node['c'][2]
            target[0] = rewrite_url(target[0])
        return
    for value in node.values():
        _fix_images(value, rewrite_url)


# The monospace wrappers pandoc reads into a `Code` inline. A pandoc `Code`
# holds a *string*, so it cannot contain another inline: given math inside one,
# pandoc has no node to build and splits the group into siblings instead --
# `\texttt{A $a_i$ $t_i$}` becomes `Code "A "`, `Math a_i`, `Code " "`,
# `Math t_i`. The math loses its monospace, and the `Code " "` separators
# collapse to `<code></code>` in HTML, so MOJ shows the reader `Aa_it_i`.
#
# Every OTHER command in the Polygon TeX subset is fine and must be left alone:
# `\textbf`/`\textit`/`\emph`/`\underline`/`\sout`/`\textsc`/`\textsubscript`/
# `\textsuperscript`, the size switches and `\href` all read into container
# nodes (Strong, Emph, Span, Link, ...) that nest `Math` correctly.
_TEXTTT = r'\\texttt[ \t]*(?=\{)'
_TT_SWITCH = r'\{[ \t]*\\(?:tt|ttfamily)(?![A-Za-z])[ \t]*'

# Regions whose content is literal, where a `$` is a dollar sign rather than
# math and a `\texttt` is six characters of text. Rewriting inside one would be
# a corruption, not a fix, so the scanner skips over them wholesale.
_VERB = r'\\verb\*?(?P<delim>[^*\sA-Za-z])'
_VERBATIM_ENV = r'\\begin\{(?P<env>verbatim|lstlisting)\}'

_SCAN = re.compile(
    f'(?P<verb>{_VERB})'
    f'|(?P<env_open>{_VERBATIM_ENV})'
    f'|(?P<cmd>{_TEXTTT})'
    f'|(?P<switch>{_TT_SWITCH})'
)

# A control word (`\alpha`, `\textbf`) in the text part of a monospace group.
# Only escaped specials (`\%`, `\_` -- backslash then a NON-letter) survive the
# move into math mode unchanged, so anything else bails out.
_CONTROL_WORD = re.compile(r'\\[A-Za-z]')

# Bare characters that mean something different inside math than they did in the
# text-mode group they came from. Braces are in the set because they open a
# group or a command argument, which is the nested-markup case.
_UNSAFE_IN_MATH = frozenset('_^%&#{}~')


def _read_group(tex: str, start: int) -> Optional[int]:
    """Index just past the balanced brace group opening at ``tex[start]``.

    ``None`` when the group never closes -- malformed input rbx passes through
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


def _split_on_math(body: str) -> Optional[list]:
    """``[(is_math, text), ...]`` for a monospace body, or ``None`` to bail.

    Backslash escapes are consumed as a unit, so an escaped ``\\$`` is text and
    never opens a math run. Display math and an unclosed ``$`` bail.
    """
    runs = []
    text: list = []
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
        math: list = []
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
    """One monospace body as a single math span, or ``None`` to leave it alone.

    Each whitespace-separated text word becomes its own ``\\texttt{}`` atom and
    each math run contributes its body bare; the atoms are joined with ``~``.
    Math mode discards the spaces the source had, so the tie is what keeps the
    fields of a token like ``A a_i t_i`` visibly apart.
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
            if _UNSAFE_IN_MATH.intersection(re.sub(r'\\.', '', word)):
                return None
            atoms.append(f'\\texttt{{{word}}}')
    return '$' + '~'.join(atoms) + '$' if atoms else None


def rewrap_monospace_math(tex: str) -> str:
    """Rewrite every monospace group that holds math into a single math span.

    ``\\texttt{A $a_i$ $t_i$}`` -> ``$\\texttt{A}~a_i~t_i$``, which pandoc reads
    as one ``Math`` inline and renders to a single MathML node -- monospace ``A``
    included, and with real spacing between the fields. See ``_SCAN`` for why
    this cannot be done on the AST instead: there, the ``Code`` a ``\\texttt``
    left is indistinguishable from the one a ``\\verb`` left.

    Conservative by construction: a group with no math, with nested markup, with
    display math or with an unbalanced delimiter is returned untouched, as is
    anything inside a verbatim region. Rendering such a group imperfectly is a
    much smaller failure than mangling it.
    """
    out = []
    i = 0
    while True:
        hit = _SCAN.search(tex, i)
        if hit is None:
            break
        out.append(tex[i : hit.start()])
        if hit.group('verb') is not None:
            closing = tex.find(hit.group('delim'), hit.end())
            end = len(tex) if closing < 0 else closing + 1
            out.append(tex[hit.start() : end])
            i = end
            continue
        if hit.group('env_open') is not None:
            closing = tex.find(f'\\end{{{hit.group("env")}}}', hit.end())
            end = len(tex) if closing < 0 else closing + len(hit.group('env')) + 6
            out.append(tex[hit.start() : end])
            i = end
            continue
        if hit.group('cmd') is not None:
            end = _read_group(tex, hit.end())
            body_start = hit.end() + 1
        else:
            end = _read_group(tex, hit.start())
            body_start = hit.end()
        if end is None:
            break
        rewrapped = _rewrap_body(tex[body_start : end - 1])
        out.append(tex[hit.start() : end] if rewrapped is None else rewrapped)
        i = end
    out.append(tex[i:])
    return ''.join(out)


def tex_to_markdown(
    tex: str, *, rewrite_image_url: Optional[Callable[[str], str]] = None
) -> str:
    """Convert one Polygon-TeX block to Markdown.

    ``rewrite_image_url`` maps each image reference to what the document should
    cite instead. It runs on the AST rather than over the emitted Markdown so a
    replacement may be arbitrary text -- a multi-kilobyte ``data:`` URI included,
    which pandoc's writer then escapes and wraps correctly on its own.
    """
    import pypandoc

    tooling.PANDOC.ensure()

    ast = json.loads(
        pypandoc.convert_text(rewrap_monospace_math(tex), 'json', format='latex')
    )
    _fix_images(ast, rewrite_image_url)
    return pypandoc.convert_text(json.dumps(ast), 'markdown', format='json')


# `validate-problem.sh` soft-warns on any of these, because MOJ injects the
# examples itself from `tests/input/sample*`. Matched the way it matches them:
# on the raw text, case-insensitively, at the start of a line.
_EXAMPLES_HEADING = re.compile(
    r'^[ \t]*#{1,3}[ \t]*(exemplos?|examples?|sample)', re.IGNORECASE | re.MULTILINE
)
_FENCE = re.compile(r'^[ \t]*```', re.MULTILINE)


def check_moj_gate(markdown: str, *, block_name: str) -> None:
    """Reject a converted block that would make MOJ's gate warn.

    ``validate-problem.sh`` reports an examples heading or a ``` fence in
    ``render_warnings``: MOJ builds the examples section itself from
    ``tests/input/sample*``, so a statement carrying its own is duplicating it.
    rbx fails here rather than shipping a package that warns on the judge, and
    names the block so the setter knows where to look.
    """
    if _EXAMPLES_HEADING.search(markdown):
        raise MojGateError(
            f'The {block_name} block carries an examples heading, but MOJ builds '
            'the examples section itself from the sample tests, so the statement '
            'would show them twice. Remove the heading.'
        )
    if _FENCE.search(markdown):
        raise MojGateError(
            f'The {block_name} block contains a fenced code block (```), which '
            "MOJ reads as a hand-written example -- it builds the statement's "
            'examples from the sample tests instead. Use indented code or '
            '\\verb/verbatim.'
        )
