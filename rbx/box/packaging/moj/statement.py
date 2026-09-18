"""The MOJ statement documents: `docs/enunciado.md` and `docs/notes/<sample>.md`,
plus their translations at `docs/enunciado.<lang>.md` and
`docs/notes/<sample>.<lang>.md`.

Everything here is dictated by what `mojtools` does with the files, so the four
facts worth carrying in your head:

- **The renderer is pandoc** (`render-statement.sh`), the same one the editor's
  *Pré-visualizar* runs. So pandoc-flavored Markdown is the target dialect, and
  `$…$` reaches the student as MathML with no conversion.
- **The title comes from the field, not the document.** `render-statement.sh`
  injects an `<h1>` from `.moj-meta.json`'s `display_title` (or `titles[<lang>]`
  for a translation) and strips a legacy `% Title` first line, so the document
  must carry no title of its own.
- **`## Entrada`/`## Saída` are the release gate.** `validate-problem.sh` greps
  them out of the RAW file as `^\\s*#{1,3}\\s*(entrada|input)` and
  `…(saída|saida|salida|output)`, so they are emitted unconditionally -- a
  statement that simply has no input section still needs the heading. The gate
  applies to every translation too.
- **Portuguese is the canonical slot, and the languages are an allowlist.**
  `statement-langs.sh` reads `docs/enunciado.md` as Portuguese and looks for a
  translation only at `docs/enunciado.<lang>.md` for `<lang>` in `pt en es` --
  so an `enunciado.pt.md` or an `enunciado.ru.md` is never read.
"""

import dataclasses
import pathlib
from typing import Callable, Dict, List, Mapping, Optional

import typer

from rbx import console
from rbx.box import naming as box_naming
from rbx.box import package
from rbx.box.packaging.moj import naming, statement_assets
from rbx.box.statements import export
from rbx.box.statements.markdown_export import check_moj_gate, tex_to_markdown
from rbx.box.statements.schema import Statement

# The group rbx reserves for samples. Sample test names ignore it (they are
# `sample%03d`), but `naming.testcase_name` still wants a group.
SAMPLES_GROUP = 'samples'

# `validate-problem.sh` matches `entrada|input` and `saída|saida|salida|output`
# case insensitively, so a translated statement passes the gate with its own
# headings and a reader never sees a section titled in the wrong language.
_HEADINGS = {
    'pt': {'input': 'Entrada', 'output': 'Saída', 'notes': 'Notas'},
    'en': {'input': 'Input', 'output': 'Output', 'notes': 'Notes'},
    'es': {'input': 'Entrada', 'output': 'Salida', 'notes': 'Notas'},
}

# MOJ is a Brazilian judge and its own tooling is Portuguese, so an
# unrecognized language falls back to it rather than to English.
_DEFAULT_HEADING_LANGUAGE = 'pt'

# The language of the canonical, unsuffixed slot (`docs/enunciado.md`). A
# statement in this language is never a translation: MOJ has no
# `enunciado.pt.md`, so one would simply never be read.
CANONICAL_LANGUAGE = 'pt'

# `STMT_LANGS_ALL` in mojtools' `statement-langs.sh`. A translation in any other
# language lands in the package and is ignored by every reader.
SUPPORTED_LANGUAGES = ('pt', 'en', 'es')


def moj_language(language: Optional[str]) -> str:
    """The MOJ language id of an rbx statement language: its ISO 639-1 subtag.

    rbx language codes may be region-qualified (`pt-br`), and MOJ's allowlist
    and gate care only about the word.
    """
    return (language or '').split('-')[0].lower()


def enunciado_path(language: Optional[str] = None) -> pathlib.PurePosixPath:
    """Where a statement body lands, relative to the package root.

    The canonical slot for no language, `docs/enunciado.<lang>.md` for a
    translation -- exactly the two spellings `statement-langs.sh` looks for.
    """
    suffix = f'.{language}' if language else ''
    return pathlib.PurePosixPath('docs') / f'enunciado{suffix}.md'


@dataclasses.dataclass(frozen=True)
class StatementSelection:
    """Which statements a MOJ package ships, and where.

    `main` fills the canonical slot; `translations` is one statement per MOJ
    language, keyed by that language; `skipped` are the statements the package
    drops, each paired with the reason the setter is told.
    """

    main: Optional[Statement]
    translations: Dict[str, Statement]
    skipped: List[tuple[Statement, str]]


