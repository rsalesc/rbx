"""`rbx environment`, `rbx languages` and `rbx clear`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import pathlib
from typing import Annotated, Optional

import typer

from rbx import annotations, config, console
from rbx.box import (
    cd,
    environment,
    global_package,
)
from rbx.box.cli import cache as cli_cache
from rbx.box.environment import get_app_environment_path

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'environment, env',
    rich_help_panel='Configuration',
    help='Set or show the current box environment.',
)
def environment_command(
    env: Annotated[Optional[str], typer.Argument()] = None,
    install_from: Annotated[
        Optional[str],
        typer.Option(
            '--install',
            '-i',
            help='Whether to install this environment from the given file.',
        ),
    ] = None,
):
    if env is None:
        console.console.print(
            f'Current environment: [item]{environment.get_active_environment_description()}[/item]'
        )
        console.console.print(f'Location: {environment.get_active_environment_path()}')
        return
    if install_from is not None:
        environment.install_environment(env, pathlib.Path(install_from))
    if not get_app_environment_path(env).is_file():
        console.console.print(
            f'[error]Environment [item]{env}[/item] does not exist.[/error]'
        )
        raise typer.Exit(1)

    cfg = config.get_config()
    if env == cfg.boxEnvironment:
        console.console.print(
            f'Environment is already set to [item]{env}[/item].',
        )
        return
    console.console.print(
        f'Changing global environment from [item]{cfg.boxEnvironment}[/item] to [item]{env}[/item]...'
    )
    cfg.boxEnvironment = env
    config.save_config(cfg)

    # Also clear cache when changing environments.
    clear()


@app.command(
    'languages',
    rich_help_panel='Configuration',
    help='List the languages available in this environment',
)
def languages():
    env = environment.get_environment()

    console.console.print(
        f'[success]There are [item]{len(env.languages)}[/item] language(s) available.'
    )

    for language in env.languages:
        console.console.print(
            f'[item]{language.name}[/item], aka [item]{language.readableName or language.name}[/item]:'
        )
        console.console.print(language)
        console.console.print()


@app.command(
    'clear, clean',
    rich_help_panel='Management',
    help='Clears cache and build directories.',
)
def clear(global_cache: bool = typer.Option(False, '--global', '-g')):
    cleared = False
    if global_cache:
        console.console.print('Cleaning global cache...')
        cli_cache.clean_cache_dir(
            global_package.get_global_cache_dir_path(), 'Global cache'
        )
        cleared = True

    closest_package = cd.find_package()
    if closest_package is not None:
        cli_cache.clear_package_cache()
        cleared = True

    if not cleared:
        console.console.print('[error]No cache or build directories to clean.[/error]')
