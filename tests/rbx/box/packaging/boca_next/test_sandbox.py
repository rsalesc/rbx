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
