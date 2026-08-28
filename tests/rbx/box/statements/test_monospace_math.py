r"""Exhaustive tests for the monospace-group rewrite.

The module is pure text in, text out, so this suite is table-driven and needs no
fixtures, no pandoc and no package on disk. It is organized around the contract
in three parts: what gets rewritten, what is deliberately left alone, and the
invariants that hold over *every* case in the first two tables.
"""

import itertools

import pytest

from rbx.box.statements import monospace_math

REWRITTEN = [
    # -- the reported defect, in both of its spellings ---------------------
    ('\\texttt{A $a_i$ $t_i$}', '$\\texttt{A}~a_i~t_i$'),
    ('\\texttt{T $x_i$}', '$\\texttt{T}~x_i$'),
    ('{\\tt A $a_i$ B}', '$\\texttt{A}~a_i~\\texttt{B}$'),
    ('{\\ttfamily x $y$}', '$\\texttt{x}~y$'),
    # A switch may be spelled with padding; the group is what scopes it.
    ('{ \\tt A $x$}', '$\\texttt{A}~x$'),
    ('\\texttt {A $x$}', '$\\texttt{A}~x$'),
    # -- where the math sits inside the group ------------------------------
    ('\\texttt{$x$ A}', '$x~\\texttt{A}$'),
    ('\\texttt{$x$}', '$x$'),
    ('\\texttt{$x$$y$}', '$x~y$'),
    ('\\texttt{A $x$ B $y$ C}', '$\\texttt{A}~x~\\texttt{B}~y~\\texttt{C}$'),
    # -- whitespace collapses into the tie ---------------------------------
    ('\\texttt{A   $x$}', '$\\texttt{A}~x$'),
    ('\\texttt{  A $x$  }', '$\\texttt{A}~x$'),
    ('\\texttt{A\tB $x$}', '$\\texttt{A}~\\texttt{B}~x$'),
    # -- escaped specials survive the move into math mode ------------------
    ('\\texttt{100\\% $n$}', '$\\texttt{100\\%}~n$'),
    ('\\texttt{a\\_b $n$}', '$\\texttt{a\\_b}~n$'),
    ('\\texttt{\\$ $n$}', '$\\texttt{\\$}~n$'),
    ('\\texttt{\\& $n$}', '$\\texttt{\\&}~n$'),
    # -- math bodies are carried through verbatim --------------------------
    ('\\texttt{A $a_i + t_i$}', '$\\texttt{A}~a_i + t_i$'),
    ('\\texttt{A $\\frac{1}{2}$}', '$\\texttt{A}~\\frac{1}{2}$'),
    ('\\texttt{A $ x $}', '$\\texttt{A}~x$'),
    # -- only the offending group is touched -------------------------------
    (
        '\\texttt{a $x$} e \\texttt{plain} e $y$',
        '$\\texttt{a}~x$ e \\texttt{plain} e $y$',
    ),
    (
        'antes \\texttt{A $x$} meio \\texttt{B $y$} depois',
        'antes $\\texttt{A}~x$ meio $\\texttt{B}~y$ depois',
    ),
    # A literal region next to a rewritable group does not shield it.
    (
        '\\verb|$a$| e \\texttt{A $x$}',
        '\\verb|$a$| e $\\texttt{A}~x$',
    ),
    (
        '\\begin{verbatim}$a$\\end{verbatim}\n\\texttt{A $x$}',
        '\\begin{verbatim}$a$\\end{verbatim}\n$\\texttt{A}~x$',
    ),
]

UNTOUCHED = [
    # -- nothing to do -----------------------------------------------------
    '',
    'no monospace here',
    'math alone $x$ stays',
    '\\texttt{D}',
    '\\texttt{}',
    '{\\tt plain}',
    '\\textbf{A $x$}',  # container node: pandoc nests Math fine
    '\\emph{A $x$}',
    '\\href{http://x}{A $x$}',
    # -- literal regions ---------------------------------------------------
    # `\verb` is the case a TexSoup-based implementation gets wrong:
    # `find_all('texttt')` descends into it, though not into `verbatim`.
    '\\verb|A $a_i$ \\texttt{q $z$}|',
    '\\verb+\\texttt{q $z$}+',
    '\\verb*|\\texttt{q $z$}|',
    '\\begin{verbatim}\\texttt{a $b$}\\end{verbatim}',
    '\\begin{lstlisting}\\texttt{a $b$}\\end{lstlisting}',
    # Unterminated literal regions swallow the rest, as LaTeX would.
    '\\verb|\\texttt{a $b$}',
    '\\begin{verbatim}\\texttt{a $b$}',
    # -- bail-outs inside an otherwise rewritable group --------------------
    '\\texttt{\\textbf{A} $x$}',  # nested markup
    '\\texttt{\\LaTeX $x$}',  # a control word
    '\\texttt{{A} $x$}',  # a bare group
    '\\texttt{x $$y$$}',  # display math
    '\\texttt{a_b $x$}',  # bare subscript
    '\\texttt{a^b $x$}',  # bare superscript
    '\\texttt{50% $x$}',  # bare comment character
    '\\texttt{a&b $x$}',
    '\\texttt{a#b $x$}',
    '\\texttt{a~b $x$}',
    '\\texttt{unclosed $x}',  # unbalanced math
    '\\texttt{empty $ $}',  # empty math run
    '\\texttt{A $x$',  # unbalanced group
    '{\\tt A $x$',
    '\\texttt{trailing backslash $x$ \\',
]


