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
    path: Annotated[
        str,
        typer.Option(
            help='Path where to create the contest.',
            prompt='Where should the contest be created, relative to the current directory? (e.g. "contests/ioi2024")',
        ),
    ],
    preset: Annotated[
        Optional[str],
        typer.Option(
            '--preset',
            '-p',
            help='Which preset to use to create this package. Can be a named of an already installed preset, or an URI, in which case the preset will be downloaded.\n'
            'If not provided, the default preset will be used, or the active preset if any.',
        ),
    ] = None,
):
    console.console.print(f'Creating new contest at [item]{path}[/item]...')

    fetch_info = presets.get_preset_fetch_info_with_fallback(preset)
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

    presets.install_contest(dest_path, fetch_info)

    with cd.new_package_cd(dest_path):
        contest_utils.clear_all_caches()
        # fix_package()
        presets.generate_lock()


@app.command('init, i', help='Initialize a new contest in the current directory.')
def init(
    preset: Annotated[
        Optional[str],
        typer.Option(
            '--preset',
            '-p',
            help='Which preset to use to create this package. Can be a named of an already installed preset, or an URI, in which case the preset will be downloaded.\n'
            'If not provided, the default preset will be used, or the active preset if any.',
        ),
    ] = None,
):
    console.console.print('Initializing new contest in the current directory...')

    fetch_info = presets.get_preset_fetch_info_with_fallback(preset)

    presets.install_contest(pathlib.Path.cwd(), fetch_info)

    contest_utils.clear_all_caches()
    # fix_package()
    presets.generate_lock()


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
def add(
    path: Annotated[
        str,
        typer.Option(
            help='Path where to create the problem. Name part of the path will be used as the problem name.',
            prompt='Where should the problem be created, relative to the contest root? (e.g. problems/choco will create a problem named "choco" in this directory)',
        ),
    ],
    short_name: Annotated[
        str,
        typer.Option(
            help='Short name of the problem. Will be used as the identifier in the contest.',
            prompt='What should the problem be named? (e.g. "A", "B1", "B2", "Z")',
        ),
    ],
    preset: Annotated[
        Optional[str],
        typer.Option(
            help='Preset to use when creating the problem. If not specified, the active preset will be used.',
        ),
    ] = None,
):
    problem_path = pathlib.Path(path)
    name = problem_path.stem
    utils.validate_field(ContestProblem, 'short_name', short_name)
    utils.validate_field(Package, 'name', name)

    if short_name in [p.short_name for p in find_contest_package_or_die().problems]:
        console.console.print(
            f'[error]Problem [item]{short_name}[/item] already exists in contest.[/error]',
        )
        raise typer.Exit(1)

    creation.create(name, preset=preset, path=pathlib.Path(path))

    contest_pkg = find_contest_package_or_die()

    ru, contest = contest_package.get_ruyaml()

    item = {
        'short_name': short_name,
        'path': path,
    }
    if 'problems' not in contest or not contest_pkg.problems:
        contest['problems'] = [item]
    else:
        idx = 0
        while (
            idx < len(contest_pkg.problems)
            and contest_pkg.problems[idx].short_name <= short_name
        ):
            idx += 1
        contest['problems'].insert(idx, item)

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


@app.command(
    'on',
    help='Run a command in the problem (or in a set of problems) of a context.',
    context_settings={'allow_extra_args': True, 'ignore_unknown_options': True},
)
@within_contest
def on(ctx: typer.Context, problems: str) -> None:
    command = ' '.join(['rbx'] + ctx.args)
    problems_of_interest = contest_utils.get_problems_of_interest(problems)

    if not problems_of_interest:
        console.console.print(
            f'[error]No problems found in contest matching [item]{problems}[/item].[/error]'
        )
        raise typer.Exit(1)

    for p in problems_of_interest:
        console.console.print(
            f'[status]Running [item]{command}[/item] for [item]{p.short_name}[/item]...[/status]'
        )
        subprocess.call(command, cwd=p.get_path(), shell=True)
        console.console.print()
