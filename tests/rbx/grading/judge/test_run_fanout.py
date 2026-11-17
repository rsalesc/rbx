"""Contract of `StupidSandbox.run_fanout`: N contestant processes against one
interactor (`run_communication` is its one-process case).

Every scenario here is causally forced rather than timed: a process that blocks
on its stdin can only exit after the interactor lets it, and an interactor that
waits for a process's EOF can only exit after that process. Time bounds are
loose ceilings far below what a broken run would take.
"""

import os
import pathlib
import subprocess
import sys
import textwrap
import time
from typing import Any, List, Optional, Tuple
from unittest import mock

import psutil
import pytest

from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.program import Program, ProgramError
from rbx.grading.judge.sandbox import CommunicationParams, SandboxLog, SandboxParams
from rbx.grading.judge.sandboxes import stupid_sandbox
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox

# Process i answers v + i + 1, reading i from its last argument; stops at -1 or
# EOF. Writes two stderr lines, the second without a newline.
RELAY = """
import sys
index = int(sys.argv[-1])
sys.stderr.write('a%d\\nb%d' % (index, index))
sys.stderr.flush()
for line in sys.stdin:
    v = int(line)
    if v == -1:
        break
    sys.stdout.write('%d\\n' % (v + index + 1))
    sys.stdout.flush()
"""

# The relay's interactor: hands the value to process 0, 1, ... in turn, through
# the `<from_i> <to_i>` paths after its own arguments, then stops them all.
RELAY_INTERACTOR = """
import os
import sys
paths = sys.argv[1:]
n = len(paths) // 2
reads = [open(paths[2 * i], 'r') for i in range(n)]
writes = [open(paths[2 * i + 1], 'w') for i in range(n)]
v = 5
for i in range(n):
    writes[i].write('%d\\n' % v)
    writes[i].flush()
    got = int(reads[i].readline())
    if got != v + i + 1:
        sys.stderr.write('process %d answered %d to %d\\n' % (i, got, v))
        sys.stderr.flush()
        os._exit(1)
    v = got
for w in writes:
    w.write('-1\\n')
    w.flush()
sys.stderr.write('final %d\\n' % v)
sys.stderr.flush()
os._exit(0)
"""

# Writes a line and blocks on stdin; crashes (exit 3) at its EOF.
CRASH_ON_EOF = """
import os
import sys
os.write(1, b'q\\n')
if not sys.stdin.readline():
    os._exit(3)
"""

# Crashes before reading anything when it is the process given as argv[1].
CRASH_AT_START = """
import os
import sys
if sys.argv[-1] == sys.argv[1]:
    os._exit(4)
os.write(1, b'q\\n')
sys.stdin.readline()
"""

# Reads one line from every process (or stdin, with one), then rejects. Leaves
# with `os._exit`, so no file is closed before the process starts to exit.
REJECT_AFTER_READING = """
import os
import sys
paths = sys.argv[2:]
if not paths:
    sys.stdin.readline()
for k in range(len(paths) // 2):
    open(paths[2 * k], 'rb').readline()
os._exit(1)
"""

# Reads every process's output to EOF, then accepts.
ACCEPT_AFTER_EOF = """
import os
import sys
paths = sys.argv[1:]
for k in range(len(paths) // 2):
    open(paths[2 * k], 'rb').read()
os._exit(0)
"""

SLEEPER = """
import time
time.sleep(60)
"""

QUIT = """
import os
os._exit(0)
"""

# Writes a partial last line on both stdout and stderr, then exits.
UNTERMINATED = """
import os
import sys
os.write(2, b'err' + sys.argv[-1].encode())
os.write(1, b'out' + sys.argv[-1].encode())
"""

# Leaves a grandchild holding its stdout and stderr, which records its pid.
FORKER = """
import os
import sys
import time
pid = os.fork()
if pid == 0:
    time.sleep(60)
    os._exit(0)
with open('grandchild-%s.pid' % sys.argv[-1], 'w') as f:
    f.write(str(pid))
os.write(1, b'hi\\n')
"""

