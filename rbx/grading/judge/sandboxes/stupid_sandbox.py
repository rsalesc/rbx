from __future__ import annotations

import contextlib
import ctypes
import dataclasses
import errno
import fcntl
import functools
import importlib.resources
import logging
import os
import pathlib
import resource
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import typing
from typing import Dict, Hashable, Iterator, List, Optional, Tuple

from rbx import utils
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.program import (
    FileLike,
    Program,
    ProgramCode,
    ProgramError,
    ProgramIO,
    ProgramParams,
    ProgramResult,
)
from rbx.grading.judge.sandbox import (
    CommunicationParams,
    SandboxBase,
    SandboxLog,
    SandboxParams,
)

logger = logging.getLogger(__name__)

BUFFER_SIZE_BYTES = 1024 * 1024
DRAIN_CHUNK_BYTES = 64 * 1024
DRAIN_GRACE_SECONDS = 1.0


def _drain(pipe: typing.IO[bytes]) -> None:
    """Read `pipe` to EOF, discarding what comes out, then close it."""
    try:
        while os.read(pipe.fileno(), DRAIN_CHUNK_BYTES):
            pass
    except OSError:
        pass
    finally:
        pipe.close()


def _make_pipe(sized: bool = True) -> Tuple[typing.IO[bytes], typing.IO[bytes]]:
    """A pipe as two unbuffered file objects (read end, write end).

    File objects, never bare fds: a `Program` closes what it was given more than
    once, and a second `os.close` could hit an unrelated fd that reused the
    number. `sized` makes it as large as the pipes `subprocess` makes (Linux
    only) -- which a fanout run must not ask for: its 4-8 pipes per process
    would soon exceed the user's `pipe-user-pages-soft`, past which Linux hands
    every new pipe, this run's and any other's, a single page.
    """
    read_fd, write_fd = os.pipe()
    if sized and BUFFER_SIZE_BYTES > 0 and hasattr(fcntl, 'F_SETPIPE_SZ'):
        try:
            fcntl.fcntl(write_fd, fcntl.F_SETPIPE_SZ, BUFFER_SIZE_BYTES)
        except OSError:
            pass
    return open(read_fd, 'rb', buffering=0), open(write_fd, 'wb', buffering=0)


@dataclasses.dataclass
class _Channel:
    """The pipes between the interactor and one contestant process.

    One pipe each way, or, with a capture tee, two each way with the tee in the
    middle. Every end is ours until handed to the program that owns it.
    """

    interactor_reads: typing.IO[bytes]
    interactor_writes: typing.IO[bytes]
    process_reads: typing.IO[bytes]
    process_writes: typing.IO[bytes]
    # (reads, writes) of the tee on each direction, when teeing.
    tee_to_process: Optional[Tuple[typing.IO[bytes], typing.IO[bytes]]] = None
    tee_to_interactor: Optional[Tuple[typing.IO[bytes], typing.IO[bytes]]] = None

    def close(self) -> None:
        for end in (
            self.interactor_reads,
            self.interactor_writes,
            self.process_reads,
            self.process_writes,
            *(self.tee_to_process or ()),
            *(self.tee_to_interactor or ()),
        ):
            end.close()

    @staticmethod
    def open(teed: bool, sized: bool) -> '_Channel':
        if not teed:
            to_r, to_w = _make_pipe(sized)
            from_r, from_w = _make_pipe(sized)
            return _Channel(from_r, to_w, to_r, from_w)
        i2t_r, i2t_w = _make_pipe(sized)
        t2p_r, t2p_w = _make_pipe(sized)
        p2t_r, p2t_w = _make_pipe(sized)
        t2i_r, t2i_w = _make_pipe(sized)
        return _Channel(
            interactor_reads=t2i_r,
            interactor_writes=i2t_w,
            process_reads=t2p_r,
            process_writes=p2t_w,
            tee_to_process=(i2t_r, t2p_w),
            tee_to_interactor=(p2t_r, t2i_w),
        )


@dataclasses.dataclass
class _TeeRoute:
    """A pipe the capture tee copies: what it reads, into what (None: no peer),
    the clean copy it keeps (None: none) and how it marks it in the capture."""

    marker: str
    reads: typing.IO[bytes]
    writes: Optional[typing.IO[bytes]]
    extra: Optional[pathlib.Path]


# An upper bound on the descriptors a run holds at once per contestant process:
# its channel's pipes (eight when teed), the copy of its stdin, its stderr pipe
# and file, and the tee's clean copy of each of its three routes.
_FILES_PER_PROCESS = 16
# Slack on top of what is open already, for other threads' files.
_FILES_MARGIN = 32


def _ensure_open_files(needed: int) -> None:
    """Raise the soft limit on open files if `needed` more might not fit.

    A fanout run opens every channel before the interactor starts, which at 64
    processes is more than macOS's default soft limit of 256. A single process
    (an interactive problem) needs a handful, so the limit stays as it was.
    """
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        wanted = utils.get_open_fds() + needed + _FILES_MARGIN
        if soft == resource.RLIM_INFINITY or soft >= wanted:
            return
        if hard != resource.RLIM_INFINITY:
            wanted = min(wanted, hard)
        if wanted > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (wanted, hard))
    except (ValueError, OSError):
        pass


