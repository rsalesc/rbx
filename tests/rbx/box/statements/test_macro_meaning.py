import pathlib
import shutil
import subprocess

import pytest

from rbx.box.statements import macro_meaning, render
from rbx.box.statements.demacro_utils import (
    MacroDef,
    MacroDefinitions,
    collect_macro_definitions_from_text,
    extract_definitions,
)
from rbx.box.statements.latex import LatexResult


def _summary(defs: MacroDefinitions):
    return {
        name: (defs.get(name).n_args, defs.get(name).default, defs.get(name).body)
        for name in defs
    }


@pytest.mark.parametrize(
    'name, entries, expected',
    [
        (
            'plain',
            {'N': 'macro:->Output a single line with '},
            (0, None, 'Output a single line with '),
        ),
        (
            'args',
            {'N': r'\long macro:#1#2->\textbf {#1}--#2\ldots , ok'},
            (2, None, r'\textbf{#1}--#2\ldots, ok'),
        ),
        # A space after a control word stays when a letter follows it.
        ('word', {'N': r'macro:->\foo bar\par baz'}, (0, None, r'\foo bar\par baz')),
        ('prot', {'N': r'\protected\long macro:->p'}, (0, None, 'p')),
        (
            'nested',
            {'N': r'\long macro:->\def \inner ##1{##1}'},
            (0, None, r'\def\inner##1{##1}'),
        ),
        (
            'opt',
            {
                'N': r'macro:->\@protected@testopt \opt \\opt {dflt {x}}',
                'I': r'\long macro:[#1]#2->[#1]#2',
            },
            (2, 'dflt {x}', '[#1]#2'),
        ),
        (
            'oldopt',
            {'N': r'macro:->\@testopt \\oldopt {d}', 'I': r'macro:[#1]->(#1)'},
            (1, 'd', '(#1)'),
        ),
        (
            'rob',
            {'N': r'macro:->\protect \rob  ', 'R': r'\long macro:->\emph {r}'},
            (0, None, r'\emph{r}'),
        ),
        (
            'robopt',
            {
                'N': r'macro:->\protect \robopt  ',
                'R': r'macro:->\@protected@testopt \robopt  \\robopt  {d}',
                'RI': r'\long macro:[#1]->[#1]',
            },
            (1, 'd', '[#1]'),
        ),
        ('utf', {'N': 'macro:->única línea'}, (0, None, 'única línea')),
    ],
)
def test_macro_from_meaning(name, entries, expected):
    macro = macro_meaning.macro_from_meaning(name, entries, 'a.sty')
    assert macro == MacroDef(name, *expected, source_file='a.sty')


@pytest.mark.parametrize(
    'entries',
    [
        {},  # undefined when the document ended
        {'N': r'\relax'},  # a primitive
        {'N': r'\char"41'},  # a \chardef
        {'N': r'macro:#1.#2->x'},  # delimited parameters
        {'N': r'macro:->\@protected@testopt \opt \\opt {d}'},  # no inner macro
    ],
)
def test_macro_from_meaning_rejects_what_rbx_cannot_expand(entries):
    assert macro_meaning.macro_from_meaning('opt', entries) is None


def test_read_dump(tmp_path: pathlib.Path):
    path = tmp_path / macro_meaning.DUMP_FILE
    path.write_bytes(
        b'RBX-MACRO-MEANINGS 1\n'
        b'N:a:macro:->x\n'
        # pdfTeX may escape bytes it deems unprintable.
        b'N:b:macro:->^^c3^^banica\n'
        b'N:t:macro:->a^^Ib^^?\n'
        # A body holding the newline character breaks its line.
        b'N:c:macro:->one\n'
        b'two\n'
        b'I:a:macro:[#1]->y\n'
        b'RBX-MACRO-MEANINGS-END\n'
    )
    assert macro_meaning.read_dump(path) == {
        'a': {'N': 'macro:->x', 'I': 'macro:[#1]->y'},
        'b': {'N': 'macro:->única'},
        't': {'N': 'macro:->a\tb\x7f'},
        'c': {'N': 'macro:->one\ntwo'},
    }


@pytest.mark.parametrize(
    'content', [b'', b'RBX-MACRO-MEANINGS 1\nN:a:macro:->x\n', b'garbage\n']
)
def test_read_dump_rejects_incomplete_dumps(tmp_path: pathlib.Path, content):
    path = tmp_path / macro_meaning.DUMP_FILE
    path.write_bytes(content)
    assert macro_meaning.read_dump(path) is None


