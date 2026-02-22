from rbx.box.statements.demacro_utils import (
    MacroDef,
    MacroDefinitions,
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
