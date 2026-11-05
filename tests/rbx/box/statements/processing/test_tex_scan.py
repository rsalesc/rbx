import pytest

from rbx.box.statements.processing import tex_scan

TAG = '\ue0003:7\ue001'  # a sourcemap tag


@pytest.mark.parametrize(
    'text, name, end',
    [
        (r'\foo bar', 'foo', 4),
        (r'\icpcstrings@en{', 'icpcstrings@en', 15),
        (r'\,x', ',', 2),
        (r'\\x', '\\', 2),
        ('\\', '', 1),
    ],
)
def test_read_control_sequence(text, name, end):
    assert tex_scan.read_control_sequence(text, 0) == (name, end)


@pytest.mark.parametrize(
    'text, open_ch, end',
    [
        ('{a{b}c}rest', '{', 7),
        (r'{a\}b}rest', '{', 6),
        ('{a % }\nb}rest', '{', 9),
        ('[x{]}y]rest', '[', 7),
        ('{never', '{', None),
        ('[a}b]', '[', None),
    ],
)
def test_read_group(text, open_ch, end):
    assert tex_scan.read_group(text, 0, open_ch) == end


def test_skip_blanks_steps_over_comments_and_sourcemap_tags():
    text = f'  % c\n{TAG}  x'
    assert text[tex_scan.skip_blanks(text, 0)] == 'x'
    # Without newlines it still eats the comment, which eats its own newline.
    assert text[tex_scan.skip_blanks(text, 0, newlines=False)] == 'x'


@pytest.mark.parametrize(
    'text, expected',
    [
        ('{a}b', ('a', 0, 3)),
        ('  {a}', ('a', 2, 5)),
        ('\n {a}', ('a', 2, 5)),
        (r' \foo x', (r'\foo', 1, 5)),
        (' xy', ('x', 1, 2)),
        # A paragraph break: TeX would pass \par.
        ('\n\n{a}', None),
        ('}', None),
        ('', None),
    ],
)
def test_read_argument(text, expected):
    assert tex_scan.read_argument(text, 0) == expected


def test_find_environment_end_counts_nesting_and_skips_verbatim():
    text = (
        r'\begin{tikzpicture}a\begin{tikzpicture}b\end{tikzpicture}'
        r'\begin{verbatim}\end{tikzpicture}\end{verbatim}'
        r'% \end{tikzpicture}' + '\n'
        r'\end{tikzpicture}tail'
    )
    start = len(r'\begin{tikzpicture}')
    assert text[tex_scan.find_environment_end(text, start, 'tikzpicture') :] == ('tail')


@pytest.mark.parametrize(
    'text, command, expected',
    [
        (r'\newcommand{\a}{x}', 'newcommand', ('a', 0, None, 'x')),
        (r'\newcommand\a[2]{#1#2}', 'newcommand', ('a', 2, None, '#1#2')),
        (r'\newcommand*{\a}[1] [d] {x{y}}', 'newcommand', ('a', 1, 'd', 'x{y}')),
        # A comment between the name and the body (#1006's `\thanksButton`).
        ('\\newcommand{\\a} % note\n{x}', 'newcommand', ('a', 0, None, 'x')),
        (r'\def\a#1#2{x}', 'def', ('a', 2, None, 'x')),
        (r'\def\a##1{x}', 'def', ('a', 1, None, 'x')),
        (r'\def\foo@bar{x}', 'def', ('foo@bar', 0, None, 'x')),
        (r'\def\csname foo\endcsname{x}', 'def', None),
        (r'\newcommand{x}{y}', 'newcommand', None),
        (r'\textbf{x}', 'textbf', None),
    ],
)
def test_parse_definition(text, command, expected):
    definition = tex_scan.parse_definition(text, command, len(command) + 1)
    if expected is None:
        assert definition is None
        return
    assert definition is not None
    assert (
        definition.name,
        definition.n_args,
        definition.default,
        definition.body(text),
    ) == expected


def test_definition_bodies_include_nested_and_environment_code():
    text = (
        r'\newcommand{\a}{A\def\b{B}}'
        r'\newenvironment{e}{BEGIN}{END}'
        r'% \def\c{C}' + '\n'
        r'\verb|\def\d{D}| out'
    )
    bodies = [text[start:end] for start, end in tex_scan.definition_bodies(text)]
    assert bodies == [r'A\def\b{B}', 'B', 'BEGIN', 'END']
