import functools
import pathlib
from enum import Enum
from typing import Annotated, List, Optional, Type, TypeVar

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rbx import config, console, utils
from rbx.box import presets
from rbx.box.extensions import Extensions, LanguageExtensions
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.limits import Limits

T = TypeVar('T', bound=BaseModel)


class VerificationLevel(Enum):
    NONE = 0
    VALIDATE = 1
    FAST_SOLUTIONS = 2
    ALL_SOLUTIONS = 3
    FULL = 4


VerificationParam = Annotated[
    int,
    typer.Option(
        '--verification-level',
        '--verification',
        '-v',
        help='Verification level to use when building package.',
        default_factory=lambda: VerificationLevel.FULL.value,
    ),
]


class FileMapping(BaseModel):
    model_config = ConfigDict(extra='forbid')

    input: str = Field(
        default='stdin',
        description="""Path where to copy the stdin file to before running the program,
relative to the sandbox root.""",
    )

    output: str = Field(
        default='stdout',
        description="""Path where to output the stdout file after running the program,
relative to the sandbox root.""",
    )

    error: str = Field(
        default='stderr',
        description="""Path where to output the stderr file after running the program,
relative to the sandbox root.""",
    )

    capture: str = Field(
        default='capture',
        description="""Path where to output the capture file after running the program,
relative to the sandbox root.""",
    )

    compilable: str = Field(
        default='compilable',
        description="""Path where to copy the compilable file to before compiling the program,
relative to the sandbox root.""",
    )

    executable: str = Field(
        default='executable',
        description="""Path to where to output the executable file after compiling the program,
relative to the sandbox root.""",
    )


class EnvironmentSandbox(BaseModel):
    model_config = ConfigDict(extra='forbid')

    maxProcesses: Optional[int] = Field(
        default=1,
        description="""Max. number of process to allow to run concurrently for the program.""",
    )

    timeLimit: Optional[int] = Field(
        default=None,
        description="""Time limit in milliseconds to allow the program to run.""",
    )

    wallTimeLimit: Optional[int] = Field(
        default=None,
        description="""Wall time limit in milliseconds to allow the program to run.""",
    )

    memoryLimit: Optional[int] = Field(
        default=None,
        description="""Memory limit in MiB.""",
    )

    fileSizeLimit: Optional[int] = Field(
        default=None,
        description="""File size limit in KiB""",
    )

    stackLimit: Optional[int] = Field(
        default=None,
        description="""Stack limit in MiB.""",
    )

    preserveEnv: Optional[bool] = Field(
        default=False,
        description="""Whether to preserve env. variables coming from the host.""",
    )

    mirrorDirs: Optional[List[str]] = Field(
        default=[],
        description="""Directories in the host that should be read-only exposed to the sandbox.""",
    )


class CompilationConfig(BaseModel):
    commands: Optional[List[str]] = Field(
        default=[],
        description="""Commands to compile the program.""",
    )

    sandbox: Optional[EnvironmentSandbox] = Field(
        default=None,
        description="""Sandbox configuration to use when compiling for this language.""",
    )


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    command: Optional[str] = Field(
        default=None,
        description="""Command to run the program.""",
    )

    sandbox: Optional[EnvironmentSandbox] = Field(
        default=None,
        description="""Sandbox configuration to use when executing for this language.""",
    )

    problemLimits: Limits = Field(
        default_factory=Limits,
        description="""Original limits of the problem.""",
    )


class EnvironmentLanguage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(
        description="""Identifier of this language within this environment."""
    )

    readableName: Optional[str] = Field(
        default=None,
        description="""Readable name for this language.""",
    )

    extension: str = Field(
        description="""File extension supported by this language. If there's only one language
that supports a certain file extension in the environment, the tool
will automatically identify the language based on such extension."""
    )

    compilation: Optional[CompilationConfig] = Field(
        default=None,
        description="""Compilation config to use when compiling programs for this language.""",
    )

    execution: ExecutionConfig = Field(
        description="""Execution config to use when running programs for this language."""
    )

    fileMapping: Optional[FileMapping] = Field(
        default=None,
        description="""Mapping for files within the sandbox. If not specified, the default mapping
for the environment will be used.""",
    )

    extensions: Optional[LanguageExtensions] = Field(
        default=None,
        description="""Extensions to apply for this language.""",
    )

    def get_extension(self, name: str, _: Type[T]) -> Optional[T]:
        if self.extensions is None:
            return None
        if not hasattr(self.extensions, name):
            return None
        return getattr(self.extensions, name)

    def get_extension_or_default(self, name: str, cls: Type[T]) -> T:
        return self.get_extension(name, cls) or cls()


class TimingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    formula: str = Field(
        default='step_up(max(fastest * 3, slowest * 1.5), 100)',
        description="""Formula to use to calculate the time limit for the environment.""",
    )


class Environment(BaseModel):
    model_config = ConfigDict(extra='forbid')

    defaultFileMapping: Optional[FileMapping] = Field(
        default=None,
        description="""Default mapping for files within the sandbox. Fields in the mapping can be
individually overridden in the language configuration.""",
    )

    defaultCompilation: Optional[CompilationConfig] = Field(
        default=None,
        description="""Default compilation configuration to use when compiling programs. Fields in
the compilation config can be individually overridden in the language configuration.""",
    )

    defaultExecution: Optional[ExecutionConfig] = Field(
        default=None,
        description="""Default execution configuration to use when running programs. Fields in the
execution config can be individually overridden in the language configuration.""",
    )

    languages: List[EnvironmentLanguage] = Field(
        default=[],
        description="""Configuration for each language supported in this environment.""",
    )

    sandbox: str = Field(
        default='stupid',
        description="""Identifier of the sandbox used by this environment (e.g. "stupid")""",
    )

    timing: TimingConfig = Field(
        default_factory=TimingConfig,
        description="""Timing configuration for the environment.""",
    )

    extensions: Optional[Extensions] = Field(
        default=None,
        description="""Extensions to be added to the environment.""",
    )


def get_app_environment_path(env: str) -> pathlib.Path:
    return config.get_resources_file(pathlib.PosixPath('envs') / f'{env}.rbx.yml')


def get_active_environment_path() -> pathlib.Path:
    env_path = presets.get_preset_environment_path()
    if env_path is None:
        env_path = get_app_environment_path('default')
    return env_path


@functools.cache
def get_active_environment_description() -> str:
    env_path = presets.get_preset_environment_path()
    if env_path is None:
        return 'default'
    preset = presets.get_active_preset()
    return f'preset - {preset.name}'


@functools.cache
def get_environment(env: Optional[str] = None) -> Environment:
    env_path = (
        get_app_environment_path(env)
        if env is not None
        else get_active_environment_path()
    )
    if not env_path.is_file():
        console.console.print(
            f'Environment file [item]{env_path}[/item] not found.', style='error'
        )
        raise typer.Exit()
    try:
        return utils.model_from_yaml(Environment, env_path.read_text())
    except ValidationError as e:
        console.console.print(e)
        console.console.print(
            f'[error]Error parsing environment file [item]{env_path}[/item][/error]'
        )
        raise typer.Exit(1) from e


@functools.cache
def get_language(name: str) -> EnvironmentLanguage:
    for lang in get_environment().languages:
        if lang.name == name:
            return lang
    console.console.print(f'Language [item]{name}[/item] not found.', style='error')
    raise typer.Exit()


@functools.cache
def get_language_by_extension(extension: str) -> EnvironmentLanguage:
    for lang in get_environment().languages:
        if lang.extension == extension:
            return lang
    console.console.print(
        f'Language with extension [item]{extension}[/item] not found.', style='error'
    )
    raise typer.Exit()


def install_environment(name: str, file: pathlib.Path):
    if not file.is_file():
        console.console.print(
            f'[error]Environment file [item]{file}[/item] could not be found.'
        )
        raise typer.Exit(1)

    get_app_environment_path(name).parent.mkdir(parents=True, exist_ok=True)
    get_app_environment_path(name).write_bytes(file.read_bytes())
    console.console.print(
        f'[success]Environment [item]{name}[/item] was installed from [item]{file}[/item]'
    )


def _merge_shallow_models(model: Type[T], base: T, override: T) -> T:
    return model(
        **{
            **base.model_dump(exclude_unset=True),
            **override.model_dump(exclude_unset=True),
        }
    )


