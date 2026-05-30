"""Phase 9 integration harness for the rbx_boca Layer-2 runtime.

These tests validate the runtime end-to-end. They are deliberately HERMETIC:
no gcc, no root, no real SUID safeexec, no real pipe.exe (this machine cannot
build/run SUID safeexec or compile C).

Manifest reading from the .pyz uses ``pkgutil.get_data`` (zip-safe, not
deprecated); verified by ``test_pyz_limits_end_to_end`` reading task.json /
language.json from inside a real archive with NO env override.
"""

import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from rbx_boca import entrypoints, interactor_launcher, manifest, sandbox, tasks

from tests.rbx.box.packaging.boca_next import _bundle

# --- stubs --------------------------------------------------------------------

# A stub `safeexec`: skip its own -flags, find the program after `--`, honor
# -i<file>/-o<file> redirection, exec the program, propagate its exit code.
_STUB_SAFEEXEC = """#!{python}
import os
import sys

argv = sys.argv[1:]
stdin_path = None
stdout_path = None
prog = None
i = 0
while i < len(argv):
    a = argv[i]
    if a == '--':
        prog = argv[i + 1:]
        break
    if a.startswith('-i'):
        stdin_path = a[2:]
    elif a.startswith('-o'):
        stdout_path = a[2:]
    # all other -flags are limits we ignore in the stub
    i += 1

if not prog:
    sys.exit(2)

if stdin_path:
    fd = os.open(stdin_path, os.O_RDONLY)
    os.dup2(fd, 0)
if stdout_path:
    fd = os.open(stdout_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(fd, 1)

os.execv(prog[0], prog)
"""

# A stub checker: `checker <input> <team_out> <expected_out>`; exit 0 if the
# team output equals the expected output, else 1 (mirrors a trivial diff checker).
_STUB_CHECKER = """#!{python}
import sys

_input, team, expected = sys.argv[1], sys.argv[2], sys.argv[3]
with open(team) as f:
    t = f.read().split()
with open(expected) as f:
    e = f.read().split()
sys.exit(0 if t == e else 1)
"""

# A trivial solution: read an int from stdin, print it doubled.
_SOLUTION = """import sys
n = int(sys.stdin.read().split()[0])
print(n * 2)
"""


def _write_exec(path: Path, text: str) -> Path:
    path.write_text(text.format(python=sys.executable))
    os.chmod(str(path), 0o755)
    return path


def _interpreted_language_json():
    return {
        'language': {
            'id': 'py3',
            'kind': 'interpreted',
            'compiler_argv': ['python3'],
            'run_argv': ['{interp}', '{exe}'],
            'syntax_check': False,
        },
        'limits': {
            'time_sec': 3,
            'runs': 1,
            'memory_mb': 256,
            'wall_time_sec': 12,
        },
    }


# --- Task 9.1: zipapp bundle + limits e2e -------------------------------------


