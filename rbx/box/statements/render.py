"""Statements v2 render core (design §7.1, issue #564).

The "builders stay similar" half of the rework: this module reuses the v1
low-level primitives — rbxTeX block extraction, the LaTeX Jinja env, and the
``tex -> pdf`` pdflatex loop — but drives them with the v2 namespaced context
(:mod:`rbx.box.statements.context`) and operates on the overlay produced by the
stager. pdflatex always runs from the overlay **root** so the generated TeX is
portable.

Two problem render modes share the block-extraction core:

- :func:`render_problem_document` — a *full* document (``standaloneProblemTemplate``),
  compiled in place for ``rbx st b``.
- the same function with the ``contestProblemTemplate`` produces a *fragment*
  meant to be ``\\subimport``-ed by the contest join.

The contest joining document is rendered by :func:`render_contest_document`.
"""

import pathlib
import typing
from typing import Any, Dict, List, Literal

from rbx import console
from rbx.box.statements import texsoup_utils
from rbx.box.statements.builders import (
    StatementBlocks,
    render_jinja,
    render_jinja_blocks,
)
from rbx.box.statements.context import (
    ContestRenderContext,
    ProblemRenderContext,
    StatementCodeLanguage,
    contest_jinja_kwargs,
    problem_jinja_kwargs,
)
from rbx.box.statements.demacro_utils import collect_macro_definitions

Mode = Literal['latex', 'markdown']


def extract_blocks(
    root: pathlib.Path,
    content: bytes,
    *,
    lang: str,
    languages: List[StatementCodeLanguage],
    problem: ProblemRenderContext,
    contest: ContestRenderContext,
    mode: Mode = 'latex',
) -> StatementBlocks:
    """Extract the named rbxTeX blocks (legend/input/output/...) and any
    per-sample ``explanation_<i>`` blocks from a problem statement file, using
    the v2 namespaced context."""
    kwargs = problem_jinja_kwargs(
        lang=lang, languages=languages, problem=problem, contest=contest
    )
    return render_jinja_blocks(root, content, mode=mode, **kwargs)


def render_problem_document(
    root: pathlib.Path,
    template_rel: str,
    *,
    lang: str,
    languages: List[StatementCodeLanguage],
    problem: ProblemRenderContext,
    contest: ContestRenderContext,
) -> bytes:
    """Render a problem template (full standalone doc OR contest fragment) that
    has already been staged into the overlay ``root``. ``problem.blocks`` must
    be populated (via :func:`extract_blocks`)."""
    kwargs = problem_jinja_kwargs(
        lang=lang, languages=languages, problem=problem, contest=contest
    )
    return render_jinja(
        root,
        f'%- extends "{template_rel}"'.encode(),
        **kwargs,
        blocks=problem.blocks,
    )


def render_contest_document(
    root: pathlib.Path,
    template_rel: str,
    *,
    lang: str,
    languages: List[StatementCodeLanguage],
    contest: ContestRenderContext,
    problems: List[ProblemRenderContext],
) -> bytes:
    """Render the joining contest document (the contest statement ``file``),
    iterating ``problems`` and ``\\subimport``-ing each via its import handles."""
    kwargs = contest_jinja_kwargs(
        lang=lang, languages=languages, contest=contest, problems=problems
    )
    return render_jinja(
        root,
        f'%- extends "{template_rel}"'.encode(),
        **kwargs,
        blocks=contest.blocks,
    )


def render_jinja_document(
    root: pathlib.Path,
    source_rel: str,
    jinja_kwargs: Dict[str, Any],
) -> bytes:
    """Render a plain Jinja document (jinja-tex / jinja-md) staged at ``root``;
    no block extraction, just a direct template render."""
    return render_jinja(
        root,
        f'%- extends "{source_rel}"'.encode(),
        **jinja_kwargs,
    )


def compile_pdf(
    root: pathlib.Path,
    tex: bytes,
    *,
    demacro: bool = False,
    externalize: bool = False,
) -> bytes:
    """Compile ``tex`` to PDF with pdflatex, running from the overlay ``root``
    so that relative ``\\subimport`` / ``\\VerbatimInput`` paths resolve."""
    from rbx.box.statements.latex import (
        MAX_PDFLATEX_RUNS,
        Latex,
        decode_latex_output,
        should_rerun,
    )

    input_str = tex.decode()
    if externalize:
        tex_node = texsoup_utils.parse_latex(input_str)
        texsoup_utils.inject_externalization_for_tikz(tex_node)
        (root / texsoup_utils.EXTERNALIZATION_DIR).mkdir(exist_ok=True, parents=True)
        input_str = str(tex_node)

    import typer

    latex = Latex(input_str)
    latex_result = latex.build_pdf(root)
    pdf = latex_result.pdf
    logs = decode_latex_output(latex_result.result.stdout)
    runs = 1
    while pdf is not None and should_rerun(logs) and runs < MAX_PDFLATEX_RUNS:
        console.console.print('Re-running pdfLaTeX to get cross-references right...')
        latex_result = latex.build_pdf(root)
        pdf = latex_result.pdf
        logs = decode_latex_output(latex_result.result.stdout)
        runs += 1

    if pdf is None:
        console.console.print(f'{logs}')
        console.console.print('[error]PdfLaTeX compilation failed.[/error]')
        raise typer.Exit(1)

    if demacro:
        macro_defs = collect_macro_definitions(root / 'statement.tex')
        macro_defs.to_json_file(root / 'macros.json')

    return typing.cast(bytes, pdf)


def md_to_pdf(root: pathlib.Path, md: bytes) -> bytes:
    """Convert Markdown to PDF via pandoc (for plain ``md`` statements)."""
    import pypandoc

    output = root / 'statement.pdf'
    pypandoc.convert_text(
        md.decode(),
        'pdf',
        format='markdown',
        outputfile=str(output),
        extra_args=['--pdf-engine=pdflatex'],
    )
    return output.read_bytes()


def md_blocks_to_rbxtex(blocks: StatementBlocks) -> bytes:
    """Convert extracted Markdown blocks to an rbxTeX-blocks document (each block
    pandoc-converted to LaTeX), so an rbxMarkdown statement can reuse the LaTeX
    rendering path (mirrors the v1 rbxMarkdown->rbxTeX builder)."""
    import pypandoc

    result = ''
    for name, content in blocks.blocks.items():
        converted = pypandoc.convert_text(content, 'latex', 'markdown')
        result += f'%- block {name}\n{converted}\n%- endblock\n\n'
    return result.encode()
