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
import typing
from typing import List, Optional, Tuple

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

    def _get_tee_program_params(self, io: ProgramIO, pgid: int) -> ProgramParams:
        return ProgramParams(
            chdir=self.chdir,
            time_limit=None,
            wall_time_limit=None,
            memory_limit=None,
            io=io,
            pgid=pgid,
        )

    def _get_sandbox_log(
        self, result: ProgramResult, params: SandboxParams
    ) -> SandboxLog:
        return SandboxLog(
            params=params.model_copy(deep=True),
            execution_time=result.cpu_time,
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

    def _get_tee_executable(self) -> pathlib.Path:
        with importlib.resources.as_file(
            importlib.resources.files('rbx')
            / 'grading'
            / 'judge'
            / 'sandboxes'
            / 'tee.py'
        ) as file:
            return file

    def _get_tee_command(self, char: str, extra: Optional[str] = None) -> List[str]:
        return [
            sys.executable,
            str(utils.abspath(self._get_tee_executable())),
            char,
            extra or '/dev/null',
        ]

    def _get_tee_program(
        self,
        char: str,
        stdin: FileLike,
        stdout: FileLike,
        pgid: int,
        capture: Optional[pathlib.Path] = None,
        merged_capture: Optional[pathlib.Path] = None,
    ) -> Program:
        io = ProgramIO(input=stdin, output=stdout, stderr=subprocess.DEVNULL)
        if merged_capture:
            io.stderr = self.relative_path(merged_capture).open('ab')
        return Program(
            self._get_tee_command(
                char, str(self.relative_path(capture)) if capture else None
            ),
            self._get_tee_program_params(io, pgid),
        )

    def _get_pathlike_stdout(self, io: ProgramIO) -> Optional[pathlib.Path]:
        if isinstance(io.output, str) or isinstance(io.output, pathlib.Path):
            return pathlib.Path(io.output)
        return None

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
        merged_capture: Optional[pathlib.Path] = None,
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
        assert interactor.pipes.output is not None
        assert interactor.pipes.input is not None
        solution_input_pipe = interactor.pipes.output
        solution_output_pipe = interactor.pipes.input

        group_id = os.getpgid(interactor.pid)
        should_tee = self._needs_teeing(params, interactor_params, merged_capture)

        if should_tee:
            if merged_capture:
                self.create_file_from_string(merged_capture, '<\n>\n', override=True)

            solution_tee = self._get_tee_program(
                '>',
                stdin=subprocess.PIPE,
                stdout=interactor.pipes.input,
                capture=self._get_pathlike_stdout(self._get_io(params)),
                merged_capture=merged_capture,
                pgid=group_id,
            )
            interactor_tee = self._get_tee_program(
                '<',
                stdin=interactor.pipes.output,
                stdout=subprocess.PIPE,
                capture=self._get_pathlike_stdout(self._get_io(interactor_params)),
                merged_capture=merged_capture,
                pgid=group_id,
            )
            assert solution_tee.pipes.input is not None
            assert interactor_tee.pipes.output is not None
            solution_input_pipe = interactor_tee.pipes.output
            solution_output_pipe = solution_tee.pipes.input

        program_params = self._get_program_params(params)
        program_params.io = self._get_io(params, pipe_io=True)
        program_params.io.input = solution_input_pipe
        program_params.io.output = solution_output_pipe
        program_params.pgid = group_id
        program = Program(command, program_params)

        results: List[Optional[SandboxLog]] = [None, None]

        for idx in range(4 if should_tee else 2):
            pid, status, ru = os.wait4(-group_id, 0)

            if pid == interactor.pid:
                program_result = interactor.process_exit(status, ru)
                results[1] = self._get_sandbox_log(program_result, interactor_params)
                results[1].exit_index = idx

                interactor.pipes.output.close()
                if should_tee:
                    assert interactor_tee.pipes.output is not None
                    interactor_tee.pipes.output.close()

                if idx == 0 and program_result.exitcode != 0:
                    try:
                        os.killpg(group_id, signal.SIGKILL)
                    except Exception:
                        pass
            elif pid == program.pid:
                program_result = program.process_exit(status, ru)
                results[0] = self._get_sandbox_log(program_result, params)
                results[0].exit_index = idx

                interactor.pipes.input.close()
                if should_tee:
                    assert solution_tee.pipes.input is not None
                    solution_tee.pipes.input.close()
            elif should_tee and (pid in (solution_tee.pid, interactor_tee.pid)):
                pass
            else:
                raise RuntimeError(f'Unknown pid: {pid}')

        for p in (interactor, program):
            p.close()
        if should_tee:
            for p in (solution_tee, interactor_tee):
                p.close()

        return typing.cast(Tuple[SandboxLog, SandboxLog], tuple(results))

    def cleanup(self, delete=False):
        """See Sandbox.cleanup()."""
        # This sandbox doesn't have any cleanup, but we might want to delete.
        if delete:
            logger.debug('Deleting sandbox in %s.', self._path)
            shutil.rmtree(str(self._path), ignore_errors=True)
