"""Assembling `docs/enunciado.md` and `docs/notes/<sample>.md` for MOJ."""

import base64
import pathlib

import pytest

from rbx.box.packaging.moj import naming, statement
from rbx.box.statements import export, markdown_export
from rbx.box.testcase_sample_utils import SampleTestcaseInteraction, StatementSample
from rbx.box.testcase_utils import TestcaseInteractionEntry
from tests.rbx.box.packaging.moj.conftest import build_entries

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


def test_spanish_headings_pass_the_gate():
    """validate-problem.sh also accepts `salida`, so a Spanish statement reads
    Spanish and still passes."""
    doc = statement.build_enunciado(BLOCKS, language='es')
    assert '## Entrada' in doc
    assert '## Salida' in doc


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


def test_document_paths_carry_the_language_suffix():
    """`statement-langs.sh` finds a translation at `docs/enunciado.<lang>.md` and
    its notes at `docs/notes/<sample>.<lang>.md`; the canonical slot has no suffix."""
    assert str(statement.enunciado_path()) == 'docs/enunciado.md'
    assert str(statement.enunciado_path('en')) == 'docs/enunciado.en.md'
    assert str(statement.note_path('sample001')) == 'docs/notes/sample001.md'
    assert str(statement.note_path('sample001', 'es')) == 'docs/notes/sample001.es.md'


def test_moj_language_is_the_subtag():
    assert statement.moj_language('pt-br') == 'pt'
    assert statement.moj_language('EN') == 'en'
    assert statement.moj_language('es') == 'es'


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


# -- the `## Exemplo` section of a SAMPLE=no package -----------------------------


def _sample(tmp_path, index, interaction=None, input_text='1\n', output_text='2\n'):
    entry = build_entries(tmp_path, ['samples'])[index]
    testcase = entry.metadata.copied_to
    testcase.inputPath.write_text(input_text)
    testcase.outputPath.write_text(output_text)
    return StatementSample(
        entry=entry,
        inputPath=testcase.inputPath,
        outputPath=testcase.outputPath,
        interaction=SampleTestcaseInteraction(
            entries=[
                TestcaseInteractionEntry(data=data, pipe=pipe)
                for pipe, data in interaction
            ],
            chunks=[],
        )
        if interaction is not None
        else None,
    )


GUESS = [(0, '10'), (1, '6'), (0, '<'), (1, '! 3')]


def test_examples_render_each_interaction_in_one_block(tmp_path):
    text = statement.build_examples(
        [_sample(tmp_path, 0, GUESS), _sample(tmp_path, 1, [(0, '8'), (1, '! 8')])],
        {},
        language='pt',
    )

    assert text == (
        '## Exemplo\n\n'
        'Linhas recuadas são do árbitro; as demais, do seu programa.\n\n'
        '### Exemplo 1\n\n'
        '```\n       10\n6\n       <\n! 3\n```\n\n'
        '### Exemplo 2\n\n'
        '```\n       8\n! 8\n```'
    )


def test_examples_are_labelled_in_the_statement_language(tmp_path):
    text = statement.build_examples([_sample(tmp_path, 0, GUESS)], {}, language='en')
    assert text.startswith(
        "## Example\n\nIndented lines are the interactor's; the others are your "
        "program's.\n\n### Example 1\n\n"
    )


def test_examples_leave_the_program_stderr_out(tmp_path):
    text = statement.build_examples(
        [_sample(tmp_path, 0, [(0, '10'), (2, 'debug'), (1, '! 3')])],
        {},
        language='pt',
    )
    assert 'debug' not in text
    assert '```\n       10\n! 3\n```' in text


def test_examples_put_the_interactor_in_a_column_past_the_widest_program_line(
    tmp_path,
):
    text = statement.build_examples(
        [
            _sample(
                tmp_path,
                0,
                [(0, '5'), (1, '? 1 2\n? 100 200'), (0, '1\n2'), (1, '! 3')],
            )
        ],
        {},
        language='pt',
    )
    pad = ' ' * len('? 100 200') + statement.INTERACTOR_GAP
    assert f'```\n{pad}5\n? 1 2\n? 100 200\n{pad}1\n{pad}2\n! 3\n```' in text


def test_examples_column_counts_wide_characters_by_their_cells(tmp_path):
    text = statement.build_examples(
        [_sample(tmp_path, 0, [(1, '漢字'), (0, 'ok')])], {}, language='pt'
    )
    assert f'```\n漢字\n{" " * 4}{statement.INTERACTOR_GAP}ok\n```' in text


def test_examples_without_program_lines_only_shift_by_the_gap(tmp_path):
    text = statement.build_examples(
        [_sample(tmp_path, 0, [(0, 'hello')])], {}, language='pt'
    )
    assert f'```\n{statement.INTERACTOR_GAP}hello\n```' in text


def test_examples_fence_cannot_be_closed_by_the_transcript(tmp_path):
    text = statement.build_examples(
        [_sample(tmp_path, 0, [(1, '```')])], {}, language='pt'
    )
    assert '````\n```\n````' in text


def test_examples_without_an_interaction_show_input_and_output(tmp_path):
    text = statement.build_examples(
        [_sample(tmp_path, 0, None, input_text='3 10\n', output_text='3\n')],
        {},
        language='pt',
    )
    assert '**Entrada**\n\n```\n3 10\n```\n\n**Saída**\n\n```\n3\n```' in text
    # Nothing is indented, so there is nothing to explain.
    assert 'recuadas' not in text


def test_examples_carry_each_explanation_under_its_sample(tmp_path):
    text = statement.build_examples(
        [_sample(tmp_path, 0, GUESS), _sample(tmp_path, 1, GUESS)],
        {1: 'O segundo exemplo.'},
        language='pt',
    )
    assert text.index('### Exemplo 2') < text.index('O segundo exemplo.')


def test_no_samples_no_examples_section():
    assert statement.build_examples([], {}, language='pt') == ''


def test_enunciado_ends_with_the_examples():
    text = statement.build_enunciado(
        {'legend': 'L.', 'input': 'I.', 'output': 'O.'},
        language='pt',
        examples='## Exemplo\n\nx',
    )
    assert text.endswith('## Saída\n\nO.\n\n## Exemplo\n\nx\n')
