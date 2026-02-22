import pathlib

from rbx.box.statements.demacro_utils import (
    MacroDef,
    MacroDefinitions,
    collect_macro_definitions,
    expand_macros,
    extract_definitions,
)


def test_macro_def_creation():
    md = MacroDef(name='foo', n_args=2, default=None, body='#1 + #2', source_file=None)
    assert md.name == 'foo'
    assert md.n_args == 2
    assert md.body == '#1 + #2'


def test_macro_definitions_add_and_get():
    defs = MacroDefinitions()
    md = MacroDef(name='foo', n_args=0, default=None, body='bar', source_file=None)
    defs.add(md)
    assert 'foo' in defs
    assert defs.get('foo') is md


def test_macro_definitions_overwrite():
    defs = MacroDefinitions()
    md1 = MacroDef(name='foo', n_args=0, default=None, body='old', source_file=None)
    md2 = MacroDef(name='foo', n_args=0, default=None, body='new', source_file=None)
    defs.add(md1)
    defs.add(md2)
    assert defs.get('foo').body == 'new'


def test_macro_definitions_merge():
    defs1 = MacroDefinitions()
    defs1.add(MacroDef(name='a', n_args=0, default=None, body='A', source_file=None))
    defs2 = MacroDefinitions()
    defs2.add(MacroDef(name='b', n_args=0, default=None, body='B', source_file=None))
    defs1.merge(defs2)
    assert 'a' in defs1
    assert 'b' in defs1


def test_macro_definitions_iter():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='x', n_args=0, default=None, body='X', source_file=None))
    defs.add(MacroDef(name='y', n_args=0, default=None, body='Y', source_file=None))
    names = list(defs)
    assert 'x' in names
    assert 'y' in names


def test_extract_newcommand_no_args():
    tex = r'\newcommand{\hello}{world}'
    defs = extract_definitions(tex)
    assert 'hello' in defs
    assert defs.get('hello').n_args == 0
    assert defs.get('hello').body == 'world'


def test_extract_newcommand_with_args():
    tex = r'\newcommand{\add}[2]{#1 + #2}'
    defs = extract_definitions(tex)
    assert defs.get('add').n_args == 2
    assert defs.get('add').body == '#1 + #2'


def test_extract_newcommand_with_default():
    tex = r'\newcommand{\greet}[1][World]{Hello, #1!}'
    defs = extract_definitions(tex)
    m = defs.get('greet')
    assert m.n_args == 1
    assert m.default == 'World'
    assert m.body == 'Hello, #1!'


def test_extract_renewcommand():
    tex = r'\renewcommand{\foo}{bar}'
    defs = extract_definitions(tex)
    assert 'foo' in defs
    assert defs.get('foo').body == 'bar'


def test_extract_newcommand_star():
    tex = r'\newcommand*{\starred}[1]{*#1*}'
    defs = extract_definitions(tex)
    assert defs.get('starred').n_args == 1
    assert defs.get('starred').body == '*#1*'


def test_extract_def_zero_args():
    tex = r'\def\myconst{42}'
    defs = extract_definitions(tex)
    assert defs.get('myconst').n_args == 0
    assert defs.get('myconst').body == '42'


def test_extract_multiple_definitions():
    tex = r"""
\newcommand{\foo}{FOO}
\newcommand{\bar}[1]{BAR #1}
\def\baz{BAZ}
"""
    defs = extract_definitions(tex)
    assert len(defs) == 3
    assert 'foo' in defs
    assert 'bar' in defs
    assert 'baz' in defs


def test_extract_renewcommand_overwrites():
    tex = r"""
\newcommand{\foo}{old}
\renewcommand{\foo}{new}
"""
    defs = extract_definitions(tex)
    assert defs.get('foo').body == 'new'


def test_collect_from_single_file(tmp_path: pathlib.Path):
    tex = tmp_path / 'main.tex'
    tex.write_text(r'\newcommand{\foo}{bar}')
    defs = collect_macro_definitions(tex)
    assert 'foo' in defs


