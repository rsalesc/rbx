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


def _spec(id, kind, run_argv, build=None):
    return languages.LanguageSpec.from_dict(
        {
            'id': id,
            'kind': kind,
            'compiler_argv': ['cc', '{src}'],
            'compiler_fallbacks': [],
            'flags': '',
            'run_argv': run_argv,
            'build': build,
        }
    )


def test_compiled_static_run_argv():
    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    assert languages.build_run_argv(spec, exe='run.exe', memory_mb=256) == ['run.exe']


def test_jvm_run_argv_injects_jvm_flags():
    spec = _spec(
        'java',
        'jvm_jar',
        run_argv=['java', '-jar', '{jar}', '{jvm_flags}'],
        build='javac_then_jar',
    )
    out = languages.build_run_argv(spec, exe='run.jar', memory_mb=256)
    assert out == [
        'java',
        '-jar',
        'run.jar',
        '-XX:+UseSerialGC',
        '-Xmx256000K',
        '-Xss25600K',
        '-Xms256000K',
    ]


def test_kotlin_run_argv_uses_classpath_mainkt():
    spec = _spec(
        'kt',
        'jvm_jar',
        run_argv=['java', '-cp', '{jar}', '{jvm_flags}', 'MainKt'],
        build='kotlinc_include_runtime',
    )
    out = languages.build_run_argv(spec, exe='run.jar', memory_mb=256)
    assert out[:4] == ['java', '-cp', 'run.jar', '-XX:+UseSerialGC']
    assert out[-1] == 'MainKt'


def test_interpreted_run_argv():
    spec = _spec('py3', 'interpreted', run_argv=['{interp}', '{src}'])
    out = languages.build_run_argv(
        spec, exe='run.exe', memory_mb=256, interp='python3', src='sol.py'
    )
    assert out == ['python3', 'sol.py']


def test_compile_plan_compiled_static():
    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    object.__setattr__(spec, 'flags', '-O2 -static')
    plan = languages.build_compile_plan(
        spec, src='sol.cpp', exe='run.exe', basename='run'
    )
    assert plan.steps[0] == ['cc', 'sol.cpp']
    assert plan.static_link_check is True
    assert plan.artifact == 'exe'
    assert plan.shebang is None
    assert plan.write_script is None


def test_compile_plan_interpreted_writes_shebang_script():
    spec = _spec('py3', 'interpreted', run_argv=['{interp}', '{src}'])
    object.__setattr__(spec, 'syntax_check', True)
    plan = languages.build_compile_plan(
        spec, src='sol.py', exe='run.exe', basename='run', interp='python3'
    )
    assert plan.shebang == '#!python3'
    assert plan.write_script == ('sol.py', 'run.exe')
    assert plan.static_link_check is False
    assert plan.artifact == 'script'
    assert plan.syntax_check_argv == ['python3', '-m', 'py_compile', 'sol.py']
    assert plan.steps == []


def test_compile_plan_interpreted_no_syntax_check():
    spec = _spec('py2', 'interpreted', run_argv=['{interp}', '{src}'])
    plan = languages.build_compile_plan(
        spec, src='sol.py', exe='run.exe', basename='run', interp='python2'
    )
    assert plan.shebang == '#!python2'
    assert plan.syntax_check_argv is None


def test_compile_plan_jvm_javac_then_jar():
    spec = _spec(
        'java',
        'jvm_jar',
        run_argv=['java', '-jar', '{jar}'],
        build='javac_then_jar',
    )
    object.__setattr__(spec, 'compiler_argv', ['javac', '{src}'])
    plan = languages.build_compile_plan(
        spec, src='Main.java', exe='run.jar', basename='Main'
    )
    assert ['javac', 'Main.java'] in plan.steps
    assert ['jar', 'cfm', 'run.jar', 'Manifest.txt', '.'] in plan.steps
    assert plan.manifest_class == 'Main'
    assert plan.artifact == 'jar'
    assert plan.static_link_check is False


def test_compile_plan_kotlin_include_runtime():
    spec = _spec(
        'kt',
        'jvm_jar',
        run_argv=['java', '-cp', '{jar}', 'MainKt'],
        build='kotlinc_include_runtime',
    )
    object.__setattr__(spec, 'compiler_argv', ['kotlinc', '{src}'])
    plan = languages.build_compile_plan(
        spec, src='sol.kt', exe='run.jar', basename='run'
    )
    assert plan.rename == ('sol.kt', 'Main.kt')
    assert ['kotlinc', '-d', 'run.jar', '-include-runtime', 'Main.kt'] in plan.steps
    assert plan.artifact == 'jar'
    assert plan.manifest_class is None
