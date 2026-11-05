import pytest
from TexSoup import TexSoup

from rbx.box.statements.processing import texsoup_utils
from rbx.box.statements.processing.texsoup_utils import (
    add_labels_to_tikz_nodes,
    get_tikz_node_label,
    get_top_level_labeled_tikz_nodes,
    get_top_level_tikz_nodes,
    inject_externalization_for_tikz,
    inject_in_preamble,
    rewrite_includegraphics,
    strip_asset_ext,
)


def test_get_tikz_node_label_immediately_preceding():
    latex = r"""\tikzsetnextfilename{my-label}
\begin{tikzpicture}
\end{tikzpicture}"""
    soup = TexSoup(latex)
    tikz = soup.find('tikzpicture')
    assert get_tikz_node_label(tikz)[1] == 'my-label'


def test_get_tikz_node_label_with_newlines():
    latex = r"""\tikzsetnextfilename{spaced-label}


\begin{tikzpicture}
\end{tikzpicture}"""
    soup = TexSoup(latex)
    tikz = soup.find('tikzpicture')
    assert get_tikz_node_label(tikz)[1] == 'spaced-label'


def test_get_tikz_node_label_none():
    latex = r"""\begin{tikzpicture}
\end{tikzpicture}"""
    soup = TexSoup(latex)
    tikz = soup.find('tikzpicture')
    assert get_tikz_node_label(tikz) is None


def test_get_tikz_node_label_interrupted_by_text():
    # If there's text in between, it should probably return None
    latex = r"""\tikzsetnextfilename{interrupted}
some text
\begin{tikzpicture}
\end{tikzpicture}"""
    soup = TexSoup(latex)
    tikz = soup.find('tikzpicture')
    assert get_tikz_node_label(tikz) is None


def test_get_tikz_node_label_interrupted_by_command():
    latex = r"""\tikzsetnextfilename{interrupted}
\textbf{bold}
\begin{tikzpicture}
\end{tikzpicture}"""
    soup = TexSoup(latex)
    tikz = soup.find('tikzpicture')
    assert get_tikz_node_label(tikz) is None


def test_get_tikz_node_label_with_comment():
    latex = r"""\tikzsetnextfilename{commented}
% This is a comment
\begin{tikzpicture}
\end{tikzpicture}"""
    soup = TexSoup(latex)
    tikz = soup.find('tikzpicture')
    assert get_tikz_node_label(tikz)[1] == 'commented'


def test_get_tikz_node_label_multiple():
    latex = r"""\tikzsetnextfilename{first}
\begin{tikzpicture}
\end{tikzpicture}

\tikzsetnextfilename{second}
\begin{tikzpicture}
\end{tikzpicture}"""
    soup = TexSoup(latex)
    tikzs = list(soup.find_all('tikzpicture'))
    assert len(tikzs) == 2
    assert get_tikz_node_label(tikzs[0])[1] == 'first'
    assert get_tikz_node_label(tikzs[1])[1] == 'second'


def test_inject_in_preamble_with_documentclass():
    latex = r"""\documentclass{article}
\begin{document}
Hello
\end{document}"""
    soup = TexSoup(latex)
    inject_in_preamble(soup, r'\usepackage{foo}')

    # Check that it's inserted after documentclass
    s = str(soup)
    assert r'\documentclass{article}' in s
    assert r'\usepackage{foo}' in s
    # Ensure order
    assert s.index(r'\documentclass{article}') < s.index(r'\usepackage{foo}')


def test_inject_in_preamble_no_documentclass():
    latex = r"""\begin{document}
Hello
\end{document}"""
    soup = TexSoup(latex)
    inject_in_preamble(soup, r'\usepackage{bar}')

    s = str(soup)
    assert r'\usepackage{bar}' in s
    # Should be at the start roughly
    assert s.strip().startswith(r'\usepackage{bar}')


def test_inject_in_preamble_after_leading_comment():
    # Preset templates start with a `%%` comment before \documentclass; the
    # preamble must still land AFTER \documentclass (regression for the Polygon
    # externalize path emitting "\usepackage before \documentclass", #568).
    latex = r"""%% header comment
\documentclass[a4paper,11pt]{article}
\begin{document}
Hello
\end{document}"""
    soup = TexSoup(latex)
    inject_in_preamble(soup, r'\usepackage{foo}')

    s = str(soup)
    assert r'\documentclass[a4paper,11pt]{article}' in s
    assert r'\usepackage{foo}' in s
    assert s.index(r'\documentclass') < s.index(r'\usepackage{foo}')


