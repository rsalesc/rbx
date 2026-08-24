"""Assembling `docs/enunciado.md` and `docs/notes/<sample>.md` for MOJ."""

import base64
import pathlib

import pytest

from rbx.box.packaging.moj import naming, statement
from rbx.box.statements import export, markdown_export

BLOCKS = {
    'legend': 'Given two integers $a$ and $b$, compute their sum.',
    'input': 'A single line with $a$ and $b$.',
    'output': 'A single line with the sum.',
}


def test_body_has_no_title_heading():
    """render-statement.sh injects <h1> from display_title and strips a legacy
    '% Title' line, so a title in the document would be a duplicate."""
    doc = statement.build_enunciado(BLOCKS, language='pt-br', title='Soma')
    assert not doc.startswith('%')
    assert '# Soma' not in doc
    assert 'Soma' not in doc


def test_legend_opens_the_document_without_a_heading():
    doc = statement.build_enunciado(BLOCKS, language='pt-br')
    assert doc.startswith('Given two integers')


def test_mandatory_headings_are_emitted_for_portuguese():
    doc = statement.build_enunciado(BLOCKS, language='pt-br')
    assert '## Entrada' in doc
    assert '## Saída' in doc


def test_headings_follow_the_statement_language():
    """validate-problem.sh accepts entrada|input and saída|saida|output, case
    insensitively, so an English statement gets English headings and still
    passes."""
    doc = statement.build_enunciado(BLOCKS, language='en')
    assert '## Input' in doc
    assert '## Output' in doc


def test_an_unknown_language_falls_back_to_portuguese():
    doc = statement.build_enunciado(BLOCKS, language='de')
    assert '## Entrada' in doc
    assert '## Saída' in doc


def test_mandatory_headings_are_emitted_even_without_the_blocks():
    """MOJ hard-requires both headings; a statement missing the sections must
    still produce a package that passes the gate."""
    doc = statement.build_enunciado({'legend': 'Prose.'}, language='pt-br')
    assert '## Entrada' in doc
    assert '## Saída' in doc


def test_notes_block_becomes_a_section():
    doc = statement.build_enunciado(
        {**BLOCKS, 'notes': 'Beware of overflow.'}, language='pt-br'
    )
    assert '## Notas' in doc
    assert 'Beware of overflow.' in doc


def test_no_notes_section_without_a_notes_block():
    assert '## Notas' not in statement.build_enunciado(BLOCKS, language='pt-br')


def test_blocks_are_converted_to_markdown():
    doc = statement.build_enunciado(
        {**BLOCKS, 'legend': '\\textbf{bold} and \\includegraphics{fig.png}'},
        language='pt-br',
    )
    assert '**bold**' in doc
    assert '![](fig.png)' in doc


def test_a_block_leaking_examples_is_rejected():
    with pytest.raises(markdown_export.MojGateError, match='legend'):
        statement.build_enunciado(
            {**BLOCKS, 'legend': '\\section*{Exemplos}'}, language='pt-br'
        )


def test_explanations_are_written_per_sample_by_test_name():
    """mojtools pairs docs/notes/<sample>.md to tests/input/<sample> BY NAME."""
    notes = statement.build_notes({0: 'First sample.', 2: 'Third sample.'})
    assert set(notes) == {
        naming.testcase_name('samples', group_index=0, index=1, is_sample=True),
        naming.testcase_name('samples', group_index=0, index=3, is_sample=True),
    }
    assert set(notes) == {'sample001', 'sample003'}
    assert notes['sample001'].strip() == 'First sample.'


def test_explanations_are_converted_to_markdown():
    notes = statement.build_notes({0: '\\textbf{bold}'})
    assert '**bold**' in notes['sample001']


def test_a_note_carrying_math_ships_without_a_warning(capsys):
    """MOJ supports math in sample notes, so a note carrying it is shipped
    as-is and says nothing."""
    notes = statement.build_notes({0: 'The answer is $x + y$.'})
    assert '$x + y$' in notes['sample001']
    assert capsys.readouterr().out == ''


# A 1x1 PNG, so an inlined payload is a real image rather than invented bytes.
PNG_BYTES = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM'
    'IQAAAABJRU5ErkJggg=='
)

FIGURE_BLOCKS = {
    'legend': 'See it:\n\n\\includegraphics{assets/fig.png}',
    'input': 'A single line.',
    'output': 'A single line.',
}


@pytest.fixture
def docs_with_figure(tmp_path: pathlib.Path) -> pathlib.Path:
    """A materialized `docs/` holding the one figure the blocks below cite."""
    docs = tmp_path / 'docs'
    (docs / 'assets').mkdir(parents=True)
    (docs / 'assets' / 'fig.png').write_bytes(PNG_BYTES)
    return docs


@pytest.fixture
def inlining(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statement, 'INLINE_IMAGES_AS_BASE64', True)


@pytest.fixture
def shipping_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statement, 'INLINE_IMAGES_AS_BASE64', False)


def test_the_default_is_to_inline(docs_with_figure: pathlib.Path):
    """Pinned rather than left implicit: which mode a package gets is the whole
    point of the switch, and every other test here sets it explicitly."""
    doc = statement.build_enunciado(
        FIGURE_BLOCKS, language='pt-br', docs_root=docs_with_figure
    )
    assert 'data:image/png;base64,' in doc