def test_read_dump_without_a_file(tmp_path: pathlib.Path):
    assert macro_meaning.read_dump(tmp_path / 'absent') is None


_ICPCLANG = (
    r'\newcommand{\strings@en}{\def\strLine{Output a single line with }}'
    '\n'
    r'\newcommand{\strings@es}{\def\strLine{Su programa debe imprimir }}'
    '\n'
    r'\def\helper{\def\scratch{x}}'
    '\n'
)


def test_resolve_prefers_what_tex_reported(capsys):
    static = extract_definitions(_ICPCLANG, 'icpclang.sty')
    dump = {
        'strLine': {'N': 'macro:->Output a single line with '},
        'strings@en': {
            'N': r'\long macro:->\def \strLine {Output a single line with }'
        },
    }
    resolved = macro_meaning.resolve(static, dump, document=r'\strLine x')
    assert resolved.get('strLine').body == 'Output a single line with '
    assert resolved.get('strLine').source_file == 'icpclang.sty'
    # The rest fall back to their static definitions.
    assert (
        resolved.get('strings@es').body == r'\def\strLine{Su programa debe imprimir }'
    )
    assert capsys.readouterr().out == ''


def test_resolve_warns_when_an_ambiguous_static_definition_is_used(capsys):
    static = extract_definitions(_ICPCLANG, 'icpclang.sty')
    resolved = macro_meaning.resolve(static, None, document=r'\strLine x')
    assert resolved.get('strLine').body == 'Su programa debe imprimir '
    out = ' '.join(capsys.readouterr().out.split())
    assert 'static definitions of 1 macro(s)' in out
    assert r'\strLine: picked icpclang.sty, the one inside \strings@es' in out
    # `\scratch` is just as doubtful, but the document never uses it.
    assert 'scratch' not in out


def test_resolve_warns_about_a_nested_definition_tex_did_not_run(capsys):
    static = extract_definitions(r'\def\helper{\def\scratch{x}}', 'a.sty')
    macro_meaning.resolve(static, {}, document=r'\scratch')
    out = ' '.join(capsys.readouterr().out.split())
    assert r'\scratch: defined inside \helper (a.sty), which may never have run' in out


def test_resolve_falls_back_silently_for_unambiguous_definitions(capsys):
    # A problem's defs block runs inside the template's group: undefined at the
    # end of the document, but read right off the source.
    static = extract_definitions(r'\newcommand{\NN}{\mathbb{N}}', 'statement.tex')
    resolved = macro_meaning.resolve(static, {}, document=r'$\NN$')
    assert _summary(resolved) == {'NN': (0, None, r'\mathbb{N}')}
    assert capsys.readouterr().out == ''


def test_inject_dump_hook_goes_after_documentclass():
    tex = '\\documentclass[a4paper]{article} % c\n\\begin{document}x\\end{document}'
    injected = macro_meaning.inject_dump_hook(tex, ['b', 'a@x', 'a', '1bad', ','])
    assert injected.startswith('\\documentclass[a4paper]{article}\n\\makeatletter\n')
    assert injected.endswith('\\makeatother\n % c\n\\begin{document}x\\end{document}')
    # One name per line, sorted, and only names a \csname can spell.
    assert [
        line for line in injected.splitlines() if line.startswith('\\rbx@dumpmeaning{')
    ] == ['\\rbx@dumpmeaning{a}%', '\\rbx@dumpmeaning{a@x}%', '\\rbx@dumpmeaning{b}%']


def test_compile_pdf_writes_the_definitions_tex_reported(tmp_path, monkeypatch):
    """The wiring of #1007: the static pass names the macros, the compile's
    dump overrides them in macros.json. pdflatex is mocked, so the fake writes
    the dump the hook would have."""
    (tmp_path / 'icpclang.sty').write_text(_ICPCLANG)
    doc = (
        '\\documentclass{article}\n\\usepackage{icpclang}\n'
        '\\begin{document}\\strLine 1.\\end{document}\n'
    )

    def fake_build_pdf(self, temp_dir):
        assert '\\rbx@dumpmeaning{strLine}%' in self.latex
        (temp_dir / macro_meaning.DUMP_FILE).write_text(
            'RBX-MACRO-MEANINGS 1\n'
            'N:strLine:macro:->Output a single line with \n'
            'RBX-MACRO-MEANINGS-END\n'
        )
        return LatexResult(
            result=subprocess.CompletedProcess('', 0, b'', b''), pdf=b'pdf'
        )

    monkeypatch.setattr('rbx.box.statements.latex.Latex.build_pdf', fake_build_pdf)
    assert render.compile_pdf(tmp_path, doc.encode(), demacro=True) == b'pdf'
    macros = MacroDefinitions.from_json_file(tmp_path / 'macros.json')
    assert macros.get('strLine').body == 'Output a single line with '


