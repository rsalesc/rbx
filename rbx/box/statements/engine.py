"""Statements v2 build engine — shared problem rendering (design §6, §7).

The piece common to both build modes: take one problem statement and render it
into TeX against a staged overlay, by

1. extracting the rbxTeX blocks (legend/input/... + per-sample explanations),
2. staging the samples into ``<problem_root>/.samples/`` (root-relative I/O,
   ``\\subimport``-able explanations), and
3. rendering the chosen template — a *full document*
   (``standaloneProblemTemplate``, ``rbx st b``) or a *fragment*
   (``contestProblemTemplate``, joined by ``rbx contest st b``).

``rbx.box.statements.build_statements`` (standalone) and
``rbx.box.contest.build_contest_statements`` (join) drive this with the right
overlay layout and ``root_prefix``; the same problem rendering is valid in both
contexts, which is what makes the overlay portable (design §6.2).
"""

import pathlib
from typing import List

from rbx import utils
from rbx.box.statements import render, sample_staging
from rbx.box.statements.context import (
    ContestRenderContext,
    ProblemRenderContext,
    StatementCodeLanguage,
)
from rbx.box.statements.context import (
    problem_jinja_kwargs as _problem_jinja_kwargs,
)
from rbx.box.statements.schema import StatementType
from rbx.box.testcase_sample_utils import StatementSample


def _mode_for(statement_type: StatementType) -> str:
    return 'markdown' if statement_type == StatementType.rbxMarkdown else 'latex'


def _md_to_latex(markdown: str) -> str:
    import pypandoc

    return pypandoc.convert_text(markdown, 'latex', 'markdown')


def to_sample_source(sample: StatementSample) -> sample_staging.SampleSource:
    """Project the heavy ``StatementSample`` onto the lightweight staging input."""
    chunks: List = []
    if sample.interaction is not None:
        chunks = [(chunk.path, int(chunk.pipe)) for chunk in sample.interaction.chunks]
    has_output = sample.outputPath is not None and sample.outputPath.is_file()
    return sample_staging.SampleSource(
        input_path=sample.inputPath,
        output_path=sample.outputPath if has_output else None,
        has_output=has_output,
        explanation_path=sample.explanationPath,
        explanation_from_blocks=sample.explanationFromBlocks,
        interaction_chunks=chunks,
    )


