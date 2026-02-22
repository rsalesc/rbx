import pathlib

from rbx.box.statements.demacro_utils import (
    MacroDef,
    MacroDefinitions,
    collect_macro_definitions,
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
