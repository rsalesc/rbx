import enum
import functools
import importlib.resources
import pathlib
import shlex
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import typer
from pydantic import BaseModel, Field

from rbx import config, console, utils
from rbx.grading.async_executor import AsyncExecutor
from rbx.grading.grading_context import CacheLevel

app = typer.Typer(no_args_is_help=True)

_CONFIG_FILE_NAME = 'default_setter_config.yml'
_CONFIG_FILE_NAME_MAC = 'default_setter_config.mac.yml'


class SanitizersConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description='Whether to use sanitizers when running solutions.',
    )

    command_substitutions: Dict[str, str] = Field(
        default={},
        description='Substitutions to apply to commands before running them with sanitizers.',
    )


class WarningsConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description='Whether to use warning flags when running solutions.',
    )


class RepeatsConfig(BaseModel):
    reps: int = Field(
        default=1,
        description='Number of times to repeat the solution.',
    )

    retries: int = Field(
        default=0,
        description='Number of times to retry if the solution TLs.',
    )

    retries_for_stress: int = Field(
        default=0,
        description='Number of times to retry in stress mode if the solution TLs.',
    )


class ParallelizationConfig(BaseModel):
    max_workers: int = Field(
        default_factory=lambda: min(utils.get_available_cpu_count(), 4),
        description='Maximum number of workers to use when running tasks in parallel.',
    )


class CachingConfig(BaseModel):
    level: CacheLevel = Field(
        default=CacheLevel.CACHE_ALL,
        description='Whether to enable caching and which caching level to use.',
    )

    check_integrity: bool = Field(
        default=True,
        description='Whether to check the integrity of the cached result, and evict it'
        'if file has changed since it was cached.',
    )


class JudgingConfig(BaseModel):
    check_stack: bool = Field(
        default=True,
        description='Whether to check the stack size before running code.',
    )


DEFAULT_DOCKER_PACKAGES = ['g++', 'gcc', 'python3', 'default-jdk-headless']


class DockerConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description='Run every program rbx compiles or executes inside a Docker '
        'container on this machine, instead of directly on it. The container runs '
        'Linux on your own CPU architecture, so stack and memory limits are '
        'enforced even on macOS, programs have no network access and cannot write '
        'outside their working directory.',
    )
    base_image: str = Field(
        default='ubuntu:24.04',
        description='Image the toolchains come from. rbx installs itself on top of '
        'it. Must be Debian-based when `packages` is not empty.',
    )
    packages: List[str] = Field(
        default_factory=DEFAULT_DOCKER_PACKAGES.copy,
        description='apt packages installed on top of `base_image` (compilers and '
        'interpreters your problems use).',
    )
    dockerfile: Optional[str] = Field(
        default=None,
        description='A Dockerfile to build the base image from, instead of '
        '`base_image`. Built with its own directory as the context.',
    )
    mounts: List[str] = Field(
        default_factory=lambda: ['~'],
        description='Host directories visible, read-only, to programs in the '
        'container. Every problem and cache rbx uses must live under one of them.',
    )
    command_substitutions: Dict[str, str] = Field(
        default={},
        description='Used instead of the top-level `command_substitutions` (and the '
        "sanitizers' ones) while Docker is enabled, since those name tools on this "
        'machine.',
    )
    idle_timeout: int = Field(
        default=900,
        description='Seconds the container stays up with no rbx command using it.',
    )
    pids_limit: int = Field(
        default=4096,
        description='Most processes the container may hold at once, across every '
        'program running in it.',
    )
    memory: Optional[str] = Field(
        default=None,
        description='Optional memory cap for the whole container, in Docker syntax '
        "(e.g. '8g'). Per-program memory limits apply either way.",
    )


class ProblemLabelMode(str, enum.Enum):
    """What to display after the short name in the contest command-app sidebar.

    Iteration order defines the in-app cycle order.
    """

    NAME = 'name'
    TITLE = 'title'
    PATH = 'path'


class UIConfig(BaseModel):
    problem_label: ProblemLabelMode = Field(
        default=ProblemLabelMode.NAME,
        description='What to show after the short name in the `rbx on`/`rbx each` '
        'sidebar: `name` (problem name), `title` (the single problem title, '
        'falling back to the name), or `path` (problem path relative to the '
        'contest). Press `l` in that UI to cycle this live.',
    )