def test_inject_externalization_for_tikz():
    latex = r"""\documentclass{article}
\begin{document}
\end{document}"""
    soup = TexSoup(latex)
    inject_externalization_for_tikz(soup)

    s = str(soup)
    assert r'\usepackage{tikz}' in s
    assert r'\usetikzlibrary{external}' in s
    assert r'\tikzexternalize[prefix=artifacts/tikz_figures/]' in s


def test_inject_externalization_after_leading_comment():
    # The full externalization preamble must follow \documentclass even when a
    # comment leads the document (the default-preset template shape).
    latex = r"""%% Standalone problem template.
\documentclass[a4paper,11pt]{article}
\begin{document}
\end{document}"""
    soup = TexSoup(latex)
    inject_externalization_for_tikz(soup)

    s = str(soup)
    assert s.index(r'\documentclass') < s.index(r'\usepackage{tikz}')


def test_get_top_level_tikz_nodes_flat():
    latex = r"""\begin{tikzpicture}
A
\end{tikzpicture}
\begin{tikzpicture}
B
\end{tikzpicture}"""
    soup = TexSoup(latex)
    nodes = get_top_level_tikz_nodes(soup)
    assert len(nodes) == 2


def test_get_top_level_tikz_nodes_nested():
    latex = r"""\begin{tikzpicture}
    Outer
    \begin{tikzpicture}
        Inner
    \end{tikzpicture}
\end{tikzpicture}"""
    soup = TexSoup(latex)
    nodes = get_top_level_tikz_nodes(soup)
    assert len(nodes) == 1
    # Check content to be sure it's the outer one
    assert 'Outer' in str(nodes[0])


def test_get_top_level_labeled_tikz_nodes():
    latex = r"""\tikzsetnextfilename{fig1}
\begin{tikzpicture}
A
\end{tikzpicture}

\begin{tikzpicture}
B
\end{tikzpicture}

\tikzsetnextfilename{fig2}
\begin{tikzpicture}
C
\end{tikzpicture}"""
    soup = TexSoup(latex)
    labeled = get_top_level_labeled_tikz_nodes(soup)
    assert len(labeled) == 2
    assert labeled[0][2] == 'fig1'
    assert 'A' in str(labeled[0][0])
    assert labeled[1][2] == 'fig2'
    assert 'C' in str(labeled[1][0])


def test_add_labels_to_tikz_nodes():
    latex = r"""\begin{tikzpicture}
A
\end{tikzpicture}
\begin{tikzpicture}
B
\end{tikzpicture}"""
    soup = TexSoup(latex)
    add_labels_to_tikz_nodes(soup, prefix='testfig')

    s = str(soup)
    assert r'\tikzsetnextfilename{testfig_0}' in s
    assert r'\tikzsetnextfilename{testfig_1}' in s

    # Verify we can find them now
    # Re-parsing is needed here as well if we were to rely on parent pointers heavily,
    # but strictly searching might work if TexSoup updated contents internally.
    # To be safe and consistent with integration tests:
    soup = TexSoup(str(soup))
    labeled = get_top_level_labeled_tikz_nodes(soup)
    assert len(labeled) == 2
    assert labeled[0][2] == 'testfig_0'
    assert labeled[1][2] == 'testfig_1'


def test_add_labels_to_tikz_nodes_mixed():
    latex = r"""\tikzsetnextfilename{existing}
\begin{tikzpicture}
A
\end{tikzpicture}"""
    soup = TexSoup(latex)
    add_labels_to_tikz_nodes(soup, prefix='new')

    s = str(soup)
    assert r'\tikzsetnextfilename{existing}' in s

    # Existing ones are skipped, so no new labels should be added for node 0
    # But wait, the test input has only ONE node, which is already labeled.
    # So add_labels should do nothing.
    assert r'\tikzsetnextfilename{new_0}' not in s

    tikzs = list(soup.find_all('tikzpicture'))
    assert len(tikzs) == 1
    assert get_tikz_node_label(tikzs[0])[1] == 'existing'