# The relay's interactor for one process, over its own stdin/stdout.
ONE = """
import sys
sys.stdout.write('5\\n')
sys.stdout.flush()
got = int(sys.stdin.readline())
sys.stdout.write('-1\\n')
sys.stdout.flush()
sys.exit(0 if got == 6 else 1)
"""

# Reads a line from every process, then accepts.
ACCEPT_AFTER_A_LINE = """
import os
import sys
paths = sys.argv[1:]
for k in range(len(paths) // 2):
    open(paths[2 * k], 'rb').readline()
os._exit(0)
"""

SCRIPTS = {
    'one.py': ONE,
    'accept_line.py': ACCEPT_AFTER_A_LINE,
    'relay.py': RELAY,
    'relay_interactor.py': RELAY_INTERACTOR,
    'crash_on_eof.py': CRASH_ON_EOF,
    'crash_at_start.py': CRASH_AT_START,
    'reject.py': REJECT_AFTER_READING,
    'accept.py': ACCEPT_AFTER_EOF,
    'sleeper.py': SLEEPER,
    'quit.py': QUIT,
    'unterminated.py': UNTERMINATED,
    'forker.py': FORKER,
}


@pytest.fixture
def sandbox(file_cacher: FileCacher):
    sandbox = StupidSandbox(file_cacher=file_cacher)
    for name, content in SCRIPTS.items():
        sandbox.create_file_from_string(pathlib.Path(name), content)
    yield sandbox
    sandbox.cleanup(delete=True)


def _py(script: str, *args: str) -> List[str]:
    return [sys.executable, script, *args]


def _run(
    sandbox: StupidSandbox,
    solution: List[str],
    interactor: List[str],
    processes: int,
    merged_capture: Optional[pathlib.Path] = None,
    tee_stderr: bool = False,
    solution_params: Optional[SandboxParams] = None,
) -> Tuple[List[SandboxLog], SandboxLog]:
    params = solution_params or SandboxParams(
        timeout=10000,
        wallclock_timeout=30000,
        stderr_file=pathlib.Path('sol.err'),
    )
    interactor_params = SandboxParams(
        timeout=10000,
        wallclock_timeout=30000,
        stderr_file=pathlib.Path('int.err'),
    )
    communication = CommunicationParams(
        processes=processes, merged_capture=merged_capture, tee_stderr=tee_stderr
    )
    if processes == 1:
        log, interactor_log = sandbox.run_communication(
            solution, params, interactor, interactor_params, communication
        )
        return [log], interactor_log
    return sandbox.run_fanout(
        solution, params, interactor, interactor_params, communication
    )


def _read(sandbox: StupidSandbox, name: str) -> str:
    return sandbox.get_file_to_string(pathlib.Path(name), maxlen=None)


class _SpawnSpy:
    """Records every program the sandbox spawns, optionally delaying some."""

    def __init__(self, delay: float = 0.0, delay_when=None):
        self.programs: List[Program] = []
        self.delay = delay
        self.delay_when = delay_when

    def __call__(self, command, params):
        if self.delay_when is not None and self.delay_when(command, params):
            time.sleep(self.delay)
        program = Program(command, params)
        self.programs.append(program)
        return program

    def tees(self) -> List[Program]:
        return [
            p for p in self.programs if any(a.endswith('_tee.py') for a in p.command)
        ]


def _spy(**kwargs) -> Tuple[_SpawnSpy, Any]:
    spy = _SpawnSpy(**kwargs)
    return spy, mock.patch.object(stupid_sandbox, 'Program', side_effect=spy)


