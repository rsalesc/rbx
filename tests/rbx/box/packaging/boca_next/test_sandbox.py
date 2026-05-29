import pytest
from rbx_boca import sandbox


def test_build_safeexec_argv_compiled_run_profile():
    spec = sandbox.SafeExecSpec(
        runs=2,
        cpu_sec=3,
        wall_sec=12,
        mem_kb=256000,
        out_kb=65536,
        fds=10,
        n=1,
        procs=None,
        uid=65534,
        gid=65534,
        chdir='.',
        chroot=None,
        stdin='stdin0',
        stdout='stdout0',
        stderr='stderr0',
    )
    argv = sandbox.build_safeexec_argv(spec, program=['./run.exe'])
    assert argv[0].endswith('safeexec') or argv[0] == 'safeexec'
    body = argv[1:]
    assert '-r2' in body and '-t3' in body and '-T12' in body
    assert '-d256000' in body and '-m256000' in body
    assert '-f65536' in body and '-F10' in body and '-n1' in body
    assert '-U65534' in body and '-G65534' in body
    assert '-C.' in body and '-istdin0' in body
    assert '-ostdout0' in body and '-estderr0' in body
    assert '-u' not in ''.join(body)  # procs None -> no -u flag
    assert body[-1] == './run.exe'


def test_build_safeexec_argv_includes_procs_and_chroot():
    spec = sandbox.SafeExecSpec(
        runs=1,
        cpu_sec=2,
        wall_sec=8,
        mem_kb=512000,
        out_kb=1024,
        fds=256,
        n=0,
        procs=256,
        uid=1,
        gid=1,
        chdir='.',
        chroot='/jail',
        stdin='stdin0',
        stdout='stdout0',
        stderr='stderr0',
    )
    argv = sandbox.build_safeexec_argv(spec, program=['java', '-jar', 'run.jar'])
    assert '-u256' in argv and '-R/jail' in argv and '-n0' in argv
    assert argv[-3:] == ['java', '-jar', 'run.jar']


def test_profile_for_compiled_static_run():
    spec = sandbox.profile_for(
        'compiled_static',
        'run',
        cpu_sec=3,
        memory_mb=256,
        nruns=2,
        out_kb=65536,
        uid=1,
        gid=1,
    )
    assert spec.fds == 10
    assert spec.n == 1
    assert spec.procs is None
    assert spec.mem_kb == 256000
    assert spec.out_kb == 65536
    assert spec.runs == 2
    assert spec.wall_sec == 12
    assert spec.cpu_sec == 3
    assert spec.stdin == 'stdin0'


def test_profile_for_jvm_jar_run_forces_nruns_and_hardcodes():
    spec = sandbox.profile_for(
        'jvm_jar',
        'run',
        cpu_sec=2,
        memory_mb=256,
        nruns=5,
        out_kb=100,
        uid=1,
        gid=1,
    )
    assert spec.fds == 256
    assert spec.procs == 256
    assert spec.n == 0
    assert spec.mem_kb == 20000000
    assert spec.out_kb == 20000
    assert spec.runs == 1
    assert spec.wall_sec == 8
    assert spec.stdin == 'stdin0'


def test_profile_for_interpreted_run():
    spec = sandbox.profile_for(
        'interpreted',
        'run',
        cpu_sec=2,
        memory_mb=256,
        nruns=5,
        out_kb=4096,
        uid=1,
        gid=1,
    )
    assert spec.fds == 256
    assert spec.procs == 256
    assert spec.n == 0
    assert spec.mem_kb == 256000
    assert spec.out_kb == 4096
    assert spec.runs == 1
    assert spec.wall_sec == 8


def test_profile_for_compiled_static_compile():
    spec = sandbox.profile_for(
        'compiled_static',
        'compile',
        cpu_sec=10,
        memory_mb=512,
        uid=1,
        gid=1,
    )
    assert spec.fds == 1000
    assert spec.n == 0
    assert spec.procs is None
    assert spec.out_kb == 50000
    assert spec.runs == 1
    assert spec.wall_sec == 20
    assert spec.mem_kb == 512000
    assert spec.stdin is None


def test_profile_for_interpreted_compile():
    spec = sandbox.profile_for(
        'interpreted',
        'compile',
        cpu_sec=10,
        memory_mb=512,
        uid=1,
        gid=1,
    )
    assert spec.fds == 1000
    assert spec.n == 0
    assert spec.procs is None
    assert spec.out_kb == 50000
    assert spec.runs == 1
    assert spec.stdin is None


def test_profile_for_jvm_jar_compile_unified():
    spec = sandbox.profile_for(
        'jvm_jar',
        'compile',
        cpu_sec=10,
        memory_mb=512,
        uid=1,
        gid=1,
    )
    assert spec.fds == 256
    assert spec.n == 0
    assert spec.procs == 256
    assert spec.mem_kb == 20000000
    assert spec.out_kb == 50000
    assert spec.runs == 1
    assert spec.wall_sec == 20
    assert spec.stdin is None


def test_profile_for_overrides_win():
    spec = sandbox.profile_for(
        'compiled_static',
        'run',
        cpu_sec=1,
        memory_mb=64,
        uid=1,
        gid=1,
        overrides={'fds': 99},
    )
    assert spec.fds == 99


def test_profile_for_unknown_kind_raises():
    with pytest.raises(ValueError):
        sandbox.profile_for('nope', 'run', cpu_sec=1, memory_mb=64, uid=1, gid=1)


def test_profile_for_unknown_phase_raises():
    with pytest.raises(ValueError):
        sandbox.profile_for(
            'compiled_static', 'nope', cpu_sec=1, memory_mb=64, uid=1, gid=1
        )
