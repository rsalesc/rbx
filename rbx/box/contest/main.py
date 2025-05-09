import pathlib
import shutil
import subprocess
from typing import Annotated, Optional

import rich.prompt
import typer

from rbx import annotations, console, utils
from rbx.box import cd, creation, presets
from rbx.box.contest import contest_package, contest_utils, statements
from rbx.box.contest.contest_package import (
    find_contest,
    find_contest_package_or_die,
    find_contest_yaml,
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
def create(
    path: str,
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
    console.console.print(f'Creating new contest at [item]{path}[/item]...')

    fetch_info = get_preset_fetch_info(preset)
    if fetch_info is None:
        console.console.print(
            f'[error]Invalid preset name/URI [item]{preset}[/item][/error]'
        )
        raise typer.Exit(1)

    if fetch_info.is_remote():
        preset = presets.install_from_remote(fetch_info)
    elif fetch_info.is_local_dir():
        preset = presets.install_from_local_dir(fetch_info)

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

    dest_path = pathlib.Path(path)

    if dest_path.exists():
        if not rich.prompt.Confirm.ask(
            f'Directory [item]{dest_path}[/item] already exists. Create contest in it? This might be destructive.',
            show_default=False,
            console=console.console,
        ):
            console.console.print(
                f'[error]Directory [item]{dest_path}[/item] already exists.[/error]'
            )
            raise typer.Exit(1)

    dest_path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(contest_path), str(dest_path), dirs_exist_ok=True)
    shutil.rmtree(str(dest_path / 'build'), ignore_errors=True)
    shutil.rmtree(str(dest_path / '.box'), ignore_errors=True)
    shutil.rmtree(str(dest_path / '.local.rbx'), ignore_errors=True)
    # TODO: consider clearing build and .box recursively for nested problem directories
    for lock in dest_path.rglob('.preset-lock.yml'):
        lock.unlink(missing_ok=True)

    if local:
        presets.copy_local_preset(
            preset_path, dest_path, remote_uri=fetch_info.uri or preset_cfg.uri
        )

    with cd.new_package_cd(dest_path):
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
def add(path: str, short_name: str, preset: Optional[str] = None):
    problem_path = pathlib.Path(path)
    name = problem_path.stem
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
    creation.create(name, preset=preset, path=pathlib.Path(path))

    contest = find_contest_package_or_die()

    ru, contest = contest_package.get_ruyaml()

    item = {
        'short_name': short_name,
        'path': path,
    }
    if 'problems' not in contest:
        contest['problems'] = [item]
    else:
        contest['problems'].append(item)

    dest = find_contest_yaml()
    assert dest is not None
    utils.save_ruyaml(dest, ru, contest)

    console.console.print(
        f'Problem [item]{name} ({short_name})[/item] added to contest at [item]{path}[/item].'
    )


@app.command('remove, r', help='Remove problem from contest.')
@within_contest
def remove(path_or_short_name: str):
    contest = find_contest_package_or_die()

    removed_problem_idx = None
    removed_problem = None
    for i, problem in enumerate(contest.problems):
        if (
            problem.path == pathlib.Path(path_or_short_name)
            or problem.short_name == path_or_short_name
        ):
            removed_problem_idx = i
            removed_problem = problem
            break

    if removed_problem_idx is None or removed_problem is None:
        console.console.print(
            f'[error]Problem [item]{path_or_short_name}[/item] not found in contest.[/error]'
        )
        raise typer.Exit(1)

    ru, contest = contest_package.get_ruyaml()

    del contest['problems'][removed_problem_idx]
    dest = find_contest_yaml()
    assert dest is not None
    utils.save_ruyaml(dest, ru, contest)

    shutil.rmtree(str(removed_problem.path), ignore_errors=True)
    console.console.print(
        f'Problem [item]{removed_problem.short_name}[/item] removed from contest at [item]{removed_problem.path}[/item].'
    )


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
