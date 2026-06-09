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
from rbx.box.statements import builders, render, sample_staging
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
) -> bytes:
    """Render one problem statement to TeX bytes.

    ``render_root`` is where Jinja loads the (staged) template and writes temp
    files — the overlay root in both modes. ``problem_root`` is where this
    problem's assets and ``.samples/`` live (the overlay root for standalone, the
    isolated ``.problems/<SHORT>/`` for a join). ``root_prefix`` is
    ``problem_root`` relative to the overlay root, anchoring root-relative sample
    I/O for ``\\VerbatimInput``.
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

    # 2. Sample staging into <problem_root>/.samples/.
    if use_samples and samples:
        kwargs = _problem_jinja_kwargs(
            lang=lang, languages=languages, problem=problem, contest=contest
        )

        def render_text(c: bytes, m: str) -> bytes:
            return builders.render_jinja(problem_root, c, **kwargs)

        def render_blocks(c: bytes, m: str):
            return builders.render_jinja_blocks(
                problem_root, c, mode=m, **kwargs
            ).blocks

        sources = [to_sample_source(s) for s in samples]
        problem.samples = sample_staging.stage_samples(
            problem_root,
            root_prefix,
            sources,
            explanation_blocks=blocks.explanations,
            render_text=render_text,
            render_blocks=render_blocks,
            lang=lang,
            mode=mode,
        )

    # rbxMarkdown: the extracted blocks are Markdown; convert them to LaTeX so the
    # (LaTeX) template can splice them in (mirrors the v1 rbxMarkdown->rbxTeX step).
    if mode == 'markdown':
        import pypandoc

        problem.blocks = {
            name: pypandoc.convert_text(value, 'latex', 'markdown')
            for name, value in blocks.blocks.items()
        }
    else:
        problem.blocks = blocks.blocks

    # 3. Render the template (loaded from render_root where it was staged).
    return render.render_problem_document(
        render_root,
        template_rel,
        lang=lang,
        languages=languages,
        problem=problem,
        contest=contest,
    )


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

    template_abs = utils.abspath(contest_root / template_path)
    chrome_abs = utils.abspath(chrome_dir)
    try:
        return str(template_abs.relative_to(chrome_abs))
    except ValueError:
        dest = overlay_root / template_abs.name
        shutil.copyfile(template_abs, dest)
        return template_abs.name