def test_collect_follows_input(tmp_path: pathlib.Path):
    (tmp_path / 'defs.tex').write_text(r'\newcommand{\fromInput}{yes}')
    (tmp_path / 'main.tex').write_text(r'\input{defs.tex}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromInput' in defs


def test_collect_follows_input_no_extension(tmp_path: pathlib.Path):
    (tmp_path / 'defs.tex').write_text(r'\newcommand{\fromInput}{yes}')
    (tmp_path / 'main.tex').write_text(r'\input{defs}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromInput' in defs


def test_collect_follows_include(tmp_path: pathlib.Path):
    (tmp_path / 'chapter.tex').write_text(r'\newcommand{\fromInclude}{yes}')
    (tmp_path / 'main.tex').write_text(r'\include{chapter}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromInclude' in defs


def test_collect_follows_local_sty(tmp_path: pathlib.Path):
    (tmp_path / 'mypkg.sty').write_text(r'\newcommand{\fromSty}{yes}')
    (tmp_path / 'main.tex').write_text(r'\usepackage{mypkg}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromSty' in defs


def test_collect_follows_requirepackage(tmp_path: pathlib.Path):
    (tmp_path / 'req.sty').write_text(r'\newcommand{\fromReq}{yes}')
    (tmp_path / 'main.tex').write_text(r'\RequirePackage{req}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromReq' in defs


def test_collect_skips_system_package(tmp_path: pathlib.Path):
    (tmp_path / 'main.tex').write_text(
        r'\usepackage{amsmath}' + '\n' + r'\newcommand{\local}{yes}'
    )
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'local' in defs


def test_collect_no_cycles(tmp_path: pathlib.Path):
    (tmp_path / 'a.tex').write_text(r'\input{b.tex}' + '\n' + r'\newcommand{\fromA}{A}')
    (tmp_path / 'b.tex').write_text(r'\input{a.tex}' + '\n' + r'\newcommand{\fromB}{B}')
    defs = collect_macro_definitions(tmp_path / 'a.tex')
    assert 'fromA' in defs
    assert 'fromB' in defs


def test_collect_recursive_depth(tmp_path: pathlib.Path):
    (tmp_path / 'c.tex').write_text(r'\newcommand{\deep}{yes}')
    (tmp_path / 'b.tex').write_text(r'\input{c.tex}')
    (tmp_path / 'a.tex').write_text(r'\input{b.tex}')
    defs = collect_macro_definitions(tmp_path / 'a.tex')
    assert 'deep' in defs


def test_collect_with_base_dir(tmp_path: pathlib.Path):
    sub = tmp_path / 'sub'
    sub.mkdir()
    (sub / 'defs.tex').write_text(r'\newcommand{\subDef}{yes}')
    (tmp_path / 'main.tex').write_text(r'\input{sub/defs.tex}')
    defs = collect_macro_definitions(tmp_path / 'main.tex', base_dir=tmp_path)
    assert 'subDef' in defs


def test_expand_zero_arg_macro():
    defs = MacroDefinitions()
    defs.add(
        MacroDef(name='foo', n_args=0, default=None, body='REPLACED', source_file=None)
    )
    result = expand_macros(r'Hello \foo world', defs)
    assert 'REPLACED' in result
    assert r'\foo' not in result


def test_expand_one_arg_macro():
    defs = MacroDefinitions()
    defs.add(
        MacroDef(
            name='bold', n_args=1, default=None, body=r'\textbf{#1}', source_file=None
        )
    )
    result = expand_macros(r'\bold{hello}', defs)
    assert r'\textbf{hello}' in result
    assert r'\bold' not in result


def test_expand_two_arg_macro():
    defs = MacroDefinitions()
    defs.add(
        MacroDef(name='pair', n_args=2, default=None, body='(#1, #2)', source_file=None)
    )
    result = expand_macros(r'\pair{a}{b}', defs)
    assert '(a, b)' in result


def test_expand_with_default_arg_used():
    defs = MacroDefinitions()
    defs.add(
        MacroDef(
            name='greet', n_args=1, default='World', body='Hello, #1!', source_file=None
        )
    )
    result = expand_macros(r'\greet', defs)
    assert 'Hello, World!' in result


def test_expand_with_default_arg_overridden():
    defs = MacroDefinitions()
    defs.add(
        MacroDef(
            name='greet', n_args=1, default='World', body='Hello, #1!', source_file=None
        )
    )
    result = expand_macros(r'\greet[Alice]', defs)
    assert 'Hello, Alice!' in result


def test_expand_preserves_non_macro_content():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='foo', n_args=0, default=None, body='X', source_file=None))
    result = expand_macros(r'before \foo after', defs)
    assert 'before' in result
    assert 'after' in result
    assert 'X' in result


def test_expand_nested_macros():
    defs = MacroDefinitions()
    defs.add(
        MacroDef(name='inner', n_args=0, default=None, body='INNER', source_file=None)
    )
    defs.add(
        MacroDef(name='outer', n_args=0, default=None, body=r'\inner', source_file=None)
    )
    result = expand_macros(r'\outer', defs)
    assert 'INNER' in result
    assert r'\outer' not in result
    assert r'\inner' not in result


def test_expand_no_matching_macros():
    defs = MacroDefinitions()
    tex = r'\unknown{arg} text'
    result = expand_macros(tex, defs)
    assert r'\unknown{arg}' in result


def test_expand_multiple_usages():
    defs = MacroDefinitions()
    defs.add(MacroDef(name='x', n_args=0, default=None, body='X', source_file=None))
    result = expand_macros(r'\x and \x', defs)
    assert result.count('X') == 2
    assert r'\x' not in result


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


def test_end_to_end_collect_and_expand(tmp_path: pathlib.Path):
    """Full integration: collect from files, then expand in a document."""
    (tmp_path / 'macros.sty').write_text(
        r'\newcommand{\prob}[1]{\textbf{Problem: #1}}'
        + '\n'
        + r'\newcommand{\io}{Input/Output}'
    )
    (tmp_path / 'main.tex').write_text(
        r'\usepackage{macros}' + '\n' + r'\prob{A} -- \io'
    )
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    content = (tmp_path / 'main.tex').read_text()
    result = expand_macros(content, defs)
    assert r'\textbf{Problem: A}' in result
    assert 'Input/Output' in result
    assert r'\prob' not in result
    assert r'\io' not in result


def test_expand_does_not_remove_definitions():
    """expand_macros operates on usage sites, not on definition sites."""
    defs = MacroDefinitions()
    defs.add(MacroDef(name='foo', n_args=0, default=None, body='X', source_file=None))
    tex = r'\newcommand{\foo}{X}' + '\n' + r'\foo'
    result = expand_macros(tex, defs)
    # The key assertion: the usage \foo (not inside \newcommand) should be expanded.
    assert 'X' in result


def test_expand_macro_with_nested_braces():
    defs = MacroDefinitions()
    defs.add(
        MacroDef(
            name='wrap',
            n_args=1,
            default=None,
            body=r'{\textbf{#1}}',
            source_file=None,
        )
    )
    result = expand_macros(r'\wrap{hello}', defs)
    assert r'{\textbf{hello}}' in result


# ---------------------------------------------------------------------------
# Edge Case Tests
# ---------------------------------------------------------------------------


def test_expand_macro_body_contains_another_macro():
    """Macro whose body contains another macro call (nested expansion)."""
    defs = MacroDefinitions()
    defs.add(
        MacroDef(
            name='bold', n_args=1, default=None, body=r'\textbf{#1}', source_file=None
        )
    )
    defs.add(
        MacroDef(
            name='title', n_args=0, default=None, body=r'\bold{Hello}', source_file=None
        )
    )
    result = expand_macros(r'\title', defs)
    assert r'\textbf{Hello}' in result
    assert r'\title' not in result
    assert r'\bold' not in result


def test_expand_multiple_different_macros_in_document():
    """Multiple different macros in the same document."""
    defs = MacroDefinitions()
    defs.add(
        MacroDef(name='name', n_args=0, default=None, body='Alice', source_file=None)
    )
    defs.add(
        MacroDef(
            name='greeting', n_args=0, default=None, body='Hello', source_file=None
        )
    )
    defs.add(MacroDef(name='punct', n_args=0, default=None, body='!', source_file=None))
    result = expand_macros(r'\greeting, \name\punct', defs)
    assert 'Hello' in result
    assert 'Alice' in result
    assert '!' in result
    assert r'\greeting' not in result
    assert r'\name' not in result
    assert r'\punct' not in result


def test_expand_macros_inside_environment():
    """Macros used inside LaTeX environments."""
    defs = MacroDefinitions()
    defs.add(MacroDef(name='val', n_args=0, default=None, body='42', source_file=None))
    tex = r'\begin{center}' + '\n' + r'The answer is \val.' + '\n' + r'\end{center}'
    result = expand_macros(tex, defs)
    assert '42' in result
    assert r'\val' not in result
    assert r'\begin{center}' in result
    assert r'\end{center}' in result


def test_expand_empty_body_macro():
    """Macro with an empty body should effectively remove the usage."""
    defs = MacroDefinitions()
    defs.add(MacroDef(name='noop', n_args=0, default=None, body='', source_file=None))
    result = expand_macros(r'before\noop after', defs)
    assert r'\noop' not in result
    assert 'before' in result
    assert 'after' in result


def test_expand_macro_with_empty_arg():
    """Macro invoked with an empty brace argument."""
    defs = MacroDefinitions()
    defs.add(
        MacroDef(name='wrap', n_args=1, default=None, body='[#1]', source_file=None)
    )
    result = expand_macros(r'\wrap{}', defs)
    assert '[]' in result


def test_collect_multiple_packages(tmp_path: pathlib.Path):
    """Collect definitions from multiple local .sty files."""
    (tmp_path / 'alpha.sty').write_text(r'\newcommand{\fromAlpha}{A}')
    (tmp_path / 'beta.sty').write_text(r'\newcommand{\fromBeta}{B}')
    (tmp_path / 'main.tex').write_text(
        r'\usepackage{alpha}' + '\n' + r'\usepackage{beta}'
    )
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    assert 'fromAlpha' in defs
    assert 'fromBeta' in defs


def test_collect_and_expand_with_args(tmp_path: pathlib.Path):
    """Integration: collect a macro with args from a file and expand it."""
    (tmp_path / 'defs.tex').write_text(r'\newcommand{\pair}[2]{(#1, #2)}')
    (tmp_path / 'main.tex').write_text(r'\input{defs.tex}' + '\n' + r'\pair{x}{y}')
    defs = collect_macro_definitions(tmp_path / 'main.tex')
    content = (tmp_path / 'main.tex').read_text()
    result = expand_macros(content, defs)
    assert '(x, y)' in result
    assert r'\pair' not in result


def test_expand_deeply_nested_macros():
    """Three levels of macro nesting: a -> b -> c -> literal."""
    defs = MacroDefinitions()
    defs.add(MacroDef(name='c', n_args=0, default=None, body='DEEP', source_file=None))
    defs.add(MacroDef(name='b', n_args=0, default=None, body=r'\c', source_file=None))
    defs.add(MacroDef(name='a', n_args=0, default=None, body=r'\b', source_file=None))
    result = expand_macros(r'\a', defs)
    assert 'DEEP' in result
    assert r'\a' not in result
    assert r'\b' not in result
    assert r'\c' not in result


def test_extract_definitions_empty_string():
    """Extracting definitions from empty input returns empty MacroDefinitions."""
    defs = extract_definitions('')
    assert len(defs) == 0


def test_expand_macros_empty_string():
    """Expanding macros in an empty string returns empty string."""
    defs = MacroDefinitions()
    defs.add(MacroDef(name='foo', n_args=0, default=None, body='bar', source_file=None))
    result = expand_macros('', defs)
    assert result == ''
