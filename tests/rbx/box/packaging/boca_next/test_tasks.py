import os
from pathlib import Path

from rbx_boca import manifest, sandbox, tasks


def _spec(
    id,
    kind,
    compiler_argv=None,
    compiler_fallbacks=None,
    flags='',
    run_argv=None,
    build=None,
    syntax_check=False,
    sandbox_overrides=None,
):
    return manifest.LanguageSpec.from_dict(
        {
            'id': id,
            'kind': kind,
            'compiler_argv': compiler_argv if compiler_argv is not None else [],
            'compiler_fallbacks': compiler_fallbacks or [],
            'flags': flags,
            'run_argv': run_argv if run_argv is not None else ['{exe}'],
            'build': build,
            'syntax_check': syntax_check,
            'sandbox_overrides': sandbox_overrides or {},
        }
    )


def _ctx(
    tmp_path,
    runner=None,
    lang_spec=None,
    static_link_ok=None,
    task_type='batch',
    output_kb=65536,
    safeexec=None,
    checker_path='/bin/checker',
    interactor_path='/bin/interactor.exe',
    pipe_path='/bin/pipe.exe',
    interactor_launch_argv=None,
    make_fifos=None,
):
    if runner is None:

        def runner(argv, **kw):
            return 0

    spec = lang_spec if lang_spec is not None else _spec('cpp', 'compiled_static')
    lang = manifest.LanguageManifest(
        language=spec,
        limits=manifest.LimitsConfig(time_sec=1, runs=1, memory_mb=256),
    )
    task = manifest.TaskConfig(task_type=task_type, output_kb=output_kb)
    if safeexec is None:
        safeexec = sandbox.SafeExec(path='/usr/bin/safeexec', runner=runner)
    return tasks.RunContext(
        task=task,
        lang=lang,
        cwd=Path(tmp_path),
        runner=runner,
        safeexec=safeexec,
        uid=65534,
        gid=65534,
        chroot=None,
        cache_dir=Path(tmp_path) / 'cache',
        checker_path=Path(checker_path) if checker_path is not None else None,
        interactor_path=Path(interactor_path) if interactor_path is not None else None,
        pipe_path=Path(pipe_path) if pipe_path is not None else None,
        static_link_ok=static_link_ok
        if static_link_ok is not None
        else (lambda exe: True),
        interactor_launch_argv=interactor_launch_argv
        if interactor_launch_argv is not None
        else ['interactor-launch'],
        make_fifos=make_fifos,
    )


# --- Task 6.1: BatchTask.compile ---


def test_batch_compile_runs_compiler_and_checks_static_link(tmp_path):
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return 0

    spec = _spec(
        'cpp',
        'compiled_static',
        compiler_argv=['g++', '{flags}', '-o', '{exe}', '{src}'],
        flags='-O2 -static',
        run_argv=['{exe}'],
    )
    ctx = _ctx(tmp_path, runner=runner, lang_spec=spec, static_link_ok=lambda exe: True)
    rc = tasks.BatchTask().compile(ctx, src='sol.cpp', exe='run.exe', basename='run')
    assert rc == 0
    flat = [tok for argv in seen for tok in argv]
    assert 'g++' in flat and '-o' in flat and 'run.exe' in flat and 'sol.cpp' in flat


def test_batch_compile_fails_when_not_static(tmp_path):
    spec = _spec(
        'cpp',
        'compiled_static',
        compiler_argv=['g++', '{flags}', '-o', '{exe}', '{src}'],
        flags='-static',
        run_argv=['{exe}'],
    )
    ctx = _ctx(
        tmp_path,
        runner=lambda argv, **kw: 0,
        lang_spec=spec,
        static_link_ok=lambda exe: False,
    )
    rc = tasks.BatchTask().compile(ctx, src='sol.cpp', exe='run.exe', basename='run')
    assert rc == 47


def test_interactive_task_compile_works(tmp_path):
    """InteractiveTask inherits compile from BaseTask: same behavior as batch."""
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return 0

    spec = _spec(
        'cpp',
        'compiled_static',
        compiler_argv=['g++', '{flags}', '-o', '{exe}', '{src}'],
        flags='-O2 -static',
        run_argv=['{exe}'],
    )
    ctx = _ctx(
        tmp_path,
        runner=runner,
        lang_spec=spec,
        static_link_ok=lambda exe: True,
        task_type='interactive',
    )
    rc = tasks.InteractiveTask().compile(ctx, src='sol.cpp', exe='run', basename='run')
    assert rc == 0
    flat = [tok for argv in seen for tok in argv]
    assert 'g++' in flat and '-o' in flat and 'run' in flat and 'sol.cpp' in flat


# --- Task 6.2: BatchTask.run ---


