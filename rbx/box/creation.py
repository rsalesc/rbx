import pathlib
from typing import Annotated, Optional

import pydantic
import typer

from rbx import console, utils
from rbx.box import package, presets
from rbx.box.schema import Package


def create(
    name: Annotated[
        str,
        typer.Argument(
            help='The name of the problem package to create. This will also be the name of the folder. '
            'A relative path may be given, in which case the problem name is its basename.'
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
    local: Annotated[
        bool,
        typer.Option(
            '--local',
            help='Whether to fetch the init preset from the local version of rbx, instead of the remote one (not recommended).',
        ),
    ] = False,
):
    dest_path = path or pathlib.Path(name)

    # The problem name is the basename of the destination folder, even when a
    # relative path is given (e.g. `problems/my-problem` -> `my-problem`).
    problem_name = dest_path.stem
    try:
        utils.validate_field(Package, 'name', problem_name)
    except pydantic.ValidationError:
        console.console.print(
            f'[error]Invalid problem name [item]{problem_name}[/item], '
            f'derived from [item]{name}[/item].[/error]'
        )
        console.console.print(
            '[error]A problem name must be 3-32 characters long and contain only '
            'letters, digits, dashes and underscores.[/error]'
        )
        raise typer.Exit(1) from None

    console.console.print(f'Creating new problem [item]{problem_name}[/item]...')

    fetch_info = presets.get_preset_fetch_info_with_fallback(preset, local=local)

    if dest_path.exists():
        console.console.print(
            f'[error]Directory [item]{dest_path}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    presets.install_problem(dest_path, fetch_info)

    # Change problem name.
    ru, problem = package.get_ruyaml(dest_path)
    problem['name'] = problem_name
    utils.save_ruyaml(dest_path / 'problem.rbx.yml', ru, problem)

    # fix_package(dest_path)

    presets.generate_lock(dest_path)

    if preset is not None:
        presets.maybe_offer_to_register(fetch_info, dest_path)