def test_processes_relay_through_one_interactor(sandbox: StupidSandbox):
    logs, interactor_log = _run(sandbox, _py('relay.py'), _py('relay_interactor.py'), 3)

    assert interactor_log.exitstatus == StupidSandbox.EXIT_OK, _read(sandbox, 'int.err')
    # Each process read its index from argv and talked over its own pair of
    # paths, in `<from_i> <to_i>` order: any mix-up changes the sum.
    assert 'final 11' in _read(sandbox, 'int.err')
    assert [log.exitstatus for log in logs] == [StupidSandbox.EXIT_OK] * 3
    assert sorted(log.exit_index for log in [interactor_log, *logs]) == [0, 1, 2, 3]


def test_process_stderr_is_merged_grouped_and_tagged(sandbox: StupidSandbox):
    _run(sandbox, _py('relay.py'), _py('relay_interactor.py'), 3)

    assert (
        _read(sandbox, 'sol.err') == '[0] a0\n[0] b0\n[1] a1\n[1] b1\n[2] a2\n[2] b2\n'
    )
    # The per-process scratch files are gone.
    assert sorted(p.name for p in sandbox.get_root_path().glob('sol.err*')) == [
        'sol.err'
    ]


def test_merged_capture_tags_every_line_with_its_process(sandbox: StupidSandbox):
    _run(
        sandbox,
        _py('relay.py'),
        _py('relay_interactor.py'),
        3,
        merged_capture=pathlib.Path('merged.pio'),
        tee_stderr=True,
    )

    lines = _read(sandbox, 'merged.pio').splitlines()
    assert lines[:2] == ['<', '>']
    dialogue = [line for line in lines[2:] if '!' not in line]
    # The interactor talks to one process at a time, so the order is forced.
    assert dialogue == [
        '[0]<5',
        '[0]>6',
        '[1]<6',
        '[1]>8',
        '[2]<8',
        '[2]>11',
        '[0]<-1',
        '[1]<-1',
        '[2]<-1',
    ]
    assert dialogue[:6] == ['[0]<5', '[0]>6', '[1]<6', '[1]>8', '[2]<8', '[2]>11']
    for i in range(3):
        # Each process's stderr, in its own order; the unterminated last line
        # is captured whole, with a newline.
        assert [line for line in lines if line.startswith(f'[{i}]!')] == [
            f'[{i}]!a{i}',
            f'[{i}]!b{i}',
        ]
    # The clean stderr copy is still merged and tagged.
    assert _read(sandbox, 'sol.err').startswith('[0] a0\n[0] b0\n')


def test_the_last_unterminated_line_of_the_capture_gets_a_newline(
    sandbox: StupidSandbox,
):
    _run(
        sandbox,
        _py('unterminated.py'),
        _py('accept.py'),
        2,
        merged_capture=pathlib.Path('merged.pio'),
        tee_stderr=True,
    )

    merged = _read(sandbox, 'merged.pio')
    assert merged.endswith('\n')
    lines = merged.splitlines()
    for i in range(2):
        assert f'[{i}]>out{i}' in lines
        assert f'[{i}]!err{i}' in lines
    assert _read(sandbox, 'sol.err') == '[0] err0\n[1] err1\n'


def test_run_communication_returns_the_solution_and_interactor_pair(
    sandbox: StupidSandbox,
):
    solution_log, interactor_log = sandbox.run_communication(
        _py('relay.py', '0'),
        SandboxParams(timeout=10000, wallclock_timeout=30000),
        _py('one.py'),
        SandboxParams(timeout=10000, wallclock_timeout=30000),
    )
    assert isinstance(solution_log, SandboxLog)
    assert solution_log.exitstatus == StupidSandbox.EXIT_OK
    assert interactor_log.exitstatus == StupidSandbox.EXIT_OK