@pytest.mark.parametrize(('tex', 'expected'), REWRITTEN, ids=range(len(REWRITTEN)))
def test_monospace_group_with_math_becomes_one_math_span(tex, expected):
    assert monospace_math.rewrap_monospace_math(tex) == expected


@pytest.mark.parametrize('tex', UNTOUCHED, ids=range(len(UNTOUCHED)))
def test_everything_else_is_returned_verbatim(tex):
    assert monospace_math.rewrap_monospace_math(tex) == tex


# ---------------------------------------------------------------------------
# Invariants over the whole corpus.
# ---------------------------------------------------------------------------

CORPUS = [tex for tex, _ in REWRITTEN] + UNTOUCHED


@pytest.mark.parametrize('tex', CORPUS, ids=range(len(CORPUS)))
def test_rewrite_is_idempotent(tex):
    """A rewritten group has no monospace-with-math left to rewrite.

    This is what makes the transform safe to apply to a block twice -- and it
    would fail loudly if a rewritten `$\\texttt{A}~x$` were itself seen as a
    monospace group holding math.
    """
    once = monospace_math.rewrap_monospace_math(tex)
    assert monospace_math.rewrap_monospace_math(once) == once


@pytest.mark.parametrize('tex', CORPUS, ids=range(len(CORPUS)))
def test_math_delimiters_stay_as_balanced_as_they_came_in(tex):
    """The rewrite never *introduces* an odd `$`.

    An unbalanced delimiter would swallow the rest of the statement into math
    mode -- the single worst failure this transform could produce. The corpus
    includes deliberately malformed input, so the invariant is preservation:
    input that was balanced stays balanced, input that was not is not made
    worse.
    """
    out = monospace_math.rewrap_monospace_math(tex)
    assert (out.replace('\\$', '').count('$') % 2) == (
        tex.replace('\\$', '').count('$') % 2
    )


@pytest.mark.parametrize('tex', CORPUS, ids=range(len(CORPUS)))
def test_braces_stay_as_balanced_as_they_came_in(tex):
    def imbalance(text: str) -> int:
        stripped = text.replace('\\{', '').replace('\\}', '')
        return stripped.count('{') - stripped.count('}')

    assert imbalance(monospace_math.rewrap_monospace_math(tex)) == imbalance(tex)


@pytest.mark.parametrize('tex', CORPUS, ids=range(len(CORPUS)))
def test_surrounding_text_is_preserved(tex):
    """Prose bracketing a block survives untouched, wherever the block sits."""
    out = monospace_math.rewrap_monospace_math(f'antes {tex} depois')
    assert out.startswith('antes ')
    assert out.endswith(' depois')
    assert out[6:-7] == monospace_math.rewrap_monospace_math(tex)


def test_a_document_with_no_monospace_is_returned_identical():
    tex = (
        'Um paragrafo com $x$ e \\textbf{negrito}, uma lista:\n'
        '\\begin{itemize}\\item $a_i \\le 10^5$\\end{itemize}\n'
        'e uma imagem \\includegraphics{fig.png}.\n'
    )
    assert monospace_math.rewrap_monospace_math(tex) == tex


# ---------------------------------------------------------------------------
# Generated combinations: every body shape crossed with every wrapper, so a
# regression in one spelling cannot hide behind another being tested.
# ---------------------------------------------------------------------------

WRAPPERS = [
    ('\\texttt{', '}'),
    ('{\\tt ', '}'),
    ('{\\ttfamily ', '}'),
]

BODIES = [
    ('A $x$', '$\\texttt{A}~x$'),
    ('$x$ A', '$x~\\texttt{A}$'),
    ('A $x$ B', '$\\texttt{A}~x~\\texttt{B}$'),
    ('$x$ $y$', '$x~y$'),
    ('A\\% $x$', '$\\texttt{A\\%}~x$'),
]


@pytest.mark.parametrize(('wrapper', 'body'), list(itertools.product(WRAPPERS, BODIES)))
def test_every_wrapper_rewrites_every_body_shape(wrapper, body):
    opening, closing = wrapper
    source, expected = body
    assert monospace_math.rewrap_monospace_math(opening + source + closing) == expected


@pytest.mark.parametrize('wrapper', WRAPPERS)
@pytest.mark.parametrize(
    'body', ['plain', 'D', 'a_b $x$', '\\textbf{A} $x$', 'x $$y$$']
)
def test_every_wrapper_bails_on_every_bad_body(wrapper, body):
    opening, closing = wrapper
    tex = opening + body + closing
    assert monospace_math.rewrap_monospace_math(tex) == tex


@pytest.mark.parametrize('count', [1, 2, 5])
def test_many_groups_in_one_block_are_all_rewritten(count):
    tex = ' '.join(['\\texttt{A $x$}'] * count)
    expected = ' '.join(['$\\texttt{A}~x$'] * count)
    assert monospace_math.rewrap_monospace_math(tex) == expected


@pytest.mark.parametrize(
    'delimiter', ['|', '+', '!', '/', '"', "'", '#', '%', '=', '?']
)
def test_verb_is_skipped_whatever_its_delimiter(delimiter):
    tex = f'\\verb{delimiter}\\texttt{{q $z$}}{delimiter} e \\texttt{{A $x$}}'
    out = monospace_math.rewrap_monospace_math(tex)
    assert out == f'\\verb{delimiter}\\texttt{{q $z$}}{delimiter} e $\\texttt{{A}}~x$'