def test_batch_run_maps_safeexec_exit(tmp_path):
    fake = sandbox.SafeExec(path='/usr/bin/safeexec', runner=lambda argv, **kw: 11)
    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    (tmp_path / 'in.txt').write_text('5\n')
    ctx = _ctx(tmp_path, safeexec=fake, lang_spec=spec)
    rc = tasks.BatchTask().run(
        ctx, ['run.exe', str(tmp_path / 'in.txt'), '3', '2', '256', '65536']
    )
    assert rc == 9  # batch_run_exit(11)


# --- Task 6.3: compare (batch + interactive) ---


def test_batch_compare_runs_checker(tmp_path):
    (tmp_path / 'team.out').write_text('42\n')
    (tmp_path / 'exp.out').write_text('42\n')
    (tmp_path / 'in.txt').write_text('x\n')
    ctx = _ctx(tmp_path, runner=lambda argv, **kw: 1, checker_path='/bin/checker')
    rc = tasks.BatchTask().compare(
        ctx,
        [
            str(tmp_path / 'team.out'),
            str(tmp_path / 'exp.out'),
            str(tmp_path / 'in.txt'),
        ],
    )
    assert rc == 6  # compare_verdict(None, 1)


def test_compare_without_checker_path_returns_judge_error(tmp_path):
    """No testlib marker + checker_path unconfigured -> fail loudly with 47,
    and the checker/runner is never invoked."""
    (tmp_path / 'team.out').write_text('42\n')
    (tmp_path / 'exp.out').write_text('42\n')
    (tmp_path / 'in.txt').write_text('x\n')
    called = []
    ctx = _ctx(
        tmp_path,
        runner=lambda argv, **kw: called.append(argv) or 0,
        checker_path=None,
    )
    rc = tasks.BatchTask().compare(
        ctx,
        [
            str(tmp_path / 'team.out'),
            str(tmp_path / 'exp.out'),
            str(tmp_path / 'in.txt'),
        ],
    )
    assert rc == 47  # OTHER_ERROR
    assert called == []  # checker NOT invoked


def test_interactive_compare_uses_testlib_line_without_checker(tmp_path):
    (tmp_path / 'team.out').write_text('testlib exitcode 3\n')
    (tmp_path / 'exp.out').write_text('\n')
    (tmp_path / 'in.txt').write_text('x\n')
    called = []
    ctx = _ctx(
        tmp_path,
        runner=lambda argv, **kw: called.append(argv) or 0,
        checker_path='/bin/checker',
        task_type='interactive',
    )
    rc = tasks.InteractiveTask().compare(
        ctx,
        [
            str(tmp_path / 'team.out'),
            str(tmp_path / 'exp.out'),
            str(tmp_path / 'in.txt'),
        ],
    )
    assert rc == 43  # compare_verdict(3, None)
    assert called == []  # checker NOT invoked


# --- Task 6.4: InteractiveTask.run ---


def test_interactive_run_parses_pipelog_and_emits_testlib(tmp_path):
    def runner(argv, **kw):
        # emulate pipe.exe writing its 3-line log: interactor-first, sol ok, WA(1)
        (tmp_path / 'pipe.log').write_text('2\n0\n1\n')
        return 0

    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    input_path = tmp_path / 'in.txt'
    input_path.write_text('7 11\n')
    ctx = _ctx(
        tmp_path,
        runner=runner,
        lang_spec=spec,
        task_type='interactive',
        pipe_path='/bin/pipe.exe',
        make_fifos=lambda: None,
    )
    rc = tasks.InteractiveTask().run(
        ctx, ['run.exe', str(input_path), '3', '1', '256', '65536']
    )
    assert rc == 0  # interactive_run_decision(2,0,1) -> run_exit 0, testlib 1
    assert (tmp_path / 'stdout0').read_text().strip() == 'testlib exitcode 1'
    # The test input was copied into stdin0 so the interactor reads real data.
    assert (tmp_path / 'stdin0').read_text() == '7 11\n'


def test_interactive_run_pipe_failure_returns_judge_error(tmp_path):
    def runner(argv, **kw):
        # pipe.exe failed: nonzero, no pipe.log written.
        return 1

    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    (tmp_path / 'in.txt').write_text('x\n')
    ctx = _ctx(
        tmp_path,
        runner=runner,
        lang_spec=spec,
        task_type='interactive',
        pipe_path='/bin/pipe.exe',
        make_fifos=lambda: None,
    )
    rc = tasks.InteractiveTask().run(
        ctx, ['run.exe', str(tmp_path / 'in.txt'), '3', '1', '256', '65536']
    )
    assert rc == 4  # judge error


