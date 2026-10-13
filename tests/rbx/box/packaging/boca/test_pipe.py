"""BOCA's pipe.c, which the MOJ packager ships too. It needs epoll, so Linux only."""

import pathlib
import shutil
import subprocess
import sys

import pytest

from rbx.config import get_default_app_path

PIPE_C = get_default_app_path() / 'packagers' / 'boca' / 'pipe.c'

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith('linux') or shutil.which('gcc') is None,
    reason='pipe.c needs Linux (epoll) and gcc',
)


@pytest.fixture(scope='module')
def pipe(tmp_path_factory) -> pathlib.Path:
    binary = tmp_path_factory.mktemp('pipe') / 'pipe'
    subprocess.run(['gcc', '-O2', '-o', str(binary), str(PIPE_C)], check=True)
    return binary


def _run(pipe: pathlib.Path, tmp_path: pathlib.Path, solution: str, interactor: str):
    """Run both sides through pipe, crossed by two FIFOs, and return what it
    reports: who ended first (1 solution, 2 interactor) and both statuses."""
    for fifo in ('fifo.in', 'fifo.out'):
        subprocess.run(['mkfifo', str(tmp_path / fifo)], check=True)
    proc = subprocess.run(
        [
            str(pipe),
            '-i',
            'fifo.in',
            '-o',
            'fifo.out',
            '--',
            '/bin/sh',
            '-c',
            f'exec >fifo.out <fifo.in; {solution}',
            '=',
            '/bin/sh',
            '-c',
            interactor,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return [int(line) for line in proc.stdout.split()]


def test_an_interactor_writing_after_the_solution_left_is_not_killed(pipe, tmp_path):
    # The solution leaves without reading; the interactor then writes into a pipe
    # nobody reads. With the default disposition that is SIGPIPE (141) -- a judge
    # error where the verdict is the solution's.
    first, solution, interactor = _run(
        pipe, tmp_path, 'exit 0', 'sleep 0.3; echo one; echo two; exit 0'
    )
    assert (first, solution) == (1, 0)
    assert interactor == 0


def test_the_solution_still_gets_sigpipe(pipe, tmp_path):
    # Only the interactor is shielded: a solution writing after the interactor
    # left dies of SIGPIPE as before.
    first, solution, interactor = _run(
        pipe, tmp_path, 'sleep 0.3; while :; do echo x; done', 'exit 0'
    )
    assert (first, interactor) == (2, 0)
    assert solution == 128 + 13
