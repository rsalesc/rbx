import dataclasses
import os
import pathlib
import resource
import subprocess
import sys
import threading
import typing
from enum import Enum
from time import monotonic
from typing import IO, Any, Dict, List, Optional, Union

import psutil

from rbx.utils import PathOrStr

FileLike = Union[PathOrStr, IO[bytes], int]


def _maybe_close_files(files):
    for fobj in files:
        if isinstance(fobj, int):
            try:
                os.close(fobj)
            except OSError:
                pass
        else:
            fobj.close()


def _is_pathlike(obj: Any) -> bool:
    return isinstance(obj, str) or isinstance(obj, pathlib.Path)


@dataclasses.dataclass
class ProgramIO:
    input: FileLike = subprocess.PIPE
    output: FileLike = subprocess.PIPE
    stderr: FileLike = subprocess.PIPE

    def get_file_objects(self):
        if isinstance(self.input, int):
            input_fobj = self.input
        elif _is_pathlike(self.input):
            input_fobj = pathlib.Path(typing.cast(str, self.input)).open('r')
        else:
            input_fobj = typing.cast(IO[bytes], self.input)
        if isinstance(self.output, int):
            output_fobj = self.output
        elif _is_pathlike(self.output):
            output_path = pathlib.Path(typing.cast(str, self.output))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_fobj = output_path.open('w')
        else:
            output_fobj = typing.cast(IO[bytes], self.output)
        if isinstance(self.stderr, int):
            stderr_fobj = self.stderr
        elif _is_pathlike(self.stderr):
            stderr_path = pathlib.Path(typing.cast(str, self.stderr))
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_fobj = stderr_path.open('w')
        else:
            stderr_fobj = typing.cast(IO[bytes], self.stderr)
        return input_fobj, output_fobj, stderr_fobj


@dataclasses.dataclass
class ProgramPipes:
    input: Optional[IO[bytes]] = None
    output: Optional[IO[bytes]] = None
    stderr: Optional[IO[bytes]] = None


@dataclasses.dataclass
class ProgramParams:
    io: ProgramIO = dataclasses.field(default_factory=ProgramIO)
    chdir: Optional[pathlib.Path] = None
    time_limit: Optional[float] = None  # seconds
    wall_time_limit: Optional[float] = None  # seconds
    memory_limit: Optional[int] = None  # megabytes
    fs_limit: Optional[int] = None  # kilobytes
    env: Dict[str, str] = dataclasses.field(default_factory=dict)
    pgid: Optional[int] = None


