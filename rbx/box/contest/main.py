import inspect
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING, Annotated, List, Optional, Tuple

import rich.prompt
import syncer
import typer

from rbx import annotations, console, utils
from rbx.box import cd, creation, issues, naming, presets, summary, yaml_include
from rbx.box.contest import (
    contest_package,
    contest_state,
    contest_utils,
    problem_selector,
    statements,
)
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
from rbx.box.yaml_validation import (
    YamlSyntaxError,
    YamlValidationError,
    load_yaml_model,
)
from rbx.config import open_editor

if TYPE_CHECKING:
    from rbx.box.ui.command_app import CommandEntry

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
            autocompletion=annotations._adapt('contest_variant'),  # noqa: SLF001
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
    statements.tutorials_app,
    name='tutorials, tut',
    cls=annotations.AliasGroup,
    help='Manage contest-level tutorials/editorials.',
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
            help='Path (relative to the current directory) where to create the contest '
            '(e.g. "contests/ioi2024").',
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
    variant: Annotated[
        Optional[str],
        typer.Option(
            '--variant',
            '-v',
            help='Which template variant of the preset to use. Omit to use the '
            'canonical template, or to be prompted when the preset offers variants.',
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

    template = presets.install_contest(dest_path, fetch_info, variant=variant)

    with cd.new_package_cd(dest_path):
        contest_utils.clear_all_caches()
        # fix_package()
        presets.generate_lock(template=template)

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

    template = presets.install_contest(pathlib.Path.cwd(), fetch_info)

    contest_utils.clear_all_caches()
    # fix_package()
    presets.generate_lock(template=template)

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
        # The returned template is ignored on purpose: this scratch package is
        # thrown away and never locked, so no lock can disagree with it.
        presets.install_contest(scratch, fetch_info, materialize=False)
        template_text = (scratch / 'contest.rbx.yml').read_text()

    # Include-tolerant: a preset's contest template may use `<<: !include`,
    # which plain ruyaml refuses to construct.
    ru = yaml_include.make_yaml()
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
            help='Path (relative to the contest root) where to create the problem. '
            'The name part of the path will be used as the problem name '
            '(e.g. "problems/choco" creates a problem named "choco" in that directory).',
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
    variant: Annotated[
        Optional[str],
        typer.Option(
            '--variant',
            '-v',
            help='Which template variant of the preset to use. Omit to use the '
            'canonical template, or to be prompted when the preset offers variants.',
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            '--yes',
            '-y',
            help='Do not ask for confirmation when the edit lands in a fragment '
            'shared with other contests.',
        ),
    ] = False,
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

    dest = find_contest_yaml()
    assert dest is not None

    # `problems` may live in an `!include`d fragment; edit whichever file owns
    # it. Resolved and confirmed BEFORE creating anything on disk, so declining
    # a shared edit does not leave an orphaned problem directory behind.
    target = yaml_include.open_for_edit(dest, 'problems')
    if not yaml_include.confirm_shared_edit(target, dest, dest.parent, yes=yes):
        raise typer.Exit(1)

    creation.create(name, preset=preset, path=pathlib.Path(path), variant=variant)

    contest_pkg = find_contest_package_or_die()

    item = {
        'short_name': short_name,
        'path': path,
    }
    if target.value is None or not contest_pkg.problems:
        target.replace([item])
    else:
        idx = 0
        while (
            idx < len(contest_pkg.problems)
            and contest_pkg.problems[idx].short_name <= short_name
        ):
            idx += 1
        target.value.insert(idx, item)

    target.save()

    console.console.print(
        f'Problem [item]{name} ({short_name})[/item] added to contest at [item]{path}[/item].'
    )


@app.command('remove, r', help='Remove problem from contest.')
@within_contest
def remove(
    path_or_short_name: str,
    yes: Annotated[
        bool,
        typer.Option(
            '--yes',
            '-y',
            help='Do not ask for confirmation when the edit lands in a fragment '
            'shared with other contests.',
        ),
    ] = False,
):
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

    dest = find_contest_yaml()
    assert dest is not None

    target = yaml_include.open_for_edit(dest, 'problems')
    del target.value[removed_problem_idx]

    if not yaml_include.confirm_shared_edit(target, dest, dest.parent, yes=yes):
        raise typer.Exit(1)
    target.save()

    shutil.rmtree(str(removed_problem.path), ignore_errors=True)
    console.console.print(
        f'Problem [item]{removed_problem.short_name}[/item] removed from contest at [item]{removed_problem.path}[/item].'
    )


# The selector syntax, documented once: `rbx on` is declared both here and as a
# top-level command in `rbx/box/cli.py`, and both render into the CLI reference.
PROBLEM_SELECTOR_DOCS = inspect.cleandoc("""
The problem selector is a comma-separated list. Each entry names a problem by its
short name, by the `name` it declares in its `problem.rbx.yml`, by one of its
aliases, or by the basename of its folder -- looked up in that order, so the
letter always wins over another problem's alias.

| Selector | Selects |
| :--- | :--- |
| `B` | the problem whose short name, name, alias or folder is `B` |
| `A,C` | both problems |
| `A..C` | every problem from `A` to `C`, in contest order |
| `day1-*` | every problem matching the pattern (`*` and `?` are wildcards) |
| `*` | every problem in the contest |
| `*,!C` | every problem but `C` |
| `!C` | the same -- a selector of exclusions starts from every problem |

Ranges are written with two dots: `A-C` is read as a literal name, since a
problem may well be called `two-sum`. An entry that matches no problem is an
error, so a typo never runs on a subset of what you meant.

Quote selectors that use `*` or `!`, which your shell would otherwise expand.
""")

PROBLEM_SELECTOR_HELP = (
    'Problems to run on: short names, names, aliases or folders, comma-separated. '
    'Also `A..C`, `*`, globs and `!` exclusions.'
)

KEEP_GOING_OPTION = typer.Option(
    False,
    '--keep-going',
    '-k',
    help=(
        'Keep running the rest of a chain in a problem even after a command '
        'fails. Must come before the problem selector in `rbx on`.'
    ),
)

INLINE_OPTION = typer.Option(
    False,
    '--inline',
    '-i',
    help=(
        'Run the commands straight in this terminal, one after another, instead '
        'of opening the TUI. Must come before the problem selector in `rbx on`.'
    ),
)


def _export_contest_selection() -> None:
    """Make the active contest selection visible to the `rbx` children we spawn.

    `-C <id>` is materialized into a contextvar, which dies with this process,
    so a child would fall back to the canonical contest and fail to find itself
    in its `problems[]`. `RBX_CONTEST` is the only channel that survives the
    fork, and the root callbacks already read it, so exporting it here is
    enough -- for the inline `subprocess.call`, for the commands the TUI
    spawns, and for whatever the user types into the TUI later.

    No-op when there is no explicit selection (single-contest mode), and a
    self-assignment when the selection came from the env var in the first place.
    """
    selection = contest_state.resolve_explicit_selection()
    if selection is not None:
        os.environ[contest_state.ENV_VAR] = selection


def _offer_run_history(problem_names: Optional[List[str]] = None) -> bool:
    """Offer to reopen a past `each`/`on` session.

    Reached when there is no command to forward. Returns True once it has shown
    something; False means the caller should open a blank session instead --
    either nothing was ever recorded, or the user asked for a new one. No-argument
    `each` has always opened a blank session, and history must not cost that.
    """
    from rbx.box.ui import run_picker

    outcome = run_picker.open_run_history(problem_names)
    return outcome == run_picker.HANDLED


def _build_command_argvs_or_die(
    args: List[str],
) -> Tuple[List[List[str]], Optional[str]]:
    try:
        return contest_utils.build_command_argvs(args)
    except contest_utils.EmptyCommandError as e:
        console.console.print(f'[error]{e}[/error]')
        raise typer.Exit(1) from e


def _run_inline(commands: List['CommandEntry'], keep_going: bool) -> None:
    """Run every chain in this terminal instead of opening the TUI.

    Each entry's commands run in order in the entry's directory, and their
    output goes straight to the terminal -- nothing is captured, so a command
    that draws its own progress still looks like it does on its own. A failing
    command skips the rest of that entry's chain unless `keep_going`; other
    entries run either way, mirroring the TUI. The exit code is non-zero if any
    command failed, which is what makes the flag usable from a script.
    """
    failed = False
    for command in commands:
        for argv in command.argvs:
            line = shlex.join(argv)
            console.console.print(
                f'[status]Running [item]{line}[/item] for '
                f'[item]{command.display_name}[/item]...[/status]'
            )
            code = subprocess.call(line, cwd=command.cwd, shell=True)
            if code == 0:
                continue
            failed = True
            console.console.print(
                f'[error]Command [item]{line}[/item] failed for '
                f'[item]{command.display_name}[/item] with exit code {code}.[/error]'
            )
            if not keep_going:
                break

    if failed:
        raise typer.Exit(1)


def _die_with_nothing_to_run() -> None:
    console.console.print(
        '[error]No command to run.[/error]\n'
        '[status]Pass a command to run inline, e.g. '
        '[item]rbx each --inline build[/item].[/status]'
    )
    raise typer.Exit(1)


@app.command(
    'each',
    help=(
        'Run a command for each problem in the contest. '
        f'Chain commands with `{contest_utils.COMMAND_SEPARATOR}` to queue them.'
    ),
    context_settings={
        'allow_extra_args': True,
        'ignore_unknown_options': True,
        # Stop parsing at the first positional, otherwise click would steal a
        # `-k` meant for one of the chained commands.
        'allow_interspersed_args': False,
    },
)
@within_contest
def each(
    ctx: typer.Context,
    keep_going: bool = KEEP_GOING_OPTION,
    inline: bool = INLINE_OPTION,
) -> None:
    from rbx.box.ui.command_app import CommandEntry, start_command_app

    contest = find_contest_package_or_die()
    _export_contest_selection()
    if not ctx.args:
        # There is nothing to type a command into when running inline, so an
        # empty `--inline` is a mistake rather than an invitation to browse.
        if inline:
            _die_with_nothing_to_run()
        if _offer_run_history():
            return
    argvs, placeholder_prefix = _build_command_argvs_or_die(ctx.args)
    commands = [
        CommandEntry(
            argvs=argvs,
            placeholder_prefix=placeholder_prefix,
            name=naming.get_contest_problem_label(problem),
            labels=naming.get_contest_problem_labels(problem),
            cwd=str(problem.get_path()),
        )
        for problem in contest.problems
    ]
    if inline:
        _run_inline(commands, keep_going=keep_going)
        return
    start_command_app(commands, keep_going=keep_going)


@app.command(
    'on',
    help=(
        'Run a command in the problem (or in a set of problems) of a context. '
        f'Chain commands with `{contest_utils.COMMAND_SEPARATOR}` to queue them.'
    ),
    context_settings={
        'allow_extra_args': True,
        'ignore_unknown_options': True,
        # See `each`: keeps a chained command's own flags out of click's hands.
        # As a result, `-k` has to come before the problem selector.
        'allow_interspersed_args': False,
    },
)
@within_contest
@annotations.docs(
    'Run a command in the problem (or in a set of problems) of a contest.\n\n'
    + PROBLEM_SELECTOR_DOCS
    + '\n\nChain commands with `::` to queue them.'
)
def on(
    ctx: typer.Context,
    problems: Annotated[
        Optional[str],
        typer.Argument(
            autocompletion=annotations._adapt('problem'),  # noqa: SLF001
            help=PROBLEM_SELECTOR_HELP,
        ),
    ] = None,
    keep_going: bool = KEEP_GOING_OPTION,
    inline: bool = INLINE_OPTION,
) -> None:
    _export_contest_selection()
    if problems is None:
        # No selector and nothing to run: history is all that is on offer, since
        # there is no problem set to open a blank session over.
        if not _offer_run_history():
            console.console.print(
                '[error]No recorded runs found for this contest.[/error]\n'
                '[status]Pass a problem selector, e.g. '
                '[item]rbx contest on A build[/item].[/status]'
            )
            raise typer.Exit(1)
        return
    try:
        problems_of_interest = contest_utils.get_problems_of_interest(problems)
    except problem_selector.ProblemSelectorError as e:
        console.console.print(f'[error]{e}[/error]')
        raise typer.Exit(1) from e

    if not problems_of_interest:
        console.console.print(
            f'[error]No problems found in contest matching [item]{problems}[/item].[/error]'
        )
        raise typer.Exit(1)

    if not ctx.args:
        # See `each`: inline has nowhere to queue a command typed later.
        if inline:
            _die_with_nothing_to_run()
        if _offer_run_history(
            [naming.get_contest_problem_label(p) for p in problems_of_interest]
        ):
            # A selector but nothing to run: show this problem's history.
            return

    argvs, placeholder_prefix = _build_command_argvs_or_die(ctx.args)

    from rbx.box.ui.command_app import CommandEntry, start_command_app

    commands = [
        CommandEntry(
            argvs=argvs,
            placeholder_prefix=placeholder_prefix,
            name=naming.get_contest_problem_label(p),
            labels=naming.get_contest_problem_labels(p),
            cwd=str(p.get_path()),
        )
        for p in problems_of_interest
    ]

    # A single command on a single problem already reads fine in the terminal,
    # so it takes the inline path whether or not the flag is there; anything
    # else needs the queue, and opens the app unless asked to stay inline.
    if inline or (len(problems_of_interest) == 1 and len(argvs) <= 1):
        _run_inline(commands, keep_going=keep_going)
        return

    start_command_app(commands, keep_going=keep_going)


@app.command(
    'summary, sum',
    help='Print a summary of the contest.',
)
@within_contest
@syncer.sync
async def summary_cmd():
    contest = find_contest_package_or_die()
    await summary.print_contest_summary(contest, get_problems(contest))


@app.command(
    'issues',
    help="Show what each problem's last run revealed.",
)
@within_contest
def issues_cmd(
    detailed: Annotated[
        bool,
        typer.Option(
            '--detailed',
            '-d',
            help="Follow the table with every problem's issues in full.",
        ),
    ] = False,
    format: Annotated[
        issues.IssuesFormat,
        typer.Option(
            '--format',
            help='How to print the issues. Use `json` to consume them from a tool.',
        ),
    ] = issues.IssuesFormat.RICH,
):
    contest = find_contest_package_or_die()
    rows = issues.collect_contest_rows(contest, get_problems(contest))

    if format is issues.IssuesFormat.JSON:
        # Straight to stdout, not through the themed console: this output is
        # parsed, and Rich would wrap and highlight it.
        print(issues.contest_to_json(rows))
        return

    issues.print_contest_report(rows, detailed=detailed)


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
