import pathlib
from typing import Annotated, Optional

import typer

from rbx import console, utils
from rbx.box import package, presets


def create(
    name: Annotated[
        str,
        typer.Argument(
            help='The name of the problem package to create. This will also be the name of the folder.'
        ),
    ],
    preset: Annotated[
        Optional[str],
        typer.Option(
            '--preset',
            '-p',
            help='Which preset to use to create this package. Can be a named of an already installed preset, or an URI, in which case the preset will be downloaded.',
        ),
    ] = None,
    path: Optional[pathlib.Path] = None,
):
    console.console.print(f'Creating new problem [item]{name}[/item]...')

    fetch_info = presets.get_preset_fetch_info_with_fallback(preset)
    dest_path = path or pathlib.Path(name)

    if dest_path.exists():
        console.console.print(
            f'[error]Directory [item]{dest_path}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    presets.install_problem(dest_path, fetch_info)

    # Change problem name.
    ru, problem = package.get_ruyaml(dest_path)
    problem['name'] = name
    utils.save_ruyaml(dest_path / 'problem.rbx.yml', ru, problem)

    # fix_package(dest_path)

    presets.generate_lock(dest_path)
