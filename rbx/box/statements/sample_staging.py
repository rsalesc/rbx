"""Statements v2 recursive sample staging (design §6.3, issue #562).

Each sample gets its own hermetic folder ``<problem_root>/.samples/<idx>/``:

- generated ``in`` / ``out`` are mirrored in; the handles expose them as
  **root-relative** paths because ``\\VerbatimInput`` (sample I/O) ignores the
  ``\\subimport`` base (§6.4);
- the explanation — whether it comes from an inline ``explanation_<i>`` block or
  an authored explanation file — is rendered into ``explanation.tex``; for a
  *file* explanation the entire containing directory is overlaid so the
  explanation can ``\\includegraphics`` its own figures. The handle exposes
  ``dir`` / ``explanation_file`` as **import-base-relative** for ``\\subimport``;
- interactive chunks are mirrored in and exposed root-relative.

The input is the lightweight :class:`SampleSource` (plain paths) so the staging
is decoupled from the heavy ``StatementSample`` model and unit-testable.
"""

import dataclasses
import pathlib
import shutil
from typing import Callable, Dict, List, Optional, Tuple

from rbx.box.statements import overlay
from rbx.box.statements.context import SampleHandle

SAMPLES_DIRNAME = '.samples'

# (content: bytes, mode: 'latex'|'markdown') -> rendered bytes
RenderText = Callable[[bytes, str], bytes]
# (content: bytes, mode) -> {lang_block: content}
RenderBlocks = Callable[[bytes, str], Dict[str, str]]


@dataclasses.dataclass
class SampleInteractionChunkHandle:
    path: str
    pipe: int
    data: Optional[str] = None


@dataclasses.dataclass
class SampleInteractionHandle:
    chunks: List[SampleInteractionChunkHandle]


@dataclasses.dataclass
class SampleSource:
    """A single sample's source files, resolved from a ``StatementSample``."""

    input_path: pathlib.Path
    output_path: Optional[pathlib.Path] = None
    has_output: bool = False
    explanation_path: Optional[pathlib.Path] = None
    explanation_from_blocks: bool = False
    interaction_chunks: List[Tuple[pathlib.Path, int]] = dataclasses.field(
        default_factory=list
    )


def _resolve_explanation(
    index: int,
    source: SampleSource,
    explanation_blocks: Dict[int, str],
    extra_explanations: Dict[int, str],
    render_text: Optional[RenderText],
    render_blocks: Optional[RenderBlocks],
    lang: str,
    mode: str,
) -> Optional[bytes]:
    """Return the final explanation content for a sample, or None.

    Precedence: inline ``explanation_<i>`` blocks → ``extra_explanations`` →
    the authored file on disk. ``extra_explanations`` only overrides the staged
    *text* of a separate-file explanation (e.g. the engine's already-externalized
    copy); it does NOT suppress the source-dir mirror, so the explanation's own
    figures still resolve (the caller's mirror guard is left untouched).
    """
    if index in explanation_blocks:
        return explanation_blocks[index].encode()
    if index in extra_explanations:
        return extra_explanations[index].encode()
    if source.explanation_path is None or not source.explanation_path.is_file():
        return None
    raw = source.explanation_path.read_bytes()
    if source.explanation_from_blocks and render_blocks is not None:
        blocks = render_blocks(raw, mode)
        selected = blocks.get(lang)
        return selected.encode() if selected is not None else None
    if render_text is not None:
        return render_text(raw, mode)
    return raw


def stage_samples(
    problem_root: pathlib.Path,
    root_prefix: str,
    sources: List[SampleSource],
    *,
    explanation_blocks: Optional[Dict[int, str]] = None,
    extra_explanations: Optional[Dict[int, str]] = None,
    render_text: Optional[RenderText] = None,
    render_explanation_text: Optional[RenderText] = None,
    render_blocks: Optional[RenderBlocks] = None,
    lang: str = 'en',
    mode: str = 'latex',
) -> List[SampleHandle]:
    """Stage every sample under ``<problem_root>/.samples/<idx>/`` and return the
    template handles.

    ``root_prefix`` is the problem root's path relative to the overlay root
    (``''`` for standalone, ``'.problems/<SHORT>/'`` for a join member); it
    anchors the root-relative I/O / chunk paths. ``render_explanation_text`` (a
    back-compat alias of ``render_text``) renders an authored explanation file's
    Jinja before it is written into the sample folder.
    """
    explanation_blocks = explanation_blocks or {}
    extra_explanations = extra_explanations or {}
    render_text = render_text or render_explanation_text
    samples_root = problem_root / SAMPLES_DIRNAME

    handles: List[SampleHandle] = []
    for index, source in enumerate(sources):
        folder_name = f'{index:03d}'
        folder = samples_root / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        rel = f'{root_prefix}{SAMPLES_DIRNAME}/{folder_name}'

        explanation = _resolve_explanation(
            index,
            source,
            explanation_blocks,
            extra_explanations,
            render_text,
            render_blocks,
            lang,
            mode,
        )

        # Overlay the authored explanation's directory FIRST (for its figures);
        # the staged I/O / chunks / explanation below then overwrite anything the
        # mirror brought in (e.g. a source file literally named `in`/`out`), so
        # the generated sample data is always authoritative.
        if (
            explanation is not None
            and index not in explanation_blocks
            and source.explanation_path is not None
            and source.explanation_path.is_file()
        ):
            overlay.mirror_tree(source.explanation_path.parent, folder)

        shutil.copyfile(source.input_path, folder / 'in')
        handle = SampleHandle(index=index, input=f'{rel}/in')

        if source.has_output and source.output_path is not None:
            shutil.copyfile(source.output_path, folder / 'out')
            handle.output = f'{rel}/out'
        else:
            handle.has_output = False

        if explanation is not None:
            # The explanation is always `\subimport`-ed by a LaTeX template (both
            # the standalone and the contest-problem templates are LaTeX), so it
            # is written as `.tex` regardless of the source format; rbxMarkdown
            # explanations are converted upstream (see engine.render_problem_tex).
            (folder / 'explanation.tex').write_bytes(explanation)
            handle.dir = f'{SAMPLES_DIRNAME}/{folder_name}/'
            handle.explanation_file = 'explanation'

        if source.interaction_chunks:
            chunks: List[SampleInteractionChunkHandle] = []
            for chunk_index, (chunk_path, pipe) in enumerate(source.interaction_chunks):
                chunk_name = f'chunk_{chunk_index:03d}.txt'
                shutil.copyfile(chunk_path, folder / chunk_name)
                chunks.append(
                    SampleInteractionChunkHandle(path=f'{rel}/{chunk_name}', pipe=pipe)
                )
            handle.interaction = SampleInteractionHandle(chunks=chunks)

        handles.append(handle)

    return handles
