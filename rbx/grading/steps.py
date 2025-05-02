import asyncio
import contextlib
import dataclasses
import functools
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import typing
from enum import Enum
from typing import IO, Any, Dict, Iterable, List, Optional, Tuple, Union

import typer
from pydantic import BaseModel, Field
from rich.text import Text

from rbx import utils
from rbx.config import get_bits_stdcpp, get_jngen, get_testlib
from rbx.console import console
from rbx.grading import processing_context
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.judge.storage import Storage, copyfileobj
from rbx.grading.limits import Limits

MAX_STDOUT_LEN = 1024 * 1024 * 128  # 128 MB


class Outcome(Enum):
    ACCEPTED = 'accepted'
    WRONG_ANSWER = 'wrong-answer'
    MEMORY_LIMIT_EXCEEDED = 'memory-limit-exceeded'
    TIME_LIMIT_EXCEEDED = 'time-limit-exceeded'
    RUNTIME_ERROR = 'runtime-error'
    OUTPUT_LIMIT_EXCEEDED = 'output-limit-exceeded'
    JUDGE_FAILED = 'judge-failed'
    INTERNAL_ERROR = 'internal-error'

    @classmethod
    def worst_outcome(cls, outcomes: Iterable['Outcome']) -> 'Outcome':
        def _outcome_to_int(o: 'Outcome') -> int:
            return cls._member_names_.index(o.name)

        return max(outcomes, key=_outcome_to_int)


class DigestHolder(BaseModel):
    value: Optional[str] = None


class GradingLogsHolder(BaseModel):
    run: Optional['RunLog'] = None
    preprocess: Optional[List['PreprocessLog']] = None
    cached: bool = False


class DigestOrSource(BaseModel):
    # Source path relative to the FS.
    src: Optional[pathlib.Path] = None
    # Digest if we should get file from storage.
    digest: Optional[DigestHolder] = None

    @staticmethod
    def create(data: Union[pathlib.Path, DigestHolder, str]) -> 'DigestOrSource':
        if isinstance(data, str):
            return DigestOrSource(digest=DigestHolder(value=data))
        if isinstance(data, DigestHolder):
            return DigestOrSource(digest=data)
        return DigestOrSource(src=data)

    def expand(self) -> Dict[str, Any]:
        res = {}
        if self.src is not None:
            res['src'] = self.src
        if self.digest is not None:
            res['digest'] = self.digest
        return res


class DigestOrDest(BaseModel):
    # Destination path relative to the FS.
    dest: Optional[pathlib.Path] = None
    # Digest if we should get file from storage.
    digest: Optional[DigestHolder] = None

    @staticmethod
    def create(data: Union[pathlib.Path, DigestHolder, str]) -> 'DigestOrDest':
        if isinstance(data, str):
            return DigestOrDest(digest=DigestHolder(value=data))
        if isinstance(data, DigestHolder):
            return DigestOrDest(digest=data)
        return DigestOrDest(dest=data)

    def expand(self) -> Dict[str, Any]:
        res = {}
        if self.dest is not None:
            res['dest'] = self.dest
        if self.digest is not None:
            res['digest'] = self.digest
        return res


class GradingFileInput(BaseModel):
    # Destination path relative to the sandboox.
    dest: pathlib.Path
    # Source path relative to the FS.
    src: Optional[pathlib.Path] = None
    # Digest if we should get file from storage.
    digest: Optional[DigestHolder] = None
    # Whether the destination file should be marked as an executable.
    executable: bool = False