# `pidfd_open`'s number on every architecture rbx runs on (Linux 5.3+).
_SYS_PIDFD_OPEN = 434


def _pidfd_open(pid: int) -> int:
    """A pidfd for `pid`: readable once it has exited.

    `os.pidfd_open` is missing from some Python builds -- the standalone CPython
    the Docker image runs, for one -- so the system call is made directly then.
    """
    if hasattr(os, 'pidfd_open'):
        return os.pidfd_open(pid)
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.syscall(_SYS_PIDFD_OPEN, pid, 0)
    if fd < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return fd


@functools.cache
def _has_pidfds() -> bool:
    if sys.platform != 'linux' or not hasattr(select, 'epoll'):
        return False
    try:
        os.close(_pidfd_open(os.getpid()))
    except (OSError, AttributeError):
        return False
    return True


# What `_ExitOrder`'s own wake-up pipe is watched as.
_WAKE = object()


class _ExitOrder:
    """The order in which the interactor and the processes stopped, as the
    kernel saw it.

    Reaping is no clock: by the time `wait4` returns, several programs may have
    exited, and they come back in whatever order the kernel lists children. A
    kernel event queue -- kqueue on macOS, epoll over pidfds on Linux -- queues
    each event when it happens, so it gives the true order however late (or
    loaded) the reaper was. It is read as the run goes (`start`), not at the end,
    since epoll forgets some watches early.

    The interactor counts as stopped when it *starts* to exit: its exit closes
    its pipes, and a process woken by that EOF can finish exiting before the
    interactor does. So the interactor also holds the only write ends of
    liveness pipes nobody writes to (`watch_eof`), which its exit closes before
    the pipes it talks over -- one below them and one above, since kernels close
    an exiting process's descriptors in ascending order (older Linux) or in
    descending order (measured: macOS, and Linux 6 too).

    A process, likewise, counts as stopped when its stdout loses its last
    writer (`watch_hangup`): that is the moment the interactor can see it go,
    and a busy kernel can take long enough to finish its exit that the
    interactor, woken by the EOF, starts exiting first (measured in Docker at 48
    processes and up; never on macOS).
    """

    def __init__(self) -> None:
        self._kqueue = select.kqueue() if hasattr(select, 'kqueue') else None
        self._epoll = select.epoll() if self._kqueue is None and _has_pidfds() else None
        # What each queued event is about, by (filter, ident) for kqueue (a pid
        # and an fd may share a number) and by fd for epoll.
        self._keys: Dict[Tuple[int, int], Hashable] = {}
        # Descriptors this object opened, closed with it.
        self._own_fds: List[int] = []
        self._order: List[Hashable] = []
        self._follower: Optional[threading.Thread] = None
        self._wake: Optional[int] = None
        self._stopped = False

    @property
    def available(self) -> bool:
        return self._kqueue is not None or self._epoll is not None

    def _saw(self, key: Hashable) -> None:
        if key is _WAKE:
            self._stopped = True
        elif key not in self._order:
            self._order.append(key)

    def _take(self, events) -> None:
        assert self._kqueue is not None
        for event in events:
            key = self._keys.get((event.filter, event.ident))
            if key is None:
                continue
            if event.flags & select.KQ_EV_ERROR:
                # Registering on a process that already exited (a zombie) is
                # refused with ESRCH: it stopped before anything watched since.
                if event.filter == select.KQ_FILTER_PROC and event.data == errno.ESRCH:
                    self._saw(key)
                continue
            self._saw(key)

    def watch_exit(self, key: Hashable, pid: int) -> None:
        if self._kqueue is not None:
            self._keys[(select.KQ_FILTER_PROC, pid)] = key
            # Whatever is queued already happened first.
            self.collect()
            self._take(
                self._kqueue.control(
                    [
                        select.kevent(
                            pid,
                            select.KQ_FILTER_PROC,
                            select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                            select.KQ_NOTE_EXIT,
                        )
                    ],
                    1,
                    0,
                )
            )
        elif self._epoll is not None:
            # A pidfd of a process that already exited is readable at once.
            pidfd = _pidfd_open(pid)
            self._own_fds.append(pidfd)
            self._register(pidfd, select.EPOLLIN, key)

    def _register(self, fd: int, mask: int, key: Hashable) -> None:
        assert self._epoll is not None
        if (0, fd) in self._keys:
            # A descriptor watched and closed since (`watch_hangup`) left its
            # number behind; epoll names events by number, so take a fresh one.
            fd = fcntl.fcntl(fd, fcntl.F_DUPFD, max(f for _, f in self._keys) + 1)
            os.set_inheritable(fd, False)
            self._own_fds.append(fd)
        self._keys[(0, fd)] = key
        # One event each, and never unregistered: a watched descriptor may be
        # closed already.
        self._epoll.register(fd, mask | select.EPOLLONESHOT)

    def watch_eof(self, key: Hashable, read_end: typing.IO[bytes]) -> None:
        """`key` stopped when `read_end` sees EOF. Nothing must write to it."""
        fd = read_end.fileno()
        if self._kqueue is not None:
            self._keys[(select.KQ_FILTER_READ, fd)] = key
            self.collect()
            self._take(
                self._kqueue.control(
                    [
                        select.kevent(
                            fd,
                            select.KQ_FILTER_READ,
                            select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                        )
                    ],
                    1,
                    0,
                )
            )
        elif self._epoll is not None:
            self._register(fd, select.EPOLLIN, key)

    def watch_hangup(self, key: Hashable, read_end: typing.IO[bytes]) -> None:
        """`key` stopped when the last writer of `read_end`'s pipe closes it.

        The caller closes its `read_end` right after: epoll keeps the watch for
        as long as another holder of that read end (the interactor, a tee) has
        it, and holding one ourselves would spare the writer the SIGPIPE it gets
        once that holder is gone. Linux only -- kqueue drops a watch with its
        descriptor, and macOS orders these exits right without (measured).
        """
        if self._epoll is not None:
            # The hangup only, never the data passing through. (Named, not
            # implied by an empty mask: with only EPOLLONESHOT, epoll counts the
            # watch as disabled.)
            self._register(read_end.fileno(), select.EPOLLHUP, key)

    def _read(self, timeout: Optional[float]) -> bool:
        """Record one batch of events, waiting up to `timeout` (`None`: as long
        as it takes) for it. Whether there was any."""
        if self._kqueue is not None:
            events = self._kqueue.control(None, 64, timeout)
            self._take(events)
            return bool(events)
        if self._epoll is not None:
            events = self._epoll.poll(-1 if timeout is None else timeout)
            for fd, _ in events:
                key = self._keys.get((0, fd))
                if key is not None:
                    self._saw(key)
            return bool(events)
        return False

    def collect(self) -> None:
        """Read every event queued so far, in the order they happened."""
        while self._read(0):
            pass

    def start(self) -> None:
        """Keep reading events as they happen, until `ranks`.

        Not just at the end: epoll drops a hangup watch -- its queued event
        too -- once the last holder of the watched read end closes it, which
        the interactor does when it exits, long before the run is over.
        Nothing may be watched from here on.
        """
        if not self.available:
            return
        self.collect()
        wake_read, self._wake = os.pipe()
        self._own_fds += [wake_read, self._wake]
        if self._kqueue is not None:
            self._keys[(select.KQ_FILTER_READ, wake_read)] = _WAKE
            self._kqueue.control(
                # One-shot like every watch here: the byte waking it is never
                # read, so a level-triggered watch would fire forever.
                [
                    select.kevent(
                        wake_read,
                        select.KQ_FILTER_READ,
                        select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                    )
                ],
                0,
                0,
            )
        else:
            self._register(wake_read, select.EPOLLIN, _WAKE)
        self._follower = threading.Thread(target=self._follow, daemon=True)
        self._follower.start()

    def _follow(self) -> None:
        while not self._stopped:
            self._read(None)

    def _stop(self) -> None:
        if self._follower is not None:
            assert self._wake is not None
            os.write(self._wake, b'.')
            self._follower.join()
            self._follower = None

    def ranks(self) -> Optional[Dict[Hashable, int]]:
        """Each watched key's place in the order, or `None` if any is missing."""
        if not self.available:
            return None
        self._stop()
        self.collect()
        watched = set(self._keys.values()) - {_WAKE}
        if not watched.issubset(self._order):
            return None
        return {key: rank for rank, key in enumerate(self._order)}

    def close(self) -> None:
        self._stop()
        for queue in (self._kqueue, self._epoll):
            if queue is not None:
                queue.close()
        for fd in self._own_fds:
            os.close(fd)
        self._own_fds = []