# How the statement's figures travel to MOJ. A code-level switch on purpose: both
# shapes are valid packages, MOJ shows the reader the same statement either way,
# and nothing about a problem says which one it wants -- so this is a decision
# about the packager, not a knob for `problem.rbx.yml`.
#
# `True` (the default) inlines each figure into the document as a `data:` URI and
# ships no image files at all:
#
#     docs/enunciado.md      ![](data:image/png;base64,iVBORw0KGgo…)
#
# The statement then renders identically anywhere pandoc runs -- with no resource
# path, in a preview, pasted somewhere else entirely -- which is what makes it the
# default: it removes the one thing about a MOJ statement that depends on files
# landing where the renderer expects them. The cost is blunt: base64 is ~4/3 the
# size, a figure cited from both the body and a note is carried twice, and the raw
# Markdown stops being readable by a human.
#
# `False` ships the image files beside the documents and leaves the references
# pointing at them:
#
#     docs/enunciado.md      ![](assets/fig.png)
#     docs/assets/fig.png
#
# which is the shape mojtools was built around -- `render-statement.sh` passes
# `--resource-path=<pkg>/docs` precisely so pandoc can find them, and it is the
# renderer, not rbx, that base64-embeds each figure into the HTML a student
# reads. Keeping the files also keeps them inspectable in the tarball, keeps the
# Markdown readable in MOJ's editor, and lets one figure cited twice be sent once.
INLINE_IMAGES_AS_BASE64 = True


def _image_rewriter(
    docs_root: Optional[pathlib.Path],
) -> Optional[Callable[[str], str]]:
    """The image-reference rewrite these documents need, if any.

    ``None`` -- the untouched references -- whenever the packager is shipping the
    files, and also whenever the caller passed no ``docs_root``: inlining reads
    the *materialized* figures, so a caller with no directory to read them from
    could only be handed a document citing images it never shipped.
    """
    if not INLINE_IMAGES_AS_BASE64 or docs_root is None:
        return None
    return statement_assets.base64_inliner(docs_root)


def discard_inlined_assets(bundle: export.StatementBundle, root: pathlib.Path) -> None:
    """Drop the materialized asset files once the documents carry them inline.

    A no-op in the shipping-files mode, so the packager may call it
    unconditionally and this module stays the only place that reads the switch.
    """
    if INLINE_IMAGES_AS_BASE64:
        statement_assets.discard_assets(bundle, root)


def _headings(language: Optional[str]) -> Dict[str, str]:
    """The section titles for a statement language.

    Matched on the language *subtag* (`pt-br` -> `pt`), since rbx language codes
    are region-qualified and MOJ's gate cares only about the word.
    """
    return _HEADINGS.get(moj_language(language), _HEADINGS[_DEFAULT_HEADING_LANGUAGE])


def _select_main(
    statements: List[Statement], main_language: Optional[str]
) -> Statement:
    """The statement for the canonical slot.

    `main_language` picks it, and naming a language the problem has none in is
    an error. Without one, the Portuguese statement is preferred, since that is
    what the slot *means* to MOJ and a Portuguese statement anywhere else would
    never be read; only a problem with none falls back to the topmost declared
    statement, as everywhere else in rbx.
    """
    if main_language is None:
        for statement in statements:
            if moj_language(statement.language) == CANONICAL_LANGUAGE:
                return statement
        return statements[0]
    for statement in statements:
        if statement.language == main_language:
            return statement
    available = '[/item], [item]'.join(
        sorted({statement.language for statement in statements})
    )
    console.console.print(
        f'[error]No statement in language [item]{main_language}[/item].'
        f'[/error]\n[error]This problem has statements in: '
        f'[item]{available}[/item].[/error]'
    )
    raise typer.Exit(1)