class GradingFileOutput(BaseModel):
    # Source path relative to the sandbox.
    src: pathlib.Path
    # Destination path relative to the FS.
    dest: Optional[pathlib.Path] = None
    # Digest if we should put file in storage.
    digest: Optional[DigestHolder] = None
    # Whether the destination file should be marked as an executable.
    executable: bool = False
    # Whether the file is optional or not.
    optional: bool = False
    # Whether to cap its size
    maxlen: Optional[int] = None
    # Whether the file is just an intermediate file that should not be tracked.
    intermediate: bool = False
    # Whether to track file through its hash (disable for optimization).
    hash: bool = True
    # Whether to touch the file before the command runs.
    touch: bool = False

    def get_file(self, storage: Storage) -> Optional[IO[bytes]]:
        if self.dest is not None:
            if self.optional and not self.dest.exists():
                return None
            return self.dest.open('rb')
        if self.digest is not None and self.digest.value is not None:
            if self.optional and not storage.exists(self.digest.value):
                return None
            return storage.get_file(self.digest.value)
        raise ValueError('No file to get')


class GradingFifo(BaseModel):
    # Destination path relative to the sandbox.
    path: pathlib.Path
    # Symlink to the FIFO outside the sandbox.
    symlink: Optional[pathlib.Path] = None
    # Whether to create the FIFO if it does not exist.
    create: bool = True


class GradingArtifacts(BaseModel):
    # Root directory for the produced artifacts.
    root: pathlib.Path = pathlib.PosixPath('.')
    # List of input files to copy to the sandbox.
    inputs: List[GradingFileInput] = []
    # List of output files to copy from the sandbox.
    outputs: List[GradingFileOutput] = []
    # List of FIFOs
    fifos: List[GradingFifo] = []
    # Capture certain logs of the execution.
    logs: Optional[GradingLogsHolder] = None

    def get_input_file_for_dest(self, dest: pathlib.Path) -> Optional[GradingFileInput]:
        for input in self.inputs:
            if input.dest == dest:
                return input
        return None

    def get_output_file_for_src(self, src: pathlib.Path) -> Optional[GradingFileOutput]:
        for output in self.outputs:
            if output.src == src:
                return output
        return None


class TestcaseIO(BaseModel):
    index: int
    input: Optional[pathlib.Path] = None
    output: Optional[pathlib.Path] = None


class RunLogMetadata(BaseModel):
    language: Optional[str] = None
    is_sanitized: bool = False
    limits: Limits = Field(default_factory=Limits)
    timeLimit: Optional[int] = None
    memoryLimit: Optional[int] = None
    retryIndex: Optional[int] = None


class ProcessingContextLog(BaseModel):
    pid: int = -1
    exitindex: int = -1


class RunLog(BaseModel):
    exitcode: int = 0
    exitstatus: str = SandboxBase.EXIT_SANDBOX_ERROR
    time: Optional[float] = 0.0
    memory: Optional[int] = 0
    sandbox: str = ''
    warnings: bool = False
    metadata: Optional[RunLogMetadata] = None

    def get_run_language(self) -> Optional[str]:
        if self.metadata is None:
            return None
        return self.metadata.language

    def get_summary(self) -> str:
        if self.exitcode == 0:
            return 'OK'
        time = self.time or 0.0
        memory = self.memory or 0
        return f'FAILED with exit code {self.exitcode} and sandbox status {self.exitstatus} (time: {time}s, memory: {memory // (1024 * 1024)}MB)'


class PreprocessLog(RunLog):
    cmd: List[str]
    log: str

    def get_command(self) -> str:
        return ' '.join(self.cmd)


class TestcaseLog(RunLog):
    stdout_absolute_path: Optional[pathlib.Path] = None
    stderr_absolute_path: Optional[pathlib.Path] = None
    log_absolute_path: Optional[pathlib.Path] = None


class CheckerResult(BaseModel):
    outcome: Outcome
    message: str = ''
    no_tle_outcome: Optional[Outcome] = None
    sanitizer_warnings: bool = False


class Evaluation(BaseModel):
    result: CheckerResult
    testcase: TestcaseIO
    log: TestcaseLog


