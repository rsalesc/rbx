"""The recording engine: runs commands on a pty and builds an asciicast.

Why this exists rather than driving an external recorder: every off-the-shelf
tool either cannot emit asciicast (VHS) or detects command completion by
matching a shell prompt in the output stream. Prompt matching is fragile
against `rbx`'s Rich progress rendering, and the one tool that does it well
(autocast) hangs on modern macOS.

So we do not use a persistent shell at all. Each instruction is spawned as its
own process on its own pty, and *EOF is the completion signal* -- unambiguous,
no pattern matching, nothing to tune. The prompt and the typing animation are
synthesized directly into the cast timeline, which means the recorded output
contains exactly the command's own output and nothing else.

Consequence worth knowing: shell state does not persist between instructions.
Every instruction runs in the same working directory with the same environment,
so a `cd` inside a recording affects only that instruction.
"""

import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import termios
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from scripts.casts.spec import RecordingSpec, Tagged

# rbx warns loudly when the stack limit is low, and tells the user to raise it
# from their shell rc. Instructions run via `sh -c`, which sources no rc, so
# without this every cast would open with that warning. The value is the one
# rbx itself recommends.
STACK_PREAMBLE = 'ulimit -s 65520 2>/dev/null || true; '

# Inherited variables that would silently change what a cast shows.
_DROPPED_ENV = frozenset({'NO_COLOR', 'FORCE_COLOR', 'CLICOLOR', 'CLICOLOR_FORCE'})

# Time between polls of the pty while a command runs.
_POLL_SECONDS = 0.02
# Pause inserted after a command's output, before the next prompt.
_AFTER_COMMAND_SECONDS = 0.6

_DURATION = re.compile(r'^(\d+(?:\.\d+)?)\s*(us|ms|s)$')
_CONTROL = re.compile(r'^\^([A-Za-z@\[\]\\^_])$')


class RecordingError(RuntimeError):
    pass


def parse_duration(value: str) -> float:
    """Parse autocast's duration grammar (``1s``, ``150ms``, ``900us``)."""
    match = _DURATION.match(str(value).strip())
    if match is None:
        raise ValueError(f'invalid duration: {value!r} (expected e.g. 1s, 150ms)')
    amount = float(match.group(1))
    return amount * {'us': 1e-6, 'ms': 1e-3, 's': 1.0}[match.group(2)]


def key_bytes(key: str) -> bytes:
    """Translate one key from an `!Interactive` block into bytes.

    Accepts a literal character, or a caret-escaped control code such as
    ``^C`` (which becomes 0x03).
    """
    control = _CONTROL.match(key)
    if control:
        char = control.group(1).upper()
        return bytes([ord(char) ^ 0x40])
    return key.encode()


def build_env(
    spec: RecordingSpec, home: str, base: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """The recording environment: inherited, then pinned where it matters.

    A fully synthetic environment is tempting but breaks real work -- dropping
    TMPDIR and the platform toolchain variables makes the C++ compiler fail, so
    a recording of `rbx run` would show nothing but compile errors.

    So we inherit, then remove what could change the recording invisibly
    (`RBX_*` overrides, an ambient NO_COLOR) and pin what must be identical
    every time: HOME, terminal size, locale and timezone.
    """
    env = dict(os.environ if base is None else base)
    for name in list(env):
        if name.startswith('RBX_') or name in _DROPPED_ENV:
            del env[name]

    env.update(
        {
            'HOME': home,
            'TERM': 'xterm-256color',
            'COLUMNS': str(spec.width),
            'LINES': str(spec.height),
            'LC_ALL': 'C.UTF-8',
            'LANG': 'C.UTF-8',
            'TZ': 'UTC',
            # Rich checks this; forcing it keeps colour stable regardless of how
            # the recording itself was invoked.
            'FORCE_COLOR': '1',
        }
    )
    return env


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))


class _Session:
    """One command running on its own pty."""

    def __init__(
        self, command: str, cwd: str, env: Dict[str, str], rows: int, cols: int
    ):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # pragma: no cover - child process never returns
            try:
                _set_winsize(0, rows, cols)
                os.chdir(cwd)
                os.execve('/bin/sh', ['sh', '-c', STACK_PREAMBLE + command], env)
            except BaseException:
                os._exit(127)
        _set_winsize(self.fd, rows, cols)

    def read_available(self, timeout: float) -> bytes:
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout)
        except (OSError, ValueError):
            return b''
        if not ready:
            return b''
        try:
            return os.read(self.fd, 65536)
        except OSError:
            return b''

    def write(self, data: bytes) -> None:
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def finished(self) -> bool:
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            return True
        return pid == self.pid

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.waitpid(self.pid, 0)
        except (ChildProcessError, OSError):
            pass