def test_shipping_files_keeps_the_reference_pointing_at_the_file(
    shipping_files,
    docs_with_figure: pathlib.Path,
):
    """The image travels as its own file and the document cites it, which is the
    shape render-statement.sh's --resource-path exists for."""
    doc = statement.build_enunciado(
        FIGURE_BLOCKS, language='pt-br', docs_root=docs_with_figure
    )
    assert '(assets/fig.png)' in doc
    assert 'data:image/png;base64,' not in doc


def test_inlining_carries_the_figure_inside_the_document(
    inlining, docs_with_figure: pathlib.Path
):
    doc = statement.build_enunciado(
        FIGURE_BLOCKS, language='pt-br', docs_root=docs_with_figure
    )
    assert f'data:image/png;base64,{base64.b64encode(PNG_BYTES).decode()}' in doc
    assert '(assets/fig.png)' not in doc


def test_inlining_carries_a_note_figure_too(inlining, docs_with_figure: pathlib.Path):
    notes = statement.build_notes(
        {0: 'Look:\n\n\\includegraphics{assets/fig.png}'},
        docs_root=docs_with_figure,
    )
    assert 'data:image/png;base64,' in notes['sample001']


def test_inlining_without_a_docs_root_leaves_the_references_alone(inlining):
    """Nothing on disk to read, so rewriting could only cite files the caller is
    not shipping."""
    doc = statement.build_enunciado(FIGURE_BLOCKS, language='pt-br')
    assert '(assets/fig.png)' in doc


def test_inlining_leaves_a_reference_it_cannot_resolve(
    inlining, docs_with_figure: pathlib.Path
):
    """A missing file, an absolute URL: not this rewrite's to fix, and MOJ's own
    renderer complains about the first in the same words either way."""
    doc = statement.build_enunciado(
        {
            'legend': (
                '\\includegraphics{assets/missing.png}\n\n'
                '\\includegraphics{https://example.com/f.png}'
            ),
        },
        language='pt-br',
        docs_root=docs_with_figure,
    )
    assert '(assets/missing.png)' in doc
    assert '(https://example.com/f.png)' in doc


def test_discarding_inlined_assets_removes_the_files_and_their_dirs(
    inlining, tmp_path: pathlib.Path
):
    (tmp_path / 'docs' / 'assets').mkdir(parents=True)
    (tmp_path / 'docs' / 'assets' / 'fig.png').write_bytes(PNG_BYTES)
    (tmp_path / 'docs' / 'enunciado.md').write_text('kept\n')
    bundle = export.StatementBundle(
        blocks={},
        explanations={},
        assets=[
            export.BundledAsset(
                asset=export.ResolvedAsset(
                    scope=export.AssetScope.STATEMENT,
                    source=tmp_path / 'docs' / 'assets' / 'fig.png',
                    rel=pathlib.PurePosixPath('fig.png'),
                ),
                dest=pathlib.PurePosixPath('docs/assets/fig.png'),
            )
        ],
        remaps={},
    )

    statement.discard_inlined_assets(bundle, tmp_path)

    assert not (tmp_path / 'docs' / 'assets').exists()
    assert (tmp_path / 'docs' / 'enunciado.md').is_file()


def test_discarding_is_a_no_op_when_the_files_are_what_ships(
    shipping_files,
    tmp_path: pathlib.Path,
):
    (tmp_path / 'docs' / 'assets').mkdir(parents=True)
    (tmp_path / 'docs' / 'assets' / 'fig.png').write_bytes(PNG_BYTES)
    bundle = export.StatementBundle(
        blocks={},
        explanations={},
        assets=[
            export.BundledAsset(
                asset=export.ResolvedAsset(
                    scope=export.AssetScope.STATEMENT,
                    source=tmp_path / 'docs' / 'assets' / 'fig.png',
                    rel=pathlib.PurePosixPath('fig.png'),
                ),
                dest=pathlib.PurePosixPath('docs/assets/fig.png'),
            )
        ],
        remaps={},
    )

    statement.discard_inlined_assets(bundle, tmp_path)

    assert (tmp_path / 'docs' / 'assets' / 'fig.png').is_file()


def test_layout_uses_docs_as_the_remap_base_for_both_slots():
    """The note FILE lives in docs/notes/, but gen-problem-json.sh renders it
    with --resource-path=<pkg>/docs, so its images resolve against docs/. A
    remap base of docs/notes/ would derive '../assets/f.png' and break every
    note image."""
    layout = statement.moj_layout()
    assert layout.document_dir(export.DocumentSlot.body()) == pathlib.PurePosixPath(
        'docs'
    )
    assert layout.document_dir(export.DocumentSlot.sample(1)) == pathlib.PurePosixPath(
        'docs'
    )


def test_layout_keeps_sample_assets_namespaced_by_index():
    layout = statement.moj_layout()
    asset = export.ResolvedAsset(
        scope=export.AssetScope.SAMPLE,
        source=pathlib.Path('/nowhere/diagram.png'),
        rel=pathlib.PurePosixPath('diagram.png'),
        sample_index=1,
    )
    assert layout.place_asset(asset) == pathlib.PurePosixPath(
        'docs/samples/001/diagram.png'
    )


def test_layout_rasterizes_pdf_assets():
    layout = statement.moj_layout()
    asset = export.ResolvedAsset(
        scope=export.AssetScope.TIKZ,
        source=pathlib.Path('/nowhere/artifacts/tikz_figures/i_0.pdf'),
        rel=pathlib.PurePosixPath('artifacts/tikz_figures/i_0.pdf'),
    )
    assert layout.place_asset(asset).suffix == '.png'
