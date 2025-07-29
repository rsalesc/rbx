import dataclasses
import pathlib
import re
import resource
import shlex
import sys
from enum import Enum
from pathlib import PosixPath
from typing import List, Optional

import rich
import rich.text
import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import download, global_package, package, setter_config, state
from rbx.box.environment import (
    CompilationConfig,
    ExecutionConfig,
    FileMapping,
    get_compilation_config,
    get_execution_config,
    get_file_mapping,
    get_language,
    get_mapped_command,
    get_mapped_commands,
    get_sandbox_params_from_config,
    merge_execution_configs,
)
from rbx.box.formatting import get_formatted_memory
from rbx.box.remote import is_path_remote
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import CodeItem
from rbx.grading import grading_context, profiling, steps, steps_with_caching
from rbx.grading.judge.sandbox import SandboxParams
from rbx.grading.steps import (
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    RunLog,
    RunLogMetadata,
    get_exe_from_command,
    is_cpp_command,
    is_cxx_command,
    maybe_get_bits_stdcpp_for_commands,
)

MERGED_CAPTURE_FILENAME = 'merged_capture.pio'


class SanitizationLevel(Enum):
    NONE = 0
    PREFER = 1
    FORCE = 2

    def should_sanitize(self) -> bool:
        cfg = setter_config.get_setter_config()
        if cfg.sanitizers.enabled or state.STATE.sanitized:
            return self.value >= SanitizationLevel.PREFER.value
        return self.value >= SanitizationLevel.FORCE.value


class CompilationMetadata(BaseModel):
    is_sanitized: bool


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
    if executable.digest.value is None:
        return False
    cacher = package.get_file_cacher()
    desc = cacher.get_metadata(
        executable.digest.value, 'compilation', CompilationMetadata
    )
    if desc is None:
        return False
    return desc.is_sanitized


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


def maybe_rename_java_class(
    compilable_path: pathlib.Path, file_mapping: FileMapping
) -> pathlib.Path:
    mapped_path = PosixPath(file_mapping.compilable)
    if mapped_path.suffix != '.java':
        return compilable_path
    import re

    cls_name = mapped_path.stem

    java_content = compilable_path.read_text()
    regex = re.compile(r'public\s+class\s+[A-Za-z0-9_$]+([^A-Za-z0-9_$])')
    match = regex.search(java_content)
    if match is None:
        console.console.print(
            f'[error]Java public class not found in file: [item]{compilable_path}[/item][/error]'
        )
        raise typer.Exit(1)

    new_content = regex.sub(f'public class {cls_name}\\1', java_content)
    if new_content == java_content:
        return compilable_path

    preprocessed_path = package.get_problem_preprocessed_path(compilable_path)
    preprocessed_path.write_text(new_content)
    return preprocessed_path


def _format_stack_limit(limit: int) -> str:
    if limit == resource.RLIM_INFINITY:
        return 'unlimited'
    return get_formatted_memory(limit)


def _check_stack_limit():
    cfg = setter_config.get_setter_config()
    if not cfg.judging.check_stack:
        return
    if not state.STATE.run_through_cli:
        return
    if sys.platform != 'darwin':
        return
    soft, hard = resource.RLIM_INFINITY, resource.RLIM_INFINITY

    TARGET = 256 * 1024 * 1024  # 256 MiB
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
    except Exception:
        pass

    if soft != hard and soft != resource.RLIM_INFINITY and soft < TARGET:
        soft_fmt = _format_stack_limit(soft)
        hard_fmt = _format_stack_limit(hard)
        console.console.print(
            f'[error]Stack limit is too low (limit is set as [item]{soft_fmt}[/item], but configured user capacity is [item]{hard_fmt}[/item]).[/error]'
        )
        console.console.print(
            '[error]It is not safe to develop problems in [item]rbx[/item] with this configuration.[/error]'
        )
        console.console.print(
            'To solve this, add the following lines to the end of your [item]~/.bashrc[/item] or [item]~/.zshrc[/item] file (or equivalent shell configuration file):'
        )

        target_text = TARGET
        if hard != resource.RLIM_INFINITY:
            target_text = min(hard, TARGET)
        console.console.print(
            f"""
```
function rbx() {{
    local rbx_bin=`bash -c "type -P rbx"`
    ulimit -s {target_text // 1024} && $rbx_bin "$@"
}}
```
        """
        )
        console.console.print()
        console.console.print(
            'You can read more about this in [item]https://rsalesc.github.io/rbx/stack-limit/[/item].'
        )
        raise typer.Exit(1)


