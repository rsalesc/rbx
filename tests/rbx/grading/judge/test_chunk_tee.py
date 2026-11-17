import importlib.resources
import os
import pathlib
import select
import subprocess
import sys
import threading
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
    # The clean copy is verbatim; the shared capture ends every record.
    assert (tmp_path / 'merged').read_bytes() == b'>1 2\n>\n>  3\n>last\n'


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
    assert (tmp_path / 'merged').read_bytes() == b'<1234\n<5\n'


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


def _start_routes(
    tmp_path: pathlib.Path, routes, line: bool = False
) -> subprocess.Popen:
    """`routes`: (marker, read fd, write fd or None, extra file name)."""
    command = [sys.executable, '-S', str(TEE)]
    if line:
        command.append('--line')
    command.append('--routes')
    fds = []
    for marker, src, dst, extra in routes:
        command += [
            marker,
            str(src),
            '-' if dst is None else str(dst),
            str(tmp_path / extra),
        ]
        fds += [src] if dst is None else [src, dst]
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=(tmp_path / 'merged').open('wb'),
        pass_fds=fds,
    )


def test_routes_forward_every_pipe_and_tag_whole_capture_lines(
    tmp_path: pathlib.Path,
):
    # Two channels to peers, as for two processes of a fanout run, and one
    # stderr route with no peer.
    to_r, to_tee = os.pipe()
    from_tee, to_peer = os.pipe()
    up_r, up_tee = os.pipe()
    up_from_tee, up_peer = os.pipe()
    err_r, err_w = os.pipe()
    proc = _start_routes(
        tmp_path,
        [
            ('[0]<', to_r, to_peer, 'to0'),
            ('[1]>', up_r, up_peer, 'from1'),
            ('[1]!', err_r, None, 'err1'),
        ],
    )
    # The tee holds its own copies now.
    for fd in (to_r, to_peer, up_r, up_peer, err_r):
        os.close(fd)

    # Partial lines on several routes at once still reach each peer right away.
    os.write(to_tee, b'5 ')
    os.write(up_tee, b'ans')
    os.write(err_w, b'debug ')
    assert _read_within(from_tee, 2) == b'5 '
    assert _read_within(up_from_tee, 3) == b'ans'

    os.write(to_tee, b'6\n7\n')
    os.write(up_tee, b'wer\n')
    os.write(err_w, b'line\nunterminated')
    assert _read_within(from_tee, 4) == b'6\n7\n'
    assert _read_within(up_from_tee, 4) == b'wer\n'

    for fd in (to_tee, up_tee, err_w):
        os.close(fd)
    assert _read_within(from_tee, 1) == b''
    assert _read_within(up_from_tee, 1) == b''
    assert proc.wait(timeout=10) == 0
    os.close(from_tee)
    os.close(up_from_tee)

    assert (tmp_path / 'to0').read_bytes() == b'5 6\n7\n'
    assert (tmp_path / 'from1').read_bytes() == b'answer\n'
    assert (tmp_path / 'err1').read_bytes() == b'debug line\nunterminated'
    lines = (tmp_path / 'merged').read_bytes().split(b'\n')
    # Every record is whole and newline-terminated, the last one included.
    assert lines[-1] == b''
    assert sorted(lines[:-1]) == sorted(
        [b'[0]<5 6', b'[0]<7', b'[1]>answer', b'[1]!debug line', b'[1]!unterminated']
    )
    # Each route's lines keep their order.
    assert [x for x in lines if x.startswith(b'[0]<')] == [b'[0]<5 6', b'[0]<7']
    assert [x for x in lines if x.startswith(b'[1]!')] == [
        b'[1]!debug line',
        b'[1]!unterminated',
    ]


