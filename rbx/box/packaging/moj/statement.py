"""The MOJ statement documents: `docs/enunciado.md` and `docs/notes/<sample>.md`.

Everything here is dictated by what `mojtools` does with the files, so the three
facts worth carrying in your head:

- **The renderer is pandoc** (`render-statement.sh`), the same one the editor's
  *Pré-visualizar* runs. So pandoc-flavored Markdown is the target dialect, and
  `$…$` reaches the student as MathML with no conversion.
- **The title comes from the field, not the document.** `render-statement.sh`
  injects an `<h1>` from `.moj-meta.json`'s `display_title` and strips a legacy
  `% Title` first line, so the document must carry no title of its own.
- **`## Entrada`/`## Saída` are the release gate.** `validate-problem.sh` greps
  them out of the RAW file as `^\\s*#{1,3}\\s*(entrada|input)` and
  `…(saída|saida|output)`, so they are emitted unconditionally -- a statement
  that simply has no input section still needs the heading.
"""

import pathlib
import re
from typing import Dict, Mapping, Optional

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

# `validate-problem.sh` matches `entrada|input` and `saída|saida|output` case
# insensitively, so an English statement passes the gate with English headings
# and a reader never sees a section titled in the wrong language.
_HEADINGS = {
    'pt': {'input': 'Entrada', 'output': 'Saída', 'notes': 'Notas'},
    'en': {'input': 'Input', 'output': 'Output', 'notes': 'Notes'},
}

# MOJ is a Brazilian judge and its own tooling is Portuguese, so an
# unrecognized language falls back to it rather than to English.
_DEFAULT_HEADING_LANGUAGE = 'pt'


def _headings(language: Optional[str]) -> Dict[str, str]:
    """The section titles for a statement language.

    Matched on the language *subtag* (`pt-br` -> `pt`), since rbx language codes
    are region-qualified and MOJ's gate cares only about the word.
    """
    subtag = (language or '').split('-')[0].lower()
    return _HEADINGS.get(subtag, _HEADINGS[_DEFAULT_HEADING_LANGUAGE])


def get_main_statement(main_language: Optional[str] = None) -> Optional[Statement]:
    """The single statement a MOJ package ships.

    MOJ holds one statement per problem, so this is the one choice that matters:
    the body and `display_title` both resolve from it, and they must never come
    from different languages. `main_language` picks it; without one, the topmost
    declared statement wins, as everywhere else in rbx.
    """
    pkg = package.find_problem_package_or_die()
    if not pkg.expanded_statements:
        return None
    if main_language is None:
        return pkg.expanded_statements[0]
    for statement in pkg.expanded_statements:
        if statement.language == main_language:
            return statement
    available = '[/item], [item]'.join(
        sorted({statement.language for statement in pkg.expanded_statements})
    )
    console.console.print(
        f'[error]No statement in language [item]{main_language}[/item].'
        f'[/error]\n[error]This problem has statements in: '
        f'[item]{available}[/item].[/error]'
    )
    raise typer.Exit(1)


def get_display_title(main_language: Optional[str] = None) -> str:
    """MOJ's `display_title`, resolved through the shared naming helper.

    `naming.get_problem_title` is what BOCA uses: it honors a statement's own
    `title` override, falls back to the package title and then to the package
    name, and raises an actionable error when a package has several titles and no
    statement to disambiguate them.

    The statement it resolves against is `get_main_statement`'s, so anything
    reporting what a MOJ upload would be titled -- the packager, `rbx tooling moj
    summary` -- agrees with the package that eventually gets built.
    """
    statement = get_main_statement(main_language)
    language = statement.language if statement is not None else None
    return box_naming.get_problem_title(language, statement, fallback_to_title=True)


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


def _convert(blocks: Mapping[str, str], name: str) -> str:
    """Convert one block to Markdown and check it against MOJ's gate."""
    content = (blocks.get(name) or '').strip()
    if not content:
        return ''
    markdown = tex_to_markdown(content).strip()
    check_moj_gate(markdown, block_name=name)
    return markdown


def build_enunciado(
    blocks: Mapping[str, str],
    *,
    language: Optional[str],
    title: Optional[str] = None,
) -> str:
    """Render `docs/enunciado.md` from a bundle's blocks.

    `title` is accepted and deliberately unused: it documents that the caller's
    title has a home (`display_title` in `.moj-meta.json`) and that this
    document is not it.
    """
    del title  # See the docstring: MOJ injects the <h1> from display_title.

    headings = _headings(language)
    parts = [_convert(blocks, 'legend')]

    # Emitted unconditionally, empty block or not: these two headings ARE the
    # release gate, grepped out of the raw file by validate-problem.sh.
    parts.append(f'## {headings["input"]}\n\n{_convert(blocks, "input")}')
    parts.append(f'## {headings["output"]}\n\n{_convert(blocks, "output")}')

    notes = _convert(blocks, 'notes')
    if notes:
        parts.append(f'## {headings["notes"]}\n\n{notes}')

    return '\n\n'.join(part.strip() for part in parts if part.strip()) + '\n'


# Rendered notes go through pandoc WITHOUT `--mathml` (`gen-problem-json.sh`),
# unlike the body, so any math in one reaches the student as a literal `\(x\)`.
_MATH = re.compile(r'\$[^$\n]+\$')


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


def build_notes(explanations: Mapping[int, str]) -> Dict[str, str]:
    """Render each sample explanation, keyed by the sample's test name."""
    notes: Dict[str, str] = {}
    for index in sorted(explanations):
        content = (explanations[index] or '').strip()
        if not content:
            continue
        name = sample_note_name(index)
        markdown = tex_to_markdown(content).strip()
        check_moj_gate(markdown, block_name=f'explanation for {name}')
        if _MATH.search(markdown):
            console.console.print(
                f'[warning]The explanation for [item]{name}[/item] contains math, '
                'but MOJ renders sample notes without MathML (unlike the statement '
                'body), so it will reach the student as literal '
                '[item]\\(…\\)[/item].[/warning]\n'
                '[warning]Rewrite it without math if that matters.[/warning]'
            )
        notes[name] = markdown + '\n'
    return notes


def note_path(name: str) -> pathlib.PurePosixPath:
    """Where a note file lands, relative to the package root.

    Note this is NOT the layout's `document_dir` for the slot: the file lives in
    `docs/notes/`, while its image references resolve against `docs/`.
    """
    return pathlib.PurePosixPath('docs') / 'notes' / f'{name}.md'
