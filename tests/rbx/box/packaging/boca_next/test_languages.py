from rbx_boca import languages


def test_render_argv_string_substitution():
    out = languages.render_argv(
        ['g++', '{flags}', '-o', '{exe}', '{src}'],
        flags='-O2 -static',
        exe='run.exe',
        src='sol.cpp',
    )
    assert out == ['g++', '-O2', '-static', '-o', 'run.exe', 'sol.cpp']


def test_render_argv_list_splice():
    out = languages.render_argv(
        ['java', '{jvm_flags}', '-jar', '{jar}'],
        jvm_flags=['-Xmx256000K', '-Xss25600K'],
        jar='run.jar',
    )
    assert out == ['java', '-Xmx256000K', '-Xss25600K', '-jar', 'run.jar']


def test_render_argv_empty_token_dropped():
    out = languages.render_argv(['cc', '{flags}', '{src}'], flags='', src='a.c')
    assert out == ['cc', 'a.c']


def test_resolve_compiler_prefers_path(monkeypatch):
    spec = languages.LanguageSpec.from_dict(
        {
            'id': 'cpp',
            'kind': 'compiled_static',
            'compiler_argv': ['g++', '{src}'],
            'compiler_fallbacks': ['/opt/g++'],
            'flags': '',
            'run_argv': ['{exe}'],
        }
    )
    monkeypatch.setattr(languages.shutil, 'which', lambda name: '/usr/bin/g++')
    assert languages.resolve_compiler(spec) == '/usr/bin/g++'


def test_resolve_compiler_uses_fallback(monkeypatch, tmp_path):
    fallback = tmp_path / 'kotlinc'
    fallback.write_text('#!/bin/sh\n')
    fallback.chmod(0o755)
    spec = languages.LanguageSpec.from_dict(
        {
            'id': 'kt',
            'kind': 'jvm_jar',
            'compiler_argv': ['kotlinc', '{src}'],
            'compiler_fallbacks': [str(fallback)],
            'flags': '',
            'run_argv': ['java', '-jar', '{jar}'],
            'build': 'kotlinc_include_runtime',
        }
    )
    monkeypatch.setattr(languages.shutil, 'which', lambda name: None)
    assert languages.resolve_compiler(spec) == str(fallback)