def _process_input_artifacts(artifacts: GradingArtifacts, sandbox: SandboxBase):
    for input_artifact in artifacts.inputs:
        if input_artifact.digest is not None:
            assert input_artifact.digest.value is not None
            sandbox.create_file_from_storage(
                input_artifact.dest,
                input_artifact.digest.value,
                override=True,
                executable=input_artifact.executable,
                try_symlink=True,
            )
            continue
        assert input_artifact.src is not None
        sandbox.create_file_from_other_file(
            input_artifact.dest,
            artifacts.root / input_artifact.src,
            executable=input_artifact.executable,
            override=True,
            try_symlink=True,
        )
    for output_artifact in artifacts.outputs:
        if output_artifact.touch:
            sandbox.create_file_from_string(
                output_artifact.src,
                '',
                executable=output_artifact.executable,
                override=True,
            )


def _process_output_artifacts(
    artifacts: GradingArtifacts, sandbox: SandboxBase
) -> bool:
    for output_artifact in artifacts.outputs:
        if output_artifact.hash and output_artifact.digest is None:
            output_artifact.digest = DigestHolder()
        if not sandbox.file_exists(output_artifact.src):
            if output_artifact.optional:
                continue
            console.print(
                f'[error]Output artifact [item]{output_artifact.src}[/item] does not exist.[/error]'
            )
            return False

        if output_artifact.digest is not None:
            output_artifact.digest.value = sandbox.get_file_to_storage(
                output_artifact.src, trunc_len=output_artifact.maxlen
            )
        if output_artifact.dest is None:
            continue
        dst: pathlib.Path = artifacts.root / output_artifact.dest
        # Ensure dst directory exists.
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open('wb') as f:
            with sandbox.get_file(output_artifact.src) as sb_f:
                copyfileobj(
                    sb_f,
                    f,
                    maxlen=output_artifact.maxlen,
                )
        if output_artifact.executable:
            dst.chmod(0o755)
    return True


def _process_fifos(artifacts: GradingArtifacts, sandbox: SandboxBase):
    for fifo in artifacts.fifos:
        if fifo.symlink is not None:
            sandbox.create_symlink(fifo.path, fifo.symlink, override=True)
        else:
            sandbox.create_fifo(fifo.path, override=True)


def testlib_grading_input() -> GradingFileInput:
    return GradingFileInput(src=get_testlib(), dest=pathlib.Path('testlib.h'))


def jngen_grading_input() -> GradingFileInput:
    return GradingFileInput(src=get_jngen(), dest=pathlib.Path('jngen.h'))


def _expand_part(part: str, sandbox: SandboxBase) -> List[str]:
    part = part.strip()
    if part.startswith('@glob:'):
        return [shlex.quote(str(path)) for path in sandbox.glob(part[6:])]
    return [part]


def _get_java_memory_limits(sandbox: SandboxBase) -> Tuple[int, int]:
    max_memory = sandbox.params.address_space
    if max_memory is None:
        max_memory = 2048
    return max_memory, min(512, int(max_memory * 0.9))


def _split_and_expand(command: str, sandbox: SandboxBase) -> List[str]:
    res = []
    max_mem, init_mem = _get_java_memory_limits(sandbox)
    parts = shlex.split(command.format(memory=max_mem, initialMemory=init_mem))
    for part in parts:
        res.extend(_expand_part(part, sandbox))
    return res


def get_exe_from_command(command: str) -> str:
    cmds = shlex.split(command)
    if not cmds:
        return command
    return cmds[0]


def _is_c_command(exe_command: str) -> bool:
    return 'gcc' in exe_command or 'clang' in exe_command


def _is_cpp_command(exe_command: str) -> bool:
    return 'g++' in exe_command or 'clang++' in exe_command


def is_cxx_command(exe_command: str) -> bool:
    return _is_cpp_command(exe_command) or _is_c_command(exe_command)


def is_cxx_sanitizer_command(command: str) -> bool:
    exe = get_exe_from_command(command)
    if not exe:
        return False
    if not is_cxx_command(exe):
        return False
    return 'fsanitize' in command


