from TexSoup import TexSoup

from rbx.box.statements.texsoup_utils import (
    add_labels_to_tikz_nodes,
    get_tikz_node_label,
    get_top_level_labeled_tikz_nodes,
    get_top_level_tikz_nodes,
    inject_externalization_for_tikz,
    inject_in_preamble,
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
    from rbx.box.statements.texsoup_utils import replace_labeled_tikz_nodes

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
    from rbx.box.statements.texsoup_utils import replace_labeled_tikz_nodes

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
    from rbx.box.statements.texsoup_utils import replace_labeled_tikz_nodes

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
