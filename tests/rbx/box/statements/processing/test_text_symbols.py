"""The text-symbol translation table and the scanner that applies it.

Pure-text tests first (no pandoc), then the table run through the installed
pandoc: every translated row must arrive with nothing dropped, and every
`PANDOC_NATIVE` command must still be converted by pandoc on its own -- the
golden that notices a pandoc upgrade breaking one.
"""

import pytest

from rbx.box.statements import markdown_export
from rbx.box.statements.processing import text_symbols
from rbx.box.statements.processing.text_symbols import (
    EM_SPACE,
    EN_SPACE,
    TEXT_SYMBOLS,
    THIN_SPACE,
    translate_text_symbols,
)

# --- the scanner ---------------------------------------------------------------


@pytest.mark.parametrize(
    'tex, expected',
    [
        # A control word swallows the blanks after it, and an empty group.
        (r'a \textbar b', 'a |b'),
        (r'a \textbar{} b', 'a | b'),
        (r'a \textbar{}b', 'a |b'),
        (r'a \textbar\ b', r'a |\ b'),
        (r'a\textbar\space b', 'a| b'),
        # One line break is a blank; two are a paragraph and stay.
        ('a \\textbar\nb', 'a |b'),
        ('a \\textbar\n\nb', 'a |\n\nb'),
        # A control symbol swallows nothing.
        (r'a\: b', 'a\u2005 b'),
        (r'a\!b', 'ab'),
        # A longer control word is a different command.
        (r'\textbarx', r'\textbarx'),
        # Characters TeX would read as something else stay escaped.
        (r'\textunderscore{}x', r'\_x'),
        (r'\textbraceleft{}x\textbraceright{}', r'\{x\}'),
        # Inside arguments, as anywhere in text mode.
        (r'\texttt{a\textbar{}b}', r'\texttt{a|b}'),
        (r'\underline{\texttt{2}}\textbar{}', r'\underline{\texttt{2}}|'),
        # Vertical space and layout are dropped as a decision.
        (r'\noindent Hello', 'Hello'),
        ('a\n\\vspace{1em}\nb', 'a\n\nb'),
        (r'a \vspace*{2pt} b', 'a  b'),
    ],
)
def test_translates_in_text_mode(tex, expected):
    assert translate_text_symbols(tex) == expected


@pytest.mark.parametrize(
    'tex',
    [
        r'$a \textbar b$',
        r'$$a \textbar b$$',
        r'\(a \textbar b\)',
        r'\[a \textbar b\]',
        '\\begin{equation}a \\textbar b\\end{equation}',
        '\\begin{align*}a \\quad b\\end{align*}',
        r'\verb|\textbar|',
        '\\begin{verbatim}\n\\textbar \\quad\n\\end{verbatim}',
        '% \\textbar in a comment\n',
        r'\url{http://x.y/\textbar}',
        r'\href{http://x.y/\space}{text}',
        r'\includegraphics[width=\textbar]{a\space b.png}',
        r'\$ \textless{} \S',
        '',
        'plain text with nothing to do',
    ],
)
def test_leaves_alone_what_is_not_text_mode_or_not_in_the_table(tex):
    assert translate_text_symbols(tex) == tex


def test_math_after_an_escaped_dollar_is_still_math():
    assert translate_text_symbols(r'\$5 and $\quad$ \quad') == (
        r'\$5 and $\quad$ ' + EM_SPACE
    )


def test_text_after_math_is_translated():
    assert translate_text_symbols(r'$x$ \textbar{} $y$') == '$x$ | $y$'


def test_text_after_href_is_translated():
    assert translate_text_symbols(r'\href{u}{a\textbar{}b}') == r'\href{u}{a|b}'


