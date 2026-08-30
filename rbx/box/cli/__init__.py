"""The `rbx` command surface.

Nothing here imports a command's implementation. Every subcommand -- the ones
defined in `rbx.box.cli.commands`, and the sub-apps mounted from elsewhere in
the tree -- is registered in `_ENTRIES` as an import path, and resolved only
when it is actually invoked. See `rbx/box/lazy_cli.py` for the machinery, and
keep this module's import block light: whatever lands at its top level is paid
for by `rbx --help`, by shell completion, and by every other command.
"""

from typing import Annotated, Optional

import typer

from rbx import annotations
from rbx.box.lazy_cli import LazyCommand, lazy_group_cls
from rbx.grading import grading_context

_COMMANDS = [
    LazyCommand(
        'ui',
        'rbx.box.cli.commands.ui_cmds:app',
        help='Show an UI for exploring testcases of the current problem.',
    ),
    LazyCommand(
        'on',
        'rbx.box.cli.commands.flow:app',
        help=(
            'Run a command in the context of a problem (or a set of problems) of a '
            'contest. Chain commands with `::` to queue them.'
        ),
    ),
    LazyCommand(
        'each',
        'rbx.box.cli.commands.flow:app',
        help=(
            'Run a command for each problem in the contest. '
            'Chain commands with `::` to queue them.'
        ),
    ),
    LazyCommand('diff', 'rbx.box.cli.commands.ui_cmds:app', hidden=True),
    LazyCommand('serve', 'rbx.box.cli.commands.ui_cmds:app', hidden=True),
    LazyCommand(
        'edit, e',
        'rbx.box.cli.commands.create:app',
        help='Open problem.rbx.yml in your default editor.',
        rich_help_panel='Configuration',
    ),
    LazyCommand(
        'build, b',
        'rbx.box.cli.commands.build:app',
        help='Build all tests for the problem.',
        rich_help_panel='Deploying',
    ),
    LazyCommand(
        'run, r',
        'rbx.box.cli.commands.run:app',
        help='Build and run solution(s).',
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'summary, sum',
        'rbx.box.cli.commands.run:app',
        help='Print a summary of the problem.',
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'time, t',
        'rbx.box.cli.commands.time_cmd:app',
        help=(
            'Estimate a time limit for the problem using the timings of its '
            'solutions and the estimation strategy configured in the environment.'
        ),
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'preship',
        'rbx.box.cli.commands.time_cmd:app',
        help=(
            'Estimate a time limit and check the whole package against it: every '
            'solution is run, and every one of them has to behave as '
            'problem.rbx.yml says it does.'
        ),
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'irun, ir',
        'rbx.box.cli.commands.run:app',
        help='Build and run solution(s) by passing testcases in the CLI.',
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'create, c',
        'rbx.box.cli.commands.create:app',
        help='Create a new problem package.',
        rich_help_panel='Management',
    ),
    LazyCommand(
        'stress',
        'rbx.box.cli.commands.stress:app',
        help='Run a stress test.',
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'compile',
        'rbx.box.cli.commands.assets:app',
        help='Compile an asset given its path.',
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'validate',
        'rbx.box.cli.commands.assets:app',
        help='Run the validator in a one-off fashion, interactively.',
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'unit',
        'rbx.box.cli.commands.assets:app',
        help='Run unit tests for the validator and checker.',
        rich_help_panel='Testing',
    ),
    LazyCommand(
        'header',
        'rbx.box.cli.commands.assets:app',
        help='Generate the rbx.h header file.',
        rich_help_panel='Configuration',
    ),
    LazyCommand(
        'vars',
        'rbx.box.cli.commands.vars_cmd:app',
        help='Show the expanded vars of this problem.',
        rich_help_panel='Configuration',
    ),
    LazyCommand(
        'environment, env',
        'rbx.box.cli.commands.config_cmds:app',
        help='Set or show the current box environment.',
        rich_help_panel='Configuration',
    ),
    LazyCommand(
        'languages',
        'rbx.box.cli.commands.config_cmds:app',
        help='List the languages available in this environment',
        rich_help_panel='Configuration',
    ),
    LazyCommand(
        'stats',
        'rbx.box.cli.commands.manage:app',
        help='Show stats about current and related packages.',
        rich_help_panel='Management',
    ),
    LazyCommand(
        'fix',
        'rbx.box.cli.commands.manage:app',
        help='Format files of the current package.',
        rich_help_panel='Management',
    ),
    LazyCommand(
        'wizard',
        'rbx.box.cli.commands.manage:app',
        help='Run the wizard.',
        rich_help_panel='Management',
    ),
    LazyCommand(
        'clear, clean',
        'rbx.box.cli.commands.config_cmds:app',
        help='Clears cache and build directories.',
        rich_help_panel='Management',
    ),
]