def test_routes_log_a_reply_after_the_line_it_answers(tmp_path: pathlib.Path):
    to_r, to_tee = os.pipe()
    from_tee, to_peer = os.pipe()
    up_r, up_tee = os.pipe()
    up_from_tee, up_peer = os.pipe()
    proc = _start_routes(
        tmp_path,
        [('[0]<', to_r, to_peer, 'a'), ('[0]>', up_r, up_peer, 'b')],
    )
    for fd in (to_r, to_peer, up_r, up_peer):
        os.close(fd)

    for i in range(50):
        os.write(to_tee, b'%d\n' % i)
        # The reply is written only once the query went through the tee.
        assert _read_within(from_tee, len(b'%d\n' % i)) == b'%d\n' % i
        os.write(up_tee, b'%d\n' % (i + 1))
        assert _read_within(up_from_tee, len(b'%d\n' % (i + 1))) == b'%d\n' % (i + 1)

    for fd in (to_tee, up_tee):
        os.close(fd)
    assert proc.wait(timeout=10) == 0
    os.close(from_tee)
    os.close(up_from_tee)

    expected = b''.join(b'[0]<%d\n[0]>%d\n' % (i, i + 1) for i in range(50))
    assert (tmp_path / 'merged').read_bytes() == expected


def test_line_mode_routes_forward_whole_lines_only(tmp_path: pathlib.Path):
    to_r, to_tee = os.pipe()
    from_tee, to_peer = os.pipe()
    proc = _start_routes(tmp_path, [('<', to_r, to_peer, 'a')], line=True)
    os.close(to_r)
    os.close(to_peer)

    os.write(to_tee, b'12')
    assert _read_within(from_tee, 2, timeout=0.5) == b''
    os.write(to_tee, b'3\n')
    assert _read_within(from_tee, 4) == b'123\n'

    os.close(to_tee)
    assert proc.wait(timeout=10) == 0
    os.close(from_tee)
    assert (tmp_path / 'merged').read_bytes() == b'<123\n'


@pytest.mark.parametrize('line', [False, True], ids=['chunk', 'line'])
def test_a_long_line_costs_linear_time(tmp_path: pathlib.Path, line: bool):
    # 64 MiB with no newline until the end: searching the whole held line on
    # every read took ~13 s here, against ~0.1 s for one pass.
    data = b'1 ' * (32 * 1024 * 1024) + b'\n'
    to_r, to_tee = os.pipe()
    from_tee, to_peer = os.pipe()
    proc = _start_routes(tmp_path, [('>', to_r, to_peer, 'extra')], line=line)
    os.close(to_r)
    os.close(to_peer)
    received = []

    def peer() -> None:
        while chunk := os.read(from_tee, 1 << 20):
            received.append(len(chunk))

    reader = threading.Thread(target=peer)
    reader.start()
    start = time.monotonic()
    view = memoryview(data)
    while view:
        view = view[os.write(to_tee, view) :]
    os.close(to_tee)
    assert proc.wait(timeout=60) == 0
    elapsed = time.monotonic() - start
    reader.join()
    os.close(from_tee)

    assert sum(received) == len(data)
    assert (tmp_path / 'merged').stat().st_size == len(data) + 1
    assert elapsed < 5, f'{elapsed:.1f} s for one 64 MiB line'


def test_a_peer_gone_mid_line_captures_each_line_once(tmp_path: pathlib.Path):
    to_r, to_tee = os.pipe()
    from_tee, to_peer = os.pipe()
    proc = _start_routes(tmp_path, [('>', to_r, to_peer, 'extra')])
    os.close(to_r)
    os.close(to_peer)

    os.write(to_tee, b'abc')
    # Through the tee, so `abc` is its held tail when the peer goes.
    assert _read_within(from_tee, 3) == b'abc'
    os.close(from_tee)
    # One write, so one read: its forward is the one that finds the peer gone.
    try:
        os.write(to_tee, b'def\nxyz')
    except BrokenPipeError:
        pass
    os.close(to_tee)
    assert proc.wait(timeout=10) == 0

    assert (tmp_path / 'merged').read_bytes() == b'>abcdef\n>xyz\n'
    assert (tmp_path / 'extra').read_bytes() == b'abcdef\nxyz'
