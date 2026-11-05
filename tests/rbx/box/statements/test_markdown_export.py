"""Golden files for the Polygon-TeX subset through pandoc.

One `.tex`/`.md` pair per construct. These record *behavior*: the whole subset
was verified to survive `pandoc -f latex -t markdown` and round-trip back to
HTML the way MOJ renders it, so a diff here means pandoc changed, not that the
expectation was aspirational.
"""

import os
import pathlib

import pytest

from rbx import tooling
from rbx.box.statements import markdown_export

TESTDATA = pathlib.Path(__file__).parent / 'testdata' / 'markdown_export'

CASES = sorted(path.stem for path in TESTDATA.glob('*.tex'))

# The pandoc whose Markdown writer these goldens record. CI installs exactly
# this one; keep the two in step (`.github/workflows/tests.yml`).
PANDOC_GOLDEN = '3.7.0.2'


@pytest.fixture
def golden_pandoc():
    """Skip when the installed pandoc is not the one the goldens record.

    The writer changes between releases -- 3.1.3 pads list markers to
    `-   item` and falls back to a simple table where 3.7 writes an aligned
    grid one -- so on another version these cases fail for a reason that has
    nothing to do with the setter's change, and the diff is pandoc's.

    CI is exempt: it installs `PANDOC_GOLDEN` on purpose, so a mismatch there
    means the workflow drifted from this constant and must be seen.
    """
    if os.environ.get('CI') or not tooling.PANDOC.is_available():
        return

    import pypandoc

    version = pypandoc.get_pandoc_version()
    if version != PANDOC_GOLDEN:
        pytest.skip(
            f'these goldens record pandoc {PANDOC_GOLDEN}, but pandoc {version} '
            f'is installed, and its Markdown writer differs.'
        )


def test_there_are_goldens():
    assert CASES


@pytest.mark.parametrize('case', CASES)
def test_tex_converts_to_the_golden_markdown(case, golden_pandoc):
    tex = (TESTDATA / f'{case}.tex').read_text()
    expected = (TESTDATA / f'{case}.md').read_text()
    assert markdown_export.tex_to_markdown(tex) == expected


def test_image_alt_text_is_cleared():
    """pandoc's LaTeX reader emits ![image](f.png); non-empty alt triggers
    implicit_figures on MOJ's side, captioning EVERY figure 'image'."""
    out = markdown_export.tex_to_markdown('\\includegraphics{fig.png}')
    assert '![](fig.png)' in out
    assert '![image]' not in out


def test_converted_output_has_no_fences():
    """A ``` fence trips validate-problem.sh's hand-written-example warning.
    pandoc emits INDENTED code blocks by default -- this pins that."""
    out = markdown_export.tex_to_markdown(
        '\\begin{lstlisting}\nx = 1\n\\end{lstlisting}'
    )
    assert '```' not in out


def test_inline_math_survives_untouched():
    """MOJ renders with --mathml, so $...$ needs no conversion at all."""
    out = markdown_export.tex_to_markdown('The value $n \\le 10^5$ holds.')
    assert '$n \\le 10^5$' in out


def test_rewrapped_monospace_math_reaches_markdown_as_one_span():
    """The end-to-end shape MOJ reads back: one `$...$`, no split code spans."""
    out = markdown_export.tex_to_markdown('\\texttt{A $a_i$ $t_i$} is a reply.')
    assert '$\\texttt{A}~a_i~t_i$' in out
    assert '`' not in out


@pytest.mark.parametrize(
    'block',
    [
        '## Exemplos\n',
        '### Examples\n',
        '```\nx\n```\n',
    ],
)
def test_gate_guard_rejects_leaked_examples(block):
    with pytest.raises(markdown_export.MojGateError, match='legend'):
        markdown_export.check_moj_gate(block, block_name='legend')


@pytest.mark.parametrize(
    'block',
    [
        'Just prose.\n',
        '## Entrada\n\nA single integer.\n',
        'An example is worth a thousand words.\n',
    ],
)
def test_gate_guard_accepts_clean_blocks(block):
    markdown_export.check_moj_gate(block, block_name='legend')


# --- what pandoc drops (#1013) -------------------------------------------------


def test_a_dropped_command_is_reported_with_its_snippet():
    conversion = markdown_export.convert_tex_to_markdown(r'a \foo{x} b')
    assert [d.snippet for d in conversion.diagnostics] == [r'\foo{x}']
    assert all(d.dropped for d in conversion.diagnostics)


def test_translated_symbols_are_not_reported_as_dropped():
    conversion = markdown_export.convert_tex_to_markdown(r'a \textbar\space b \foo{x}')
    assert [d.snippet for d in conversion.diagnostics] == [r'\foo{x}']


def test_clean_input_has_no_diagnostics():
    tex = r'Read $n$ and \textbf{print} \texttt{x}. \textless{} \S'
    assert markdown_export.convert_tex_to_markdown(tex).diagnostics == []


def test_layout_only_commands_are_not_reported():
    tex = '\\noindent a\n\n\\medskip\n\\vspace{1em}\n\\begin{center}\\centering b\\end{center}'
    assert markdown_export.convert_tex_to_markdown(tex).diagnostics == []


def test_a_backtracked_skip_is_reported_once():
    # pandoc's reader reports `\centering` twice here at one position; it is
    # not in the table when called raw, so go through the raw diagnostics.
    import logging

    record = logging.LogRecord(
        'pypandoc', logging.INFO, '', 0, "Skipped '\\x ' at line 1 column 3", (), None
    )
    diagnostics = markdown_export.diagnostics_from_records([record, record])
    assert [d.snippet for d in diagnostics] == ['\\x']


def test_other_info_lines_are_ignored_and_warnings_kept():
    import logging

    records = [
        logging.LogRecord('pypandoc', logging.INFO, '', 0, 'Loaded foo', (), None),
        logging.LogRecord(
            'pypandoc', logging.WARNING, '', 0, 'Could not convert TeX math', (), None
        ),
    ]
    diagnostics = markdown_export.diagnostics_from_records(records)
    assert diagnostics == [
        markdown_export.PandocDiagnostic(message='Could not convert TeX math')
    ]


def test_capturing_leaves_the_pypandoc_logger_as_it_was():
    import logging

    logger = logging.getLogger('pypandoc')
    before = (logger.level, logger.propagate)
    markdown_export.convert_tex_to_markdown(r'a \foo b')
    assert (logger.level, logger.propagate) == before
    # pypandoc may add its own handler on an uncaptured call; ours never stays.
    assert not any(type(h).__name__ == '_Capture' for h in logger.handlers)


def test_the_markdown_config_supports_translated_and_native_commands():
    from rbx.box.statements import polygon_utils

    tex = r'a \textbar\space b \textless{} \hspace*{1em} \foo{x}'
    errors = polygon_utils.validate_polygon_tex(
        tex, markdown_export.markdown_tex_config()
    )
    assert [e.construct for e in errors] == [r'\foo']
    # The Polygon default is untouched.
    assert len(polygon_utils.validate_polygon_tex(tex)) == 5


def test_dropped_content_is_never_printed_raw(capfd):
    # pypandoc installs its own stderr handler after its first conversion with
    # none attached; a later capture must still be the only place records go.
    import pypandoc

    pypandoc.convert_text('x', 'markdown', format='latex')
    markdown_export.convert_tex_to_markdown(r'a \foo b')
    markdown_export.convert_tex_to_markdown(r'a \foo b')
    captured = capfd.readouterr()
    assert 'Skipped' not in captured.err
    assert 'Skipped' not in captured.out
