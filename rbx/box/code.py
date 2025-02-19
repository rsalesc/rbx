import pathlib
import re
import shlex
from enum import Enum
from pathlib import PosixPath
from typing import List, Optional

import rich
import rich.text
import typer

from rbx import console
from rbx.box import download, package, setter_config
from rbx.box.environment import (
    ExecutionConfig,
    get_compilation_config,
    get_execution_config,
    get_file_mapping,
    get_language,
    get_mapped_command,
    get_mapped_commands,
    get_sandbox_params_from_config,
    merge_execution_configs,
)
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import CodeItem
from rbx.grading import steps_with_caching
from rbx.grading.steps import (
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    RunLog,
    RunLogMetadata,
    is_cxx_command,
)


class SanitizationLevel(Enum):
    NONE = 0
    PREFER = 1
    FORCE = 2

    def should_sanitize(self) -> bool:
        cfg = setter_config.get_setter_config()
        if cfg.sanitizers.enabled:
            return self.value >= SanitizationLevel.PREFER.value
        return self.value >= SanitizationLevel.FORCE.value


def substitute_commands(commands: List[str], sanitized: bool = False) -> List[str]:
    cfg = setter_config.get_setter_config()
    return [cfg.substitute_command(command, sanitized) for command in commands]


def get_extension(code: CodeItem) -> str:
    path: pathlib.Path = PosixPath(code.path)
    return path.suffix[1:]


def find_language_name(code: CodeItem) -> str:
    if code.language is not None:
        return get_language(code.language).name
    return get_language(get_extension(code)).name


def is_executable_sanitized(executable: DigestOrSource) -> bool:
    if executable.digest is None:
        return False
    storage = package.get_cache_storage()
    return storage.exists(f'{executable.digest.value}.san')


def add_sanitizer_flags_to_command(command: str) -> str:
    if is_cxx_command(command):
        return command + ' -fsanitize=address,undefined -fno-omit-frame-pointer -g'
    return command


def add_sanitizer_flags(commands: List[str]) -> List[str]:
    return [add_sanitizer_flags_to_command(command) for command in commands]


CXX_WARNING_FLAGS = (
    '-Wall -Wshadow -Wno-unused-result -Wno-sign-compare -Wno-char-subscripts'
)


def add_warning_flags_to_command(command: str) -> str:
    if is_cxx_command(command):
        return command + ' ' + CXX_WARNING_FLAGS
    return command


def add_warning_flags(commands: List[str], force_warnings: bool) -> List[str]:
    cfg = setter_config.get_setter_config()
    if cfg.warnings.enabled or force_warnings:
        return [add_warning_flags_to_command(command) for command in commands]
    return commands


def _add_warning_pragmas(code: str) -> str:
    flags = CXX_WARNING_FLAGS.split()
    pragma_lines = '\n'.join(
        [
            f'#pragma GCC diagnostic ignored "{flag}"'
            for flag in flags
            if not flag.startswith('-Wno-')
        ]
    )

    return re.sub(
        r'^(#include[^\n]*)',
        '#pragma GCC diagnostic push\n'
        + pragma_lines
        + '\n\\1'
        + '\n#pragma GCC diagnostic pop\n',
        code,
        flags=re.MULTILINE,
    )


def _add_warning_pragmas_around(code: str) -> str:
    flags = CXX_WARNING_FLAGS.split()
    pragma_lines = '\n'.join(
        [
            f'#pragma GCC diagnostic ignored "{flag}"'
            for flag in flags
            if not flag.startswith('-Wno-')
        ]
    )

    return (
        '#pragma GCC diagnostic push\n'
        + pragma_lines
        + '\n'
        + code
        + '\n'
        + '#pragma GCC diagnostic pop\n'
    )


def _ignore_warning_in_cxx_input(input: GradingFileInput):
    if input.src is None or input.src.suffix not in ('.h', '.hpp'):
        return
    preprocessed_path = package.get_problem_preprocessed_path(input.src)
    preprocessed_path.write_text(_add_warning_pragmas_around(input.src.read_text()))
    input.src = preprocessed_path