def test_add_labels_and_replace():
    from rbx.box.statements.processing.texsoup_utils import replace_labeled_tikz_nodes

    latex = r"""\begin{tikzpicture}
A
\end{tikzpicture}

Text

\begin{tikzpicture}
B
\end{tikzpicture}"""
    soup = TexSoup(latex)

    # 1. Add labels
    add_labels_to_tikz_nodes(soup, prefix='fig')

    # Workaround: Re-parse to fix tree integrity
    soup = TexSoup(str(soup))

    # 2. Replace labeled nodes
    replace_labeled_tikz_nodes(soup, prefix='img/', center=True)

    s = str(soup)
    assert r'\tikzsetnextfilename' not in s
    assert r'\begin{tikzpicture}' not in s
    assert r'\end{tikzpicture}' not in s

    # Check for replacements
    assert r'\begin{center}\includegraphics{img/fig_0}\end{center}' in s
    assert r'\begin{center}\includegraphics{img/fig_1}\end{center}' in s


def test_add_labels_and_replace_mixed():
    from rbx.box.statements.processing.texsoup_utils import replace_labeled_tikz_nodes

    latex = r"""\tikzsetnextfilename{manual}
\begin{tikzpicture}
Manual
\end{tikzpicture}

\begin{tikzpicture}
Auto
\end{tikzpicture}"""
    soup = TexSoup(latex)

    # 1. Add labels (should skip 'manual' and label 'Auto')
    add_labels_to_tikz_nodes(soup, prefix='auto')

    # Workaround: Re-parse
    soup = TexSoup(str(soup))

    # 2. Replace
    replace_labeled_tikz_nodes(soup, prefix='out/', center=True)

    s = str(soup)
    assert r'\tikzsetnextfilename' not in s

    # Manual should be preserved but replaced with its label
    assert r'\begin{center}\includegraphics{out/manual}\end{center}' in s

    # Auto should get new label
    # Note: index is 1 because it's the second node in iteration
    assert r'\begin{center}\includegraphics{out/auto_1}\end{center}' in s


def test_add_labels_and_replace_no_center():
    from rbx.box.statements.processing.texsoup_utils import replace_labeled_tikz_nodes

    latex = r"""\begin{tikzpicture}
A
\end{tikzpicture}"""
    soup = TexSoup(latex)

    add_labels_to_tikz_nodes(soup, prefix='nc')
    soup = TexSoup(str(soup))
    replace_labeled_tikz_nodes(soup, prefix='p/', center=False)

    s = str(soup)
    assert r'\begin{center}' not in s
    assert r'\includegraphics{p/nc_0}' in s


def test_strip_asset_ext_drops_only_asset_extensions():
    # Every recognized extension, asserted through behavior.
    assert strip_asset_ext('img/diagram.png') == 'img/diagram'
    assert strip_asset_ext('img/diagram.jpg') == 'img/diagram'
    assert strip_asset_ext('img/diagram.jpeg') == 'img/diagram'
    assert strip_asset_ext('img/diagram.pdf') == 'img/diagram'
    # Matching is case-insensitive.
    assert strip_asset_ext('img/diagram.PDF') == 'img/diagram'
    assert strip_asset_ext('img/diagram') == 'img/diagram'
    # Not an asset extension: left alone, dots and all.
    assert strip_asset_ext('data.v2') == 'data.v2'


def test_rewrite_includegraphics_subdir_reference():
    out = rewrite_includegraphics(
        r'see \includegraphics{img/diagram}.', {'img/diagram': 'img__diagram.png'}
    )
    assert r'\includegraphics{img__diagram.png}' in out


def test_rewrite_includegraphics_root_level_reference():
    # Audit finding #6: an unqualified (no subdirectory) reference is rewritten to
    # the flat name instead of relying on the judge resolving the bare stem.
    out = rewrite_includegraphics(r'\includegraphics{pic}', {'pic': 'pic.png'})
    assert out.strip() == r'\includegraphics{pic.png}'


def test_rewrite_includegraphics_no_double_extension():
    out = rewrite_includegraphics(
        r'\includegraphics{img/diagram.png}', {'img/diagram': 'img__diagram.png'}
    )
    assert r'\includegraphics{img__diagram.png}' in out
    assert '.png.png' not in out


def test_rewrite_includegraphics_preserves_optional_arg():
    out = rewrite_includegraphics(
        r'\includegraphics[width=0.5\textwidth]{pic}', {'pic': 'pic.png'}
    )
    assert r'[width=0.5\textwidth]' in out
    assert r'{pic.png}' in out


