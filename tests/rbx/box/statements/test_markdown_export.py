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
