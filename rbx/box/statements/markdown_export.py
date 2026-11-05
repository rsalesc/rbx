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

Two more defects have to be corrected *before* pandoc runs, on the TeX --
monospace wrappers holding math, which live in ``monospace_math.py``, and the
text-symbol and spacing commands pandoc silently drops (``\\textbar``,
``\\space``, ``\\quad``), which ``processing/text_symbols.py`` translates. So the
output here is deliberately **not** what a plain ``pandoc -f latex -t markdown``
would produce.

What pandoc *still* drops is reported, not lost: ``convert_tex_to_markdown``
runs the TeX reader with ``--verbose`` and hands back each ``Skipped '...'``
line, and any pandoc warning, as a ``PandocDiagnostic``. That is the safety net
for everything the translation table and the validator do not know yet -- it
reports what the *installed* pandoc actually lost.

**The goldens in ``tests/.../testdata/markdown_export`` are pandoc-version
sensitive.** They record what a specific pandoc emits; a diff there means pandoc
changed its Markdown writer, not that the expectation was wrong.
"""

import contextlib
import dataclasses
import json
import logging
import re
from typing import Any, Callable, Iterator, List, Optional

from rbx import tooling
from rbx.box.statements.monospace_math import rewrap_monospace_math
from rbx.box.statements.polygon_utils import PolygonTeXConfig
from rbx.box.statements.processing import text_symbols


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


def markdown_tex_config() -> PolygonTeXConfig:
    """The TeX the Markdown path can show: the Polygon subset, plus every
    command ``text_symbols`` translates and every text command pandoc converts
    on its own. A validator using it warns only about what would really be lost
    or misrendered, not about ``\\textbar`` or ``\\textless``.

    Externalized TikZ needs no entry: by the time a block is validated, each
    figure is already an ``\\includegraphics``.
    """
    config = PolygonTeXConfig.default()
    config.allowed_commands |= text_symbols.supported_names()
    return config


@dataclasses.dataclass(frozen=True)
class PandocDiagnostic:
    """Something pandoc reported while reading a block's TeX.

    ``snippet`` is set for a ``Skipped '<snippet>'`` line -- content pandoc's
    reader dropped -- and ``None`` for a warning, whose ``message`` is pandoc's
    own text. ``line``/``column`` are pandoc's, in the TeX it was handed, which
    the pre-pandoc passes may have shifted; they are kept for de-duplication,
    not for display.
    """

    message: str
    snippet: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None

    @property
    def dropped(self) -> bool:
        return self.snippet is not None


@dataclasses.dataclass(frozen=True)
class MarkdownConversion:
    markdown: str
    diagnostics: List[PandocDiagnostic]


_SKIPPED_RE = re.compile(
    r"^Skipped '(?P<snippet>.*)' at line (?P<line>\d+) column (?P<column>\d+)\s*$",
    re.DOTALL,
)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextlib.contextmanager
def _capturing_pandoc_log() -> Iterator[_Capture]:
    """Route pypandoc's re-logged pandoc stderr into a list, for one call.

    pypandoc re-logs each ``[LEVEL] message`` line of pandoc's stderr on its
    ``pypandoc`` logger. INFO is below every default threshold, so it is let
    through here; and the capture is the *only* place the records go, so a
    pandoc warning reaches the setter once, as an rbx warning. That means
    detaching the logger's own handlers too, not just cutting propagation:
    pypandoc installs a stderr ``StreamHandler`` the first time it converts with
    none attached, which would otherwise print every ``[INFO] Skipped`` line
    raw.
    """
    logger = logging.getLogger('pypandoc')
    capture = _Capture()
    old_level, old_propagate = logger.level, logger.propagate
    old_handlers = list(logger.handlers)
    for handler in old_handlers:
        logger.removeHandler(handler)
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield capture
    finally:
        logger.removeHandler(capture)
        for handler in old_handlers:
            logger.addHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate


def diagnostics_from_records(
    records: List[logging.LogRecord],
) -> List[PandocDiagnostic]:
    """``Skipped`` lines and warnings, once each.

    pandoc's reader backtracks, so one dropped command can be reported twice at
    the same position; those collapse. Every other INFO line is progress chatter
    and is ignored.
    """
    seen = set()
    diagnostics: List[PandocDiagnostic] = []
    for record in records:
        message = record.getMessage().strip()
        match = _SKIPPED_RE.match(message)
        if match is not None:
            diagnostic = PandocDiagnostic(
                message=message,
                snippet=match.group('snippet').strip(),
                line=int(match.group('line')),
                column=int(match.group('column')),
            )
        elif record.levelno >= logging.WARNING:
            diagnostic = PandocDiagnostic(message=message)
        else:
            continue
        if diagnostic in seen:
            continue
        seen.add(diagnostic)
        diagnostics.append(diagnostic)
    return diagnostics


def prepare_tex_for_pandoc(tex: str) -> str:
    """The TeX fix-ups pandoc needs before it reads a block; see the module
    docstring."""
    return text_symbols.translate_text_symbols(rewrap_monospace_math(tex))


def convert_tex_to_markdown(
    tex: str, *, rewrite_image_url: Optional[Callable[[str], str]] = None
) -> MarkdownConversion:
    """Convert one Polygon-TeX block to Markdown, with what pandoc dropped.

    ``rewrite_image_url`` maps each image reference to what the document should
    cite instead. It runs on the AST rather than over the emitted Markdown so a
    replacement may be arbitrary text -- a multi-kilobyte ``data:`` URI included,
    which pandoc's writer then escapes and wraps correctly on its own.
    """
    import pypandoc

    tooling.PANDOC.ensure()

    with _capturing_pandoc_log() as capture:
        ast = json.loads(
            pypandoc.convert_text(
                prepare_tex_for_pandoc(tex),
                'json',
                format='latex',
                extra_args=['--verbose'],
            )
        )
    _fix_images(ast, rewrite_image_url)
    markdown = pypandoc.convert_text(json.dumps(ast), 'markdown', format='json')
    return MarkdownConversion(
        markdown=markdown, diagnostics=diagnostics_from_records(capture.records)
    )


def tex_to_markdown(
    tex: str, *, rewrite_image_url: Optional[Callable[[str], str]] = None
) -> str:
    """Convert one Polygon-TeX block to Markdown, discarding the diagnostics;
    see ``convert_tex_to_markdown``."""
    return convert_tex_to_markdown(tex, rewrite_image_url=rewrite_image_url).markdown


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