def select_statements(main_language: Optional[str] = None) -> StatementSelection:
    """Which statements a MOJ package ships, and where each lands.

    The main statement fills `docs/enunciado.md` whatever its language, and the
    body and `display_title` both resolve from it, so they can never come from
    different languages. Every other statement in a language MOJ supports ships
    as a translation, one per language (the topmost declared wins); the rest are
    skipped, each with the reason the packager reports.

    A Portuguese statement that is not the main one is skipped too: MOJ reads
    Portuguese only from the canonical slot, so shipping it as
    `enunciado.pt.md` would be shipping a file nothing reads.
    """
    pkg = package.find_problem_package_or_die()
    statements = pkg.expanded_statements
    if not statements:
        return StatementSelection(main=None, translations={}, skipped=[])

    main = _select_main(statements, main_language)
    main_moj_language = moj_language(main.language)
    translations: Dict[str, Statement] = {}
    skipped: List[tuple[Statement, str]] = []
    for statement in statements:
        if statement is main:
            continue
        language = moj_language(statement.language)
        if language not in SUPPORTED_LANGUAGES:
            supported = '[/item], [item]'.join(SUPPORTED_LANGUAGES)
            skipped.append(
                (statement, f'MOJ supports only [item]{supported}[/item] statements')
            )
        elif language == CANONICAL_LANGUAGE:
            skipped.append(
                (
                    statement,
                    'MOJ reads Portuguese only from [item]docs/enunciado.md[/item], '
                    f'which the [item]{main.language}[/item] statement fills',
                )
            )
        elif language == main_moj_language:
            skipped.append(
                (statement, f'the main statement is already in [item]{language}[/item]')
            )
        elif language in translations:
            skipped.append(
                (
                    statement,
                    f'MOJ takes one [item]{language}[/item] statement, and '
                    f'[item]{translations[language].variant}[/item] was declared first',
                )
            )
        else:
            translations[language] = statement
    return StatementSelection(main=main, translations=translations, skipped=skipped)


def get_main_statement(main_language: Optional[str] = None) -> Optional[Statement]:
    """The statement that fills `docs/enunciado.md`; see `select_statements`."""
    return select_statements(main_language).main


def _title_of(statement: Optional[Statement]) -> str:
    """A statement's title, resolved through the shared naming helper.

    `naming.get_problem_title` is what BOCA uses: it honors a statement's own
    `title` override, falls back to the package title and then to the package
    name, and raises an actionable error when a package has several titles and no
    statement to disambiguate them.
    """
    language = statement.language if statement is not None else None
    return box_naming.get_problem_title(language, statement, fallback_to_title=True)


def get_display_title(main_language: Optional[str] = None) -> str:
    """MOJ's `display_title`, resolved from the main statement.

    Anything reporting what a MOJ upload would be titled -- the packager, `rbx
    tooling moj summary` -- resolves through here, so they agree with the package
    that eventually gets built.
    """
    return _title_of(get_main_statement(main_language))


def get_translated_titles(main_language: Optional[str] = None) -> Dict[str, str]:
    """MOJ's `titles`: the title of each shipped translation, by MOJ language.

    A translation contributes an entry only when it has a title *of its own* --
    the statement's `title`, else the package's `titles[<lang>]` -- and that
    title differs from `display_title`. `statement-langs.sh` falls back to
    `display_title` for a translation with no entry, so an identical one is
    noise, and `naming.get_problem_title`'s last resort (the package *name*) is
    deliberately not taken: it would replace that fallback with a name the
    setter never meant as a title.
    """
    pkg = package.find_problem_package_or_die()
    selection = select_statements(main_language)
    display_title = _title_of(selection.main)
    titles = {}
    for language, statement in selection.translations.items():
        title = statement.title or pkg.titles.get(statement.language)
        if title is not None and title != display_title:
            titles[language] = title
    return titles


def report_skipped(selection: StatementSelection) -> None:
    """Warn about every statement the package drops, and why."""
    for statement, reason in selection.skipped:
        console.console.print(
            f'[warning]Not shipping the [item]{statement.language}[/item] '
            f'statement ([item]{statement.variant}[/item]): {reason}.[/warning]'
        )


def moj_layout() -> statement_assets.RasterizingLayout:
    """Where MOJ's statement assets and documents go.

    ```
    docs/enunciado.md              body
    docs/notes/sample001.md        per-sample explanations, paired by test name
    docs/assets/…                  statement-scope assets
    docs/samples/{index}/…         sample-scope assets
    ```
    """
    return statement_assets.RasterizingLayout(
        export.SubtreeLayout(
            asset_roots={
                export.AssetScope.STATEMENT: 'docs/assets',
                export.AssetScope.TIKZ: 'docs/assets/tikz',
                export.AssetScope.EXTERNAL: 'docs/assets/external',
                # The one root that must stay per-sample: many files land in it,
                # and two samples shipping `diagram.png` would collide.
                export.AssetScope.SAMPLE: 'docs/samples/{index:03d}',
            },
            document_dirs={
                'body': 'docs',
                # Constant `docs`, NOT `docs/notes`, even though that is where the
                # note file lands. `gen-problem-json.sh` renders every note with
                # `--resource-path="$PKG/docs"` regardless of which sample it
                # belongs to, so `docs` is the base its image references resolve
                # against. A base of `docs/notes` would derive `../assets/f.png`
                # and break every note image.
                'sample_explanation': 'docs',
            },
        )
    )