def is_java_command(exe_command: str) -> bool:
    return 'javac' in exe_command or 'java' in exe_command


def is_kotlin_command(exe_command: str) -> bool:
    return 'kotlinc' in exe_command or 'kotlin' in exe_command


def is_java_like_command(exe_command: str) -> bool:
    return is_java_command(exe_command) or is_kotlin_command(exe_command)


@functools.cache
def _complain_about_clang() -> None:
    console.print(
        '[warning]Notice your C++ files are being compiled with [item]clang[/item] instead of [item]g++[/item].[/warning]'
    )
    console.print('[warning]This may lead to unexpected behavior.[/warning]')
    console.print('[warning]Consider using [item]g++[/item] instead.[/warning]')
    console.print(
        '[warning]See [item]https://rsalesc.github.io/rbx/cpp-on-macos[/item] for instructions on how to use [item]g++[/item] on MacOS.'
    )


def _get_cxx_version_output(command: str) -> Optional[str]:
    cmds = shlex.split(command)
    if not cmds:
        return None
    exe = cmds[0]
    if not is_cxx_command(exe):
        return None

    exe = cmds[0]
    output = subprocess.run([exe, '-v'], capture_output=True)
    if output.returncode != 0:
        console.print('[error]Failed to get C/C++ compiler version.[/error]')
        return None
    return output.stderr.decode()


def _maybe_get_bits_stdcpp_for_clang(command: str) -> Optional[GradingFileInput]:
    version_output = _get_cxx_version_output(command)
    if version_output is None:
        return None
    lines = version_output.splitlines()
    if not lines:
        return None
    # Check the first line for `clang`.
    if 'clang' not in lines[0]:
        return None

    if not is_cxx_sanitizer_command(command):
        _complain_about_clang()
    bits = get_bits_stdcpp()
    return GradingFileInput(src=bits, dest=pathlib.Path('bits/stdc++.h'))


def _maybe_get_bits_stdcpp_for_commands(
    commands: List[str],
) -> Optional[GradingFileInput]:
    for command in commands:
        res = _maybe_get_bits_stdcpp_for_clang(command)
        if res is not None:
            return res
    return None


@functools.cache
def _try_following_alias_for_exe(exe: str) -> Optional[str]:
    output = subprocess.run(
        f'which {exe}', shell=True, executable=shutil.which('bash'), capture_output=True
    )
    if output.returncode != 0:
        return None
    return output.stdout.decode().strip()


def _try_following_alias_for_command(command: str) -> str:
    cmds = shlex.split(command)
    if not cmds:
        return command
    exe = cmds[0]
    new_exe = _try_following_alias_for_exe(exe)
    if new_exe is None:
        return command
    return shlex.join([new_exe, *cmds[1:]])


def _try_following_alias_for_commands(commands: List[str]) -> List[str]:
    res: List[str] = []
    for command in commands:
        res.append(_try_following_alias_for_command(command))
    return res


@functools.cache
def _maybe_complain_about_sanitization(command: str) -> None:
    if not is_cxx_sanitizer_command(command):
        return
    if sys.platform != 'darwin':
        return

    version_output = _get_cxx_version_output(command)
    if version_output is None:
        return
    lines = version_output.splitlines()
    if not lines:
        return
    if 'gcc' in lines[-1]:
        console.print(
            '[error]Notice you are using sanitizers in [item]MacOS[/item], but your C/C++ compiler is [item]gcc[/item].[/error]'
        )
        console.print('[error]GCC does not support sanitization in MacOS.[/error]')
        console.print(
            '[warning]See [item]https://rsalesc.github.io/rbx/cpp-on-macos[/item] for instructions on how to use C/C++ sanitizers on MacOS.[/warning]'
        )
        raise typer.Exit(1)


