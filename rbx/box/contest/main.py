import pathlib
import shutil
import subprocess
import tempfile
from typing import Annotated, Optional

import rich.prompt
import ruyaml
import syncer
import typer

from rbx import annotations, console, utils
from rbx.box import cd, creation, naming, presets, summary
from rbx.box.contest import contest_package, contest_state, contest_utils, statements
from rbx.box.contest.contest_package import (
    find_contest,
    find_contest_package_or_die,
    find_contest_yaml,
    get_problems,
    within_contest,
)
from rbx.box.contest.schema import Contest, ContestProblem
from rbx.box.packaging import contest_main as packaging
from rbx.box.schema import Package
from rbx.box.ui.command_app import CommandEntry, start_command_app
from rbx.box.yaml_validation import (
    YamlSyntaxError,
    YamlValidationError,
    load_yaml_model,
)
from rbx.config import open_editor

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


@app.callback()
def contest_main(
    contest_id: Annotated[
        Optional[str],
        typer.Option(
            '-C',
            '--contest',
            help='Select a contest variant by id.',
            envvar='RBX_CONTEST',
        ),
    ] = None,
):
    # When the root cli callback also set this, the sub-app's value wins
    # (local override beats global), since this fires after the root.
    contest_state.apply_cli_selection(contest_id)


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
    local: Annotated[
        bool,
        typer.Option(
            '--local',
            help='Whether to use a preset from the local version of rbx, instead of the global one (not recommended).',
        ),
    ] = False,
):
    console.console.print(f'Creating new contest at [item]{path}[/item]...')

    fetch_info = presets.get_preset_fetch_info_with_fallback(preset, local=local)
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

    if preset is not None:
        presets.maybe_offer_to_register(fetch_info, dest_path)


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

    if preset is not None:
        presets.maybe_offer_to_register(fetch_info, pathlib.Path.cwd())