class CastBuilder:
    """Accumulates asciicast v2 events on a virtual timeline."""

    def __init__(self, width: int, height: int, title: Optional[str] = None):
        self.width = width
        self.height = height
        self.title = title
        self.clock = 0.0
        self.events: List[Tuple[float, str, str]] = []

    def advance(self, seconds: float) -> None:
        self.clock += seconds

    def output(self, data: str) -> None:
        if data:
            self.events.append((round(self.clock, 6), 'o', data))

    def marker(self, label: str) -> None:
        self.events.append((round(self.clock, 6), 'm', label))

    def hold(self, seconds: float) -> None:
        """Extend the cast without changing what is on screen.

        A player takes the cast's duration from its last event, so advancing
        the clock alone is invisible -- the recording would still end, and
        loop, at the last byte of output. Emitting a zero-byte output event
        at the later timestamp is what actually holds the final frame.
        """
        if seconds <= 0:
            return
        self.advance(seconds)
        self.events.append((round(self.clock, 6), 'o', ''))

    def to_text(self) -> str:
        header: Dict[str, Any] = {
            'version': 2,
            'width': self.width,
            'height': self.height,
            'env': {'TERM': 'xterm-256color', 'SHELL': '/bin/sh'},
        }
        if self.title is not None:
            header['title'] = self.title
        lines = [json.dumps(header, sort_keys=True)]
        lines.extend(json.dumps(list(event)) for event in self.events)
        return '\n'.join(lines) + '\n'


class Engine:
    def __init__(self, spec: RecordingSpec, workdir: str, home: str):
        self.spec = spec
        self.workdir = workdir
        self.env = build_env(spec, home)
        self.type_speed = parse_duration(spec.type_speed)
        self.timeout = parse_duration(spec.timeout)
        self.cast = CastBuilder(spec.width, spec.height, spec.title)

    # -- rendering -------------------------------------------------------

    def _type_command(self, command: str) -> None:
        self.cast.output('$ ')
        for char in command:
            self.cast.advance(self.type_speed)
            self.cast.output(char)
        self.cast.advance(self.type_speed)
        self.cast.output('\r\n')

    # -- running ---------------------------------------------------------

    def _drain(
        self,
        session: _Session,
        capture: bool,
        keys: Sequence[str] = (),
    ) -> None:
        """Pump one command to completion, recording output as it arrives."""
        started = time.monotonic()
        pending = list(keys)
        next_key_at = started + self.type_speed
        tick = started

        def emit(data: bytes) -> None:
            if capture:
                self.cast.output(data.decode('utf-8', errors='replace'))

        def sync() -> None:
            """Move the cast clock forward by the real time that just passed.

            Advancing by a fixed amount per iteration would be wrong: at EOF
            the pty read returns immediately, so the loop can spin thousands
            of times per real second and the cast would claim a duration of
            hours.
            """
            nonlocal tick
            moment = time.monotonic()
            self.cast.advance(moment - tick)
            tick = moment

        while True:
            now = time.monotonic()
            if now - started > self.timeout:
                session.close()
                raise RecordingError(
                    f'recording `{self.spec.name}` timed out after '
                    f'{self.timeout:g}s. Raise `timeout` in the spec, or check '
                    f'that the command exits on its own.'
                )

            if pending and now >= next_key_at:
                key = pending.pop(0)
                try:
                    wait = parse_duration(key)
                except ValueError:
                    session.write(key_bytes(key))
                    next_key_at = now + self.type_speed
                else:
                    next_key_at = now + wait

            chunk = session.read_available(_POLL_SECONDS)
            sync()
            if chunk:
                emit(chunk)
                continue

            if session.finished() and not pending:
                # The child is gone; flush whatever the pty still holds.
                while True:
                    leftover = session.read_available(0)
                    if not leftover:
                        break
                    emit(leftover)
                break

            # At EOF the read above returns instantly, so without this the
            # loop would burn CPU while waiting out the remaining keys.
            time.sleep(_POLL_SECONDS)

        session.close()

    def _run(self, command: str, capture: bool, keys: Sequence[str] = ()) -> None:
        session = _Session(
            command,
            cwd=self.workdir,
            env=self.env,
            rows=self.spec.height,
            cols=self.spec.width,
        )
        self._drain(session, capture=capture, keys=keys)

    # -- instruction dispatch --------------------------------------------

    def _instruction(self, instruction: Any) -> None:
        if isinstance(instruction, str):
            self._command(instruction, hidden=False)
            return
        if not isinstance(instruction, Tagged):
            raise RecordingError(f'unsupported instruction: {instruction!r}')

        tag, value = instruction.tag, instruction.value
        if tag == 'Command':
            if isinstance(value, str):
                self._command(value, hidden=False)
            else:
                self._command(value['command'], hidden=bool(value.get('hidden')))
        elif tag == 'Interactive':
            self._command(
                value['command'], hidden=False, keys=[str(k) for k in value['keys']]
            )
        elif tag == 'Wait':
            self.cast.advance(parse_duration(value))
        elif tag == 'Marker':
            self.cast.marker(str(value))
        elif tag == 'Clear':
            self.cast.output('\x1b[H\x1b[2J\x1b[3J')
        else:
            raise RecordingError(f'unknown instruction tag: !{tag}')

    def _command(self, command: str, hidden: bool, keys: Sequence[str] = ()) -> None:
        if hidden:
            # Setup work still runs for real; it just is not shown.
            clock = self.cast.clock
            self._run(command, capture=False)
            self.cast.clock = clock
            return
        self._type_command(command)
        self._run(command, capture=True, keys=keys)
        self.cast.advance(_AFTER_COMMAND_SECONDS)

    def run(self) -> str:
        for command in self.spec.setup:
            self._command(command, hidden=True)
        for instruction in self.spec.instructions:
            self._instruction(instruction)
        self.cast.hold(parse_duration(self.spec.end_pause))
        return self.cast.to_text()


def run_recording(spec: RecordingSpec, workdir: str, home: str) -> str:
    return Engine(spec, workdir, home).run()