def _check_for_sanitizer_warnings_in_line(line: str) -> bool:
    line = line.lower()
    return 'runtime error:' in line or '==error' in line


def _check_for_sanitizer_warnings(
    sandbox: SandboxBase, stderr_file: Optional[pathlib.Path]
) -> bool:
    if stderr_file is None:
        return False
    if not sandbox.file_exists(stderr_file):
        return False
    with sandbox.get_file(stderr_file) as f:
        return any(_check_for_sanitizer_warnings_in_line(line.decode()) for line in f)


_WARNING_RE = re.compile(r'([^:]+):\d+:\d+:[ ]+warning:.*')


def _check_for_compilation_warnings_in_line(line: str) -> bool:
    if line.startswith('./'):
        return False
    match = _WARNING_RE.match(line)
    if match is None:
        return False
    file = match.group(1).strip().lower()
    if 'testlib' in file or 'jngen' in file or 'stresslib' in file:
        return False
    if file.endswith('.h'):
        return False
    return True


def _check_for_compilation_warnings(
    sandbox: SandboxBase, stderr_file: Optional[pathlib.Path]
) -> bool:
    if stderr_file is None:
        return False
    if not sandbox.file_exists(stderr_file):
        return False
    with sandbox.get_file(stderr_file) as f:
        return any(
            _check_for_compilation_warnings_in_line(line.strip().decode()) for line in f
        )


def compile(
    commands: List[str],
    params: SandboxParams,
    sandbox: SandboxBase,
    artifacts: GradingArtifacts,
) -> bool:
    commands = _try_following_alias_for_commands(commands)
    bits_artifact = _maybe_get_bits_stdcpp_for_commands(commands)
    if bits_artifact is not None:
        _process_input_artifacts(GradingArtifacts(inputs=[bits_artifact]), sandbox)
    _process_input_artifacts(artifacts, sandbox)

    if not commands:
        # Code does not need preprocessing of any kind.
        return True

    logs: List[PreprocessLog] = []
    sandbox.set_params(params)

    for i, command in enumerate(commands):
        _maybe_complain_about_sanitization(command)
        cmd = _split_and_expand(command, sandbox)
        stdout_file = pathlib.PosixPath(f'compile-{i}.stdout')
        stderr_file = pathlib.PosixPath(f'compile-{i}.stderr')
        sandbox.params.set_stdall(stdout=stdout_file, stderr=stderr_file)

        # Remove memory constraints for Java.
        if is_java_like_command(get_exe_from_command(command)):
            sandbox.params.address_space = None

        if bits_artifact is not None and _is_cpp_command(cmd[0]):
            # Include from sandbox directory to import bits/stdc++.h.
            cmd.append('-I.')

        if not sandbox.execute_without_std(cmd):
            console.print(
                '[error]Sandbox crashed while processing command:[/error]',
                utils.highlight_json_obj(cmd),
                '[error]and logs[/error]',
                sandbox.debug_message(),
            )
            return False

        std_outputs = [
            sandbox.get_file_to_string(stderr_file, maxlen=None)
            if sandbox.file_exists(stderr_file)
            else '<No stderr produced by command>',
            sandbox.get_file_to_string(stdout_file, maxlen=None)
            if sandbox.file_exists(stdout_file)
            else '<No stdout produced by command>',
        ]

        log = PreprocessLog(
            cmd=cmd,
            exitcode=sandbox.get_exit_code(),
            exitstatus=sandbox.get_exit_status(),
            time=sandbox.get_execution_time(),
            memory=sandbox.get_memory_used(),
            warnings=_check_for_compilation_warnings(sandbox, stderr_file),
            log='\n'.join(std_outputs),
            sandbox=sandbox.get_detailed_logs(),
        )
        logs.append(log)

        if log.exitcode != 0:
            break

    if artifacts.logs is not None:
        artifacts.logs.preprocess = logs

    if logs and logs[-1].exitcode != 0:
        console.print(
            '[error]FAILED[/error] Preprocessing failed with command',
            utils.highlight_json_obj(logs[-1].cmd),
        )
        console.print(f'[error]Summary:[/error] {logs[-1].get_summary()}')
        console.print(Text.from_ansi(logs[-1].log), style='default')
        return False

    return _process_output_artifacts(artifacts, sandbox)


