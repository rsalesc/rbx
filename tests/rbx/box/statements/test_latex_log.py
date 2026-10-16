"""`latex.parse_errors` over logs captured from a real pdflatex (TeX Live 2024)
run with `-file-line-error` and an unwrapped log."""

from rbx.box.statements import latex
from rbx.box.statements.latex import parse_errors

UNDEFINED_AND_MATH = r"""This is pdfTeX, Version 3.141592653-2.6-1.40.26 (TeX Live 2024)
(./statement.tex
(/usr/local/texlive/2024/texmf-dist/tex/latex/base/article.cls
Document Class: article 2023/05/17 v1.4n Standard LaTeX document class
(/usr/local/texlive/2024/texmf-dist/tex/latex/base/size10.clo))
./statement.tex:5: Undefined control sequence.
l.5 \foo
        {x}
./statement.tex:6: Missing { inserted.
<to be read again> 
                   $
l.6 $a^$
        
./statement.tex:6: Missing } inserted.
<inserted text> 
                }
l.6 $a^$
        
[1{/usr/local/texlive/2024/texmf-var/fonts/map/pdftex/updmap/pdftex.map}] (./statement.aux) )
Output written on statement.pdf (1 page, 14130 bytes).
"""

MISSING_PACKAGE = r"""(./statement.tex
LaTeX2e <2023-11-01> patch level 1
(/usr/local/texlive/2024/texmf-dist/tex/latex/base/article.cls))

! LaTeX Error: File `nopenope.sty' not found.

Type X to quit or <RETURN> to proceed,
or enter new name. (Default extension: sty)

Enter file name: 
./statement.tex:3: Emergency stop.
<read *> 
         
l.3 \begin
          {document}^^M
./statement.tex:3:  ==> Fatal error occurred, no output PDF file produced!
Transcript written on statement.log.
"""


def _summary(errors):
    return [(e.message, e.file, e.line, e.context) for e in errors]


def test_located_errors_with_context():
    errors = parse_errors(UNDEFINED_AND_MATH)
    # The two halves of a split line are joined with a space: TeX drops the
    # space after a control word where it breaks, and `\foo` + `{x}` must not
    # read as one longer command name.
    assert _summary(errors) == [
        ('Undefined control sequence.', './statement.tex', 5, '\\foo {x}'),
        ('Missing { inserted.', './statement.tex', 6, '$a^$'),
        ('Missing } inserted.', './statement.tex', 6, '$a^$'),
    ]
    assert errors[0].reading == ('\\foo', '{x}')
    # `<to be read again>` and `<inserted text>` are TeX's, never source.
    assert errors[1].excerpts == ()


def test_bare_error_takes_the_emergency_stop_location():
    assert _summary(parse_errors(MISSING_PACKAGE)) == [
        (
            "LaTeX Error: File `nopenope.sty' not found.",
            './statement.tex',
            3,
            '\\begin {document}',
        )
    ]


def test_emergency_stop_alone_is_an_error():
    log = './statement.tex:9: Emergency stop.\nl.9 \\end\n'
    assert _summary(parse_errors(log)) == [
        ('Emergency stop.', './statement.tex', 9, '\\end')
    ]


def test_fatal_trailers_are_not_errors():
    log = (
        '! File ended while scanning use of \\includeProblem.\n'
        '! Emergency stop.\n'
        '!  ==> Fatal error occurred, no output PDF file produced!\n'
    )
    assert [e.message for e in parse_errors(log)] == [
        'File ended while scanning use of \\includeProblem.'
    ]


def test_nested_file_and_windows_paths():
    log = (
        './.samples/000/explanation.tex:2: Undefined control sequence.\n'
        'C:\\work\\statement.tex:7: Missing $ inserted.\n'
    )
    assert [(e.file, e.line) for e in parse_errors(log)] == [
        ('./.samples/000/explanation.tex', 2),
        ('C:\\work\\statement.tex', 7),
    ]


def test_clean_log_has_no_errors():
    assert (
        parse_errors('(./statement.tex [1] )\nOutput written on statement.pdf\n') == []
    )


def test_repeated_error_is_reported_once():
    log = './s.tex:1: Undefined control sequence.\n' * 2
    assert len(parse_errors(log)) == 1


DEFERRED_ARGUMENT = r"""./statement.tex:35: Undefined control sequence.
<argument> \badcmd 
                   The input is a single line containing two integers $A$ and $B$. 
l.35 }
      \end{document}
The control sequence at the end of the top line
"""


def test_error_in_a_stored_argument_keeps_the_argument():
    [error] = parse_errors(DEFERRED_ARGUMENT)
    assert (error.file, error.line) == ('./statement.tex', 35)
    assert error.excerpts == (
        (
            '\\badcmd ',
            'The input is a single line containing two integers $A$ and $B$.',
        ),
    )
    assert error.context == (
        '\\badcmd The input is a single line containing two integers $A$ and $B$.'
    )


# `\errorcontextlines=1000`: every level, here a macro body holding the text.
MACRO_BODY = r"""./statement.tex:7: Missing { inserted.
<to be read again>
                   $
\stored ->Some text here with a formula $a^$
                                             inside and more.
l.7 \stored

"""


def test_macro_body_levels_are_excerpts():
    [error] = parse_errors(MACRO_BODY)
    assert error.excerpts == (
        ('Some text here with a formula $a^$', 'inside and more.'),
    )
    assert error.reading == ('\\stored', '')


def test_bare_error_keeps_its_argument_through_the_emergency_stop():
    log = (
        '! Undefined control sequence.\n'
        '<argument> \\badcmd \n'
        '                   rest of it\n'
        './statement.tex:9: Emergency stop.\n'
        'l.9 \\end{document}\n'
    )
    [error] = parse_errors(log)
    assert (error.file, error.line) == ('./statement.tex', 9)
    assert error.excerpts == (('\\badcmd ', 'rest of it'),)


def test_a_bang_line_inside_a_printed_macro_body_is_not_an_error():
    """With every context level printed, LaTeX's own error macros show their
    bodies -- which hold lines starting with `! `."""
    log = (
        "./statement.tex:3: LaTeX Error: File `nope.sty' not found.\n"
        '\\@missingfileerror #1#2->\\typeout {^^J\n'
        "! LaTeX Error: File `#1.#2' not found.^^J}\n"
        '                         \\@latex@error\n'
        'l.3 \\usepackage{nope}\n'
        '                       \n'
    )
    assert [e.message for e in parse_errors(log)] == [
        "LaTeX Error: File `nope.sty' not found."
    ]


def test_decode_latex_output_reads_utf8():
    assert latex.decode_latex_output('Overfull \\hbox — ç'.encode()) == (
        'Overfull \\hbox — ç'
    )


def test_decode_latex_output_detects_a_non_utf8_log():
    text = 'Underfull \\hbox in paragraph: acentuação é comum em português. ' * 20
    assert latex.decode_latex_output(text.encode('latin-1')) == text