def test_rewrite_includegraphics_handles_multiple_nodes_and_prefix_collisions():
    # The claim the parser exists to satisfy: several nodes in one block, with a
    # remap key that is a prefix of another. A naive str.replace of `pic` would
    # corrupt `pic2` into `a.png2` (or vice versa, depending on ordering).
    out = rewrite_includegraphics(
        r'\includegraphics{pic} then \includegraphics{pic2}',
        {'pic': 'a.png', 'pic2': 'b.png'},
    )
    assert r'\includegraphics{a.png}' in out
    assert r'\includegraphics{b.png}' in out
    assert 'a.png2' not in out
    assert 'pic' not in out


def test_rewrite_includegraphics_leaves_unmapped_untouched():
    # Regression guard: externalized-TikZ references emitted by
    # replace_labeled_tikz_nodes must survive an asset remap untouched (and this
    # exercises a multi-segment extensionless path through strip_asset_ext).
    block = r'\includegraphics{artifacts/tikz_figures/0_0}'
    assert rewrite_includegraphics(block, {'pic': 'pic.png'}).strip() == block


def test_rewrite_includegraphics_empty_remap_is_identity():
    # `is`, not `==`: a TexSoup parse/serialize round-trip is not guaranteed
    # byte-identical, so returning the input untouched is a deliberate
    # no-round-trip guarantee for callers with nothing to rewrite.
    block = r'\includegraphics{pic}'
    assert rewrite_includegraphics(block, {}) is block


# ---------------------------------------------------------------------------
# Figures in running text vs. displays (#1006, option B)
# ---------------------------------------------------------------------------

FIG = 'artifacts/tikz_figures/'
PIC = r'\begin{tikzpicture}P\end{tikzpicture}'


def _substituted(text: str) -> str:
    return texsoup_utils.substitute_labeled_tikz_pictures(
        texsoup_utils.label_tikz_pictures(
            texsoup_utils.normalize_tikz_commands(text), prefix='b'
        )
    )