async def run(
    command: str,
    params: SandboxParams,
    sandbox: SandboxBase,
    artifacts: GradingArtifacts,
    metadata: Optional[RunLogMetadata] = None,
    kill_on_processing_context_exit: bool = False,
) -> Optional[RunLog]:
    _process_input_artifacts(artifacts, sandbox)
    _process_fifos(artifacts, sandbox)
    cmd = _split_and_expand(command, sandbox)
    sandbox.set_params(params)

    # Remove memory constraints for Java.
    if is_java_like_command(get_exe_from_command(command)):
        sandbox.params.address_space = None

    if not await asyncio.to_thread(sandbox.execute_without_std, cmd):
        console.print(
            '[error]Sandbox crashed while processing command:[/error]',
            utils.highlight_json_obj(cmd),
            '[error]and logs[/error]',
            sandbox.debug_message(),
        )
        return None

    if sandbox.get_exit_code() != 0 and kill_on_processing_context_exit:
        processing_context.terminate_all_processes_in_context(clear=False)

    if not _process_output_artifacts(artifacts, sandbox):
        return None

    execution_time = sandbox.get_execution_time()
    if execution_time is not None and (
        sandbox.get_exit_status() == SandboxBase.EXIT_TIMEOUT
        or sandbox.get_exit_status() == SandboxBase.EXIT_TIMEOUT_WALL
    ):
        execution_time = max(execution_time, (params.timeout or 0.0) / 1000)

    run_log = RunLog(
        exitcode=sandbox.get_exit_code(),
        exitstatus=sandbox.get_exit_status(),
        time=sandbox.get_execution_time(),
        memory=sandbox.get_memory_used(),
        metadata=metadata,
        sandbox=sandbox.get_detailed_logs(),
    )
    if metadata is not None and metadata.is_sanitized:
        run_log.warnings = _check_for_sanitizer_warnings(
            sandbox,
            params.stderr_file,
        )
    if artifacts.logs is not None:
        artifacts.logs.run = run_log.model_copy()
    return run_log


@dataclasses.dataclass
class CoordinatedRunParams:
    command: str
    params: SandboxParams
    sandbox: SandboxBase
    artifacts: GradingArtifacts
    metadata: Optional[RunLogMetadata] = None


async def run_coordinated(
    interactor: CoordinatedRunParams,
    solution: CoordinatedRunParams,
) -> Tuple[Optional[RunLog], Optional[RunLog]]:
    with processing_context.new_processing_context(terminate_all_on_error=True):
        # Schedule both runs to execute immediately.
        runs = tuple(
            asyncio.create_task(
                run(
                    params.command,
                    params.params,
                    params.sandbox,
                    params.artifacts,
                    params.metadata,
                    kill_on_processing_context_exit=True,
                )
            )
            for params in [interactor, solution]
        )
        await processing_context.wait_all_processes_in_context(wait_for=2)
        logs = typing.cast(
            Tuple[Optional[RunLog], Optional[RunLog]],
            tuple(await asyncio.gather(*runs)),
        )
        return logs


def _normalize_checked_words(s: str) -> Tuple[str, ...]:
    return tuple(s.split())


def _wcmp_check(expected: str, output: str) -> Outcome:
    if _normalize_checked_words(expected) == _normalize_checked_words(output):
        return Outcome.ACCEPTED

    return Outcome.WRONG_ANSWER


def get_checker_sandbox_params() -> SandboxParams:
    params = SandboxParams(
        max_processes=None,
        preserve_env=True,
    )
    params.add_mapped_directory(pathlib.Path('/usr'))
    params.add_mapped_directory(pathlib.Path('/etc'))
    return params