_GROUPS = [
    LazyCommand(
        'config, cfg',
        'rbx.box.setter_config:app',
        help='Manage setter configuration (sub-command).',
        rich_help_panel='Configuration',
        is_group=True,
    ),
    LazyCommand(
        'statements, st',
        'rbx.box.statements.build_statements:app',
        help='Manage statements (sub-command).',
        rich_help_panel='Deploying',
        is_group=True,
    ),
    LazyCommand(
        'tutorials, tut',
        'rbx.box.statements.build_statements:tutorials_app',
        help='Manage tutorials/editorials (sub-command).',
        rich_help_panel='Deploying',
        is_group=True,
    ),
    LazyCommand(
        'download, down',
        'rbx.box.download:app',
        help='Download an asset from supported repositories (sub-command).',
        rich_help_panel='Management',
        is_group=True,
    ),
    LazyCommand(
        'presets',
        'rbx.box.presets:app',
        help='Manage presets (sub-command).',
        rich_help_panel='Configuration',
        is_group=True,
    ),
    LazyCommand(
        'package, pkg',
        'rbx.box.packaging.main:app',
        help='Build problem packages (sub-command).',
        rich_help_panel='Deploying',
        is_group=True,
    ),
    LazyCommand(
        'contest',
        'rbx.box.contest.main:app',
        help='Manage contests (sub-command).',
        rich_help_panel='Management',
        is_group=True,
    ),
    LazyCommand(
        'testcases, tc, t',
        'rbx.box.testcases.main:app',
        help='Manage testcases (sub-command).',
        rich_help_panel='Management',
        is_group=True,
    ),
    LazyCommand(
        'tool, tooling',
        'rbx.box.tooling.main:app',
        help='Manage tooling (sub-command).',
        rich_help_panel='Misc',
        is_group=True,
    ),
    LazyCommand(
        'vscode',
        'rbx.box.vscode.main:app',
        help='Manage the rbx editor extension (sub-command).',
        rich_help_panel='Misc',
        is_group=True,
    ),
    LazyCommand(
        'visualize, viz',
        'rbx.box.visualization:app',
        help='Visualize a single testcase (sub-command).',
        rich_help_panel='Management',
        is_group=True,
    ),
]

# Commands ahead of groups, mirroring the order Typer used to build the click
# group in: an ambiguous alias ('t', claimed by both 'time, t' and
# 'testcases, tc, t') resolves to whichever comes first.
ENTRIES = [*_COMMANDS, *_GROUPS]

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    cls=lazy_group_cls(ENTRIES),
)


def version_callback(value: bool) -> None:
    if value:
        from rbx import console, utils

        console.console.print(f'rbx version {utils.get_version()}')
        raise typer.Exit()


def _is_readonly_command(ctx: typer.Context) -> bool:
    """Whether the invoked command promised not to touch the package cache.

    Only `rbx visualize` so far. It exists to render one artifact for a testcase
    the user pointed at, and an editor drives it from a click -- so clearing the
    cache (and with it the build tree) underneath that click is the one outcome
    it must never have.
    """
    invoked = ctx.invoked_subcommand or ''
    # Sub-apps are registered under their alias list ('visualize, viz'), and
    # which spelling arrives here depends on how the group resolved it.
    aliases = {alias.strip() for alias in invoked.split(',')}
    return bool(aliases & {'visualize', 'viz'})


