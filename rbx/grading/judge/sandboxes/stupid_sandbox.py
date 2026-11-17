from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import importlib.resources
import logging
import os
import pathlib
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import typing
from typing import Iterator, List, Optional, Tuple

from rbx import utils
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.program import (
    FileLike,
    Program,
    ProgramCode,
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


def _make_pipe() -> Tuple[typing.IO[bytes], typing.IO[bytes]]:
    """A pipe as two unbuffered file objects (read end, write end).

    File objects, never bare fds: a `Program` closes what it was given more than
    once, and a second `os.close` could hit an unrelated fd that reused the
    number. Sized like the pipes `subprocess` makes (where the OS allows it).
    """
    read_fd, write_fd = os.pipe()
    if BUFFER_SIZE_BYTES > 0 and hasattr(fcntl, 'F_SETPIPE_SZ'):
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
    def open(teed: bool) -> '_Channel':
        if not teed:
            to_r, to_w = _make_pipe()
            from_r, from_w = _make_pipe()
            return _Channel(from_r, to_w, to_r, from_w)
        i2t_r, i2t_w = _make_pipe()
        t2p_r, t2p_w = _make_pipe()
        p2t_r, p2t_w = _make_pipe()
        t2i_r, t2i_w = _make_pipe()
        return _Channel(
            interactor_reads=t2i_r,
            interactor_writes=i2t_w,
            process_reads=t2p_r,
            process_writes=p2t_w,
            tee_to_process=(i2t_r, t2p_w),
            tee_to_interactor=(p2t_r, t2i_w),
        )


# An upper bound on the descriptors a run holds at once per contestant process:
# its channel's pipes (eight when teed), the copy of its stdin, its stderr pipe
# and file, and the merged capture each of its three tees appends to.
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
        self, io: ProgramIO, pgid: Optional[int]
    ) -> ProgramParams:
        return ProgramParams(
            chdir=self.chdir,
            time_limit=None,
            wall_time_limit=None,
            memory_limit=None,
            io=io,
            pgid=pgid,
            pipesize=BUFFER_SIZE_BYTES,
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
    ) -> bool:
        return (
            params.stdout_file is not None
            or interactor_params.stdout_file is not None
            or merged_capture is not None
        )

    def _get_tee_executable(
        self, communication_params: CommunicationParams
    ) -> pathlib.Path:
        if communication_params.tee_mode == 'line':
            with importlib.resources.as_file(
                importlib.resources.files('rbx')
                / 'grading'
                / 'judge'
                / 'sandboxes'
                / 'line_tee.py'
            ) as file:
                return file
        with importlib.resources.as_file(
            importlib.resources.files('rbx')
            / 'grading'
            / 'judge'
            / 'sandboxes'
            / 'chunk_tee.py'
        ) as file:
            return file

    def _get_tee_command(
        self,
        char: str,
        communication_params: CommunicationParams,
        extra: Optional[str] = None,
    ) -> List[str]:
        return [
            sys.executable,
            str(utils.abspath(self._get_tee_executable(communication_params))),
            char,
            extra or '/dev/null',
        ]

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
            self._get_tee_program_params(io, pgid),
        )

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
        should_tee = self._needs_teeing(params, interactor_params, merged_capture)
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
        channels = [_Channel.open(should_tee) for _ in range(n)]

        # Every program joins the process group of the first one started, so
        # one `wait4` reaps them all and one `killpg` stops them all.
        group_id: Optional[int] = None

        def started(program: Program) -> Program:
            nonlocal group_id
            if group_id is None:
                group_id = os.getpgid(program.pid)
            return program

        # The processes (and their tees) before the interactor. Until it starts
        # nothing can talk, so a process that exits meanwhile quit on its own --
        # really first. From the interactor on, every exit is reaped as it
        # happens, so `exit_index` orders them truly; exits that piled up while
        # we were still starting programs would be reaped in whatever order the
        # kernel lists children.
        tees: List[Program] = []
        programs: List[Program] = []
        try:
            for i, channel in enumerate(channels):
                if channel.tee_to_process is not None:
                    assert channel.tee_to_interactor is not None
                    # The '>' tee first, as it always was. A tee forwards a chunk
                    # before it logs it, so the capture can show a reply ahead of
                    # the line it answers; measured, the other spawn order makes
                    # that ~5x likelier on macOS (8% vs 1.5% of runs of
                    # `test_run_coordinated_with_merged_capture`).
                    tees.append(
                        started(
                            self._get_tee_program(
                                marker(i, '>'),
                                stdin=channel.tee_to_interactor[0],
                                stdout=channel.tee_to_interactor[1],
                                capture=capture_path(params),
                                pgid=group_id,
                                communication_params=communication_params,
                            )
                        )
                    )
                    tees.append(
                        started(
                            self._get_tee_program(
                                marker(i, '<'),
                                stdin=channel.tee_to_process[0],
                                stdout=channel.tee_to_process[1],
                                capture=capture_path(interactor_params),
                                pgid=group_id,
                                communication_params=communication_params,
                            )
                        )
                    )
                    for end in (*channel.tee_to_process, *channel.tee_to_interactor):
                        end.close()

                program_params = self._get_program_params(params)
                program_params.io = self._get_io(params, pipe_io=True)
                # The process gets its own copy of the read end it consumes. Ours
                # stays open, so the interactor -- or its capture tee -- never writes
                # into a pipe nobody holds: a process may answer and exit without
                # reading everything the interactor still has to say, and once it is
                # gone we drain the rest (as BAPCtools' relay and problemtools do)
                # instead of letting the interactor die of SIGPIPE, or block forever
                # on a full pipe.
                program_params.io.input = open(
                    os.dup(channel.process_reads.fileno()), 'rb', buffering=0
                )
                program_params.io.output = channel.process_writes
                path = stderr_path(i)
                stderr_writer: Optional[typing.IO[bytes]] = None
                if should_tee_stderr:
                    # The tee writes the clean copy to the process's stderr file and
                    # the marked copy to the merged capture.
                    stderr_reader, stderr_writer = _make_pipe()
                    tees.append(
                        started(
                            self._get_tee_program(
                                marker(i, '!'),
                                stdin=stderr_reader,
                                stdout=subprocess.DEVNULL,
                                capture=path,
                                pgid=group_id,
                                communication_params=communication_params,
                            )
                        )
                    )
                    stderr_reader.close()
                    program_params.io.stderr = stderr_writer
                elif path is not None:
                    program_params.io.stderr = self.relative_path(path)
                program_params.pgid = group_id
                programs.append(
                    started(
                        Program(
                            command + [str(i)] if fanout else command, program_params
                        )
                    )
                )
                channel.process_writes.close()
                if stderr_writer is not None:
                    stderr_writer.close()

            interactor_program_params = self._get_program_params(interactor_params)
            interactor_io = self._get_io(interactor_params, pipe_io=True)
            if fanout:
                interactor_io.input = subprocess.DEVNULL
                interactor_io.output = subprocess.DEVNULL
                fds: List[int] = []
                for channel in channels:
                    fds += [
                        channel.interactor_reads.fileno(),
                        channel.interactor_writes.fileno(),
                    ]
                interactor_command = interactor_command + [
                    f'/dev/fd/{fd}' for fd in fds
                ]
                interactor_program_params.pass_fds = tuple(fds)
            else:
                interactor_io.input = channels[0].interactor_reads
                interactor_io.output = channels[0].interactor_writes
            interactor_program_params.io = interactor_io
            interactor_program_params.pgid = group_id
            interactor = Program(interactor_command, interactor_program_params)
        except BaseException:
            # A program that could not start (say, a missing interactor) must not
            # strand the ones already started, blocked on pipes nobody will ever
            # write to or close.
            if group_id is not None:
                try:
                    os.killpg(group_id, signal.SIGKILL)
                except OSError:
                    pass
            for program in (*programs, *tees):
                try:
                    _, status, ru = os.wait4(program.pid, 0)
                    program.process_exit(status, ru)
                except OSError:
                    pass
                program.close()
            for channel in channels:
                channel.close()
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

        reaped = 0

        def on_exit(pid: int, status: int, ru) -> None:
            nonlocal reaped, interactor_result
            idx = reaped
            reaped += 1
            if pid == interactor.pid:
                program_result = interactor.process_exit(status, ru)
                interactor_result = self._get_sandbox_log(
                    program_result, interactor_params
                )
                interactor_result.exit_index = idx
                # Kill the processes still running if the interactor failed,
                # whatever was reaped before: a capture tee may exit (and be
                # reaped) ahead of the interactor it reads from. If it did not
                # fail, they see EOF and finish within their own limits.
                if program_result.exitcode != 0 and any(r is None for r in results):
                    try:
                        os.killpg(group_id, signal.SIGKILL)
                    except Exception:
                        pass
            elif pid in process_index:
                i = process_index[pid]
                program_result = programs[i].process_exit(status, ru)
                result = self._get_sandbox_log(program_result, params)
                result.exit_index = idx
                results[i] = result
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

        while reaped < 1 + n + len(tees):
            pid, status, ru = os.wait4(-group_id, 0)
            if pid == interactor.pid:
                # Programs that exited before we looked come back in whatever
                # order the kernel lists them -- oldest first on Linux, newest
                # first on macOS. Between the interactor and a process that both
                # had, the process goes first, on both: a process that failed
                # first (say, crashed, so the interactor read EOF) must not be
                # blamed on the interactor, and the opposite -- a process killed
                # by SIGPIPE writing to an interactor already gone -- is told
                # apart by its signal (`checkers.check_communication`).
                for program in programs:
                    if results[process_index[program.pid]] is None:
                        other, other_status, other_ru = os.wait4(
                            program.pid, os.WNOHANG
                        )
                        if other:
                            on_exit(other, other_status, other_ru)
            on_exit(pid, status, ru)

        # Every writer has been reaped by now, so the drainers are at EOF --
        # unless something the interactor spawned still holds a write end.
        for drainer in drainers:
            drainer.join(DRAIN_GRACE_SECONDS)
            if drainer.is_alive():
                try:
                    os.killpg(group_id, signal.SIGKILL)
                except Exception:
                    pass
                drainer.join()
        for channel in channels:
            channel.process_reads.close()
        for program in (interactor, *programs, *tees):
            program.close()

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