@app.command('add_variant, av', help='Scaffold a new contest variant file.')
def add_variant(
    variant_id: Annotated[
        str,
        typer.Argument(
            help='Id of the new variant. Must match ^[A-Za-z][A-Za-z0-9_-]*$.',
        ),
    ],
    preset: Annotated[
        Optional[str],
        typer.Option(
            '--preset',
            '-p',
            help='Preset to scaffold the variant from. Defaults to the active '
            'preset in the current directory, then the default preset.',
        ),
    ] = None,
):
    if not contest_state.is_valid_variant_id(variant_id):
        console.console.print(
            f'[error]Invalid variant id [item]{variant_id}[/item]. '
            r'Must match ^[A-Za-z][A-Za-z0-9_-]*$.[/error]'
        )
        raise typer.Exit(1)

    contest_root = contest_package.find_contest_root(pathlib.Path())
    if contest_root is None:
        console.console.print(
            '[error]Not inside a contest directory '
            '(no [item]contest.rbx.yml[/item] found).[/error]'
        )
        raise typer.Exit(1)

    dest = contest_root / f'contest.{variant_id}.rbx.yml'
    if dest.exists():
        console.console.print(
            f'[error]Variant file [item]{dest.name}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    fetch_info = presets.get_preset_fetch_info_with_fallback(preset)

    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp)
        if fetch_info is None:
            # `None` means: use the active preset in the cwd. Install it into
            # the scratch dir so `install_contest` can resolve it there.
            presets.install_preset_from_dir(
                presets.get_active_preset_path(),
                scratch / '.local.rbx',
                ensure_contest=True,
            )
        # Only the templated contest.rbx.yml is read out of the scratch dir, so
        # skip fetching/materializing libraries (avoids needless network work
        # and failures for a discarded scratch package).
        presets.install_contest(scratch, fetch_info, materialize=False)
        template_text = (scratch / 'contest.rbx.yml').read_text()

    ru = ruyaml.YAML()
    data = ru.load(template_text)
    data['name'] = f'{variant_id}-c'
    data['problems'] = []
    utils.save_ruyaml(dest, ru, data)

    # Make sure the result is a valid Contest before declaring success.
    try:
        load_yaml_model(dest, Contest)
    except (YamlValidationError, YamlSyntaxError) as e:
        dest.unlink(missing_ok=True)
        console.console.print(
            f'[error]Scaffolded variant did not validate against the contest '
            f'schema: {e}[/error]'
        )
        raise typer.Exit(1) from e

    find_contest_yaml.cache_clear()
    contest_utils.clear_all_caches()
    console.console.print(
        f'Created contest variant at [item]{dest}[/item]. '
        f'Select it with [item]-C {variant_id}[/item].'
    )


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

    existing_identifiers = set()
    for p in find_contest_package_or_die().problems:
        existing_identifiers.update(p.all_identifiers())
    if short_name.lower() in existing_identifiers:
        console.console.print(
            f'[error]Problem [item]{short_name}[/item] already exists in contest (as short_name or alias).[/error]',
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
    path_or_short_name_lower = path_or_short_name.lower()
    for i, problem in enumerate(contest.problems):
        if (
            problem.path == pathlib.Path(path_or_short_name)
            or problem.short_name == path_or_short_name
            or path_or_short_name_lower in problem.all_identifiers()
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
    contest = find_contest_package_or_die()
    if ctx.args:
        argv, placeholder_prefix = contest_utils.build_command_argv(ctx.args)
    else:
        argv, placeholder_prefix = [], 'rbx'
    commands = [
        CommandEntry(
            argv=argv,
            placeholder_prefix=placeholder_prefix,
            name=naming.get_contest_problem_label(problem),
            cwd=str(problem.get_path()),
        )
        for problem in contest.problems
    ]
    start_command_app(commands)


@app.command(
    'on',
    help='Run a command in the problem (or in a set of problems) of a context.',
    context_settings={'allow_extra_args': True, 'ignore_unknown_options': True},
)
@within_contest
def on(ctx: typer.Context, problems: str) -> None:
    problems_of_interest = contest_utils.get_problems_of_interest(problems)

    if not problems_of_interest:
        console.console.print(
            f'[error]No problems found in contest matching [item]{problems}[/item].[/error]'
        )
        raise typer.Exit(1)

    if len(problems_of_interest) == 1:
        command = ' '.join(['rbx'] + ctx.args)
        console.console.print(
            f'[status]Running [item]{command}[/item] for [item]{naming.get_contest_problem_label(problems_of_interest[0])}[/item]...[/status]'
        )
        subprocess.call(command, cwd=problems_of_interest[0].get_path(), shell=True)
        return

    argv, placeholder_prefix = contest_utils.build_command_argv(ctx.args)
    commands = [
        CommandEntry(
            argv=argv,
            placeholder_prefix=placeholder_prefix,
            name=naming.get_contest_problem_label(p),
            cwd=str(p.get_path()),
        )
        for p in problems_of_interest
    ]
    start_command_app(commands)


@app.command(
    'summary, sum',
    help='Print a summary of the contest.',
)
@within_contest
@syncer.sync
async def summary_cmd():
    contest = find_contest_package_or_die()
    await summary.print_contest_summary(contest, get_problems(contest))


@app.command('list, ls', help='List all contests in the current directory.')
def list_contests():
    contest_root = contest_package.find_contest_root()
    if contest_root is None:
        console.console.print('[warning]No contests found in this directory.[/warning]')
        return

    # discover_contest_variants always returns a non-empty dict here:
    # find_contest_root returned a real path, so canonical contest.rbx.yml exists.
    variants = contest_package.discover_contest_variants(contest_root)

    if not variants:
        console.console.print('[warning]No contests found in this directory.[/warning]')
        return

    if list(variants.keys()) == [None]:
        console.console.print('[item]contest.rbx.yml[/item] (single contest)')
        return

    active = contest_state.resolve_explicit_selection()
    default_path = variants.get(None)

    if default_path is not None:
        # When no explicit selection is set, the default is implicitly active.
        marker = ' *' if active is None else ''
        console.console.print(f'[item]contest.rbx.yml[/item] (default){marker}')

    for vid in sorted(k for k in variants if k is not None):
        marker = ' *' if vid == active else ''
        console.console.print(f'[item]{vid}[/item]{marker}')