@pytest.mark.skipif(shutil.which('pdflatex') is None, reason='needs pdflatex')
def test_tex_reports_the_selected_language_table(tmp_path: pathlib.Path):
    """#1007 end to end against real TeX: a package that picks its string
    table by option, macros of every shape, and a UTF-8 body."""
    (tmp_path / 'icpclang.sty').write_text(
        r'\ProvidesPackage{icpclang}'
        '\n'
        r'\def\icpclang{en}'
        '\n'
        r'\DeclareOption*{\edef\icpclang{\CurrentOption}}'
        '\n'
        r'\ProcessOptions\relax'
        '\n'
        r'\newcommand{\icpcstrings@en}{\def\strLine{Output a single line with }'
        r'\def\strCount##1{##1 problems}}'
        '\n'
        r'\newcommand{\icpcstrings@es}{\def\strLine{Su programa debe imprimir una '
        r'única línea con }\def\strCount##1{##1 problemas}}'
        '\n'
        r'\icpcstrings@en'
        '\n'
        r'\csname icpcstrings@\icpclang\endcsname'
        '\n'
        r'\newcommand{\opt}[2][dflt]{\textbf{#1}--#2}'
        '\n'
        r'\DeclareRobustCommand{\rob}{\emph{r}}'
        '\n'
        r'\newcommand{\longbody}{' + 'x' * 3000 + '}\n',
        encoding='utf-8',
    )
    doc = (
        '\\documentclass{article}\n'
        '\\usepackage[en]{icpclang}\n'
        '\\begin{document}\n'
        '\\begingroup\\newcommand{\\local}{L}\\endgroup\n'
        '\\strLine \\strCount{3}, \\opt{a}, \\rob.\n'
        '\\end{document}\n'
    )
    static = collect_macro_definitions_from_text(
        doc, base_dir=tmp_path, source_file=tmp_path / 'statement.tex'
    )
    # Statically, the Spanish table is the last one written.
    assert static.get('strLine').body.startswith('Su programa')

    (tmp_path / 'statement.tex').write_text(
        macro_meaning.inject_dump_hook(doc, static), encoding='utf-8'
    )
    completed = subprocess.run(
        ['pdflatex', '-interaction', 'nonstopmode', 'statement.tex'],
        cwd=tmp_path,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout.decode(errors='replace')

    dump = macro_meaning.read_dump(tmp_path / macro_meaning.DUMP_FILE)
    resolved = macro_meaning.resolve(static, dump, document=doc)
    summary = _summary(resolved)
    assert summary['strLine'] == (0, None, 'Output a single line with ')
    assert summary['strCount'] == (1, None, '#1 problems')
    assert summary['opt'] == (2, 'dflt', r'\textbf{#1}--#2')
    assert summary['rob'] == (0, None, r'\emph{r}')
    assert summary['longbody'] == (0, None, 'x' * 3000)
    assert summary['icpcstrings@es'][2].endswith('##1 problemas}')
    # Undefined when the document ended: the static definition stands.
    assert summary['local'] == (0, None, 'L')


@pytest.mark.skipif(shutil.which('pdflatex') is None, reason='needs pdflatex')
def test_dump_survives_tikz_externalization_in_the_same_compile(
    tmp_path: pathlib.Path,
):
    """Externalization re-runs the document once per figure, under another
    job name; only the main job may write the dump."""
    from rbx.box.statements import texsoup_utils

    doc = (
        '\\documentclass{article}\n'
        '\\newcommand{\\word}{hello}\n'
        '\\begin{document}\n'
        '\\word\\ \\tikzsetnextfilename{legend_0}'
        '\\begin{tikzpicture}\\draw (0,0) -- (1,1);\\end{tikzpicture}\n'
        '\\end{document}\n'
    )
    tex = texsoup_utils.inject_in_preamble_text(
        doc, texsoup_utils.EXTERNALIZATION_PREAMBLE
    )
    tex = macro_meaning.inject_dump_hook(tex, ['word'])
    (tmp_path / texsoup_utils.EXTERNALIZATION_DIR).mkdir(parents=True)
    (tmp_path / 'statement.tex').write_text(tex)
    completed = subprocess.run(
        ['pdflatex', '-shell-escape', '-interaction', 'nonstopmode', 'statement.tex'],
        cwd=tmp_path,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout.decode(errors='replace')

    figures = tmp_path / texsoup_utils.EXTERNALIZATION_DIR
    assert (figures / 'legend_0.pdf').is_file()
    assert sorted(p.name for p in tmp_path.rglob('*.meaning')) == [
        macro_meaning.DUMP_FILE
    ]
    assert macro_meaning.read_dump(tmp_path / macro_meaning.DUMP_FILE) == {
        'word': {'N': '\\long macro:->hello'}
    }


@pytest.mark.skipif(shutil.which('pdflatex') is None, reason='needs pdflatex')
def test_a_document_using_every_write_stream_still_compiles(tmp_path: pathlib.Path):
    """Review finding 5: the hook must not take a stream the document needs.
    It allocates at the end of the document, and only when one is free."""
    doc = (
        '\\documentclass{article}\n'
        + ''.join(f'\\newwrite\\w{chr(97 + i)}\n' for i in range(13))
        + '\\newcommand{\\word}{hello}\n\\begin{document}\\word\\end{document}\n'
    )
    (tmp_path / 'statement.tex').write_text(
        macro_meaning.inject_dump_hook(doc, ['word'])
    )
    completed = subprocess.run(
        ['pdflatex', '-interaction', 'nonstopmode', 'statement.tex'],
        cwd=tmp_path,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout.decode(errors='replace')
    # No stream left: no dump, and the static definitions stand.
    assert macro_meaning.read_dump(tmp_path / macro_meaning.DUMP_FILE) is None


@pytest.mark.skipif(shutil.which('pdflatex') is None, reason='needs pdflatex')
def test_block_local_redefinitions_beat_the_end_of_document_meaning(
    tmp_path: pathlib.Path,
):
    """Review finding 2: the template runs the blocks inside a group, so by
    the end of the document a block's `\\renewcommand{\\vec}` is gone and TeX
    reports the kernel's `\\vec`. What the block text sees is what it wrote;
    the package's language table still resolves to what TeX ran (#1007)."""
    (tmp_path / 'strings.sty').write_text(
        r'\newcommand{\strings@en}{\def\strLine{Output a line }}'
        '\n'
        r'\newcommand{\strings@es}{\def\strLine{Imprima una linea }}'
        '\n'
        r'\csname strings@en\endcsname'
        '\n'
    )
    doc = (
        '\\documentclass{article}\n\\usepackage{strings}\n\\begin{document}\n'
        '\\begingroup\n'
        '\\renewcommand{\\vec}[1]{\\mathbf{#1}}\n'
        '\\renewcommand{\\b}{blue}\n'
        'Let $\\vec{v}$ be a \\b{} vector. \\strLine 1.\n'
        '\\endgroup\n\\end{document}\n'
    )
    static = collect_macro_definitions_from_text(
        doc, base_dir=tmp_path, source_file=tmp_path / 'statement.tex'
    )
    (tmp_path / 'statement.tex').write_text(macro_meaning.inject_dump_hook(doc, static))
    completed = subprocess.run(
        ['pdflatex', '-interaction', 'nonstopmode', 'statement.tex'],
        cwd=tmp_path,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout.decode(errors='replace')
    dump = macro_meaning.read_dump(tmp_path / macro_meaning.DUMP_FILE)
    # TeX itself only knows the kernel's definitions by now.
    assert 'mathbf' not in dump['vec']['N']

    resolved = macro_meaning.resolve(
        static,
        dump,
        document=doc,
        body=macro_meaning.body_definitions(doc, tmp_path),
    )
    summary = _summary(resolved)
    assert summary['vec'] == (1, None, r'\mathbf{#1}')
    assert summary['b'] == (0, None, 'blue')
    assert summary['strLine'] == (0, None, 'Output a line ')