def merge_compilation_configs(
    compilation_configs: List[Optional[CompilationConfig]],
) -> CompilationConfig:
    merged_cfg = CompilationConfig()
    merged_cfg.sandbox = EnvironmentSandbox(
        maxProcesses=None,
        timeLimit=10000,
        wallTimeLimit=10000,
        memoryLimit=512,
        preserveEnv=True,
        mirrorDirs=['/etc', '/usr'],
    )
    for cfg in compilation_configs:
        if cfg is None:
            continue
        merged_cfg.commands = cfg.commands or merged_cfg.commands
        if cfg.sandbox is not None:
            merged_cfg.sandbox = _merge_shallow_models(
                EnvironmentSandbox, merged_cfg.sandbox, cfg.sandbox
            )
    return merged_cfg


@functools.cache
def get_compilation_config(language: str) -> CompilationConfig:
    environment = get_environment()
    return merge_compilation_configs(
        [environment.defaultCompilation, get_language(language).compilation]
    )


def merge_execution_configs(
    execution_configs: List[Optional[ExecutionConfig]],
) -> ExecutionConfig:
    merged_cfg = ExecutionConfig()
    merged_cfg.sandbox = EnvironmentSandbox()
    merged_cfg.problemLimits = Limits()
    for cfg in execution_configs:
        if cfg is None:
            continue
        merged_cfg.command = cfg.command or merged_cfg.command
        if cfg.sandbox is not None:
            merged_cfg.sandbox = _merge_shallow_models(
                EnvironmentSandbox, merged_cfg.sandbox, cfg.sandbox
            )
        if cfg.problemLimits is not None:
            merged_cfg.problemLimits = _merge_shallow_models(
                Limits, merged_cfg.problemLimits, cfg.problemLimits
            )
    return merged_cfg


@functools.cache
def get_execution_config(language: str) -> ExecutionConfig:
    environment = get_environment()
    return merge_execution_configs(
        [environment.defaultExecution, get_language(language).execution]
    )


@functools.cache
def get_file_mapping(language: str, file_prefix: Optional[str] = None) -> FileMapping:
    environment = get_environment()
    mapping = _merge_shallow_models(
        FileMapping,
        environment.defaultFileMapping or FileMapping(),
        get_language(language).fileMapping or FileMapping(),
    )
    if file_prefix is not None:
        mapping.input = f'{file_prefix}_{mapping.input}'
        mapping.output = f'{file_prefix}_{mapping.output}'
        mapping.error = f'{file_prefix}_{mapping.error}'
        mapping.compilable = f'{file_prefix}_{mapping.compilable}'
        mapping.executable = f'{file_prefix}_{mapping.executable}'
    return mapping


@functools.cache
def get_sandbox_type() -> Type[SandboxBase]:
    used_sandbox = get_environment().sandbox
    if used_sandbox == 'stupid':
        return StupidSandbox
    return StupidSandbox


def get_mapped_commands(
    commands: List[str], mapping: Optional[FileMapping] = None
) -> List[str]:
    mapping = mapping or FileMapping()
    return [cmd.format(**mapping.model_dump()) for cmd in commands]


def get_mapped_command(command: str, mapping: Optional[FileMapping] = None) -> str:
    return get_mapped_commands([command], mapping)[0]


def get_sandbox_params_from_config(
    config: Optional[EnvironmentSandbox],
) -> SandboxParams:
    config = config or EnvironmentSandbox()
    params = SandboxParams()
    params.timeout = config.timeLimit
    params.wallclock_timeout = config.wallTimeLimit
    params.address_space = config.memoryLimit
    params.max_processes = config.maxProcesses
    params.fsize = config.fileSizeLimit
    if config.preserveEnv:
        params.preserve_env = True
    if config.mirrorDirs:
        for dir in config.mirrorDirs:
            path = pathlib.Path(dir)
            params.add_mapped_directory(path)
    return params


def get_extension(name: str, _: Type[T]) -> Optional[T]:
    pkg = get_environment()
    if pkg.extensions is None:
        return None
    if not hasattr(pkg.extensions, name):
        return None
    return getattr(pkg.extensions, name)


def get_extension_or_default(name: str, cls: Type[T]) -> T:
    return get_extension(name, cls) or cls()
