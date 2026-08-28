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
monospace wrappers holding math, which live in ``monospace_math.py``. So the
output here is deliberately **not** what a plain ``pandoc -f latex -t markdown``
would produce.

**The goldens in ``tests/.../testdata/markdown_export`` are pandoc-version
sensitive.** They record what a specific pandoc emits; a diff there means pandoc
changed its Markdown writer, not that the expectation was wrong.
"""

import json
import re
from typing import Any, Callable, Optional

from rbx import tooling
from rbx.box.statements.monospace_math import rewrap_monospace_math


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