def _liveness_pipe(
    above: int = -1,
) -> Tuple[typing.IO[bytes], typing.IO[bytes]]:
    """A pipe whose write end is numbered above `above`, for `_ExitOrder.watch_eof`."""
    read_end, write_end = _make_pipe(sized=False)
    if write_end.fileno() > above:
        return read_end, write_end
    # F_DUPFD's copy is inheritable; it must reach only the program it is
    # handed to.
    high = fcntl.fcntl(write_end.fileno(), fcntl.F_DUPFD, above + 1)
    os.set_inheritable(high, False)
    write_end.close()
    return read_end, open(high, 'wb', buffering=0)


class StupidSandbox(SandboxBase):
    """A stupid sandbox implementation. It has very few features and
    is not secure against things like box escaping and fork
    bombs. Yet, it is very portable and has no dependencies, so it's
    very useful for testing. Using in real contests is strongly
    discouraged.

    """

    exec_num: int

    def __init__(
        self,
        file_cacher: Optional[FileCacher] = None,
        name: Optional[str] = None,
        temp_dir: Optional[pathlib.Path] = None,
        path: Optional[pathlib.Path] = None,
    ):
        """Initialization.

        For arguments documentation, see SandboxBase.__init__.

        path (Path|None): adopt this existing box directory instead of creating
            a fresh one under `temp_dir`. Used to run programs in a box another
            process prepared (see `DockerSandbox`); `reset()` still makes a new
            directory.

        """
        if not temp_dir:
            temp_dir = pathlib.Path(tempfile.gettempdir())
        SandboxBase.__init__(self, file_cacher, name, temp_dir)

        # Make box directory
        self._adopted_path = path
        self.initialize()

    def initialize(self):
        if self._adopted_path is not None:
            self._path = self._adopted_path
            self._adopted_path = None
        else:
            self._path = pathlib.Path(
                tempfile.mkdtemp(dir=str(self.temp_dir), prefix='rbx-%s-' % (self.name))
            )
        self.exec_num = -1
        self.log = None
        self.returncode = None
        self._path.mkdir(parents=True, exist_ok=True)

        logger.debug("Sandbox in `%s' created, using stupid box.", self._path)

        # Box parameters
        self.chdir = self._path

    def get_root_path(self) -> pathlib.Path:
        """Return the toplevel path of the sandbox.

        return (Path): the root path.

        """
        return self._path

    @classmethod
    def use_soft_timeout(cls) -> bool:
        """Whether the sandbox uses soft timeouts."""
        return True

    def _get_exit_status(self, result: ProgramResult) -> str:
        if ProgramCode.TE in result.program_codes:
            return SandboxBase.EXIT_TERMINATED
        if ProgramCode.WT in result.program_codes:
            return SandboxBase.EXIT_TIMEOUT_WALL
        if ProgramCode.TO in result.program_codes:
            return SandboxBase.EXIT_TIMEOUT
        if ProgramCode.OL in result.program_codes:
            return SandboxBase.EXIT_OUTPUT_LIMIT_EXCEEDED
        if ProgramCode.ML in result.program_codes:
            return SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED
        if ProgramCode.SG in result.program_codes:
            return SandboxBase.EXIT_SIGNAL
        if ProgramCode.RE in result.program_codes:
            return SandboxBase.EXIT_NONZERO_RETURN
        return SandboxBase.EXIT_OK

    def _get_io(self, params: SandboxParams, pipe_io: bool = False) -> ProgramIO:
        io = ProgramIO()
        if params.stdin_file and not pipe_io:
            io.input = self.relative_path(params.stdin_file)
        if params.stdout_file and not pipe_io:
            io.output = self.relative_path(params.stdout_file)
        if params.stderr_file:
            io.stderr = self.relative_path(params.stderr_file)
        return io

    def _get_program_params(self, params: SandboxParams) -> ProgramParams:
        return ProgramParams(
            chdir=self.chdir,
            time_limit=params.timeout / 1000 if params.timeout else None,
            wall_time_limit=params.wallclock_timeout / 1000
            if params.wallclock_timeout
            else None,
            memory_limit=params.address_space,
            stack_limit=params.stack_space,
            fs_limit=params.fsize,
            env=params.set_env,
            io=self._get_io(params),
            pipesize=BUFFER_SIZE_BYTES,
        )

    def _get_tee_program_params(
        self, io: ProgramIO, pgid: Optional[int], sized_pipes: bool = True
    ) -> ProgramParams:
        return ProgramParams(
            chdir=self.chdir,
            time_limit=None,
            wall_time_limit=None,
            memory_limit=None,
            io=io,
            pgid=pgid,
            pipesize=BUFFER_SIZE_BYTES if sized_pipes else -1,
            rlimits=False,
        )

    def _get_sandbox_log(
        self, result: ProgramResult, params: SandboxParams
    ) -> SandboxLog:
        return SandboxLog(
            params=params.model_copy(deep=True),
            execution_time=result.cpu_time,
            wall_time=result.wall_time,
            memory_used=result.memory_used,
            exitcode=result.exitcode,
            exitstatus=self._get_exit_status(result),
            killing_signal=result.killing_signal,
            other_logs={
                'program_codes': [code.value for code in result.program_codes],
                'alarm_msg': result.alarm_msg,
                'wall_time': result.wall_time,
            },
        )

    def _needs_teeing(
        self,
        params: SandboxParams,
        interactor_params: SandboxParams,
        merged_capture: Optional[pathlib.Path] = None,
        fanout: bool = False,
    ) -> bool:
        if merged_capture is not None:
            return True
        # The clean copies (`.pin`/`.pout`) are written for one process only.
        return not fanout and (
            params.stdout_file is not None or interactor_params.stdout_file is not None
        )

    def _get_tee_script(self, name: str) -> List[str]:
        with importlib.resources.as_file(
            importlib.resources.files('rbx') / 'grading' / 'judge' / 'sandboxes' / name
        ) as file:
            # `-S`: a tee imports nothing but the standard library, and skipping
            # `site` saves ~1.3 ms per spawn in the Docker image.
            return [sys.executable, '-S', str(utils.abspath(file))]

    def _get_tee_command(
        self,
        char: str,
        communication_params: CommunicationParams,
        extra: Optional[str] = None,
    ) -> List[str]:
        script = (
            'line_tee.py' if communication_params.tee_mode == 'line' else 'chunk_tee.py'
        )
        return [*self._get_tee_script(script), char, extra or '/dev/null']

    def _get_tee_program(
        self,
        char: str,
        stdin: FileLike,
        stdout: FileLike,
        communication_params: CommunicationParams,
        pgid: Optional[int],
        capture: Optional[pathlib.Path] = None,
    ) -> Program:
        io = ProgramIO(input=stdin, output=stdout, stderr=subprocess.DEVNULL)
        if communication_params.merged_capture:
            io.stderr = self.relative_path(communication_params.merged_capture).open(
                'ab'
            )
        return Program(
            self._get_tee_command(
                char,
                communication_params,
                str(self.relative_path(capture)) if capture else None,
            ),
            self._get_tee_program_params(
                io, pgid, sized_pipes=communication_params.processes == 1
            ),
        )

    def _get_capture_tee(
        self,
        routes: List[_TeeRoute],
        communication_params: CommunicationParams,
        pgid: Optional[int],
    ) -> Program:
        """The one tee of a communication run, copying every route at once (see
        `chunk_tee.py`): each tee is one more process a message wakes on its
        way."""
        command = self._get_tee_script('chunk_tee.py')
        if communication_params.tee_mode == 'line':
            command.append('--line')
        command.append('--routes')
        fds: List[int] = []
        for route in routes:
            command += [
                route.marker,
                str(route.reads.fileno()),
                '-' if route.writes is None else str(route.writes.fileno()),
                str(self.relative_path(route.extra)) if route.extra else '/dev/null',
            ]
            fds.append(route.reads.fileno())
            if route.writes is not None:
                fds.append(route.writes.fileno())
        io = ProgramIO(
            input=subprocess.DEVNULL,
            output=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if communication_params.merged_capture:
            io.stderr = self.relative_path(communication_params.merged_capture).open(
                'ab'
            )
        params = self._get_tee_program_params(io, pgid, sized_pipes=False)
        params.pass_fds = tuple(fds)
        return Program(command, params)

    @contextlib.contextmanager
    def _local_capture(
        self, merged_capture: Optional[pathlib.Path]
    ) -> Iterator[Optional[pathlib.Path]]:
        """A local file for the tees to append the merged capture to, copied
        into the box at `merged_capture` once they are all done.

        Several tees append to it at once, and only a local filesystem keeps each
        append whole: through Docker Desktop's file share (virtiofs), which the
        box lives on, concurrent `O_APPEND` writes overwrite each other --
        measured, two writers of 64 KiB blocks lost ~13% of them, and a fanout
        capture silently missed whole chunks. The temp directory is local both
        on the host and in the container (a tmpfs there).
        """
        if merged_capture is None:
            yield None
            return
        fd, scratch = tempfile.mkstemp(prefix='rbx-capture-', suffix='.pio')
        try:
            # The prefix header the '.pio' parser expects; the tees then append
            # their marked lines.
            os.write(fd, b'<\n>\n')
            os.close(fd)
            yield pathlib.Path(scratch)
            target = self.relative_path(merged_capture)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(scratch, target)
        finally:
            pathlib.Path(scratch).unlink(missing_ok=True)

    def run(self, command: List[str], params: SandboxParams) -> SandboxLog:
        self.exec_num += 1

        logger.debug(
            "Executing program in sandbox with command: `%s'.", ' '.join(command)
        )
        with open(
            self.relative_path(self.cmd_file), 'at', encoding='utf-8'
        ) as commands:
            commands.write('%s\n' % command)

        if params.merged_capture is not None:
            with self._local_capture(params.merged_capture) as capture:
                assert capture is not None
                return self._run_with_merged_capture(command, params, capture)

        program = Program(command, self._get_program_params(params))
        result = program.wait()

        return self._get_sandbox_log(result, params)

    def _run_with_merged_capture(
        self, command: List[str], params: SandboxParams, capture: pathlib.Path
    ) -> SandboxLog:
        """Run a single program, teeing its stdout ('>') and stderr ('!') into a
        merged capture file in true write order while still producing the clean
        stdout/stderr files. Used by ``rbx irun --merge-stderr`` for batch tasks.
        """
        communication_params = CommunicationParams(
            merged_capture=capture,
            tee_mode=params.tee_mode or 'line',
        )

        program_params = self._get_program_params(params)
        base_io = self._get_io(params)
        # The program's stdout/stderr are piped into the tees; its stdin still
        # comes straight from the input file (if any).
        program_params.io = ProgramIO(
            input=base_io.input,
            output=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        program = Program(command, program_params)
        assert program.pipes.output is not None
        assert program.pipes.stderr is not None

        group_id = os.getpgid(program.pid)
        stdout_tee = self._get_tee_program(
            '>',
            stdin=program.pipes.output,
            stdout=subprocess.DEVNULL,
            capture=params.stdout_file,
            pgid=group_id,
            communication_params=communication_params,
        )
        stderr_tee = self._get_tee_program(
            '!',
            stdin=program.pipes.stderr,
            stdout=subprocess.DEVNULL,
            capture=params.stderr_file,
            pgid=group_id,
            communication_params=communication_params,
        )

        result: Optional[SandboxLog] = None
        for _ in range(3):
            pid, status, ru = os.wait4(-group_id, 0)
            if pid == program.pid:
                program_result = program.process_exit(status, ru)
                result = self._get_sandbox_log(program_result, params)
                # Closing the read ends signals EOF to the tees so they finish.
                program.pipes.output.close()
                program.pipes.stderr.close()
            elif pid == stdout_tee.pid:
                stdout_tee.process_exit(status, ru)
            elif pid == stderr_tee.pid:
                stderr_tee.process_exit(status, ru)
            else:
                raise RuntimeError(f'Unknown pid: {pid}')

        for p in (program, stdout_tee, stderr_tee):
            p.close()

        assert result is not None
        return result

    def run_fanout(
        self,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
        communication_params: Optional[CommunicationParams] = None,
    ) -> Tuple[List[SandboxLog], SandboxLog]:
        communication_params = communication_params or CommunicationParams()
        self.exec_num += 1

        logger.debug(
            "Executing program in sandbox with command: `%s'.", ' '.join(command)
        )
        with open(
            self.relative_path(self.cmd_file), 'at', encoding='utf-8'
        ) as commands:
            commands.write('%s\n' % command)

        with self._local_capture(communication_params.merged_capture) as capture:
            return self._run_fanout(
                command,
                params,
                interactor_command,
                interactor_params,
                communication_params.model_copy(update={'merged_capture': capture}),
            )

    def _run_fanout(
        self,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
        communication_params: CommunicationParams,
    ) -> Tuple[List[SandboxLog], SandboxLog]:
        n = communication_params.processes
        fanout = n > 1
        # Where the tees append, not where the capture ends up (`run_fanout`).
        merged_capture = communication_params.merged_capture
        should_tee = self._needs_teeing(
            params, interactor_params, merged_capture, fanout=fanout
        )
        # Tee the processes' stderr into the merged capture (marked '!') only
        # when we already have a merged file to append to.
        should_tee_stderr = (
            should_tee
            and communication_params.tee_stderr
            and merged_capture is not None
        )

        def marker(i: int, direction: str) -> str:
            return f'[{i}]{direction}' if fanout else direction

        def stderr_path(i: int) -> Optional[pathlib.Path]:
            # Several processes write to scratch files, merged once all are done.
            if params.stderr_file is None or not fanout:
                return params.stderr_file
            return params.stderr_file.with_name(f'{params.stderr_file.name}.{i}')

        def capture_path(stdout_of: SandboxParams) -> Optional[pathlib.Path]:
            # The clean copies of the dialogue (`.pin`/`.pout`) exist for a single
            # process only: several would all write to the one file.
            return None if fanout else stdout_of.stdout_file

        _ensure_open_files(n * _FILES_PER_PROCESS)

        # Every program joins the process group of the first one started, which
        # leads it (`setpgid(0, 0)`), so one `wait4` reaps them all and one
        # `killpg` stops them all. Its pid is the group's id: asking the kernel
        # instead fails once the leader has exited.
        group_id: Optional[int] = None

        def started(program: Program, into: List[Program]) -> Program:
            nonlocal group_id
            # Recorded before anything else can fail, so the cleanup below
            # always knows it.
            into.append(program)
            if group_id is None:
                group_id = program.pid
            return program

        exit_order = _ExitOrder()
        channels: List[_Channel] = []
        tee_routes: List[_TeeRoute] = []
        stderr_writers: List[Optional[typing.IO[bytes]]] = [None] * n
        liveness: List[typing.IO[bytes]] = []
        tees: List[Program] = []
        programs: List[Program] = []
        started_interactor: List[Program] = []
        try:
            try:
                for _ in range(n):
                    channels.append(_Channel.open(should_tee, sized=not fanout))
            except OSError as e:
                if e.errno not in (errno.EMFILE, errno.ENFILE):
                    raise
                soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
                raise ProgramError(
                    f'Cannot open the pipes for {n} solution process(es): {e}. '
                    f'The open-file limit is {soft} (hard limit {hard}); raise it '
                    '(e.g. `ulimit -n`) or run fewer processes at once.'
                ) from e

            # What the capture tee copies: each channel both ways, and each
            # process's stderr when that goes into the merged capture too.
            for i, channel in enumerate(channels):
                if channel.tee_to_process is not None:
                    assert channel.tee_to_interactor is not None
                    tee_routes.append(
                        _TeeRoute(
                            marker(i, '>'),
                            *channel.tee_to_interactor,
                            extra=capture_path(params),
                        )
                    )
                    tee_routes.append(
                        _TeeRoute(
                            marker(i, '<'),
                            *channel.tee_to_process,
                            extra=capture_path(interactor_params),
                        )
                    )
                if should_tee_stderr:
                    # The tee writes the clean copy to the process's stderr file
                    # and the marked copy to the merged capture.
                    stderr_reader, stderr_writers[i] = _make_pipe(sized=not fanout)
                    tee_routes.append(
                        _TeeRoute(marker(i, '!'), stderr_reader, None, stderr_path(i))
                    )

            # The tee, then the processes, then the interactor: until it starts
            # nothing can talk, so a process that exits meanwhile quit on its
            # own, first.
            if tee_routes:
                started(
                    self._get_capture_tee(
                        tee_routes, communication_params, pgid=group_id
                    ),
                    tees,
                )
                for i, channel in enumerate(channels):
                    if channel.tee_to_interactor is not None:
                        # What the process writes reaches the interactor through
                        # the tee.
                        exit_order.watch_hangup(i, channel.tee_to_interactor[0])
                for route in tee_routes:
                    route.reads.close()
                    if route.writes is not None:
                        route.writes.close()

            for i, channel in enumerate(channels):
                program_params = self._get_program_params(params)
                program_params.io = self._get_io(params, pipe_io=True)
                # Its wall clock starts with the interactor's, below.
                program_params.defer_wall_clock = True
                if fanout:
                    # Nor any pipe `subprocess` makes for it (see `_make_pipe`):
                    # past the quota Linux refuses with EPERM, failing the spawn.
                    program_params.pipesize = -1
                # The process gets its own copy of the read end it consumes. Ours
                # stays open, so the interactor -- or the capture tee -- never
                # writes into a pipe nobody holds: a process may answer and exit
                # without reading everything the interactor still has to say,
                # and once it is gone we drain the rest (as BAPCtools' relay and
                # problemtools do) instead of letting the interactor die of
                # SIGPIPE, or block forever on a full pipe.
                program_params.io.input = open(
                    os.dup(channel.process_reads.fileno()), 'rb', buffering=0
                )
                program_params.io.output = channel.process_writes
                path = stderr_path(i)
                stderr_writer = stderr_writers[i]
                if stderr_writer is not None:
                    program_params.io.stderr = stderr_writer
                elif path is not None:
                    program_params.io.stderr = self.relative_path(path)
                program_params.pgid = group_id
                process = started(
                    Program(command + [str(i)] if fanout else command, program_params),
                    programs,
                )
                exit_order.watch_exit(i, process.pid)
                if channel.tee_to_interactor is None:
                    # Watched before the interactor starts, like everything
                    # `exit_order` sees: a watch armed late records its event
                    # late, and a whole exchange can fit in that gap.
                    exit_order.watch_hangup(i, channel.interactor_reads)
                channel.process_writes.close()
                if stderr_writer is not None:
                    stderr_writer.close()

            interactor_program_params = self._get_program_params(interactor_params)
            interactor_io = self._get_io(interactor_params, pipe_io=True)
            if fanout:
                interactor_program_params.pipesize = -1
            protocol_fds: List[int] = []
            if fanout:
                for channel in channels:
                    protocol_fds += [
                        channel.interactor_reads.fileno(),
                        channel.interactor_writes.fileno(),
                    ]
                interactor_command = interactor_command + [
                    f'/dev/fd/{fd}' for fd in protocol_fds
                ]
                # Liveness, below the protocol fds: its stdin, as a write end
                # (it reads nothing there; its stdout may carry debug prints).
                low_read, low_write = _liveness_pipe()
                liveness += [low_read, low_write]
                interactor_io.input = low_write
                interactor_io.output = subprocess.DEVNULL
            else:
                interactor_io.input = channels[0].interactor_reads
                interactor_io.output = channels[0].interactor_writes
            # Liveness, above the protocol fds (with one process, those are its
            # stdin/stdout).
            high_read, high_write = _liveness_pipe(above=max(protocol_fds, default=2))
            liveness += [high_read, high_write]
            interactor_program_params.pass_fds = (*protocol_fds, high_write.fileno())
            interactor_program_params.io = interactor_io
            interactor_program_params.pgid = group_id
            # Armed while we still hold the write ends, so they cannot fire yet.
            for end in liveness[0::2]:
                exit_order.watch_eof('interactor', end)
            interactor = started(
                Program(interactor_command, interactor_program_params),
                started_interactor,
            )
            # Nothing could talk before the interactor started, however long
            # the processes and tees took to spawn (~1 s for 64 processes with
            # capture, in Docker): each process's wall time counts from here.
            for program in programs:
                program.start_wall_clock(interactor.start_time)
            exit_order.watch_exit('interactor', interactor.pid)
            exit_order.start()
            for end in liveness[1::2]:
                end.close()
        except BaseException:
            # A program that could not start (say, a missing interactor) must not
            # strand the ones already started, blocked on pipes nobody will ever
            # write to or close.
            if group_id is not None:
                try:
                    os.killpg(group_id, signal.SIGKILL)
                except OSError:
                    pass
            for program in (*started_interactor, *programs, *tees):
                try:
                    _, status, ru = os.wait4(program.pid, 0)
                    program.process_exit(status, ru)
                except OSError:
                    pass
                program.close()
            for channel in channels:
                channel.close()
            for route in tee_routes:
                route.reads.close()
            for writer in stderr_writers:
                if writer is not None:
                    writer.close()
            for end in liveness:
                end.close()
            exit_order.close()
            raise
        assert group_id is not None
        # The interactor holds its own ends now; ours would keep EOF (and
        # SIGPIPE) from ever reaching the processes.
        for channel in channels:
            channel.interactor_reads.close()
            channel.interactor_writes.close()

        results: List[Optional[SandboxLog]] = [None] * n
        interactor_result: Optional[SandboxLog] = None
        drainers: List[threading.Thread] = []
        process_index = {program.pid: i for i, program in enumerate(programs)}
        tee_by_pid = {tee.pid: tee for tee in tees}

        def kill_group() -> None:
            try:
                os.killpg(group_id, signal.SIGKILL)
            except OSError:
                pass

        # Once the interactor and every process are gone, the tees should see
        # EOF at once; one still running is held open by something they left
        # behind (a grandchild holding stdout), and is given this long.
        tee_timer = threading.Timer(DRAIN_GRACE_SECONDS, kill_group)
        tee_timer.daemon = True
        tee_timer_started = False
        reaped = 0
        main_left = 1 + n

        def on_exit(pid: int, status: int, ru) -> None:
            nonlocal reaped, interactor_result, main_left, tee_timer_started
            idx = reaped
            reaped += 1
            if pid == interactor.pid:
                program_result = interactor.process_exit(status, ru)
                interactor_result = self._get_sandbox_log(
                    program_result, interactor_params
                )
                interactor_result.exit_index = idx
                main_left -= 1
                # Kill the processes still running if the interactor failed,
                # whatever was reaped before: a capture tee may exit (and be
                # reaped) ahead of the interactor it reads from. If it did not
                # fail, they see EOF and finish within their own limits.
                if program_result.exitcode != 0 and any(r is None for r in results):
                    kill_group()
            elif pid in process_index:
                i = process_index[pid]
                program_result = programs[i].process_exit(status, ru)
                result = self._get_sandbox_log(program_result, params)
                result.exit_index = idx
                results[i] = result
                main_left -= 1
                if interactor_result is None:
                    drainer = threading.Thread(
                        target=_drain, args=(channels[i].process_reads,), daemon=True
                    )
                    drainer.start()
                    drainers.append(drainer)
                else:
                    channels[i].process_reads.close()
            elif pid in tee_by_pid:
                tee_by_pid[pid].process_exit(status, ru)
            else:
                raise RuntimeError(f'Unknown pid: {pid}')
            if main_left == 0 and reaped < 1 + n + len(tees) and not tee_timer_started:
                tee_timer_started = True
                tee_timer.start()

        try:
            while reaped < 1 + n + len(tees):
                pid, status, ru = os.wait4(-group_id, 0)
                if pid in process_index and interactor_result is None:
                    # Ties go to the interactor: if it has exited as well, it is
                    # indexed first (what `exit_order` refines, when the kernel
                    # can tell).
                    other, other_status, other_ru = os.wait4(interactor.pid, os.WNOHANG)
                    if other:
                        on_exit(other, other_status, other_ru)
                on_exit(pid, status, ru)
        finally:
            tee_timer.cancel()

        # Every writer has been reaped by now, so the drainers are at EOF --
        # unless something the interactor spawned still holds a write end.
        for drainer in drainers:
            drainer.join(DRAIN_GRACE_SECONDS)
            if drainer.is_alive():
                kill_group()
                drainer.join()
        # Nothing the run started outlives it: whatever is left in the group is
        # something a program spawned and left behind. (The group can only be
        # gone, not reused, this soon after its last member was reaped.)
        kill_group()
        for channel in channels:
            channel.process_reads.close()
        for program in (interactor, *programs, *tees):
            program.close()

        ranks = exit_order.ranks()
        exit_order.close()
        for end in liveness:
            end.close()
        if ranks is not None:
            interactor_result.exit_index = ranks['interactor']
            for i, result in enumerate(results):
                assert result is not None
                result.exit_index = ranks[i]

        if fanout and params.stderr_file is not None:
            self._merge_process_stderr(
                params.stderr_file, [stderr_path(i) for i in range(n)]
            )

        assert interactor_result is not None
        return typing.cast(List[SandboxLog], results), interactor_result

    def _merge_process_stderr(
        self, into: pathlib.Path, parts: List[Optional[pathlib.Path]]
    ) -> None:
        """Fold each process's stderr into one file, grouped by process, every
        line tagged `[i] ` like the merged capture's `[i]` markers."""
        with self.relative_path(into).open('wb') as merged:
            for i, part in enumerate(parts):
                if part is None or not self.relative_path(part).is_file():
                    continue
                tag = b'[%d] ' % i
                with self.relative_path(part).open('rb') as f:
                    for line in f:
                        merged.write(tag + line)
                        if not line.endswith(b'\n'):
                            merged.write(b'\n')
                self.relative_path(part).unlink()

    def cleanup(self, delete=False):
        """See Sandbox.cleanup()."""
        # This sandbox doesn't have any cleanup, but we might want to delete.
        if delete:
            logger.debug('Deleting sandbox in %s.', self._path)
            shutil.rmtree(str(self._path), ignore_errors=True)
