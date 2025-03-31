import functools
import importlib.resources
import pathlib
import shlex
import sys
from typing import Dict

import typer
from pydantic import BaseModel, Field

from rbx import config, console, utils

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


class SetterConfig(BaseModel):
    sanitizers: SanitizersConfig = Field(
        default_factory=SanitizersConfig,  # type: ignore
        description='Configuration for sanitizers.',
    )
    warnings: WarningsConfig = Field(
        default_factory=WarningsConfig,  # type: ignore
        description='Configuration for warnings.',
    )

    repeats: RepeatsConfig = Field(
        default_factory=RepeatsConfig,  # type: ignore
        description='Configuration for repeats.',
    )

    command_substitutions: Dict[str, str] = Field(
        default={},
        description='Substitutions to apply to commands before running them.',
    )

    def substitute_command(self, command: str, sanitized: bool = False) -> str:
        exe = shlex.split(command)[0]
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


def save_setter_config(config: SetterConfig):
    config_path = get_setter_config_path()
    config_path.write_text(utils.model_to_yaml(config))
    get_setter_config.cache_clear()


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