def test_the_real_textbar_space_separator():
    tex = (
        '\\begin{center}\n'
        '\\underline{\\texttt{2}}\\texttt{ 1}\n'
        '\\textbar\\space\n'
        '\\underline{\\texttt{4}}\\texttt{ 2}\n'
        '\\end{center}'
    )
    assert translate_text_symbols(tex) == (
        '\\begin{center}\n'
        '\\underline{\\texttt{2}}\\texttt{ 1}\n'
        '| \\underline{\\texttt{4}}\\texttt{ 2}\n'
        '\\end{center}'
    )


@pytest.mark.parametrize(
    'length, expected',
    [
        ('1em', EM_SPACE),
        ('2em', EM_SPACE * 2),
        ('0.5em', EN_SPACE),
        ('1.5em', EM_SPACE + EN_SPACE),
        ('0.9em', EM_SPACE),
        ('0.2em', THIN_SPACE),
        ('0.01em', THIN_SPACE),
        ('11pt', EM_SPACE),
        ('100cm', EM_SPACE * 8),
        ('0pt', ''),
        ('-1em', ''),
        (r'\fill', ' '),
        (r'\stretch{1}', ' '),
        (r'0.5\linewidth', ' '),
        ('3furlongs', ' '),
    ],
)
def test_hspace_becomes_the_closest_unicode_spaces(length, expected):
    assert text_symbols.hspace_to_spaces(length) == expected


def test_hspace_and_its_star_take_their_argument():
    assert translate_text_symbols(r'a\hspace{1em}b\hspace*{0.5em}c') == (
        f'a{EM_SPACE}b{EN_SPACE}c'
    )


def test_a_malformed_hspace_is_left_for_pandoc():
    assert translate_text_symbols(r'a\hspace') == r'a\hspace'


def test_translation_is_idempotent():
    tex = r'a \textbar\space b \quad c \hspace{1em} $\textbar$'
    once = translate_text_symbols(tex)
    assert translate_text_symbols(once) == once


def test_the_native_list_and_the_table_do_not_overlap():
    assert not set(TEXT_SYMBOLS) & text_symbols.PANDOC_NATIVE


def test_supported_names_spell_starred_commands_as_the_validator_does():
    names = text_symbols.supported_names()
    assert {'hspace', 'hspace*', 'vspace*', 'textbar', 'textless'} <= names


# --- through the installed pandoc ----------------------------------------------

_SYMBOL_ROWS = sorted(
    (row for row in TEXT_SYMBOLS.values() if row.arguments == 0),
    key=lambda row: row.name,
)


@pytest.mark.parametrize('row', _SYMBOL_ROWS, ids=lambda row: row.name)
def test_every_translated_symbol_reaches_markdown(row):
    conversion = markdown_export.convert_tex_to_markdown(f'a \\{row.name}{{}} b')
    assert conversion.diagnostics == []
    expected = row.replace().lstrip('\\').strip()
    if expected:
        # Read back the way MOJ does -- pandoc over the Markdown -- since the
        # writer escapes (`\|`) and smartens (`--` for an en dash).
        import pypandoc

        rendered = pypandoc.convert_text(conversion.markdown, 'plain', 'markdown')
        assert expected in rendered


@pytest.mark.parametrize('name', sorted(text_symbols.PANDOC_NATIVE))
def test_pandoc_still_converts_the_native_commands(name):
    conversion = markdown_export.convert_tex_to_markdown(f'a \\{name}{{}} b')
    assert conversion.diagnostics == []
    assert conversion.markdown.strip() != 'a b'


def test_the_real_example_keeps_its_separator():
    tex = (
        '\\begin{center}\n'
        '\\underline{\\texttt{2}}\\texttt{ 1}\n'
        '\\textbar\\space\n'
        '\\underline{\\texttt{4}}\\texttt{ 2}\n'
        '\\end{center}'
    )
    conversion = markdown_export.convert_tex_to_markdown(tex)
    assert conversion.diagnostics == []
    assert '[`2`]{.underline}` 1` \\| [`4`]{.underline}` 2`' in conversion.markdown