@pytest.mark.parametrize(
    'text, expected',
    [
        # In running text: a bare figure, no paragraph break.
        (f'Press {PIC}, now.', rf'Press \includegraphics{{{FIG}b_0}}, now.'),
        (
            f'one button:\n{PIC}.\nAfter',
            f'one button:\n\\includegraphics{{{FIG}b_0}}.\nAfter',
        ),
        # A display gets a center of its own...
        (
            f'Text.\n\n{PIC}\n\nMore',
            f'Text.\n\n\\begin{{center}}\\includegraphics{{{FIG}b_0}}'
            '\\end{center}\n\nMore',
        ),
        # ... unless it already is in one: no `:::: center` / `::: center`.
        (
            f'We include it.\n\\begin{{center}}\n{PIC}\n\\end{{center}}\nOf course',
            f'We include it.\n\\begin{{center}}\n\\includegraphics{{{FIG}b_0}}\n'
            '\\end{center}\nOf course',
        ),
        # Text next to it inside a center is still running text.
        (
            f'\\begin{{center}}Press {PIC} here\\end{{center}}',
            f'\\begin{{center}}Press \\includegraphics{{{FIG}b_0}} here\\end{{center}}',
        ),
        # Comments are not content, and a comment line is not a blank line.
        (
            f'Text. % c\n\n% only a comment\n{PIC}% x\n\nNext',
            f'Text. % c\n\n% only a comment\n\\begin{{center}}'
            f'\\includegraphics{{{FIG}b_0}}\\end{{center}}% x\n\nNext',
        ),
        (f'Text\n% c\n{PIC}', f'Text\n% c\n\\includegraphics{{{FIG}b_0}}'),
        # Through groups and arguments, to the paragraph around them.
        (
            f'a\n\n{{\\small {PIC}}}\n\nb',
            f'a\n\n{{\\small \\begin{{center}}\\includegraphics{{{FIG}b_0}}'
            '\\end{center}}\n\nb',
        ),
        (
            f'see \\textbf{{{PIC}}} ok',
            f'see \\textbf{{\\includegraphics{{{FIG}b_0}}}} ok',
        ),
        # A table cell is running text: a center there would not even compile.
        (
            f'\\begin{{tabular}}{{cc}}{PIC} & x\\end{{tabular}}',
            f'\\begin{{tabular}}{{cc}}\\includegraphics{{{FIG}b_0}} & x\\end{{tabular}}',
        ),
        # A caption is a paragraph of its own, and `figure` + `\centering`
        # already center: no second center (review finding 7).
        (
            f'\\begin{{figure}}\\centering\n{PIC}\n\\caption{{c}}\\end{{figure}}',
            f'\\begin{{figure}}\\centering\n\\includegraphics{{{FIG}b_0}}\n'
            '\\caption{c}\\end{figure}',
        ),
        (
            f'{{\\centering {PIC}\n\n}}',
            f'{{\\centering \\includegraphics{{{FIG}b_0}}\n\n}}',
        ),
        (
            f'\\begin{{minipage}}{{3cm}}{PIC}\\end{{minipage}}',
            f'\\begin{{minipage}}{{3cm}}\\includegraphics{{{FIG}b_0}}\\end{{minipage}}',
        ),
        # A command's argument or an item's text: never a center there.
        (
            f'\\centerline{{{PIC}}}',
            f'\\centerline{{\\includegraphics{{{FIG}b_0}}}}',
        ),
        (
            f'\\begin{{itemize}}\\item {PIC}\n\\item x\\end{{itemize}}',
            f'\\begin{{itemize}}\\item \\includegraphics{{{FIG}b_0}}\n'
            '\\item x\\end{itemize}',
        ),
        # Groups that are not plain text next to a figure (review finding 1:
        # TexSoup's `.string` asserted on them).
        (f'First {PIC}{{}} red.', f'First \\includegraphics{{{FIG}b_0}}{{}} red.'),
        (
            f'Text.\n\n{PIC}{{}}\n\nMore',
            f'Text.\n\n\\begin{{center}}\\includegraphics{{{FIG}b_0}}'
            '\\end{center}{}\n\nMore',
        ),
        (f'{PIC} {{\\bf x}}', f'\\includegraphics{{{FIG}b_0}} {{\\bf x}}'),
        # `\tikz{...}` and `\tikz ...;` are pictures too.
        (
            r'Press \tikz[baseline=(c.base)]{\node (c) {T};}, now.',
            rf'Press \includegraphics{{{FIG}b_0}}, now.',
        ),
        (
            r'A line \tikz \draw (0,0) -- (1,0); here.',
            rf'A line \includegraphics{{{FIG}b_0}} here.',
        ),
    ],
)
def test_substitution_keeps_each_figure_where_it_was(text, expected):
    assert _substituted(text) == expected


def test_labeling_is_a_splice_not_a_round_trip():
    # A TexSoup round trip prints `\def\foo#1{x}` as `\def\foo{#1}{x}`, which
    # TeX reads as something else; nothing outside the pictures may change.
    text = '\\def\\foo#1{x #1}\nCost \\$5: ' + PIC + ' % done\n'
    labeled = texsoup_utils.label_tikz_pictures(text, prefix='legend')
    assert labeled == text.replace(PIC, r'\tikzsetnextfilename{legend_0}' + PIC)
    assert texsoup_utils.substitute_labeled_tikz_pictures(labeled) == (
        text.replace(PIC, rf'\includegraphics{{{FIG}legend_0}}')
    )
    # Nothing to label: the very same text.
    assert texsoup_utils.label_tikz_pictures('\\def\\foo#1{x}', 'x') == (
        '\\def\\foo#1{x}'
    )


def test_pictures_inside_definitions_are_not_labeled():
    text = (
        '\\newcommand{\\a}{' + PIC + '}\n'
        # TexSoup leaves this body outside the command; the text scan does not.
        '\\newcommand{\\b} % note\n{' + PIC + '}\n'
        '\\def\\c{\\tikz{\\draw (0,0);}}\n'
    )
    normalized = texsoup_utils.normalize_tikz_commands(text)
    assert texsoup_utils.label_tikz_pictures(normalized, 'defs') == normalized
    assert not texsoup_utils.draws_tikz_pictures(text)
    assert texsoup_utils.draws_tikz_pictures(text + '\\tikz{\\draw (0,0);}')


def test_normalize_tikz_commands_leaves_lookalikes_and_verbatim_alone():
    text = (
        r'\tikzset{a/.style={}} \tikzstyle{b}=[] \verb|\tikz{x}| '
        '% \\tikz{y}\n'
        r'\tikz[s]{\node {\tikz \draw (0,0);};}'
    )
    assert texsoup_utils.normalize_tikz_commands(text) == (
        r'\tikzset{a/.style={}} \tikzstyle{b}=[] \verb|\tikz{x}| '
        '% \\tikz{y}\n'
        r'\begin{tikzpicture}[s]\node {\begin{tikzpicture}\draw (0,0);'
        r'\end{tikzpicture}};\end{tikzpicture}'
    )