# Compile code item and return its digest in the storage.
def compile_item(
    code: CodeItem,
    sanitized: SanitizationLevel = SanitizationLevel.PREFER,
    force_warnings: bool = False,
    verbose: bool = False,
) -> str:
    generator_path = PosixPath(code.path)

    if not generator_path.is_file():
        console.console.print(
            f'[error]Compilation file not found: [item]{generator_path}[/item][/error]'
        )
        raise typer.Exit(1)

    language = find_language_name(code)
    compilation_options = get_compilation_config(language)
    file_mapping = get_file_mapping(language)
    dependency_cache = package.get_dependency_cache()
    sandbox = package.get_singleton_sandbox()
    sandbox_params = get_sandbox_params_from_config(compilation_options.sandbox)

    if not compilation_options.commands:
        # Language is not compiled.
        return sandbox.file_cacher.put_file_from_path(generator_path)

    commands = get_mapped_commands(compilation_options.commands, file_mapping)
    commands = add_warning_flags(commands, force_warnings)
    commands = substitute_commands(commands, sanitized=sanitized.should_sanitize())

    if sanitized.should_sanitize():
        commands = add_sanitizer_flags(commands)

        # Remove any memory constraints for a sanitized executable.
        # Sanitizers are known to be memory-hungry.
        sandbox_params.address_space = None

        # Reset timeout configs since sanitizers are known to be time-hungry.
        sandbox_params.timeout = None
        sandbox_params.wallclock_timeout = None

    compiled_digest = DigestHolder()

    artifacts = GradingArtifacts()
    artifacts.inputs.extend(
        GradingFileInput(src=src, dest=dest)
        for src, dest in package.get_compilation_files(code)
    )

    download.maybe_add_testlib(code, artifacts)
    download.maybe_add_jngen(code, artifacts)
    artifacts.inputs.append(
        GradingFileInput(src=generator_path, dest=PosixPath(file_mapping.compilable))
    )

    artifacts.outputs.append(
        GradingFileOutput(
            src=PosixPath(file_mapping.executable),
            digest=compiled_digest,
            executable=True,
        )
    )

    for input in artifacts.inputs:
        _ignore_warning_in_cxx_input(input)

    if not steps_with_caching.compile(
        commands,
        params=sandbox_params,
        artifacts=artifacts,
        sandbox=sandbox,
        dependency_cache=dependency_cache,
    ):
        raise typer.Exit(1)

    assert compiled_digest.value is not None

    if verbose and artifacts.logs is not None and artifacts.logs.preprocess is not None:
        for log in artifacts.logs.preprocess:
            console.console.print(f'[status]Command:[/status] {log.get_command()}')
            console.console.print(f'[status]Summary:[/status] {log.get_summary()}')
            console.console.print(rich.text.Text.from_ansi(log.log), style='default')

    # Write compiler warnings.
    cfg = setter_config.get_setter_config()
    if (
        (cfg.warnings.enabled or force_warnings)
        and artifacts.logs is not None
        and artifacts.logs.preprocess is not None
    ):
        any_warning = any(log.warnings for log in artifacts.logs.preprocess)
        if any_warning:
            warning_stack.get_warning_stack().add_warning(code)

    # Create sentinel to indicate this executable is sanitized.
    storage = package.get_cache_storage()
    if sanitized.should_sanitize():
        pf = storage.create_file(f'{compiled_digest.value}.san')
        if pf is not None:
            storage.commit_file(pf)
    elif storage.exists(f'{compiled_digest.value}.san'):
        storage.delete(f'{compiled_digest.value}.san')

    return compiled_digest.value


def run_item(
    code: CodeItem,
    executable: DigestOrSource,
    stdin: Optional[DigestOrSource] = None,
    stdout: Optional[DigestOrDest] = None,
    stderr: Optional[DigestOrDest] = None,
    inputs: Optional[List[GradingFileInput]] = None,
    outputs: Optional[List[GradingFileOutput]] = None,
    extra_args: Optional[str] = None,
    extra_config: Optional[ExecutionConfig] = None,
) -> Optional[RunLog]:
    language = find_language_name(code)
    execution_options = get_execution_config(language)
    if extra_config is not None:
        execution_options = merge_execution_configs([execution_options, extra_config])
    file_mapping = get_file_mapping(language)
    dependency_cache = package.get_dependency_cache()
    sandbox = package.get_singleton_sandbox()
    sandbox_params = get_sandbox_params_from_config(execution_options.sandbox)

    # Sanitization parameters.
    sanitized = False
    if is_executable_sanitized(executable):
        # Remove any memory constraints for a sanitized executable.
        # Sanitizers are known to be memory-hungry.
        sandbox_params.address_space = None

        # Reset timeout configs since sanitizers are known to be time-hungry.
        sandbox_params.timeout = None
        sandbox_params.wallclock_timeout = None
        sanitized = True

    sandbox_params.set_stdall(
        stdin=PosixPath(file_mapping.input) if stdin is not None else None,
        stdout=PosixPath(file_mapping.output) if stdout is not None else None,
        stderr=PosixPath(file_mapping.error)
        if stderr is not None or sanitized
        else None,
    )

    assert execution_options.command
    command = get_mapped_command(execution_options.command, file_mapping)
    command = substitute_commands([command], sanitized=sanitized)[0]

    if extra_args is not None:
        splitted_command = shlex.split(command)
        splitted_command.extend(shlex.split(extra_args))
        command = shlex.join(splitted_command)

    artifacts = GradingArtifacts()
    artifacts.inputs.append(
        GradingFileInput(
            **executable.expand(),
            dest=PosixPath(file_mapping.executable),
            executable=True,
        )
    )
    if stdin is not None:
        artifacts.inputs.append(
            GradingFileInput(
                **stdin.expand(),
                dest=PosixPath(file_mapping.input),
            )
        )
    if stdout is not None:
        artifacts.outputs.append(
            GradingFileOutput(
                src=PosixPath(file_mapping.output),
                **stdout.expand(),
            )
        )
    if stderr is not None:
        artifacts.outputs.append(
            GradingFileOutput(
                src=PosixPath(file_mapping.error),
                **stderr.expand(),
            )
        )
    if inputs:
        artifacts.inputs.extend(inputs)
    if outputs:
        artifacts.outputs.extend(outputs)

    run_log = steps_with_caching.run(
        command,
        params=sandbox_params,
        sandbox=sandbox,
        artifacts=artifacts,
        dependency_cache=dependency_cache,
        metadata=RunLogMetadata(
            language=code.language,
            is_sanitized=sanitized,
            timeLimit=sandbox_params.timeout,
            memoryLimit=sandbox_params.address_space,
        ),
    )

    # Find sanitizer logs.
    if run_log is not None and run_log.warnings:
        assert sandbox_params.stderr_file is not None
        stderr_output = artifacts.get_output_file_for_src(sandbox_params.stderr_file)
        if stderr_output is not None:
            warning_stack.get_warning_stack().add_sanitizer_warning(
                package.get_cache_storage(), code, stderr_output
            )
    return run_log
