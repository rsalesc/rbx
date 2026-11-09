import importlib.resources
import os
import pathlib
import select
import subprocess
import sys
import time

import pytest

from rbx.grading.judge.sandbox import CommunicationParams, SandboxParams

with importlib.resources.as_file(
    importlib.resources.files('rbx')
    / 'grading'
    / 'judge'
    / 'sandboxes'
    / 'chunk_tee.py'
) as _path:
    TEE = pathlib.Path(_path)


def _start(tmp_path: pathlib.Path, marker: str = '<') -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(TEE), marker, str(tmp_path / 'extra')],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=(tmp_path / 'merged').open('wb'),
        bufsize=0,
    )


def _read_within(fd: int, n: int, timeout: float = 5.0) -> bytes:
    got = b''
    deadline = time.monotonic() + timeout
    while len(got) < n:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([fd], [], [], max(remaining, 0))
        if not ready:
            break
        data = os.read(fd, n - len(got))
        if not data:
            break
        got += data
    return got


def _finish(proc: subprocess.Popen) -> bytes:
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.close()
    rest = proc.stdout.read()
    assert proc.wait(timeout=10) == 0
    return rest


def test_forwards_a_partial_line_before_more_input_arrives(tmp_path: pathlib.Path):
    proc = _start(tmp_path)
    assert proc.stdin is not None and proc.stdout is not None

    # No newline and the writer keeps the pipe open: the bytes must still reach
    # the peer, or a program that asks "? 5" without a newline would deadlock.
    proc.stdin.write(b'? 5')
    assert _read_within(proc.stdout.fileno(), 3) == b'? 5'

    proc.stdin.write(b' 6\n')
    assert _read_within(proc.stdout.fileno(), 3) == b' 6\n'
    assert _finish(proc) == b''


def test_marks_every_line_and_copies_the_extra_file_verbatim(
    tmp_path: pathlib.Path,
):
    proc = _start(tmp_path, marker='>')
    assert proc.stdin is not None and proc.stdout is not None
    data = b'1 2\n\n  3\nlast'
    proc.stdin.write(data)
    assert _finish(proc) == data

    assert (tmp_path / 'extra').read_bytes() == data
    assert (tmp_path / 'merged').read_bytes() == b'>1 2\n>\n>  3\n>last'


def test_a_line_split_across_chunks_is_captured_whole(tmp_path: pathlib.Path):
    proc = _start(tmp_path)
    assert proc.stdin is not None and proc.stdout is not None

    proc.stdin.write(b'12')
    assert _read_within(proc.stdout.fileno(), 2) == b'12'
    # Nothing of an unfinished line is in the merged capture yet, so another
    # tee appending there cannot land in the middle of it.
    assert (tmp_path / 'merged').read_bytes() == b''

    proc.stdin.write(b'34\n5')
    assert _read_within(proc.stdout.fileno(), 4) == b'34\n5'
    assert (tmp_path / 'merged').read_bytes() == b'<1234\n'

    assert _finish(proc) == b''
    assert (tmp_path / 'merged').read_bytes() == b'<1234\n<5'


def test_copies_megabytes_unchanged(tmp_path: pathlib.Path):
    lines = [f'{i} {i * 7}\n'.encode() for i in range(200_000)]
    data = b''.join(lines)
    proc = _start(tmp_path)
    out, _ = proc.communicate(data, timeout=30)
    assert proc.returncode == 0

    assert out == data
    assert (tmp_path / 'extra').read_bytes() == data
    assert (tmp_path / 'merged').read_bytes() == b''.join(b'<' + x for x in lines)


def test_exits_quietly_when_the_peer_is_gone(tmp_path: pathlib.Path):
    proc = _start(tmp_path)
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdout.close()

    proc.stdin.write(b'hello\n')
    proc.stdin.close()
    assert proc.wait(timeout=10) == 0
    # No traceback leaks into the merged capture, only what was written.
    assert (tmp_path / 'merged').read_bytes() == b'<hello\n'


@pytest.mark.parametrize('value', ['char', 'chunk'])
def test_char_tee_mode_reads_back_as_chunk(value: str):
    assert CommunicationParams(tee_mode=value).tee_mode == 'chunk'  # type: ignore[arg-type]
    assert SandboxParams(tee_mode=value).tee_mode == 'chunk'  # type: ignore[arg-type]
    assert (
        SandboxParams.model_validate_json(f'{{"tee_mode": "{value}"}}').tee_mode
        == 'chunk'
    )