def _convert(
    blocks: Mapping[str, str],
    name: str,
    rewrite_image_url: Optional[Callable[[str], str]] = None,
) -> str:
    """Convert one block to Markdown and check it against MOJ's gate."""
    content = (blocks.get(name) or '').strip()
    if not content:
        return ''
    markdown = tex_to_markdown(content, rewrite_image_url=rewrite_image_url).strip()
    check_moj_gate(markdown, block_name=name)
    return markdown


def build_enunciado(
    blocks: Mapping[str, str],
    *,
    language: Optional[str],
    title: Optional[str] = None,
    docs_root: Optional[pathlib.Path] = None,
) -> str:
    """Render `docs/enunciado.md` from a bundle's blocks.

    `title` is accepted and deliberately unused: it documents that the caller's
    title has a home (`display_title` in `.moj-meta.json`) and that this
    document is not it.

    `docs_root` is the materialized `docs/` the body's image references resolve
    against, and is what `INLINE_IMAGES_AS_BASE64` needs to read the figures.
    Optional so a caller with no package on disk -- a test converting blocks, a
    statement with no images -- keeps working; without it the references are left
    as the bundle wrote them whatever the switch says.
    """
    del title  # See the docstring: MOJ injects the <h1> from display_title.

    headings = _headings(language)
    rewrite = _image_rewriter(docs_root)
    parts = [_convert(blocks, 'legend', rewrite)]

    # Emitted unconditionally, empty block or not: these two headings ARE the
    # release gate, grepped out of the raw file by validate-problem.sh.
    parts.append(f'## {headings["input"]}\n\n{_convert(blocks, "input", rewrite)}')
    parts.append(f'## {headings["output"]}\n\n{_convert(blocks, "output", rewrite)}')

    notes = _convert(blocks, 'notes', rewrite)
    if notes:
        parts.append(f'## {headings["notes"]}\n\n{notes}')

    return '\n\n'.join(part.strip() for part in parts if part.strip()) + '\n'


def sample_note_name(index: int) -> str:
    """The test name a sample explanation pairs with.

    `gen-problem-json.sh` pairs `docs/notes/<name>.md` to `tests/input/<name>`
    **by name**, so this must be the very name the packager gave the test.
    Derived through `naming.testcase_name` rather than by re-spelling
    `sample%03d`, so the two can never drift; the `+ 1` mirrors the packager's
    1-based per-group counter.
    """
    return naming.testcase_name(
        SAMPLES_GROUP, group_index=0, index=index + 1, is_sample=True
    )


def build_notes(
    explanations: Mapping[int, str],
    *,
    docs_root: Optional[pathlib.Path] = None,
) -> Dict[str, str]:
    """Render each sample explanation, keyed by the sample's test name.

    `docs_root` is `docs/`, exactly as in `build_enunciado` -- a note's images
    resolve against it and not against `docs/notes/`, where the file itself
    lands; see `moj_layout`.
    """
    notes: Dict[str, str] = {}
    rewrite = _image_rewriter(docs_root)
    for index in sorted(explanations):
        content = (explanations[index] or '').strip()
        if not content:
            continue
        name = sample_note_name(index)
        markdown = tex_to_markdown(content, rewrite_image_url=rewrite).strip()
        check_moj_gate(markdown, block_name=f'explanation for {name}')
        notes[name] = markdown + '\n'
    return notes


def note_path(name: str, language: Optional[str] = None) -> pathlib.PurePosixPath:
    """Where a note file lands, relative to the package root.

    `docs/notes/<sample>.<lang>.md` for a translation's note (`stmt_note_file`
    prefers it and falls back to the unsuffixed Portuguese one). Note this is
    NOT the layout's `document_dir` for the slot: the file lives in
    `docs/notes/`, while its image references resolve against `docs/`.
    """
    suffix = f'.{language}' if language else ''
    return pathlib.PurePosixPath('docs') / 'notes' / f'{name}{suffix}.md'
