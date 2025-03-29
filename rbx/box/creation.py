import pathlib
import shutil
from typing import Annotated, Optional

import typer

from rbx import console, utils
from rbx.box import package, presets
from rbx.box.presets.fetch import get_preset_fetch_info


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
    preset = preset or 'default'
    console.console.print(f'Creating new problem [item]{name}[/item]...')

    fetch_info = get_preset_fetch_info(preset)
    if fetch_info is None:
        console.console.print(
            f'[error]Invalid preset name/URI [item]{preset}[/item].[/error]'
        )
        raise typer.Exit(1)

    if fetch_info.fetch_uri is not None:
        preset = presets.install_from_remote(fetch_info)

    preset_cfg = presets.get_installed_preset(preset)

    problem_path = (
        presets.get_preset_installation_path(preset) / preset_cfg.problem
        if preset_cfg.problem is not None
        else presets.get_preset_installation_path('default') / 'problem'
    )

    if not problem_path.is_dir():
        console.console.print(
            f'[error]Problem template [item]{problem_path}[/item] does not exist.[/error]'
        )
        raise typer.Exit(1)

    dest_path = path or pathlib.Path(name)

    if dest_path.exists():
        console.console.print(
            f'[error]Directory [item]{dest_path}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(problem_path), str(dest_path))

    # Remove a few left overs.
    shutil.rmtree(str(dest_path / 'build'), ignore_errors=True)
    shutil.rmtree(str(dest_path / '.box'), ignore_errors=True)
    for lock in dest_path.rglob('.preset-lock.yml'):
        lock.unlink(missing_ok=True)

    # Change problem name.
    ru, problem = package.get_ruyaml(dest_path)
    problem['name'] = name
    utils.save_ruyaml(dest_path / 'problem.rbx.yml', ru, problem)

    presets.generate_lock(preset, root=dest_path)