def _check(
    sandbox: SandboxBase,
    testcase: TestcaseIO,
    output_path: pathlib.Path,
    should_use_python_checker: bool = False,
) -> CheckerResult:
    if testcase.output is None:
        # No output to compare.
        return CheckerResult(outcome=Outcome.ACCEPTED)

    if should_use_python_checker:
        # Use default wcmp checker.
        expected = testcase.output.read_text()
        output = output_path.read_text()

        return CheckerResult(outcome=_wcmp_check(expected, output))

    sandbox.params.set_stdall(
        stdin=None,
        stdout=pathlib.PosixPath('stdout.txt'),
        stderr=pathlib.PosixPath('stderr.txt'),
    )

    sandbox.create_file_from_string(
        pathlib.PosixPath('expected.txt'), testcase.output.read_text(), override=True
    )
    sandbox.create_file_from_string(
        pathlib.PosixPath('output.txt'), output_path.read_text(), override=True
    )
    sandbox.create_file_from_string(
        pathlib.PosixPath('input.txt'),
        testcase.input.read_text() if testcase.input is not None else '',
        override=True,
    )

    if not sandbox.execute_without_std(
        ['./checker', 'input.txt', 'output.txt', 'expected.txt'],
    ):
        console.print(
            '[error]Sandbox crashed while running checker.[/error]',
            '[error]and logs[/error]',
            sandbox.debug_message(),
        )
        return CheckerResult(outcome=Outcome.INTERNAL_ERROR)

    checker_stderr = sandbox.get_file_to_string(
        pathlib.PosixPath('stderr.txt'), maxlen=None
    )
    if sandbox.get_exit_code() in [1, 2]:
        return CheckerResult(outcome=Outcome.WRONG_ANSWER, message=checker_stderr)
    if sandbox.get_exit_code() == 3:
        return CheckerResult(outcome=Outcome.JUDGE_FAILED, message=checker_stderr)
    return CheckerResult(outcome=Outcome.ACCEPTED, message=checker_stderr)


# Always assume a `checker` executable in the sandbox if should use checker.
def evaluate(
    sandbox: SandboxBase,
    testcase: TestcaseIO,
    log: Optional[TestcaseLog],
    artifacts: GradingArtifacts,
    should_use_python_checker: bool = False,
) -> Evaluation:
    if log is None:
        return Evaluation(
            testcase=testcase,
            log=TestcaseLog(),
            result=CheckerResult(outcome=Outcome.INTERNAL_ERROR),
        )
    if log.exitstatus != SandboxBase.EXIT_OK:
        return Evaluation(
            testcase=testcase,
            log=log,
            result=CheckerResult(outcome=Outcome.RUNTIME_ERROR),
        )

    if not testcase.output:
        # No output to compare.
        return Evaluation(
            testcase=testcase, log=log, result=CheckerResult(outcome=Outcome.ACCEPTED)
        )

    _process_input_artifacts(artifacts, sandbox)
    if log.stdout_absolute_path is None:
        return Evaluation(
            testcase=testcase,
            log=log,
            result=CheckerResult(outcome=Outcome.INTERNAL_ERROR, message='No output'),
        )

    checker_result = _check(
        sandbox,
        testcase,
        log.stdout_absolute_path,
        should_use_python_checker=should_use_python_checker,
    )
    return Evaluation(
        testcase=testcase,
        log=log,
        result=checker_result,
    )


@contextlib.contextmanager
def make_fifos():
    with tempfile.TemporaryDirectory() as temp_dir:
        fifo_in = pathlib.PosixPath(temp_dir) / 'fifo.in'
        fifo_out = pathlib.PosixPath(temp_dir) / 'fifo.out'
        os.mkfifo(fifo_in)
        os.mkfifo(fifo_out)
        yield fifo_in, fifo_out