def test_size_inline_figures_only_touches_running_text():
    text = (
        f'Press \\includegraphics{{{FIG}a}} now.\n\n'
        f'\\begin{{center}}\\includegraphics{{{FIG}b}}\\end{{center}}\n'
        f'And \\includegraphics[width=1cm]{{{FIG}c}}, '
        r'\includegraphics{img/photo} '
        f'and \\includegraphics{{{FIG}unknown}}.'
    )
    heights = {f'{FIG}a': 14.00432, f'{FIG}b': 99.0, f'{FIG}c': 5.0}
    assert texsoup_utils.size_inline_figures(text, heights.get) == text.replace(
        f'\\includegraphics{{{FIG}a}}', f'\\includegraphics[height=14pt]{{{FIG}a}}'
    )


def test_inject_in_preamble_text_changes_nothing_else():
    text = '% lead\n\\documentclass[a4paper]{article}\\def\\x#1{#1}\n\\begin{document}'
    assert texsoup_utils.inject_in_preamble_text(text, '\\usepackage{foo}') == (
        '% lead\n\\documentclass[a4paper]{article}\n\\usepackage{foo}\n'
        '\\def\\x#1{#1}\n\\begin{document}'
    )
    assert texsoup_utils.inject_in_preamble_text('body', 'X') == 'X\nbody'


def test_size_inline_figures_survives_non_text_groups():
    # Review finding 1: `{}` and `\includegraphics{\foo}` used to assert.
    text = f'First \\includegraphics{{{FIG}a}}{{}} red, \\includegraphics{{\\foo}}.'
    assert texsoup_utils.size_inline_figures(text, lambda ref: 10.0) == (
        text.replace(
            f'\\includegraphics{{{FIG}a}}', f'\\includegraphics[height=10pt]{{{FIG}a}}'
        )
    )


def test_size_figures_sizes_every_figure_for_html():
    text = (
        r'Press \includegraphics{btn.png} now.'
        '\n\n'
        r'\begin{center}\includegraphics{fig.png}\end{center}'
        '\n\n'
        r'\includegraphics[width=0.5\textwidth]{fig.png}'
        '\n\n'
        r'\includegraphics[height=12.3bp]{btn.png} and more'
        '\n\n'
        r'\includegraphics[angle=90]{fig.png}'
        '\n\n'
        r'\includegraphics{unknown.svg}'
    )
    sizes = {'btn.png': (20.0, 10.0), 'fig.png': (300.0, 100.0)}
    assert texsoup_utils.size_figures(text, sizes.get, 1.09) == (
        r'Press \includegraphics[height=10.9pt]{btn.png} now.'
        '\n\n'
        r'\begin{center}\includegraphics[width=327pt]{fig.png}\end{center}'
        '\n\n'
        r'\includegraphics[width=0.5\textwidth]{fig.png}'
        '\n\n'
        r'\includegraphics[height=13.41pt]{btn.png} and more'
        '\n\n'
        r'\includegraphics[angle=90]{fig.png}'
        '\n\n'
        r'\includegraphics{unknown.svg}'
    )


def test_size_figures_scales_the_inline_height_the_export_gave():
    # `size_inline_figures` runs first, on every target; on MOJ the height it
    # wrote is an absolute size like any other, and is scaled.
    text = f'Press \\includegraphics{{{FIG}a}} now.'
    sized = texsoup_utils.size_inline_figures(text, lambda ref: 10.0)
    assert texsoup_utils.size_figures(sized, lambda ref: (40.0, 10.0), 1.5) == (
        f'Press \\includegraphics[height=14.94pt]{{{FIG}a}} now.'
    )


def test_size_figures_leaves_forms_it_cannot_read_alone():
    text = (
        r'\includegraphics*{a} \includegraphics[0,0][1,1]{a} '
        r'\includegraphics{\foo} text'
    )
    assert texsoup_utils.size_figures(text, lambda ref: None, 1.09) == text
    assert texsoup_utils.size_figures('no figures', lambda ref: None, 1.09) == (
        'no figures'
    )
