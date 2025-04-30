from __future__ import annotations

import importlib.resources
import logging
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import (
    SandboxBase,
    SandboxParams,
)

logger = logging.getLogger(__name__)


class StupidSandbox(SandboxBase):
    """A stupid sandbox implementation. It has very few features and
    is not secure against things like box escaping and fork
    bombs. Yet, it is very portable and has no dependencies, so it's
    very useful for testing. Using in real contests is strongly
    discouraged.

    """

    exec_num: int
    popen: Optional[subprocess.Popen]
    returncode: Optional[int]
    log: Optional[Dict[str, str]]

    def __init__(
        self,
        file_cacher: Optional[FileCacher] = None,
        name: Optional[str] = None,
        temp_dir: Optional[pathlib.Path] = None,
        params: Optional[SandboxParams] = None,
    ):
        """Initialization.

        For arguments documentation, see SandboxBase.__init__.

        """
        if not temp_dir:
            temp_dir = pathlib.Path(tempfile.gettempdir())
        SandboxBase.__init__(self, file_cacher, name, temp_dir, params)

        # Make box directory
        self._path = pathlib.Path(
            tempfile.mkdtemp(dir=str(self.temp_dir), prefix='rbx-%s-' % (self.name))
        )
        self.initialize()

        self.exec_num = -1
        self.log = None
        self.returncode = None

        logger.debug("Sandbox in `%s' created, using stupid box.", self._path)

        # Box parameters
        self.chdir = self._path

    def initialize(self):
        self._path.mkdir(parents=True, exist_ok=True)

    def get_timeit_executable(self) -> pathlib.Path:
        with importlib.resources.as_file(
            importlib.resources.files('rbx')
            / 'grading'
            / 'judge'
            / 'sandboxes'
            / 'timeit.py'
        ) as file:
            return file

    def get_timeit_args(self) -> List[str]:
        args = []
        if self.params.timeout:
            timeout_in_s = self.params.timeout / 1000
            if self.params.extra_timeout:
                timeout_in_s += self.params.extra_timeout / 1000
            args.append(f'-t{timeout_in_s:.3f}')
        if self.params.wallclock_timeout:
            walltimeout_in_s = self.params.wallclock_timeout / 1000
            args.append(f'-w{walltimeout_in_s:.3f}')
        if self.params.address_space:
            args.append(f'-m{self.params.address_space}')
        if self.params.fsize:
            args.append(f'-f{self.params.fsize}')
        if self.chdir:
            args.append(f'-c{self.chdir}')

        file_args = []
        if self.params.stdin_file:
            file_args.append(f'-i{self.params.stdin_file}')
        if self.params.stdout_file:
            file_args.append(f'-o{self.params.stdout_file}')
        if self.params.stderr_file:
            file_args.append(f'-e{self.params.stderr_file}')
        if self.params.reverse_io:
            file_args.reverse()
        args.extend(file_args)

        if self.params.timeit_dups:
            for i, files in self.params.timeit_dups.items():
                assert i.lower() in ['di', 'do', 'de']
                for file in files:
                    args.append(f'-{i}{file}')
        if self.params.timeit_prefix:
            args.append(f'-P{self.params.timeit_prefix}')

        return args

    def get_root_path(self) -> pathlib.Path:
        """Return the toplevel path of the sandbox.

        return (Path): the root path.

        """
        return self._path

    def get_execution_time(self) -> Optional[float]:
        """Return the time spent in the sandbox.

        return (float): time spent in the sandbox.

        """
        if self.log is None:
            return None
        return float(self.log['time'])

    def get_execution_wall_clock_time(self) -> Optional[float]:
        """Return the total time from the start of the sandbox to the
        conclusion of the task.

        return (float): total time the sandbox was alive.

        """
        if self.log is None:
            return None
        return float(self.log['time-wall'])

    def use_soft_timeout(self) -> bool:
        return True

    def get_memory_used(self) -> Optional[int]:
        """Return the memory used by the sandbox.

        return (int): memory used by the sandbox (in bytes).

        """
        if self.log is None:
            return None
        return int(self.log['mem']) * 1024

    def get_killing_signal(self) -> int:
        """Return the signal that killed the sandboxed process.

        return (int): offending signal, or 0.

        """
        assert self.log is not None
        if 'exit-sig' not in self.log:
            return 0
        return int(self.log['exit-sig'])

    def get_status_list(self) -> List[str]:
        """Reads the sandbox log file, and set and return the status
        of the sandbox.

        return (list): list of statuses of the sandbox.

        """
        assert self.log is not None
        if 'status' in self.log:
            return self.log['status'].split(',')
        return []

    # This sandbox only discriminates between processes terminating
    # properly or being killed with a signal; all other exceptional
    # conditions (RAM or CPU limitations, ...) result in some signal
    # being delivered to the process
    def get_exit_status(self) -> str:
        """Get information about how the sandbox terminated.

        return (string): the main reason why the sandbox terminated.

        """
        if self.returncode is not None and not self.translate_box_exitcode(
            self.returncode
        ):
            return self.EXIT_SANDBOX_ERROR
        status_list = self.get_status_list()
        if 'TE' in status_list:
            return self.EXIT_TERMINATED
        if 'WT' in status_list:
            return self.EXIT_TIMEOUT_WALL
        if 'TO' in status_list:
            return self.EXIT_TIMEOUT
        if 'OL' in status_list:
            return self.EXIT_OUTPUT_LIMIT_EXCEEDED
        if 'ML' in status_list:
            return self.EXIT_MEMORY_LIMIT_EXCEEDED
        if 'SG' in status_list:
            return self.EXIT_SIGNAL
        if 'RE' in status_list:
            return self.EXIT_NONZERO_RETURN
        return self.EXIT_OK

    def get_exit_code(self) -> int:
        """Return the exit code of the sandboxed process.

        return (float): exitcode, or 0.

        """
        assert self.log is not None
        return int(self.log['exit-code'])

    def get_detailed_logs(self) -> str:
        return str(self.log)

    def get_human_exit_description(self) -> str:
        """Get the status of the sandbox and return a human-readable
        string describing it.

        return (string): human-readable explaination of why the
                         sandbox terminated.

        """
        status = self.get_exit_status()
        if status == self.EXIT_OK:
            return (
                'Execution successfully finished (with exit code %d)'
                % self.get_exit_code()
            )
        elif status == self.EXIT_SANDBOX_ERROR:
            return 'Execution failed because of sandbox error'
        elif status == self.EXIT_TIMEOUT:
            return 'Execution timed out'
        elif status == self.EXIT_TIMEOUT_WALL:
            return 'Execution timed out (wall clock limit exceeded)'
        elif status == self.EXIT_SIGNAL:
            return 'Execution killed with signal %s' % self.get_killing_signal()
        elif status == self.EXIT_NONZERO_RETURN:
            return 'Execution failed because the return code was nonzero'
        elif status == self.EXIT_OUTPUT_LIMIT_EXCEEDED:
            return 'Execution exceeded output limit'
        return ''

    def get_current_log_name(self) -> pathlib.Path:
        return pathlib.Path(f'logs.{self.exec_num}')

    def hydrate_logs(self):
        self.log = None
        if not self.relative_path(self.get_current_log_name()).is_file():
            return
        self.log = {}
        raw_log = self.get_file_to_string(self.get_current_log_name(), maxlen=None)
        for line in raw_log.splitlines():
            items = line.split(':', 1)
            if len(items) != 2:
                continue
            key, value = items
            self.log[key] = value.strip()

    def execute_without_std(
        self,
        command: List[str],
    ) -> bool:
        """Execute the given command in the sandbox using
        subprocess.Popen and discarding standard input, output and
        error. More specifically, the standard input gets closed just
        after the execution has started; standard output and error are
        read until the end, in a way that prevents the execution from
        being blocked because of insufficient buffering.

        command ([string]): executable filename and arguments of the
            command.

        return (bool): True if the sandbox didn't report errors
            (caused by the sandbox itself), False otherwise

        """
        self.exec_num += 1

        logger.debug(
            "Executing program in sandbox with command: `%s'.", ' '.join(command)
        )
        with open(
            self.relative_path(self.cmd_file), 'at', encoding='utf-8'
        ) as commands:
            commands.write('%s\n' % command)

        real_command = (
            [
                sys.executable,
                str(self.get_timeit_executable().resolve()),
                str(self.relative_path(self.get_current_log_name()).resolve()),
            ]
            + self.get_timeit_args()
            + command
        )
        with subprocess.Popen(
            real_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, **self.params.set_env},
        ) as p:
            self.set_pid(p.pid)
            try:
                self.returncode = p.wait()
            except Exception:
                p.kill()
                raise
        self.hydrate_logs()
        return self.translate_box_exitcode(self.returncode)

    def translate_box_exitcode(self, exitcode: int) -> bool:
        # SIGALRM can be safely ignored, just in case it leaks away. SIGTERM also.
        if self.log is None:
            return False
        if 'TE' in self.get_status_list():
            return True
        return super().translate_box_exitcode(exitcode) or -exitcode == signal.SIGALRM

    def debug_message(self) -> Any:
        return f'returncode = {self.returncode}\nlogs = {self.log}\ntimeit_args = {self.get_timeit_args()}'

    def cleanup(self, delete=False):
        """See Sandbox.cleanup()."""
        # This sandbox doesn't have any cleanup, but we might want to delete.
        if delete:
            logger.debug('Deleting sandbox in %s.', self._path)
            shutil.rmtree(str(self._path), ignore_errors=True)