@dataclasses.dataclass
class PreparedRun:
    command: str
    sandbox_params: SandboxParams
    artifacts: GradingArtifacts
    sanitized: bool

    file_mapping: FileMapping
    metadata: RunLogMetadata


def _prepare_run(
    code: CodeItem,
    executable: DigestOrSource,
    stdin: Optional[DigestOrSource] = None,
    stdout: Optional[DigestOrDest] = None,
    stderr: Optional[DigestOrDest] = None,
    inputs: Optional[List[GradingFileInput]] = None,
    outputs: Optional[List[GradingFileOutput]] = None,
    extra_args: Optional[str] = None,
    extra_config: Optional[ExecutionConfig] = None,
    retry_index: Optional[int] = None,
    file_prefix: Optional[str] = None,
):
    language = find_language_name(code)
    execution_options = get_execution_config(language)
    if extra_config is not None:
        execution_options = merge_execution_configs([execution_options, extra_config])
    file_mapping = get_file_mapping(language, file_prefix)
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
                touch=True,
            )
        )
    if stderr is not None:
        artifacts.outputs.append(
            GradingFileOutput(
                src=PosixPath(file_mapping.error),
                **stderr.expand(),
                touch=True,
            )
        )
    if inputs:
        artifacts.inputs.extend(inputs)
    if outputs:
        artifacts.outputs.extend(outputs)

    return PreparedRun(
        command=command,
        sandbox_params=sandbox_params,
        artifacts=artifacts,
        sanitized=sanitized,
        file_mapping=file_mapping,
        metadata=RunLogMetadata(
            language=code.language,
            is_sanitized=sanitized,
            timeLimit=sandbox_params.timeout,
            memoryLimit=sandbox_params.address_space,
            limits=execution_options.problemLimits,
            retryIndex=retry_index,
        ),
    )


def _should_precompile(commands: List[str]) -> bool:
    return any(is_cpp_command(command) for command in commands)


def _precompile_header(
    compilation_options: CompilationConfig,
    sanitized: SanitizationLevel,
    sandbox_params: SandboxParams,
    artifacts: GradingArtifacts,
    input_artifact: GradingFileInput,
    force_warnings: bool = False,
    verbose: bool = False,
    include_other_headers: bool = False,
) -> GradingFileInput:
    """
    Precompile a header file (.h).

    Assumes input artifact is a header file (.h) and compilation commands are C++.
    """
    assert compilation_options.commands is not None

    sandbox = global_package.get_global_sandbox()
    dependency_cache = global_package.get_global_dependency_cache()

    # TODO: deduplicate code with compile_item.
    commands = get_mapped_commands(
        compilation_options.commands,
        FileMapping(
            compilable='precompilable.h',
            executable='precompilable.h.gch',
        ),
    )
    commands = add_warning_flags(commands, force_warnings)
    commands = substitute_commands(commands, sanitized=sanitized.should_sanitize())

    if sanitized.should_sanitize():
        commands = add_sanitizer_flags(commands)

    precompilation_artifacts = GradingArtifacts()

    # Keep only header files.
    if include_other_headers:
        precompilation_artifacts.inputs = [
            input
            for input in artifacts.inputs
            if input.src is not None and input.src.suffix == '.h'
        ]
    precompilation_artifacts.inputs.append(
        GradingFileInput(
            src=input_artifact.src,
            dest=PosixPath('precompilable.h'),
        )
    )

    # Pull only the precompiled header file.
    precompiled_digest = DigestHolder()
    precompilation_artifacts.outputs.append(
        GradingFileOutput(
            src=PosixPath('precompilable.h.gch'),
            digest=precompiled_digest,
        )
    )

    with profiling.PushContext('code.precompile_header'):
        if not steps_with_caching.compile(
            commands,
            params=sandbox_params,
            artifacts=precompilation_artifacts,
            sandbox=sandbox,
            dependency_cache=dependency_cache,
        ):
            console.console.print(
                f'[error]Failed to precompile header file: [item]{input_artifact.src}[/item][/error]'
            )
            raise typer.Exit(1)

        if verbose:
            console.console.print(
                f'[status]Precompiled header file: [item]{input_artifact.src}[/item]'
            )

            if (
                precompilation_artifacts.logs is not None
                and precompilation_artifacts.logs.preprocess is not None
            ):
                for log in precompilation_artifacts.logs.preprocess:
                    console.console.print(
                        f'[status]Command:[/status] {log.get_command()}'
                    )
                    console.console.print(
                        f'[status]Summary:[/status] {log.get_summary()}'
                    )

    assert precompiled_digest.value is not None

    digest_path = dependency_cache.cacher.path_for_symlink(precompiled_digest.value)
    if digest_path is not None and digest_path.is_file():
        # If storage backend supports symlinks, use it as the grading input.
        input = DigestOrSource.create(digest_path)
    else:
        # Otherwise, copy the file to the local cache, transiently.
        local_cacher = package.get_file_cacher()
        with dependency_cache.cacher.get_file(precompiled_digest.value) as f:
            with grading_context.cache_level(
                grading_context.CacheLevel.CACHE_TRANSIENTLY
            ):
                input = DigestOrSource.create(local_cacher.put_file_from_fobj(f))

    return GradingFileInput(
        **input.expand(),
        dest=input_artifact.dest.with_suffix('.h.gch'),
        # Do not track fingerprint of the precompiled header file,
        # trust the compilation step above.
        hash=False,
    )


