import pathlib
import shutil
import subprocess
from typing import Annotated, Optional

import typer

from rbx import annotations, console, utils
from rbx.box import creation, presets
from rbx.box.contest import contest_utils, statements
from rbx.box.contest.contest_package import (
    find_contest,
    find_contest_package_or_die,
    find_contest_yaml,
    save_contest,
    within_contest,
)
from rbx.box.contest.schema import ContestProblem
from rbx.box.packaging import contest_main as packaging
from rbx.box.presets.fetch import get_preset_fetch_info
from rbx.box.schema import Package
from rbx.config import open_editor

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)
app.add_typer(
    statements.app,
    name='statements, st',
    cls=annotations.AliasGroup,
    help='Manage contest-level statements.',
)
app.add_typer(
    packaging.app,
    name='package, pkg',
    cls=annotations.AliasGroup,
    help='Build contest-level packages.',
)


@app.command('create, c', help='Create a new contest package.')
@within_contest
def create(
    name: str,
    preset: Annotated[
        str,
        typer.Option(
            '--preset',
            '-p',
            help='Which preset to use to create this package. Can be a named of an already installed preset, or an URI, in which case the preset will be downloaded.',
        ),
    ] = 'default',
    local: bool = typer.Option(
        False,
        '--local',
        '-l',
        help='Whether to inline the installed preset within the contest folder.',
    ),
):
    console.console.print(f'Creating new contest [item]{name}[/item]...')

    fetch_info = get_preset_fetch_info(preset)
    if fetch_info is None:
        console.console.print(
            f'[error]Invalid preset name/URI [item]{preset}[/item].[/error]'
        )
        raise typer.Exit(1)

    if fetch_info.fetch_uri is not None:
        preset = presets.install_from_remote(fetch_info)

    preset_cfg = presets.get_installed_preset(preset)
    preset_path = (
        presets.get_preset_installation_path(preset)
        if preset_cfg.contest is not None
        else presets.get_preset_installation_path('default')
    )

    contest_path = (
        presets.get_preset_installation_path(preset) / preset_cfg.contest
        if preset_cfg.contest is not None
        else presets.get_preset_installation_path('default') / 'contest'
    )

    if not contest_path.is_dir():
        console.console.print(
            f'[error]Contest template [item]{contest_path}[/item] does not exist.[/error]'
        )
        raise typer.Exit(1)

    dest_path = pathlib.Path(name)

    if dest_path.exists():
        console.console.print(
            f'[error]Directory [item]{dest_path}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    shutil.copytree(str(contest_path), str(dest_path))
    shutil.rmtree(str(dest_path / 'build'), ignore_errors=True)
    shutil.rmtree(str(dest_path / '.box'), ignore_errors=True)
    # TODO: consider clearing build and .box recursively for nested problem directories
    for lock in dest_path.rglob('.preset-lock.yml'):
        lock.unlink(missing_ok=True)

    if local:
        shutil.copytree(str(preset_path), str(dest_path / '.local.rbx'))

    with utils.new_cd(dest_path):
        contest_utils.clear_all_caches()
        presets.generate_lock(preset if not local else presets.LOCAL)


@app.command('edit, e', help='Open contest.rbx.yml in your default editor.')
@within_contest
def edit():
    console.console.print('Opening contest definition in editor...')
    # Call this function just to raise exception in case we're no in
    # a problem package.
    find_contest()
    open_editor(find_contest_yaml() or pathlib.Path())


@app.command('add, a', help='Add new problem to contest.')
@within_contest
def add(name: str, short_name: str, preset: Optional[str] = None):
    utils.validate_field(ContestProblem, 'short_name', short_name)
    utils.validate_field(Package, 'name', name)

    if short_name in [p.short_name for p in find_contest_package_or_die().problems]:
        console.console.print(
            f'[error]Problem [item]{short_name}[/item] already exists in contest.[/error]',
        )
        raise typer.Exit(1)

    preset_lock = presets.get_preset_lock()
    if preset is None and preset_lock is not None:
        preset = preset_lock.preset_name
    creation.create(name, preset=preset, path=pathlib.Path(short_name))

    contest = find_contest_package_or_die()
    # Reassign mutable object before saving.
    contest.problems = sorted(
        [
            *contest.problems,
            ContestProblem(short_name=short_name, path=pathlib.Path(short_name)),
        ],
        key=lambda p: p.short_name,
    )

    save_contest(contest)
    console.console.print(f'Problem [item]{short_name}[/item] added to contest.')


@app.command(
    'each',
    help='Run a command for each problem in the contest.',
    context_settings={'allow_extra_args': True, 'ignore_unknown_options': True},
)
@within_contest
def each(ctx: typer.Context) -> None:
    command = ' '.join(['rbx'] + ctx.args)
    contest = find_contest_package_or_die()
    ok = True
    for problem in contest.problems:
        console.console.print(
            f'[status]Running [item]{command}[/item] for [item]{problem.short_name}[/item]...[/status]'
        )

        retcode = subprocess.call(
            command,
            cwd=problem.get_path(),
            shell=True,
        )
        ok = ok and retcode == 0
        console.console.print()

    if not ok:
        console.console.print(
            '[error]One of the commands above failed. Check the output![/error]'
        )
