import pathlib
import sys
from typing import Literal, Optional

import pytest

from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import CommunicationParams, SandboxParams
from rbx.grading.judge.sandboxes import stupid_sandbox
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox

# Pipes are shrunk to this size (where the platform honours it at all) so the
# noise below overflows every pipe between the two programs -- a capture tee
# adds a second one -- without making a char-mode tee crawl through megabytes.
PIPE_BYTES = 64 * 1024
NOISE_BYTES = 512 * 1024

# Writes a query, then a line the solution is allowed to ignore, then reads the
# answer. Python ignores SIGPIPE itself, so a write into a pipe nobody reads any
# more fails this interactor with BrokenPipeError instead of killing it.
INTERACTOR = """
import sys
noise = int(sys.argv[1])
sys.stdout.write('5\\n')
sys.stdout.flush()
sys.stdout.write('z' * noise + '\\n')
sys.stdout.flush()
answer = sys.stdin.readline().split()
sys.stderr.write('got %r\\n' % answer)
sys.exit(0 if answer == ['!', '6'] else 1)
"""

# Answers right after the first line and exits, never reading the noise.
SOLUTION = """
import sys
x = int(sys.stdin.readline())
sys.stdout.write('! %d\\n' % (x + 1))
sys.stdout.flush()
"""


@pytest.fixture
def sandbox(file_cacher: FileCacher, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(stupid_sandbox, 'BUFFER_SIZE_BYTES', PIPE_BYTES)
    sandbox = StupidSandbox(file_cacher=file_cacher)
    sandbox.create_file_from_string(pathlib.Path('interactor.py'), INTERACTOR)
    sandbox.create_file_from_string(pathlib.Path('solution.py'), SOLUTION)
    yield sandbox
    sandbox.cleanup(delete=True)


@pytest.mark.parametrize(
    'solution_stdout,merged_capture,tee_mode',
    [
        (None, None, 'char'),
        (pathlib.Path('solution.out'), None, 'char'),
        (pathlib.Path('solution.out'), None, 'line'),
        (pathlib.Path('solution.out'), pathlib.Path('merged.txt'), 'char'),
    ],
    ids=['raw', 'tee-char', 'tee-line', 'tee-merged'],
)
def test_interactor_outlives_solution_that_skips_its_output(
    sandbox: StupidSandbox,
    solution_stdout: Optional[pathlib.Path],
    merged_capture: Optional[pathlib.Path],
    tee_mode: Literal['char', 'line'],
):
    solution_params = SandboxParams(
        timeout=5000, wallclock_timeout=10000, stdout_file=solution_stdout
    )
    interactor_params = SandboxParams(
        timeout=5000,
        wallclock_timeout=10000,
        stderr_file=pathlib.Path('interactor.err'),
    )

    solution_log, interactor_log = sandbox.run_communication(
        [sys.executable, 'solution.py'],
        solution_params,
        [sys.executable, 'interactor.py', str(NOISE_BYTES)],
        interactor_params,
        CommunicationParams(merged_capture=merged_capture, tee_mode=tee_mode),
    )

    assert solution_log.exitcode == 0
    assert solution_log.exit_index < interactor_log.exit_index
    assert interactor_log.exitstatus == StupidSandbox.EXIT_OK, (
        sandbox.get_file_to_string(pathlib.Path('interactor.err'))
    )
    assert interactor_log.exitcode == 0
    assert "got ['!', '6']" in sandbox.get_file_to_string(
        pathlib.Path('interactor.err')
    )