def render_problem_tex(
    *,
    render_root: pathlib.Path,
    problem_root: pathlib.Path,
    root_prefix: str,
    template_rel: str,
    content: bytes,
    lang: str,
    languages: List[StatementCodeLanguage],
    problem: ProblemRenderContext,
    contest: ContestRenderContext,
    samples: List[StatementSample],
    use_samples: bool,
    statement_type: StatementType,
    externalize: bool = False,
) -> bytes:
    """Render one problem statement to TeX bytes.

    ``render_root`` is where Jinja loads the (staged) template and writes temp
    files — the overlay root in both modes. ``problem_root`` is where this
    problem's assets and ``.samples/`` live (the overlay root for standalone, the
    isolated ``.problems/<SHORT>/`` for a join). ``root_prefix`` is
    ``problem_root`` relative to the overlay root, anchoring root-relative sample
    I/O for ``\\VerbatimInput``.

    ``blocks.yml`` (the raw extracted blocks) is always persisted to
    ``problem_root`` as the Polygon source of truth. When ``externalize`` is set
    (the Polygon export path), per-block TikZ figures are labeled before the
    full-doc compile so ``\\tikzexternalize`` emits one PDF per figure, and
    ``blocks.ext.yml`` (labeled) / ``blocks.sub.yml`` (TikZ replaced by
    ``\\includegraphics``) are persisted too — replicating the v1 rbxTeX builder.
    """
    mode = _mode_for(statement_type)

    # 1. Block extraction — render in problem_root so any in-statement includes
    #    resolve against the mirrored problem subtree.
    blocks = render.extract_blocks(
        problem_root,
        content,
        lang=lang,
        languages=languages,
        problem=problem,
        contest=contest,
        mode=mode,
    )
    # Always persist the raw blocks — the Polygon source of truth (design §1).
    _write_blocks(problem_root, 'blocks.yml', blocks)

    # LaTeX-form blocks/explanations: the (LaTeX) template and the TikZ
    # externalization operate on TeX, so rbxMarkdown blocks are converted first
    # (mirrors the v1 rbxMarkdown->rbxTeX step).
    latex_blocks = (
        {name: _md_to_latex(value) for name, value in blocks.blocks.items()}
        if mode == 'markdown'
        else dict(blocks.blocks)
    )
    latex_explanations = (
        {i: _md_to_latex(value) for i, value in blocks.explanations.items()}
        if mode == 'markdown'
        else dict(blocks.explanations)
    )

    # Per-block TikZ labeling must happen before the full-doc compile so the
    # externalized PDF filenames match the labels the substitution rewrites to.
    if externalize:
        latex_blocks = render.externalize_blocks(latex_blocks)
        latex_explanations = render.externalize_blocks(latex_explanations)
        _write_blocks(
            problem_root,
            'blocks.ext.yml',
            render.StatementBlocks(
                blocks=latex_blocks, explanations=latex_explanations
            ),
        )

    # 2. Sample staging into <problem_root>/.samples/. Explanations are always
    #    `\subimport`-ed by a LaTeX template; they carry the externalization
    #    labels (when externalizing) so their figures externalize too.
    if use_samples and samples:
        kwargs = _problem_jinja_kwargs(
            lang=lang, languages=languages, problem=problem, contest=contest
        )

        def render_text(c: bytes, m: str) -> bytes:
            rendered = render.render_jinja(problem_root, c, **kwargs)
            if m == 'markdown':
                rendered = _md_to_latex(rendered.decode()).encode()
            return rendered

        def render_blocks(c: bytes, m: str):
            return render.render_jinja_blocks(problem_root, c, mode=m, **kwargs).blocks

        sources = [to_sample_source(s) for s in samples]
        problem.samples = sample_staging.stage_samples(
            problem_root,
            root_prefix,
            sources,
            explanation_blocks=latex_explanations,
            render_text=render_text,
            render_blocks=render_blocks,
            lang=lang,
            mode=mode,
        )

    problem.blocks = latex_blocks

    # 3. Render the template (loaded from render_root where it was staged).
    tex = render.render_problem_document(
        render_root,
        template_rel,
        lang=lang,
        languages=languages,
        problem=problem,
        contest=contest,
    )

    # The substituted blocks (TikZ -> \includegraphics) are what Polygon uploads;
    # persist them next to the figure PDFs the compile produces.
    if externalize:
        _write_blocks(
            problem_root,
            'blocks.sub.yml',
            render.StatementBlocks(
                blocks=render.substitute_externalized_blocks(latex_blocks),
                explanations=render.substitute_externalized_blocks(latex_explanations),
            ),
        )

    return tex


def _write_blocks(
    root: pathlib.Path, name: str, blocks: render.StatementBlocks
) -> None:
    """Persist a :class:`StatementBlocks` as YAML in ``root`` (the overlay /
    problem root), the source of truth the Polygon export path reads."""
    (root / name).write_text(utils.model_to_yaml(blocks))


def relativize_template(
    contest_root: pathlib.Path,
    chrome_dir: pathlib.Path,
    template_path: pathlib.Path,
    overlay_root: pathlib.Path,
) -> str:
    """Return the template path relative to the overlay root after staging.

    Templates normally live under the contest statement-file directory (the
    chrome dir), so they are already in the overlay; otherwise the template is
    copied to the overlay root and referenced by name.
    """
    import shutil

    from rbx.box.statements.overlay import OverlayCollisionError

    template_abs = utils.abspath(contest_root / template_path)
    chrome_abs = utils.abspath(chrome_dir)
    try:
        return str(template_abs.relative_to(chrome_abs))
    except ValueError:
        # Template lives outside the contest statement-file dir, so it was not
        # brought in by the chrome overlay. Stage it at the root by basename,
        # erroring rather than silently clobbering an existing overlay asset.
        dest = overlay_root / template_abs.name
        if dest.exists() and dest.read_bytes() != template_abs.read_bytes():
            with OverlayCollisionError() as err:
                err.print(
                    f'[error]Template [item]{template_path}[/item] lives outside '
                    f'the contest statement-file directory and its basename '
                    f'[item]{template_abs.name}[/item] collides with an existing '
                    f'overlay asset.[/error]'
                )
                err.print(
                    '[warning]Move the template under the contest statement-file '
                    'directory, or rename it.[/warning]'
                )
        shutil.copyfile(template_abs, dest)
        return template_abs.name
