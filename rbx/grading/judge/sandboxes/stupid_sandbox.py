from __future__ import annotations

import logging
import os
import pathlib
import shutil
import tempfile
import typing
from typing import List, Optional, Tuple

from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.program import (
    Program,
    ProgramCode,
    ProgramIO,
    ProgramParams,
    ProgramResult,
)
from rbx.grading.judge.sandbox import (
    SandboxBase,
    SandboxLog,
    SandboxParams,
)

logger = logging.getLogger(__name__)

TEE_CODE = R"""
import sys
c = sys.argv[1]
new = True
while True:
    l = sys.stdin.read(1)
    if l=='': break
    sys.stdout.write(l)
    sys.stdout.flush()
    if new: sys.stderr.write(c)
    sys.stderr.write(l)
    sys.stderr.flush()
    new = l=='\n'
"""


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
    ):
        """Initialization.

        For arguments documentation, see SandboxBase.__init__.

        """
        if not temp_dir:
            temp_dir = pathlib.Path(tempfile.gettempdir())
        SandboxBase.__init__(self, file_cacher, name, temp_dir)

        # Make box directory
        self.initialize()

    def initialize(self):
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

    def use_soft_timeout(self) -> bool:
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
            fs_limit=params.fsize,
            env=params.set_env,
            io=self._get_io(params),
        )

    def _get_sandbox_log(
        self, result: ProgramResult, params: SandboxParams
    ) -> SandboxLog:
        return SandboxLog(
            params=params.model_copy(deep=True),
            execution_time=result.wall_time,
            memory_used=result.memory_used,
            exitcode=result.exitcode,
            exitstatus=self._get_exit_status(result),
            killing_signal=result.killing_signal,
            other_logs={
                'program_codes': [code.value for code in result.program_codes],
                'alarm_msg': result.alarm_msg,
            },
        )

    def run(self, command: List[str], params: SandboxParams) -> SandboxLog:
        self.exec_num += 1

        logger.debug(
            "Executing program in sandbox with command: `%s'.", ' '.join(command)
        )
        with open(
            self.relative_path(self.cmd_file), 'at', encoding='utf-8'
        ) as commands:
            commands.write('%s\n' % command)

        program = Program(command, self._get_program_params(params))
        result = program.wait()

        return self._get_sandbox_log(result, params)

    def run_communication(
        self,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
    ) -> Tuple[SandboxLog, SandboxLog]:
        self.exec_num += 1

        logger.debug(
            "Executing program in sandbox with command: `%s'.", ' '.join(command)
        )
        with open(
            self.relative_path(self.cmd_file), 'at', encoding='utf-8'
        ) as commands:
            commands.write('%s\n' % command)

        interactor_program_params = self._get_program_params(interactor_params)
        interactor_program_params.io = self._get_io(interactor_params, pipe_io=True)
        interactor = Program(
            interactor_command,
            interactor_program_params,
        )

        group_id = os.getpgid(interactor.pid)

        program_params = self._get_program_params(params)
        program_params.io = self._get_io(params, pipe_io=True)
        assert interactor.pipes.output is not None
        assert interactor.pipes.input is not None
        program_params.io.input = interactor.pipes.output
        program_params.io.output = interactor.pipes.input
        program_params.pgid = group_id
        program = Program(command, program_params)

        results: List[Optional[SandboxLog]] = [None, None]

        for idx in range(2):
            pid, status, ru = os.wait4(-group_id, 0)

            if pid == interactor.pid:
                interactor.pipes.output.close()

                program_result = interactor.process_exit(status, ru)
                results[1] = self._get_sandbox_log(program_result, interactor_params)
                results[1].exit_index = idx
                # TODO: kill in case of WA
            elif pid == program.pid:
                interactor.pipes.input.close()

                program_result = program.process_exit(status, ru)
                results[0] = self._get_sandbox_log(program_result, params)
                results[0].exit_index = idx
            else:
                raise RuntimeError(f'Unknown pid: {pid}')

        return typing.cast(Tuple[SandboxLog, SandboxLog], tuple(results))

    def cleanup(self, delete=False):
        """See Sandbox.cleanup()."""
        # This sandbox doesn't have any cleanup, but we might want to delete.
        if delete:
            logger.debug('Deleting sandbox in %s.', self._path)
            shutil.rmtree(str(self._path), ignore_errors=True)