def get_preexec_fn(params: ProgramParams):
    def preexec_fn():
        os.setpgid(0, params.pgid or 0)
        if params.time_limit is not None:
            time_limit_in_ms = int(params.time_limit * 1000)
            rlimit_cpu = int((time_limit_in_ms + 999) // 1000)
            resource.setrlimit(resource.RLIMIT_CPU, (rlimit_cpu, rlimit_cpu + 1))
        if params.fs_limit is not None:
            fs_limit = params.fs_limit * 1024  # in bytes
            resource.setrlimit(resource.RLIMIT_FSIZE, (fs_limit + 1, fs_limit * 2))
        if sys.platform != 'darwin':
            try:
                resource.setrlimit(
                    resource.RLIMIT_STACK,
                    (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
                )
            except ValueError:
                pass

    return preexec_fn


def get_memory_usage(ru: resource.struct_rusage) -> int:
    """Get memory usage in bytes from resource usage statistics.

    Returns the total memory usage (RSS + shared memory segments) in bytes.

    Platform differences in ru.ru_maxrss:
    - macOS/Darwin: ru.ru_maxrss is in bytes
    - Linux: ru.ru_maxrss is in kilobytes

    This function normalizes the result to always return bytes.

    Args:
        ru: Resource usage statistics from os.wait4() or similar

    Returns:
        int: Total memory usage in bytes
    """
    if sys.platform == 'darwin':
        # On macOS, ru.ru_maxrss is already in bytes
        return ru.ru_maxrss + ru.ru_ixrss * 1024
    # On Linux, ru.ru_maxrss is in kilobytes, so convert to bytes
    return (ru.ru_maxrss + ru.ru_ixrss + ru.ru_idrss + ru.ru_isrss) * 1024


def get_cpu_time(ru: resource.struct_rusage) -> float:
    """Get CPU time in seconds from resource usage statistics.

    Returns the total CPU time (user + system) in seconds.

    Args:
        ru: Resource usage statistics from os.wait4() or similar

    Returns:
        float: Total CPU time in seconds
    """
    return ru.ru_utime + ru.ru_stime


def get_file_sizes(io: ProgramIO):
    return _get_file_size(io.output) + _get_file_size(io.stderr)


def _get_file_size(filename: Optional[FileLike]) -> int:
    if filename is None or not _is_pathlike(filename):
        return 0
    path = pathlib.Path(typing.cast(str, filename))
    if not path.is_file():
        return 0
    return path.stat().st_size


class ProgramCode(Enum):
    RE = 'RE'
    SG = 'SG'
    TO = 'TO'
    WT = 'WT'
    ML = 'ML'
    OL = 'OL'
    TE = 'TE'


@dataclasses.dataclass
class ProgramResult:
    exitcode: int
    wall_time: float
    cpu_time: float
    memory_used: int
    file_sizes: int
    program_codes: List[ProgramCode]
    killing_signal: Optional[int] = None
    alarm_msg: Optional[str] = None


class Program:
    def __init__(self, command: List[str], params: ProgramParams):
        self.command = command
        self.params = params
        self.popen: Optional[subprocess.Popen] = None
        self._files = []

        self._stop_wall_handler = threading.Event()
        self._stop_alarm_handler = threading.Event()
        self._alarm_msg = ''

        self._run()

    @property
    def pipes(self) -> ProgramPipes:
        assert self.popen is not None
        return ProgramPipes(
            input=self.popen.stdin,
            output=self.popen.stdout,
            stderr=self.popen.stderr,
        )

    @property
    def pid(self) -> int:
        assert self.popen is not None
        return self.popen.pid

    def _kill_process(self):
        if self.popen is not None:
            self.popen.kill()

    def _handle_wall(self):
        if self._stop_wall_handler.wait(self.params.wall_time_limit):
            return
        self._stop_alarm_handler.set()
        self._alarm_msg = 'wall timelimit'
        self._kill_process()

    def _handle_alarm(self):
        if self._stop_alarm_handler.wait(0.3):
            return
        try:
            process = psutil.Process(self.pid)
            if self.params.time_limit is not None:
                times = process.cpu_times()
                cpu_time = times.user + times.system
                if cpu_time > self.params.time_limit:
                    self._alarm_msg = 'timelimit'
                    self._kill_process()
            if self.params.memory_limit is not None:
                memory_info = process.memory_info()
                memory_used = memory_info.rss
                if memory_used > self.params.memory_limit * 1024 * 1024:
                    self._alarm_msg = 'memorylimit'
                    self._kill_process()
            self._stop_alarm_handler.clear()
            self._handle_alarm()
        except psutil.NoSuchProcess:
            return

    def _run(self):
        self._files = self.params.io.get_file_objects()
        self.popen = subprocess.Popen(
            self.command,
            stdin=self._files[0],
            stdout=self._files[1],
            stderr=self._files[2],
            cwd=self.params.chdir,
            env={**os.environ, **self.params.env},
            preexec_fn=get_preexec_fn(self.params),
        )
        self.start_time = monotonic()

        threading.Thread(target=self._handle_wall, daemon=True).start()
        threading.Thread(target=self._handle_alarm, daemon=True).start()

    def close_pipes(self):
        if self.popen is None:
            return
        if self.params.io.input == subprocess.PIPE and self.pipes.input is not None:
            self.pipes.input.close()
        if self.params.io.output == subprocess.PIPE and self.pipes.output is not None:
            self.pipes.output.close()
        if self.params.io.stderr == subprocess.PIPE and self.pipes.stderr is not None:
            self.pipes.stderr.close()

    def close(self):
        self.close_pipes()
        _maybe_close_files(self._files)

    def process_exit(self, exitstatus, ru) -> ProgramResult:
        _maybe_close_files(self._files)

        wall_time = monotonic() - self.start_time
        cpu_time = get_cpu_time(ru)
        memory_used = get_memory_usage(ru)
        file_sizes = get_file_sizes(self.params.io)
        exitcode = os.waitstatus_to_exitcode(exitstatus)
        killing_signal = None
        program_codes = []

        if exitcode < 0:
            killing_signal = -exitcode
            program_codes.append(ProgramCode.SG)
        if exitcode > 0:
            program_codes.append(ProgramCode.RE)
        if self.params.time_limit is not None and (
            cpu_time > self.params.time_limit or -exitcode == 24
        ):
            program_codes.append(ProgramCode.TO)
        if (
            self.params.wall_time_limit is not None
            and wall_time > self.params.wall_time_limit
        ):
            program_codes.append(ProgramCode.WT)
            program_codes.append(ProgramCode.TO)
        # Memory limit checking: Two ways a process can exceed memory limits:
        # 1. Runtime monitoring (_handle_alarm) kills the process during execution
        # 2. Post-execution check using ru.ru_maxrss detects peak memory usage exceeded limit
        # Both memory_used (from ru.ru_maxrss) and memory_limit (converted to bytes) are in bytes
        if (
            self.params.memory_limit is not None
            and memory_used > self.params.memory_limit * 1024 * 1024
            or self._alarm_msg == 'memorylimit'
        ):
            program_codes.append(ProgramCode.ML)
        if (
            self.params.fs_limit is not None
            and file_sizes > self.params.fs_limit * 1024
        ):
            program_codes.append(ProgramCode.OL)

        result = ProgramResult(
            exitcode=exitcode,
            wall_time=wall_time,
            cpu_time=cpu_time,
            memory_used=memory_used,
            file_sizes=file_sizes,
            program_codes=program_codes,
            killing_signal=killing_signal,
            alarm_msg=self._alarm_msg or None,
        )
        return result

    def wait(self):
        assert self.popen is not None
        _, exitstatus, ru = os.wait4(self.pid, 0)
        res = self.process_exit(exitstatus, ru)
        self.close_pipes()
        return res