def test_pyz_limits_end_to_end(tmp_path):
    """A real .pyz reads its bundled manifests (no env override) and prints the
    limits. Proves zipimport + manifest reading works from a real archive."""
    pyz = _bundle.build_pyz(
        tmp_path,
        task_json={'task_type': 'batch', 'output_kb': 65536},
        language_json={
            'language': {
                'id': 'cpp',
                'kind': 'compiled_static',
                'compiler_argv': ['g++', '-o', '{exe}', '{src}'],
                'run_argv': ['{exe}'],
            },
            'limits': {
                'time_sec': 3,
                'runs': 2,
                'memory_mb': 256,
                'wall_time_sec': 12,
            },
        },
    )
    result = subprocess.run(
        [str(pyz), 'limits'],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['3', '2', '256', '65536']


# --- Task 9.2: batch e2e via stub safeexec + interpreted solution -------------


def test_pyz_batch_compile_and_run_end_to_end(tmp_path):
    """compile -> run through the real .pyz under a stub safeexec, executing a
    real python solution. Proves the .pyz actually runs a solution sandboxed."""
    work = tmp_path / 'work'
    work.mkdir()
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    _write_exec(bindir / 'safeexec', _STUB_SAFEEXEC)

    pyz = _bundle.build_pyz(
        tmp_path,
        {'task_type': 'batch', 'output_kb': 65536},
        _interpreted_language_json(),
    )

    (work / 'sol.py').write_text(_SOLUTION)
    (work / 'in.txt').write_text('21\n')

    env = dict(os.environ)
    env['PATH'] = str(bindir) + os.pathsep + env.get('PATH', '')

    # compile sol.py -> run (writes shebang script).
    rc = subprocess.run(
        [str(pyz), 'compile', 'sol.py', 'run', '3', '256'],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stderr
    assert (work / 'run').exists()

    # run run in.txt 3 1 256 65536 (solution exits 0 -> batch run exit 0).
    rc = subprocess.run(
        [str(pyz), 'run', 'run', 'in.txt', '3', '1', '256', '65536'],
        cwd=str(work),
        env=env,
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stderr
    # The solution wrote its doubled answer to stdout0 via stub safeexec -o.
    assert (work / 'stdout0').read_text().split() == ['42']


def test_compare_end_to_end_via_entrypoint(tmp_path):
    """compare e2e at the entrypoints.main level with an injected context using a
    real stub checker script. (Driven here rather than through the subprocess
    because load_context leaves checker_path best-effort for Layer 2.)"""
    checker = _write_exec(tmp_path / 'checker', _STUB_CHECKER)

    (tmp_path / 'in.txt').write_text('21\n')
    (tmp_path / 'team.out').write_text('42\n')
    (tmp_path / 'exp.out').write_text('42\n')
    (tmp_path / 'wrong.out').write_text('99\n')

    def _factory():
        lang = manifest.LanguageManifest(
            language=manifest.LanguageSpec.from_dict(
                _interpreted_language_json()['language']
            ),
            limits=manifest.LimitsConfig(
                time_sec=3, runs=1, memory_mb=256, wall_time_sec=12
            ),
        )
        return tasks.RunContext(
            task=manifest.TaskConfig(task_type='batch', output_kb=65536),
            lang=lang,
            cwd=tmp_path,
            runner=lambda argv, **kw: subprocess.call(argv, **kw),
            safeexec=sandbox.SafeExec(path='/usr/bin/safeexec'),
            checker_path=checker,
        )

    ac = entrypoints.main(
        [
            'compare',
            str(tmp_path / 'team.out'),
            str(tmp_path / 'exp.out'),
            str(tmp_path / 'in.txt'),
        ],
        context_factory=_factory,
    )
    assert ac == 4  # AC: team == expected

    wa = entrypoints.main(
        [
            'compare',
            str(tmp_path / 'team.out'),
            str(tmp_path / 'wrong.out'),
            str(tmp_path / 'in.txt'),
        ],
        context_factory=_factory,
    )
    assert wa == 6  # WA: team != expected


# --- Task 9.3: interactor launcher fd-inheritance + watchdog ------------------


def _fork_launch(interactor_argv, ittime, notify_fd):
    """Fork; in the child run launch() (which execv's, never returns). Returns
    the child pid in the parent."""
    pid = os.fork()
    if pid == 0:  # child
        # Become a new session/group leader BEFORE launch(). The watchdog uses
        # killpg(0, ...), which in production targets the BOCA job's group; in
        # the test it would otherwise target pytest's own group and could
        # SIGTERM/SIGKILL the test runner. setsid() contains killpg(0) to this
        # child's group. (launch() itself is unchanged to match bash production
        # behavior.)
        try:
            os.setsid()
        except OSError:
            pass
        try:
            interactor_launcher.launch(
                interactor_argv, ittime=ittime, notify_fd=notify_fd
            )
        except BaseException:
            os._exit(127)
        os._exit(0)  # unreachable if execv succeeds
    return pid


@pytest.mark.slow
def test_interactor_launcher_fd_closes_when_interactor_exits(tmp_path):
    """The notify pipe must reach EOF PROMPTLY after the interactor exits.

    Proves: launch() cleared CLOEXEC so the interactor inherited the fd AND the
    watchdog child closed its own copy. If the watchdog leaked the fd, read()
    would block until SIGKILL (ittime+5s); we assert EOF arrives well before.

    Non-vacuity: the stub interactor writes a sentinel file before exiting, so we
    can assert exec() actually happened (rather than the launcher crashing before
    exec, which would make the EOF assertion pass trivially).
    """
    read_fd, write_fd = os.pipe()
    sentinel = tmp_path / 'exec_happened'
    # Stub interactor: write a sentinel proving exec, sleep briefly, exit 0
    # (holds notify fd while alive).
    interactor = [
        sys.executable,
        '-c',
        'import time, pathlib; pathlib.Path({!r}).write_text("1"); '
        'time.sleep(0.2)'.format(str(sentinel)),
    ]
    pid = None
    try:
        pid = _fork_launch(interactor, ittime=2, notify_fd=write_fd)
        os.close(write_fd)  # drop the parent's copy; only the interactor holds it
        write_fd = -1

        # EOF must arrive once the interactor (the sole remaining holder) exits,
        # i.e. ~0.2s -- well before the watchdog kill grace (ittime+5 = 7s).
        ready, _, _ = select.select([read_fd], [], [], 4.0)
        assert ready, 'notify fd did not close (leaked into watchdog?)'
        assert os.read(read_fd, 64) == b''  # EOF
        # The interactor really reached exec (not an early launcher crash).
        assert sentinel.exists(), (
            'stub interactor never ran -> launch() crashed pre-exec'
        )
    finally:
        if write_fd != -1:
            os.close(write_fd)
        os.close(read_fd)
        if pid is not None:
            os.waitpid(pid, 0)


@pytest.mark.slow
def test_interactor_launcher_watchdog_kills_hanging_interactor(tmp_path):
    """The watchdog must kill a hung interactor at ~ittime (+kill grace), not
    let it run for its full sleep.

    Non-vacuity: the stub interactor writes a sentinel before hanging, so we
    assert exec() actually happened and the watchdog killed a *running*
    interactor (not a launcher that crashed before exec).
    """
    read_fd, write_fd = os.pipe()
    sentinel = tmp_path / 'exec_happened'
    # Stub interactor that writes a sentinel proving exec, then hangs for 60s if
    # not killed.
    interactor = [
        sys.executable,
        '-c',
        'import time, pathlib; pathlib.Path({!r}).write_text("1"); '
        'time.sleep(60)'.format(str(sentinel)),
    ]
    pid = None
    try:
        start = time.monotonic()
        pid = _fork_launch(interactor, ittime=1, notify_fd=write_fd)
        os.close(write_fd)
        write_fd = -1

        # Reap the interactor; it must die within ittime + kill_grace + slack.
        deadline = start + 9.0
        reaped = False
        status = 0
        while time.monotonic() < deadline:
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                reaped = True
                break
            time.sleep(0.05)
        elapsed = time.monotonic() - start
        if not reaped:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            pytest.fail('watchdog did not kill the interactor within 9s')
        assert elapsed < 9.0
        # The interactor really reached exec (so the watchdog killed a running
        # interactor, not a launcher that crashed before exec).
        assert sentinel.exists(), (
            'stub interactor never ran -> launch() crashed pre-exec'
        )
        # Killed by signal (SIGTERM at ittime, or SIGKILL at ittime+grace).
        assert os.WIFSIGNALED(status) or (
            os.WIFEXITED(status) and os.WEXITSTATUS(status) != 0
        )
        pid = None
    finally:
        if write_fd != -1:
            os.close(write_fd)
        os.close(read_fd)
        if pid is not None:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except OSError:
                pass


# --- Task 9.4: pipe.exe argv shape -------------------------------------------


def _interactive_ctx(tmp_path):
    spec = manifest.LanguageSpec.from_dict(
        {
            'id': 'cpp',
            'kind': 'compiled_static',
            'compiler_argv': ['g++', '-o', '{exe}', '{src}'],
            'run_argv': ['{exe}'],
        }
    )
    lang = manifest.LanguageManifest(
        language=spec,
        limits=manifest.LimitsConfig(
            time_sec=3, runs=1, memory_mb=256, wall_time_sec=12
        ),
    )
    return tasks.RunContext(
        task=manifest.TaskConfig(task_type='interactive', output_kb=65536),
        lang=lang,
        cwd=tmp_path,
        runner=lambda argv, **kw: 0,
        safeexec=sandbox.SafeExec(path='/usr/bin/safeexec'),
        checker_path=Path('/bin/checker'),
        interactor_path=Path('/box/interactor.exe'),
        pipe_path=Path('/box/pipe.exe'),
        interactor_launch_argv=[sys.executable, '-m', 'rbx_boca'],
    )


def test_build_pipe_argv_shape(tmp_path):
    ctx = _interactive_ctx(tmp_path)
    argv = tasks.InteractiveTask().build_pipe_argv(
        ctx, ['run', 'in.txt', '3', '1', '256', '65536']
    )

    # pipe.exe prefix mirrors interactor_run.sh:44.
    assert argv[:10] == [
        '/box/pipe.exe',
        '-i',
        'fifo.in',
        '-o',
        'fifo.out',
        '-e',
        'stderr0',  # solution safeexec spec.stderr
        '-E',
        'interactor.stderr',
        '--',
    ]

    # Exactly one `=` separator splitting solution side / interactor side.
    assert argv.count('=') == 1
    sep = argv.index('=')
    solution_seg = argv[10:sep]
    interactor_seg = argv[sep + 1 :]

    # Solution side: safeexec with fifo redirection + notify fd (literal __FD__).
    assert solution_seg[0] == '/usr/bin/safeexec'
    assert '-ififo.in' in solution_seg
    assert '-ofifo.out' in solution_seg
    assert '-D__FD__' in solution_seg
    # __FD__ must appear ONLY in the literal -D__FD__ token (never substituted).
    assert [t for t in solution_seg if '__FD__' in t] == ['-D__FD__']

    # Interactor side: re-enter the bundle under the launcher, ittime = wall+1.
    assert interactor_seg == [
        sys.executable,
        '-m',
        'rbx_boca',
        '__interactor_launcher__',
        '13',  # ittime = wall_time_sec(12) + 1
        '__FD__',
        '--',
        '/box/interactor.exe',
        'stdin0',
        'stdout0',
    ]


def test_interactive_run_still_parses_pipelog(tmp_path):
    """The refactor preserves the Phase 6 flow: run() builds argv, runs the
    (fake) pipe.exe, parses pipe.log, decides, emits testlib, returns."""

    def runner(argv, **kw):
        # emulate pipe.exe: interactor-first(2), sol ok(0), WA(1).
        (tmp_path / 'pipe.log').write_text('2\n0\n1\n')
        return 0

    ctx = tasks.RunContext(
        task=manifest.TaskConfig(task_type='interactive', output_kb=65536),
        lang=manifest.LanguageManifest(
            language=manifest.LanguageSpec.from_dict(
                {
                    'id': 'cpp',
                    'kind': 'compiled_static',
                    'compiler_argv': ['g++'],
                    'run_argv': ['{exe}'],
                }
            ),
            limits=manifest.LimitsConfig(
                time_sec=3, runs=1, memory_mb=256, wall_time_sec=12
            ),
        ),
        cwd=tmp_path,
        runner=runner,
        safeexec=sandbox.SafeExec(path='/usr/bin/safeexec'),
        interactor_path=Path('/box/interactor.exe'),
        pipe_path=Path('/box/pipe.exe'),
        interactor_launch_argv=[sys.executable, '-m', 'rbx_boca'],
        make_fifos=lambda: None,
    )
    (tmp_path / 'in.txt').write_text('21\n')
    rc = tasks.InteractiveTask().run(
        ctx, ['run', str(tmp_path / 'in.txt'), '3', '1', '256', '65536']
    )
    assert rc == 0
    assert (tmp_path / 'stdout0').read_text().strip() == 'testlib exitcode 1'
