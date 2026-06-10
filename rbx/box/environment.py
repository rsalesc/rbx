import functools
import pathlib
import shlex
from enum import Enum
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import typer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rbx import config, console
from rbx.box import presets, safeeval
from rbx.box.extensions import Extensions, LanguageExtensions
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.yaml_validation import load_yaml_model
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.language_kind import LanguageKind, command_kinds
from rbx.grading.limits import Limits

T = TypeVar('T', bound=BaseModel)


class VerificationLevel(Enum):
    NONE = 0
    VALIDATE = 1
    FAST_SOLUTIONS = 2
    ALL_SOLUTIONS = 3
    FULL = 4


def _verification_autocompletion():
    # Indirect through a function so module load doesn't eagerly depend on
    # rbx.annotations (keeps this module's import surface decoupled; the import
    # is light either way).
    from rbx import annotations

    return annotations._adapt('verification_level')  # noqa: SLF001


VerificationParam = Annotated[
    int,
    typer.Option(
        '--verification-level',
        '--verification',
        '-v',
        help='Verification level to use when building package.',
        default_factory=lambda: VerificationLevel.FULL.value,
        autocompletion=_verification_autocompletion(),
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
        default='{source}',
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


class BaseCompilationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    commands: Optional[List[str]] = Field(
        default=[],
        description="""Commands to compile the program.""",
    )

    sandbox: Optional[EnvironmentSandbox] = Field(
        default=None,
        description="""Sandbox configuration to use when compiling for this language.""",
    )

    passthrough: Optional[bool] = Field(
        default=None,
        description="""Whether to pass through the compilable as an executable file.""",
    )


class SolutionCompilationOverrides(BaseCompilationConfig):
    pass


class CompilationConfig(BaseCompilationConfig):
    solutionOverrides: SolutionCompilationOverrides = Field(
        default_factory=SolutionCompilationOverrides,
        description="""Overrides to apply when compiling solutions for this language.""",
    )


class BaseExecutionConfig(BaseModel):
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


class SolutionExecutionOverrides(BaseExecutionConfig):
    pass


class ExecutionConfig(BaseExecutionConfig):
    solutionOverrides: SolutionExecutionOverrides = Field(
        default_factory=SolutionExecutionOverrides,
        description="""Overrides to apply when executing solutions for this language.""",
    )


class LinterConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(description='Name of the linter to run (see registry).')
    applies_to: Optional[List[AssetKind]] = Field(
        default=None,
        description='Asset kinds this linter applies to. None means all kinds.',
    )

    @field_validator('applies_to', mode='before')
    @classmethod
    def _normalize_applies_to(cls, v):
        if v is None:
            return None
        out = []
        for item in v:
            if isinstance(item, AssetKind):
                out.append(item)
                continue
            token = str(item).rstrip('s')  # 'generators' -> 'generator'
            out.append(AssetKind(token))
        return out


class LanguageTimingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    wallTimeMultiplier: Optional[float] = Field(
        default=None,
        ge=1.0,
        description="""Overrides the environment wall-time multiplier `a` for this language.""",
    )

    wallTimeIncrement: Optional[int] = Field(
        default=None,
        ge=0,
        description="""Overrides the environment wall-time increment `b` (in milliseconds) for this language.""",
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

    extraExtensions: List[str] = Field(
        default_factory=list,
        description="""Extra file extensions supported by this language. If not specified, the tool
will automatically identify the language based on such extensions.""",
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

    linters: List[LinterConfig] = Field(
        default_factory=list,
        description="""Linters to run for this language during compilation.""",
    )

    scanners: List[str] = Field(
        default_factory=list,
        description="""Dependency scanners (by registry name) to apply for this
language, in addition to the ones automatically selected by language kind.""",
    )

    timing: Optional[LanguageTimingConfig] = Field(
        default=None,
        description="""Per-language overrides for timing configuration (e.g. wall time).""",
    )

    @field_validator('linters', mode='before')
    @classmethod
    def _coerce_linter_shorthand(cls, v):
        if v is None:
            return []
        return [{'name': item} if isinstance(item, str) else item for item in v]

    def get_extension(self, name: str, _: Type[T]) -> Optional[T]:
        if self.extensions is None:
            return None
        if not hasattr(self.extensions, name):
            return None
        return getattr(self.extensions, name)

    def get_extension_or_default(self, name: str, cls: Type[T]) -> T:
        return self.get_extension(name, cls) or cls()


class LanguageGroupFallback(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    relativeTo: Optional[str] = Field(
        default=None,
        description="""A language name whose group's estimated TL this empty group is
relative to. If omitted, the multiplier is applied to the base estimate.""",
    )
    multiplier: float = Field(
        gt=0,
        description="""Slope applied to the reference TL when this group has no
solutions. The resolved TL is ``multiplier * reference + increment``.""",
    )
    increment: Optional[int] = Field(
        default=None,
        description="""Constant offset (in milliseconds) added on top of the
multiplied reference TL when this group has no solutions. The resolved TL is
``multiplier * reference + increment``.""",
    )


class LanguageGroup(BaseModel):
    model_config = ConfigDict(extra='forbid')

    languages: List[str] = Field(
        description="""rbx language names that share a single estimated time limit.""",
    )
    whenEmpty: Optional[LanguageGroupFallback] = Field(
        default=None,
        description="""How to derive a TL for this group when it has no solutions.""",
    )


class TimingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    formula: str = Field(
        default='step_up(max(fastest * 3, slowest * 1.5), 100)',
        description="""Formula to use to calculate the time limit for the environment.""",
    )

    groups: List[LanguageGroup] = Field(
        default_factory=list,
        description="""Groups of related languages that share an estimated time limit.""",
    )

    wallTimeMultiplier: float = Field(
        default=2.0,
        ge=1.0,
        description="""Default multiplier `a` in the wall-time formula `a*x + b`, where `x` is the expanded CPU time limit.""",
    )

    wallTimeIncrement: int = Field(
        default=0,
        ge=0,
        description="""Default increment `b` (in milliseconds) in the wall-time formula `a*x + b`.""",
    )

    @model_validator(mode='after')
    def _validate_disjoint_groups(self):
        seen: set[str] = set()
        for group in self.groups:
            for lang in group.languages:
                if lang in seen:
                    raise ValueError(
                        f'Language {lang!r} appears in more than one timing group; '
                        'groups must be disjoint.'
                    )
                seen.add(lang)
        return self


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

    buildDir: pathlib.Path = Field(
        default=pathlib.Path('build'),
        description="""Directory to store the build files.""",
    )


def get_app_environment_path(env: str) -> pathlib.Path:
    return config.get_resources_file(pathlib.PosixPath('presets') / env / 'env.rbx.yml')


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
    return load_yaml_model(env_path, Environment)


@functools.cache
def get_language_or_nil(name: str) -> Optional[EnvironmentLanguage]:
    for lang in get_environment().languages:
        if lang.name == name:
            return lang
    return None


def resolve_walltime_coeffs(
    timing: TimingConfig,
    language: Optional[EnvironmentLanguage],
) -> Tuple[float, int]:
    """Resolves the effective (wall_time_multiplier, wall_time_increment_ms),
    where a per-language override takes precedence field-by-field over the
    environment-level timing defaults."""
    multiplier = timing.wallTimeMultiplier
    increment = timing.wallTimeIncrement
    if language is not None and language.timing is not None:
        if language.timing.wallTimeMultiplier is not None:
            multiplier = language.timing.wallTimeMultiplier
        if language.timing.wallTimeIncrement is not None:
            increment = language.timing.wallTimeIncrement
    return multiplier, increment


def apply_walltime_formula(cpu_tl_ms: int, coeffs: Tuple[float, int]) -> int:
    """Applies wall = a*x + b, where x is the expanded CPU time limit (ms)."""
    multiplier, increment = coeffs
    return int(cpu_tl_ms * multiplier + increment)


def get_walltime_coeffs_for_language(
    language: Optional[str],
) -> Tuple[float, int]:
    """Reads the active environment and resolves wall-time coefficients for the
    given language name (None -> environment defaults)."""
    env = get_environment()
    lang = get_language_or_nil(language) if language is not None else None
    return resolve_walltime_coeffs(env.timing, lang)


def compute_walltime(cpu_tl_ms: int, language: Optional[str]) -> int:
    """Computes the wall-time limit (ms) for a CPU time limit (ms) under the active environment's coefficients for the given language."""
    return apply_walltime_formula(cpu_tl_ms, get_walltime_coeffs_for_language(language))


def get_language(name: str) -> EnvironmentLanguage:
    lang = get_language_or_nil(name)
    if lang is not None:
        return lang
    console.console.print(f'[error]Language [item]{name}[/item] not found.[/error]')
    raise typer.Exit()


@functools.cache
def get_language_by_extension_or_nil(extension: str) -> Optional[EnvironmentLanguage]:
    for lang in get_environment().languages:
        if lang.extension == extension:
            return lang
    for lang in get_environment().languages:
        if extension in lang.extraExtensions:
            return lang
    return None


def get_language_by_extension(extension: str) -> EnvironmentLanguage:
    lang = get_language_by_extension_or_nil(extension)
    if lang is not None:
        return lang
    console.console.print(
        f'[error]Language with extension [item]{extension}[/item] not found.[/error]'
    )
    raise typer.Exit()


def get_build_dir() -> pathlib.Path:
    return get_environment().buildDir


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
    solution: bool = False,
) -> BaseCompilationConfig:
    merged_cfg = BaseCompilationConfig()
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
        base_cfg: BaseCompilationConfig = cfg
        if solution:
            if cfg.solutionOverrides.commands:
                base_cfg.commands = cfg.solutionOverrides.commands
            if cfg.solutionOverrides.sandbox is not None:
                base_cfg.sandbox = cfg.solutionOverrides.sandbox
            if cfg.solutionOverrides.passthrough is not None:
                base_cfg.passthrough = cfg.solutionOverrides.passthrough
        merged_cfg.commands = base_cfg.commands or merged_cfg.commands
        if base_cfg.sandbox is not None:
            merged_cfg.sandbox = _merge_shallow_models(
                EnvironmentSandbox, merged_cfg.sandbox, base_cfg.sandbox
            )
        if base_cfg.passthrough is not None:
            merged_cfg.passthrough = base_cfg.passthrough
    return merged_cfg


@functools.cache
def get_compilation_config(
    language: str, solution: bool = False
) -> BaseCompilationConfig:
    environment = get_environment()
    return merge_compilation_configs(
        [environment.defaultCompilation, get_language(language).compilation],
        solution,
    )


def is_interpreted(language: str, solution: bool = False) -> bool:
    """Whether the language runs its source directly (the compilable is the
    executable) rather than producing a separate binary. This is exactly the
    signal ``compile_item`` uses to take the passthrough path."""
    config = get_compilation_config(language, solution)
    return bool(config.passthrough) or not config.commands


def language_kinds(language: EnvironmentLanguage) -> Set[LanguageKind]:
    """The set of :class:`LanguageKind` a language belongs to, derived from its
    toolchain: the compilation commands if it compiles, else its execution command.
    Deriving from the actual compiler/interpreter (not the language *name*) keeps
    dispatch robust to custom language names."""
    if language.compilation and language.compilation.commands:
        commands = list(language.compilation.commands)
    elif language.execution and language.execution.command:
        commands = [language.execution.command]
    else:
        commands = []

    kinds: Set[LanguageKind] = set()
    for command in commands:
        parts = shlex.split(command)
        kinds |= command_kinds(parts[0] if parts else command)
    return kinds


def merge_execution_configs(
    execution_configs: List[Optional[Union[ExecutionConfig, BaseExecutionConfig]]],
    solution: bool = False,
) -> BaseExecutionConfig:
    merged_cfg = BaseExecutionConfig()
    merged_cfg.sandbox = EnvironmentSandbox()
    merged_cfg.problemLimits = Limits()
    for cfg in execution_configs:
        if cfg is None:
            continue
        base_cfg: BaseExecutionConfig = cfg
        if solution and isinstance(cfg, ExecutionConfig):
            if cfg.solutionOverrides.command:
                base_cfg.command = cfg.solutionOverrides.command
            if cfg.solutionOverrides.sandbox is not None:
                base_cfg.sandbox = cfg.solutionOverrides.sandbox
        merged_cfg.command = base_cfg.command or merged_cfg.command
        if base_cfg.sandbox is not None:
            merged_cfg.sandbox = _merge_shallow_models(
                EnvironmentSandbox, merged_cfg.sandbox, base_cfg.sandbox
            )
        if base_cfg.problemLimits is not None:
            merged_cfg.problemLimits = _merge_shallow_models(
                Limits, merged_cfg.problemLimits, base_cfg.problemLimits
            )
    return merged_cfg


@functools.cache
def get_execution_config(language: str, solution: bool = False) -> BaseExecutionConfig:
    environment = get_environment()
    return merge_execution_configs(
        [environment.defaultExecution, get_language(language).execution],
        solution,
    )


def _evaluate_mapping(
    mapping: FileMapping, variables: Optional[dict[str, Any]] = None
) -> FileMapping:
    res = FileMapping()
    vars = (variables or {}).copy()
    res.compilable = safeeval.eval_as_fstring(mapping.compilable, vars)
    vars['compilable'] = res.compilable
    res.executable = safeeval.eval_as_fstring(mapping.executable, vars)
    vars['executable'] = res.executable

    res.input = safeeval.eval_as_fstring(mapping.input, vars)
    vars['input'] = res.input
    res.output = safeeval.eval_as_fstring(mapping.output, vars)
    vars['output'] = res.output
    res.error = safeeval.eval_as_fstring(mapping.error, vars)
    res.capture = safeeval.eval_as_fstring(mapping.capture, vars)
    return res


def get_raw_file_mapping(language: str) -> FileMapping:
    environment = get_environment()
    return _merge_shallow_models(
        FileMapping,
        environment.defaultFileMapping or FileMapping(),
        get_language(language).fileMapping or FileMapping(),
    )


def get_file_mapping(
    language: str,
    variables: Dict[str, Any],
    file_prefix: Optional[str] = None,
) -> FileMapping:
    mapping = get_raw_file_mapping(language)
    mapping = _evaluate_mapping(mapping, variables)
    if file_prefix is not None:
        mapping.input = f'{file_prefix}_{mapping.input}'
        mapping.output = f'{file_prefix}_{mapping.output}'
        mapping.error = f'{file_prefix}_{mapping.error}'
        if 'javaClass' not in variables:
            # Do not apply file prefixing to Java classes.
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
    commands: List[str],
    mapping: Optional[FileMapping] = None,
    variables: Optional[Dict[str, Any]] = None,
    passthrough: Optional[List[str]] = None,
) -> List[str]:
    mapping = mapping or FileMapping()
    variables = (variables or {}).copy()
    variables['compilable'] = mapping.compilable
    variables['executable'] = mapping.executable
    variables['input'] = mapping.input
    variables['output'] = mapping.output
    variables['error'] = mapping.error
    variables['capture'] = mapping.capture

    for var in passthrough or []:
        variables[var] = f'{{{var}}}'
    return [safeeval.eval_as_fstring(cmd, variables) for cmd in commands]


def get_mapped_command(
    command: str,
    mapping: Optional[FileMapping] = None,
    variables: Optional[Dict[str, Any]] = None,
    passthrough: Optional[List[str]] = None,
) -> str:
    return get_mapped_commands([command], mapping, variables, passthrough)[0]


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