# Compile code item and return its digest in the storage.
def compile_item(
    code: CodeItem,
    sanitized: SanitizationLevel = SanitizationLevel.PREFER,
    force_warnings: bool = False,
    verbose: bool = False,
    precompile: bool = True,
) -> str:
    _check_stack_limit()

    compilable_path = PosixPath(code.path)

    if not compilable_path.is_file():
        console.console.print(
            f'[error]Compilation file not found: [item]{compilable_path}[/item][/error]'
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
        return sandbox.file_cacher.put_file_from_path(compilable_path)

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
    download.maybe_add_rbx_header(code, artifacts)
    compilable_path = maybe_rename_java_class(compilable_path, file_mapping)
    artifacts.inputs.append(
        GradingFileInput(src=compilable_path, dest=PosixPath(file_mapping.compilable))
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

    # Add system bits/stdc++.h to the compilation.
    bits_artifact = maybe_get_bits_stdcpp_for_commands(commands)
    if bits_artifact is not None:
        artifacts.inputs.append(bits_artifact)
        commands = [
            command + ' -I.'
            for command in commands
            if is_cxx_command(get_exe_from_command(command))
        ]

    # Precompile C++ interesting header files.
    if precompile and _should_precompile(commands):
        with profiling.Profiler('code.precompile'):
            precompilation_inputs = []
            for input in artifacts.inputs:
                if (
                    input.src is not None
                    and input.src.suffix == '.h'
                    and input.dest.name in ['stdc++.h', 'jngen.h', 'testlib.h']
                ):
                    precompilation_inputs.append(
                        _precompile_header(
                            compilation_options,
                            sanitized,
                            sandbox_params,
                            artifacts,
                            input,
                            force_warnings,
                            verbose=False,
                        )
                    )
            if precompilation_inputs:
                artifacts.inputs.extend(precompilation_inputs)

    with profiling.Profiler('code.compile'):
        # Compile the code.
        # Do not cache remote solutions.
        with grading_context.cache_level(
            grading_context.CacheLevel.NO_CACHE,
            when=lambda: is_path_remote(code.path),
        ):
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
        console.console.print(f'[status]Compiled item: [item]{code.path}[/item]')
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
    cacher = package.get_file_cacher()
    if sanitized.should_sanitize():
        cacher.set_metadata(
            compiled_digest.value, 'compilation', CompilationMetadata(is_sanitized=True)
        )
    else:
        cacher.set_metadata(compiled_digest.value, 'compilation', None)

    return compiled_digest.value


async def run_item(
    code: CodeItem,
    executable: DigestOrSource,
    stdin: Optional[DigestOrSource] = None,
    stdout: Optional[DigestOrDest] = None,
    stderr: Optional[DigestOrDest] = None,
    inputs: Optional[List[GradingFileInput]] = None,
    outputs: Optional[List[GradingFileOutput]] = None,
    extra_args: Optional[str] = None,
    extra_config: Optional[ExecutionConfig] = None,
    retry_index: Optional[int] = None,
) -> Optional[RunLog]:
    _check_stack_limit()

    dependency_cache = package.get_dependency_cache()

    prepared = _prepare_run(
        code,
        executable,
        stdin,
        stdout,
        stderr,
        inputs,
        outputs,
        extra_args,
        extra_config,
        retry_index,
    )

    with profiling.PushContext('code.run_item'):
        # Do not cache remote solutions.
        with grading_context.cache_level(
            grading_context.CacheLevel.NO_CACHE,
            when=lambda: is_path_remote(code.path),
        ):
            run_log = await steps_with_caching.run(
                prepared.command,
                params=prepared.sandbox_params,
                sandbox=package.get_singleton_sandbox(),
                artifacts=prepared.artifacts,
                dependency_cache=dependency_cache,
                metadata=prepared.metadata,
            )

    # Find sanitizer logs.
    if run_log is not None and run_log.warnings:
        assert prepared.sandbox_params.stderr_file is not None
        stderr_output = prepared.artifacts.get_output_file_for_src(
            prepared.sandbox_params.stderr_file
        )
        if stderr_output is not None:
            warning_stack.get_warning_stack().add_sanitizer_warning(
                package.get_file_cacher(), code, stderr_output
            )
    return run_log


@dataclasses.dataclass
class CommunicationItem:
    code: CodeItem
    executable: DigestOrSource
    file_prefix: str
    stderr: Optional[DigestOrDest] = None
    inputs: Optional[List[GradingFileInput]] = None
    outputs: Optional[List[GradingFileOutput]] = None
    extra_args: Optional[str] = None
    extra_config: Optional[ExecutionConfig] = None
    capture: Optional[DigestOrDest] = None

    def prepare(self) -> PreparedRun:
        return _prepare_run(
            self.code,
            self.executable,
            stdout=self.capture,
            stderr=self.stderr,
            inputs=self.inputs,
            outputs=self.outputs,
            extra_args=self.extra_args,
            extra_config=self.extra_config,
            file_prefix=self.file_prefix,
        )


async def run_communication(
    interactor: CommunicationItem,
    solution: CommunicationItem,
    merged_capture: Optional[DigestOrDest] = None,
    retry_index: Optional[int] = None,
):
    interactor_prepared = interactor.prepare()
    solution_prepared = solution.prepare()

    # Prepare retry index.
    interactor_prepared.metadata.retryIndex = retry_index
    solution_prepared.metadata.retryIndex = retry_index

    grading_artifacts = GradingArtifacts()
    grading_artifacts.inputs.extend(interactor_prepared.artifacts.inputs)
    grading_artifacts.outputs.extend(interactor_prepared.artifacts.outputs)
    grading_artifacts.inputs.extend(solution_prepared.artifacts.inputs)
    grading_artifacts.outputs.extend(solution_prepared.artifacts.outputs)

    merged_capture_path: Optional[pathlib.Path] = None
    if merged_capture is not None:
        merged_capture_path = pathlib.Path(MERGED_CAPTURE_FILENAME)
        grading_artifacts.outputs.append(
            GradingFileOutput(
                src=merged_capture_path,
                **merged_capture.expand(),
            )
        )

    interactor_run_params = steps.CoordinatedRunParams(
        command=interactor_prepared.command,
        params=interactor_prepared.sandbox_params,
        metadata=interactor_prepared.metadata,
    )
    solution_run_params = steps.CoordinatedRunParams(
        command=solution_prepared.command,
        params=solution_prepared.sandbox_params,
        metadata=solution_prepared.metadata,
    )

    # Do not cache remote solutions.
    with grading_context.cache_level(
        grading_context.CacheLevel.NO_CACHE,
        when=lambda: is_path_remote(solution.code.path),
    ):
        return await steps_with_caching.run_coordinated(
            interactor_run_params,
            solution_run_params,
            sandbox=package.get_singleton_sandbox(),
            artifacts=grading_artifacts,
            dependency_cache=package.get_dependency_cache(),
            merged_capture=merged_capture_path,
        )