@app.callback()
@annotations.docs("""
    The `rbx` CLI is the main entry point for all operations. It provides a set of
    commands to manage problems, contests, and the environment.
""")
def main(
    ctx: typer.Context,
    cache: Annotated[
        grading_context.CacheLevel,
        typer.Option(
            '-c',
            '--cache',
            help='Which degree of caching to use.',
            default_factory=lambda: grading_context.CacheLevel.CACHE_ALL.value,
        ),
    ],
    sanitized: bool = typer.Option(
        False,
        '--sanitized',
        '-s',
        help='Whether to compile and run testlib components with sanitizers enabled. '
        'If you want to run the solutions with sanitizers enabled, use the "-s" flag in the corresponding run command.',
    ),
    capture: Annotated[
        bool,
        typer.Option(
            '--capture',
            '-cp',
            help='Whether to save extra logs and outputs from interactive solutions.',
        ),
    ] = False,
    profile: Annotated[
        Optional[str],
        typer.Option(
            '-p',
            '--profile',
            help='Which timing profile to use when running solutions.',
            autocompletion=annotations._adapt('profile'),  # noqa: SLF001
        ),
    ] = None,
    profiling: bool = typer.Option(
        False,
        '--profiling',
        help='Whether to profile (capture performance statistics) of the execution.',
    ),
    contest_id: Annotated[
        Optional[str],
        typer.Option(
            '-C',
            '--contest',
            help=(
                'Select a contest variant by id (when contest.rbx.yml has '
                'use_variants: true). Defaults to the RBX_CONTEST env var.'
            ),
            envvar='RBX_CONTEST',
            autocompletion=annotations._adapt('contest_variant'),  # noqa: SLF001
        ),
    ] = None,
    version: Annotated[
        bool, typer.Option('--version', '-v', callback=version_callback, is_eager=True)
    ] = False,
):
    import atexit

    from rbx import console, utils
    from rbx.box import cd, global_package, package, presets, setter_config, state
    from rbx.box.cli import cache as cli_cache
    from rbx.box.contest import contest_state

    # Load .env variables.
    utils.load_dotenv()

    # Note: when both this callback and the contest sub-app callback fire
    # in one process, the sub-app's -C runs later and wins (local override).
    contest_state.apply_cli_selection(contest_id)

    presets.check_active_preset_compatibility()

    # A read-only command refuses rather than clears -- see `refuse_incompatible_cache`.
    # This has to happen here, ahead of both revalidations: they run in this
    # callback, so a guard inside the sub-command itself would always be too
    # late, and would find the cache (and the build tree) already gone.
    if _is_readonly_command(ctx):
        cli_cache.refuse_incompatible_cache()
    else:
        if cd.is_problem_package() and cli_cache.revalidate_cache(
            package.get_problem_cache_path(), 'Cache'
        ):
            # A cache from another rbx version leaves stale build artifacts behind.
            cli_cache.clean_build_dirs()
        cli_cache.revalidate_cache(
            global_package.get_global_cache_dir_path(), 'Global cache'
        )

    state.STATE.run_through_cli = True
    state.STATE.sanitized = sanitized
    if sanitized:
        console.console.print(
            '[warning]Sanitizers are running just for testlib components.\n'
            'If you want to run the solutions with sanitizers enabled, use the [item]-s[/item] flag in the corresponding run command.[/warning]'
        )
    state.STATE.capture_pipes = capture

    grading_context.cache_level_var.set(grading_context.CacheLevel(cache))
    grading_context.check_integrity_var.set(
        setter_config.get_setter_config().caching.check_integrity
    )

    if profile is not None:
        from rbx.box import limits_info

        limits_info.profile_var.set(profile)

    if profiling:
        from rbx.grading import profiling as profiling_module

        atexit.register(profiling_module.print_summary)