def test_a_failing_interactor_kills_the_processes(sandbox: StupidSandbox):
    sandbox.create_file_from_string(
        pathlib.Path('reject_now.py'), 'import os\nos._exit(1)\n'
    )
    start = time.monotonic()
    logs, interactor_log = _run(sandbox, _py('sleeper.py'), _py('reject_now.py'), 3)
    elapsed = time.monotonic() - start

    assert interactor_log.exitcode == 1
    assert elapsed < 20  # The sleepers would take 60 s.
    assert [log.exitstatus for log in logs] == [StupidSandbox.EXIT_SIGNAL] * 3
    assert all(log.exit_index > interactor_log.exit_index for log in logs)


@pytest.mark.parametrize('processes', [1, 16])
def test_a_rejecting_interactor_ranks_before_processes_dying_of_its_eof(
    sandbox: StupidSandbox, processes: int
):
    logs, interactor_log = _run(
        sandbox,
        _py('crash_on_eof.py'),
        _py('reject.py', 'x'),
        processes,
        solution_params=SandboxParams(timeout=10000, wallclock_timeout=30000),
    )

    assert interactor_log.exitcode == 1
    assert interactor_log.exit_index == 0
    assert all(log.exitstatus != StupidSandbox.EXIT_OK for log in logs)


@pytest.mark.parametrize('processes', [1, 16])
def test_a_process_crashing_first_ranks_first(sandbox: StupidSandbox, processes: int):
    crasher = processes - 1
    logs, interactor_log = _run(
        sandbox,
        _py('crash_at_start.py', str(crasher)),
        _py('reject.py', 'x'),
        processes,
        solution_params=SandboxParams(timeout=10000, wallclock_timeout=30000),
    )

    # The interactor reads every process, so it cannot exit before the crasher.
    assert logs[crasher].exitcode == 4
    assert logs[crasher].exit_index == 0
    assert interactor_log.exit_index == 1


def test_processes_join_a_group_whose_leader_already_exited(
    sandbox: StupidSandbox,
):
    # The leader (process 0) exits before the others are even spawned.
    spy, patch = _spy(delay=0.2, delay_when=lambda _, params: params.pgid is not None)
    with patch:
        logs, interactor_log = _run(sandbox, _py('quit.py'), _py('quit.py'), 4)

    assert interactor_log.exitstatus == StupidSandbox.EXIT_OK
    assert [log.exitstatus for log in logs] == [StupidSandbox.EXIT_OK] * 4


@pytest.mark.parametrize(
    'processes,merged_capture,tees',
    [
        (3, None, 0),
        (3, pathlib.Path('merged.pio'), 1),
        (1, pathlib.Path('merged.pio'), 1),
    ],
    ids=['fanout-no-capture', 'fanout-capture', 'interactive-capture'],
)
def test_a_run_spawns_at_most_one_tee(
    sandbox: StupidSandbox,
    processes: int,
    merged_capture: Optional[pathlib.Path],
    tees: int,
):
    spy, patch = _spy()
    with patch:
        _run(
            sandbox,
            _py('relay.py', '0'),
            _py('relay_interactor.py') if processes > 1 else _py('one.py'),
            processes,
            merged_capture=merged_capture,
            tee_stderr=True,
        )

    assert len(spy.tees()) == tees
    assert len(spy.programs) == processes + 1 + tees


def test_fanout_never_sizes_pipes(sandbox: StupidSandbox):
    spy, patch = _spy()
    real_fcntl = stupid_sandbox.fcntl.fcntl
    with (
        patch,
        mock.patch.object(
            stupid_sandbox.fcntl, 'fcntl', side_effect=real_fcntl
        ) as fcntl_spy,
    ):
        _run(
            sandbox,
            _py('relay.py'),
            _py('relay_interactor.py'),
            3,
            merged_capture=pathlib.Path('merged.pio'),
            tee_stderr=True,
        )

    assert [p.params.pipesize for p in spy.programs] == [-1] * len(spy.programs)
    set_size = getattr(stupid_sandbox.fcntl, 'F_SETPIPE_SZ', None)
    assert all(call.args[1] != set_size for call in fcntl_spy.call_args_list), (
        fcntl_spy.call_args_list
    )