class SetterConfig(BaseModel):
    sanitizers: SanitizersConfig = Field(
        default_factory=SanitizersConfig,
        description='Configuration for sanitizers.',
    )
    warnings: WarningsConfig = Field(
        default_factory=WarningsConfig,
        description='Configuration for warnings.',
    )

    repeats: RepeatsConfig = Field(
        default_factory=RepeatsConfig,
        description='Configuration for repeats.',
    )

    parallel: ParallelizationConfig = Field(
        default_factory=ParallelizationConfig,
        description='Configuration for parallelization.',
    )

    command_substitutions: Dict[str, str] = Field(
        default={},
        description='Substitutions to apply to commands before running them.',
    )
    hyperlinks: bool = Field(
        default=True,
        description='Whether to use hyperlinks in the terminal output.',
    )
    caching: CachingConfig = Field(
        default_factory=CachingConfig,
        description='Configuration for caching.',
    )
    judging: JudgingConfig = Field(
        default_factory=JudgingConfig,
        description='Configuration for judging.',
    )
    ui: UIConfig = Field(
        default_factory=UIConfig,
        description='Configuration for the interactive UI.',
    )
    docker: DockerConfig = Field(
        default_factory=DockerConfig,
        description='Run programs inside a Docker container (opt-in).',
    )

    def substitute_command(self, command: str, sanitized: bool = False) -> str:
        exe = shlex.split(command)[0]
        if self.docker.enabled:
            # The host's substitutions name tools on the host (clang++ for
            # sanitizers on macOS, a Homebrew g++-15); the container has its own.
            if exe in self.docker.command_substitutions:
                exe = self.docker.command_substitutions[exe]
                return ' '.join([exe, *shlex.split(command)[1:]])
            return command
        if sanitized and exe in self.sanitizers.command_substitutions:
            exe = self.sanitizers.command_substitutions[exe]
            return ' '.join([exe, *shlex.split(command)[1:]])
        if exe in self.command_substitutions:
            exe = self.command_substitutions[exe]
            return ' '.join([exe, *shlex.split(command)[1:]])
        return command


def get_default_setter_config_path() -> pathlib.Path:
    cfg_name = _CONFIG_FILE_NAME
    if sys.platform == 'darwin':
        cfg_name = _CONFIG_FILE_NAME_MAC

    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / cfg_name
    ) as file:
        return file


def get_default_setter_config() -> SetterConfig:
    return utils.model_from_yaml(
        SetterConfig, get_default_setter_config_path().read_text()
    )


def get_setter_config_path() -> pathlib.Path:
    return config.get_app_path() / 'setter_config.yml'


@functools.cache
def get_setter_config() -> SetterConfig:
    config_path = get_setter_config_path()
    if not config_path.is_file():
        utils.create_and_write(
            config_path, get_default_setter_config_path().read_text()
        )
    return utils.model_from_yaml(SetterConfig, config_path.read_text())


def get_thread_pool_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=get_setter_config().parallel.max_workers)


def get_async_executor(detach: bool = False) -> AsyncExecutor:
    return AsyncExecutor(
        max_workers=get_setter_config().parallel.max_workers,
        detach=detach,
    )


def save_setter_config(config: SetterConfig):
    config_path = get_setter_config_path()
    config_path.write_text(utils.model_to_yaml(config))
    get_setter_config.cache_clear()


def set_problem_label(mode: ProblemLabelMode) -> None:
    """Persist the command-app problem-label mode.

    Reassigns the whole `ui` sub-model (instead of mutating
    `cfg.ui.problem_label` in place) so the field is marked as set and survives
    `model_to_yaml`'s `exclude_unset` — otherwise configs that predate the `ui`
    field would silently drop the change.
    """
    cfg = get_setter_config()
    cfg.ui = UIConfig(problem_label=mode)
    save_setter_config(cfg)


@app.command(help='Show the path to the setter config.')
def path():
    print(get_setter_config_path())


@app.command('list, ls')
def list():
    """
    Pretty print the config file.
    """
    console.console.print_json(utils.model_json(get_setter_config()))


@app.command(help='Open the setter config in an editor.')
def edit():
    # Ensure config is created before calling the editor.
    get_setter_config()

    config.open_editor(get_setter_config_path())


@app.command()
def reset():
    """
    Reset the config file to the default one.
    """
    if not typer.confirm('Do you really want to reset your config to the default one?'):
        return
    cfg_path = get_setter_config_path()
    cfg_path.unlink(missing_ok=True)
    get_setter_config()  # Reset the config.