def test_interactive_run_malformed_log_returns_judge_error(tmp_path):
    def runner(argv, **kw):
        # pipe.exe succeeds but writes a garbage/short log.
        (tmp_path / 'pipe.log').write_text('garbage\n')
        return 0

    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    (tmp_path / 'in.txt').write_text('x\n')
    ctx = _ctx(
        tmp_path,
        runner=runner,
        lang_spec=spec,
        task_type='interactive',
        pipe_path='/bin/pipe.exe',
        make_fifos=lambda: None,
    )
    rc = tasks.InteractiveTask().run(
        ctx, ['run.exe', str(tmp_path / 'in.txt'), '3', '1', '256', '65536']
    )
    assert rc == 4  # judge error


def test_interactive_run_without_pipe_path_returns_judge_error(tmp_path):
    """pipe_path unconfigured -> fail loudly with judge error 4, runner never
    invoked (no pipe.exe built/run)."""
    called = []

    def runner(argv, **kw):
        called.append(argv)
        return 0

    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    (tmp_path / 'in.txt').write_text('x\n')
    ctx = _ctx(
        tmp_path,
        runner=runner,
        lang_spec=spec,
        task_type='interactive',
        pipe_path=None,
        make_fifos=lambda: None,
    )
    rc = tasks.InteractiveTask().run(
        ctx, ['run.exe', str(tmp_path / 'in.txt'), '3', '1', '256', '65536']
    )
    assert rc == 4  # judge error
    assert called == []  # runner NOT invoked


def test_interactive_run_without_interactor_path_returns_judge_error(tmp_path):
    """interactor_path unconfigured -> fail loudly with judge error 4."""
    called = []

    def runner(argv, **kw):
        called.append(argv)
        return 0

    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    (tmp_path / 'in.txt').write_text('x\n')
    ctx = _ctx(
        tmp_path,
        runner=runner,
        lang_spec=spec,
        task_type='interactive',
        interactor_path=None,
        make_fifos=lambda: None,
    )
    rc = tasks.InteractiveTask().run(
        ctx, ['run.exe', str(tmp_path / 'in.txt'), '3', '1', '256', '65536']
    )
    assert rc == 4  # judge error
    assert called == []  # runner NOT invoked


# --- Task 6.5: compile paths (jvm manifest, interpreted, kotlin) ---


def test_jvm_compile_writes_manifest(tmp_path):
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return 0

    spec = _spec(
        'java',
        'jvm_jar',
        compiler_argv=['javac', '{flags}', '-d', '.', '{src}'],
        build='javac_then_jar',
        run_argv=['java', '-jar', '{exe}'],
    )
    ctx = _ctx(tmp_path, runner=runner, lang_spec=spec)
    rc = tasks.BatchTask().compile(ctx, src='Main.java', exe='run.jar', basename='run')
    assert rc == 0
    manifest_path = ctx.cwd / 'Manifest.txt'
    assert manifest_path.exists()
    assert manifest_path.read_text() == 'Main-Class: run\n'
    cmds = [argv[0] for argv in seen]
    assert 'javac' in cmds
    assert 'jar' in cmds


def test_interpreted_compile_writes_shebang_script(tmp_path):
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return 0

    spec = _spec(
        'py3',
        'interpreted',
        compiler_argv=['python3'],
        run_argv=['python3', '{exe}'],
        syntax_check=True,
    )
    from rbx_boca import languages

    (tmp_path / 'sol.py').write_text('print(42)\n')
    ctx = _ctx(tmp_path, runner=runner, lang_spec=spec)
    interp = languages.resolve_compiler(spec)
    rc = tasks.BatchTask().compile(ctx, src='sol.py', exe='run', basename='run')
    assert rc == 0
    exe_path = ctx.cwd / 'run'
    contents = exe_path.read_text()
    assert contents.startswith('#!' + interp)
    assert 'print(42)' in contents
    assert os.stat(str(exe_path)).st_mode & 0o777 == 0o755
    # syntax_check argv was run.
    assert any('py_compile' in argv for argv in seen)


def test_kotlin_compile_renames_source(tmp_path):
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return 0

    spec = _spec(
        'kt',
        'jvm_jar',
        compiler_argv=['kotlinc'],
        build='kotlinc_include_runtime',
        run_argv=['java', '-jar', '{exe}'],
    )
    (tmp_path / 'sol.kt').write_text('fun main() {}\n')
    ctx = _ctx(tmp_path, runner=runner, lang_spec=spec)
    rc = tasks.BatchTask().compile(ctx, src='sol.kt', exe='run.jar', basename='run')
    assert rc == 0
    assert (ctx.cwd / 'Main.kt').exists()
    assert not (ctx.cwd / 'sol.kt').exists()
    assert any(argv[0] == 'kotlinc' for argv in seen)