def test_wall_time_counts_from_the_interactors_start(sandbox: StupidSandbox):
    delay = 3.0
    # The interactor starts `delay` seconds after the processes were spawned.
    spy, patch = _spy(
        delay=delay,
        delay_when=lambda command, _: any('relay_interactor' in a for a in command),
    )
    params = SandboxParams(
        timeout=10000,
        # Less than the delay: counted from its spawn, every process would be
        # out of wall time before the interactor even started.
        wallclock_timeout=2000,
        stderr_file=pathlib.Path('sol.err'),
    )
    with patch:
        logs, interactor_log = _run(
            sandbox,
            _py('relay.py'),
            _py('relay_interactor.py'),
            3,
            solution_params=params,
        )

    assert interactor_log.exitstatus == StupidSandbox.EXIT_OK
    for log in logs:
        assert log.exitstatus == StupidSandbox.EXIT_OK
        assert log.wall_time is not None and log.wall_time < delay


def test_a_missing_interactor_leaves_no_process_behind(sandbox: StupidSandbox):
    before = {p.pid for p in psutil.Process().children(recursive=True)}
    start = time.monotonic()
    with pytest.raises(ProgramError):
        _run(sandbox, _py('sleeper.py'), ['/nonexistent/interactor'], 3)
    # Killed, not waited for: the sleepers would take 60 s.
    assert time.monotonic() - start < 20

    # Killed and reaped: not even a zombie is left.
    after = {p.pid for p in psutil.Process().children(recursive=True)}
    assert after - before == set()


def _wait_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize(
    'merged_capture',
    [None, pathlib.Path('merged.pio')],
    ids=['no-capture', 'capture'],
)
def test_a_grandchild_holding_stdout_neither_blocks_nor_survives_the_run(
    sandbox: StupidSandbox, merged_capture: Optional[pathlib.Path]
):
    start = time.monotonic()
    logs, interactor_log = _run(
        sandbox,
        _py('forker.py'),
        _py('accept_line.py'),
        2,
        merged_capture=merged_capture,
    )
    elapsed = time.monotonic() - start

    # The grandchildren sleep 60 s holding the processes' stdout.
    assert elapsed < 30
    assert [log.exitstatus for log in logs] == [StupidSandbox.EXIT_OK] * 2
    for i in range(2):
        pid = int(_read(sandbox, f'grandchild-{i}.pid'))
        assert _wait_gone(pid), f'grandchild {pid} survived the run'


FD_LIMIT_SCRIPT = textwrap.dedent(
    """
    import pathlib
    import resource
    import sys
    import tempfile

    from rbx.grading.judge.cacher import FileCacher
    from rbx.grading.judge.program import ProgramError
    from rbx.grading.judge.sandbox import CommunicationParams, SandboxParams
    from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
    from rbx.grading.judge.storage import FilesystemStorage

    root = pathlib.Path(tempfile.mkdtemp())
    sandbox = StupidSandbox(
        file_cacher=FileCacher(FilesystemStorage(root / 'storage')), temp_dir=root
    )
    # Hard as well as soft: the sandbox raises the soft limit up to the hard one.
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    params = SandboxParams(timeout=1000, wallclock_timeout=2000)
    try:
        sandbox.run_fanout(
            ['true'], params, ['true'], params, CommunicationParams(processes=64)
        )
    except ProgramError as e:
        print('ProgramError:', e)
        sys.exit(0)
    print('no error')
    sys.exit(1)
    """
)


def test_running_out_of_file_descriptors_is_a_program_error_naming_n(
    tmp_path: pathlib.Path,
):
    # In a child process, so the lowered limit never reaches this one.
    result = subprocess.run(
        [sys.executable, '-c', FD_LIMIT_SCRIPT],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
        env={**os.environ},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ProgramError: Cannot open the pipes for 64 solution process(es)' in (
        result.stdout
    )
    assert 'open-file limit is 64' in result.stdout
