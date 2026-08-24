import atexit
import inspect
import pathlib
import shlex
import shutil
import sys
import tempfile
from typing import Annotated, List, Optional, Union

import rich
import rich.console
import rich.prompt
import syncer
import typer
from ordered_set import OrderedSet

from rbx import annotations, config, console, utils
from rbx.annotations import PackagePath
from rbx.box import (
    cd,
    compile,
    creation,
    download,
    environment,
    generator_script_handlers,
    generators,
    global_package,
    limits_info,
    package,
    presets,
    setter_config,
    sharing,
    state,
    summary,
    timing,
    timing_config,
    validators,
)
from rbx.box.contest import contest_state
from rbx.box.contest import main as contest
from rbx.box.contest.contest_package import (
    find_contest_yaml,
    get_contest_root_build_path,
)
from rbx.box.environment import VerificationLevel, get_app_environment_path
from rbx.box.generation_schema import get_parsed_entry
from rbx.box.header import generate_header
from rbx.box.packaging import main as packaging
from rbx.box.runners import registry as runners_registry
from rbx.box.runners.base import RunPurpose
from rbx.box.schema import ExpectedOutcome
from rbx.box.solutions import (
    fail_fast_abort_predicate,
    get_exact_matching_solutions,
    get_matching_solutions,
    pick_solutions,
    print_run_report,
    run_and_print_interactive_solutions,
    run_solutions,
)
from rbx.box.statements import build_statements
from rbx.box.testcases import main as testcases
from rbx.box.tooling import main as tooling
from rbx.box.vscode import extension as vscode_extension
from rbx.box.vscode import main as vscode
from rbx.grading import grading_context
from rbx.grading.judge.lock import CacheBusyError

app = typer.Typer(
    no_args_is_help=True, add_completion=False, cls=annotations.AliasGroup
)
app.add_typer(
    setter_config.app,
    name='config, cfg',
    cls=annotations.AliasGroup,
    help='Manage setter configuration (sub-command).',
    rich_help_panel='Configuration',
)
app.add_typer(
    build_statements.app,
    name='statements, st',
    cls=annotations.AliasGroup,
    help='Manage statements (sub-command).',
    rich_help_panel='Deploying',
)
app.add_typer(
    build_statements.tutorials_app,
    name='tutorials, tut',
    cls=annotations.AliasGroup,
    help='Manage tutorials/editorials (sub-command).',
    rich_help_panel='Deploying',
)
app.add_typer(
    download.app,
    name='download, down',
    cls=annotations.AliasGroup,
    help='Download an asset from supported repositories (sub-command).',
    rich_help_panel='Management',
)
app.add_typer(
    presets.app,
    name='presets',
    cls=annotations.AliasGroup,
    help='Manage presets (sub-command).',
    rich_help_panel='Configuration',
)
app.add_typer(
    packaging.app,
    name='package, pkg',
    cls=annotations.AliasGroup,
    help='Build problem packages (sub-command).',
    rich_help_panel='Deploying',
)
app.add_typer(
    contest.app,
    name='contest',
    cls=annotations.AliasGroup,
    help='Manage contests (sub-command).',
    rich_help_panel='Management',
)
app.add_typer(
    testcases.app,
    name='testcases, tc, t',
    cls=annotations.AliasGroup,
    help='Manage testcases (sub-command).',
    rich_help_panel='Management',
)
app.add_typer(
    tooling.app,
    name='tool, tooling',
    cls=annotations.AliasGroup,
    help='Manage tooling (sub-command).',
    rich_help_panel='Misc',
)
app.add_typer(
    vscode.app,
    name='vscode',
    cls=annotations.AliasGroup,
    help='Manage the rbx editor extension (sub-command).',
    rich_help_panel='Misc',
)


def version_callback(value: bool) -> None:
    if value:
        version = utils.get_version()

        console.console.print(f'rbx version {version}')
        raise typer.Exit()


def _revalidate_cache(cache_path: pathlib.Path, name: str) -> bool:
    """Clear `cache_path` if it was written by an incompatible rbx version.

    The check and the wipe happen under the cache's exclusive lock, so two rbx
    processes starting at once do not wipe each other's cache, and neither
    wipes one that a third process is already using (issue #700).
    """

    def _on_wait():
        console.console.print(
            f'[warning]Waiting for other [item]rbx[/item] processes to release the {name.lower()}...[/warning]'
        )

    try:
        cleared = global_package.ensure_cache_dir_is_valid(cache_path, on_wait=_on_wait)
    except CacheBusyError:
        console.console.print(
            f'[error]{name} was written by another version of [item]rbx[/item] and cannot be '
            'cleared while other [item]rbx[/item] processes are using it. '
            'Try again once they finish.[/error]'
        )
        raise typer.Exit(1) from None
    if cleared:
        console.console.print(
            f'[warning]{name} was incompatible with the current version of [item]rbx[/item], so it was cleared.[/warning]'
        )
    return cleared


@app.callback()
@annotations.docs("""
    The `rbx` CLI is the main entry point for all operations. It provides a set of
    commands to manage problems, contests, and the environment.
""")
def main(
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
    # Load .env variables.
    utils.load_dotenv()

    # Note: when both this callback and the contest sub-app callback fire
    # in one process, the sub-app's -C runs later and wins (local override).
    contest_state.apply_cli_selection(contest_id)

    presets.check_active_preset_compatibility()
    if cd.is_problem_package() and _revalidate_cache(
        package.get_problem_cache_path(), 'Cache'
    ):
        # A cache from another rbx version leaves stale build artifacts behind.
        _clean_build_dirs()
    _revalidate_cache(global_package.get_global_cache_dir_path(), 'Global cache')

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


@app.command('ui', help='Show an UI for exploring testcases of the current problem.')
@package.within_problem
def ui():
    from rbx.box.ui import main as ui_pkg

    ui_pkg.start()
    # After the UI, not before: a fullscreen TUI wipes anything printed ahead of
    # it, so a startup hint is a hint nobody sees.
    vscode_extension.print_outdated_hint()


@app.command(
    'on',
    help=(
        'Run a command in the context of a problem (or a set of problems) of a '
        'contest. Chain commands with `::` to queue them.'
    ),
    context_settings={
        'allow_extra_args': True,
        'ignore_unknown_options': True,
        'allow_interspersed_args': False,
    },
)
@annotations.docs(
    'Runs a command in the context of one problem (or a set of problems) of a '
    'contest.\n\n'
    + contest.PROBLEM_SELECTOR_DOCS
    + '\n\n'
    + inspect.cleandoc("""
    Like [`rbx each`](#rbx-each), commands can be chained with `::`:

    ```bash
    rbx on A..C build :: run -s
    ```

    A single command on a single problem runs directly in your terminal; anything
    else opens the TUI. Since flags after the problem selector belong to the chained
    commands, `-k`/`--keep-going` has to come first: `rbx on -k A build :: run`.
    """)
)
def on(
    ctx: typer.Context,
    problems: Annotated[
        str,
        typer.Argument(
            autocompletion=annotations._adapt('problem'),  # noqa: SLF001
            help=contest.PROBLEM_SELECTOR_HELP,
        ),
    ],
    keep_going: bool = contest.KEEP_GOING_OPTION,
) -> None:
    contest.on(ctx, problems, keep_going=keep_going)


@app.command(
    'each',
    help=(
        'Run a command for each problem in the contest. '
        'Chain commands with `::` to queue them.'
    ),
    context_settings={
        'allow_extra_args': True,
        'ignore_unknown_options': True,
        'allow_interspersed_args': False,
    },
)
@annotations.docs("""
    Runs a command for each problem in the contest, in a TUI with one tab per problem.

    Chain several commands with `::` to queue them all at once, in order:

    ```bash
    rbx each build :: package build
    ```

    Each problem runs its whole chain before the next problem starts. If a command in
    a chain fails, the rest of that problem's chain is skipped -- pass
    `-k`/`--keep-going` to run it anyway. Other problems are unaffected either way.

    Commands you type into the TUI later are queued too, but they always run, even
    after a failure.
""")
def each(ctx: typer.Context, keep_going: bool = contest.KEEP_GOING_OPTION) -> None:
    contest.each(ctx, keep_going=keep_going)


@app.command('diff', hidden=True)
def diff(path1: pathlib.Path, path2: pathlib.Path):
    from rbx.box.ui import main as ui_pkg

    ui_pkg.start_differ(path1, path2)


@app.command('serve', hidden=True)
def serve():
    from textual_serve.server import Server

    server = Server('rbx ui', port=8081)
    server.serve()


@app.command(
    'edit, e',
    rich_help_panel='Configuration',
    help='Open problem.rbx.yml in your default editor.',
)
@package.within_problem
def edit():
    console.console.print('Opening problem definition in editor...')
    # Call this function just to raise exception in case we're no in
    # a problem package.
    package.find_problem()
    config.open_editor(package.find_problem_yaml() or pathlib.Path())


@app.command(
    'build, b', rich_help_panel='Deploying', help='Build all tests for the problem.'
)
@annotations.docs("""
    Builds the problem package.

    This command compiles all generators, validators, and checkers. Then it generates
    inputs using the generator script and validates them with the validator. Finally,
    it generates the outputs using the main solution.

    It is recommended to run this command before packaging the problem to ensure
    everything is up-to-date.
""")
@package.within_problem
@syncer.sync
async def build(
    verification: environment.VerificationParam,
    validate: bool = typer.Option(
        True,
        help='Whether to validate outputs for tests.',
    ),
    visualize: bool = typer.Option(
        False,
        help='Whether to build visualizations for inputs/outputs of tests.',
    ),
):
    from rbx.box import builder

    if not await builder.build(
        verification=verification, validate=validate, visualize=visualize
    ):
        raise typer.Exit(1)


def _set_timing_profile(profile: Optional[str]) -> None:
    """Apply a command-level `--profile`, if one was given.

    Mirrors the root callback's `-p`, so `rbx run -p boca` and `rbx -p boca run`
    mean the same thing. Unlike the root flag, a missing profile is an error
    here: naming one is a deliberate act, and falling back to the package limits
    would silently run the solutions against limits the setter did not ask for.
    """
    if profile is None:
        # Leaves whatever the root callback set (or nothing) in place.
        return

    from rbx.box import limits_info

    limits_info.get_limits_profile(profile, fallback_to_package_profile=False)
    limits_info.profile_var.set(profile)


@app.command(
    'run, r',
    rich_help_panel='Testing',
    help='Build and run solution(s).',
)
@annotations.docs("""
    Runs solutions against the testcases.

    This is the primary way to test your solutions. You can run all solutions, a
    specific set of solutions, or only accepted solutions.

    You can also filter which testcases to run against, by using the `--outcome` flag
    to only confirm that solutions match a certain expected outcome (e.g. TLE, WA).
""")
@package.within_problem
@syncer.sync
async def run(
    verification: environment.VerificationParam,
    solutions: Annotated[
        Optional[List[str]],
        PackagePath,
        typer.Argument(
            help='Path to solutions to run. If not specified, will run all solutions.',
            autocompletion=annotations._adapt('solutions', file=True),  # noqa: SLF001
        ),
    ] = None,
    outcome: Optional[str] = typer.Option(
        None,
        '--outcome',
        '-o',
        help='Include only solutions whose expected outcomes intersect with this.',
        autocompletion=annotations._adapt('outcome'),  # noqa: SLF001
    ),
    tags: Annotated[
        Optional[List[str]],
        typer.Option(
            '--tag',
            help='Include only solutions whose tags intersect with this.',
        ),
    ] = None,
    check: bool = typer.Option(
        True,
        help='Whether to not build outputs for tests and run checker.',
    ),
    validate: bool = typer.Option(
        True,
        help='Whether to not validate outputs for tests.',
    ),
    detailed: bool = typer.Option(
        False,
        '--detailed',
        '-d',
        help='Whether to print a detailed view of the tests using tables.',
    ),
    sanitized: bool = typer.Option(
        False,
        '--sanitized',
        '-s',
        help='Whether to compile the solutions with sanitizers enabled.',
    ),
    choice: bool = typer.Option(
        False,
        '--choice',
        '--choose',
        '-c',
        help='Whether to pick solutions interactively.',
    ),
    share: Optional[str] = typer.Option(
        None,
        '--share',
        help='Capture the run report and copy it to the clipboard. '
        'Pass a format: --share png or --share text.',
    ),
    keep_checker_stderr: bool = typer.Option(
        False,
        '--keep-checker-stderr',
        help="Also keep each testcase's full checker stderr, as a `.checker.err` file "
        "next to its output. Only the checker's last line reaches the verdict, so "
        'this is how to read whatever it printed before that.',
    ),
    fail_fast: bool = typer.Option(
        False,
        '--fail-fast',
        '--ff',
        help='Whether to stop running a solution as soon as it gets a non-accepted verdict. '
        'Only meant for quick experimentation, as the remaining tests are reported as failed.',
    ),
    runner: str = typer.Option(
        runners_registry.DEFAULT_RUNNER,
        '--runner',
        # Built from the table, never spelled out, for the same reason as in
        # `rbx time`: this string is baked into the committed completion spec, so
        # a hard-coded list would be a second copy of the runner names with
        # nothing pinning it to the first.
        help=(
            f'Where to run the solutions '
            f'({", ".join(runners_registry.runner_names())}).'
        ),
        autocompletion=annotations._adapt('runner'),  # noqa: SLF001
    ),
    profile: Annotated[
        Optional[str],
        typer.Option(
            '-p',
            '--profile',
            help='Timing profile to run the solutions against. Must exist in this problem.',
            autocompletion=annotations._adapt('profile'),  # noqa: SLF001
        ),
    ] = None,
):
    _set_timing_profile(profile)

    if share is not None and share not in ('png', 'text'):
        console.console.print(
            f'[error]Invalid --share format: {share!r} (use png or text).[/error]'
        )
        raise typer.Exit(1)

    # Before anything is built, for the same reason as in `rbx time`: naming a
    # backend that does not exist is a typo in the command line, and a typo
    # should cost the setter an error rather than a build. `UnknownRunnerError`
    # names the valid runners, so the fix is in the message.
    solution_runner = runners_registry.get_runner(runner)

    main_solution = package.get_main_solution()
    if check and main_solution is None:
        console.console.print(
            '[warning]No main solution found, running without checkers.[/warning]'
        )
        check = False

    tracked_solutions: Optional[OrderedSet[str]] = None
    if outcome is not None or tags is not None:
        tracked_solutions = OrderedSet(
            str(solution.path)
            for solution in get_matching_solutions(
                expected_outcome=ExpectedOutcome(outcome)
                if outcome is not None
                else None,
                tags=tags or None,
            )
        )
    if solutions:
        tracked_solutions = OrderedSet(solutions)

    if choice:
        tracked_solutions = OrderedSet(
            await pick_solutions(
                tracked_solutions,
                extra_solutions=solutions,
            )
        )
        if not tracked_solutions:
            console.console.print('[error]No solutions selected. Exiting.[/error]')
            raise typer.Exit(1)

    from rbx.box import builder

    if not await builder.build(
        verification=verification, output=check, validate=validate, is_run=True
    ):
        raise typer.Exit(1)

    if verification <= VerificationLevel.VALIDATE.value:
        console.console.print(
            '[warning]Verification level is set to [item]validate (-v1)[/item], so rbx only build tests and validated them.[/warning]'
        )
        console.console.print(
            '[warning]If you want to run solutions, but skip validation, run with [item]--no-validate[/item].[/warning]'
        )
        return

    if sanitized:
        console.console.print(
            '[warning]Sanitizers are running, so the time limit for the problem will be dropped, '
            'and the environment default time limit will be used instead.[/warning]'
        )

    # Recorded on the skeleton, not only printed: a client showing this run
    # cannot otherwise tell a list rbx shortened from the whole solution set.
    only_accepted = sanitized and tracked_solutions is None
    if only_accepted:
        console.console.print(
            '[warning]Sanitizers are running, and no solutions were specified to run. Will only run [item]ACCEPTED[/item] solutions.'
        )
        tracked_solutions = OrderedSet(
            str(solution.path)
            for solution in get_exact_matching_solutions(ExpectedOutcome.ACCEPTED)
        )

    with utils.StatusProgress('Running solutions...') as s:
        solution_result = await run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            verification=VerificationLevel(verification),
            sanitized=sanitized,
            only_accepted=only_accepted,
            abort_on=fail_fast_abort_predicate if fail_fast else None,
            runner=solution_runner,
            keep_checker_stderr=keep_checker_stderr,
            # Said explicitly even though it is the default: this is the purpose
            # a backend stages for, and a remote one uploads to a different
            # problem for each. Leaving it implicit here would make the two
            # `rbx time` phases the only ones that look deliberate.
            purpose=RunPurpose.RUN,
        )

    try:
        console.console.print()
        console.console.rule('[status]Run report[/status]', style='status')
        ok = await print_run_report(
            solution_result,
            console.console,
            VerificationLevel(verification),
            detailed=detailed,
            skip_printing_limits=sanitized,
            # A solution that stopped at its first bad verdict was not timed on the
            # testcases that never ran, so every extreme in the timing summary --
            # and the time limit picked off it -- would rest on a lower bound.
            timing=not fail_fast,
        )

        def _print_fail_fast_warning(to: rich.console.Console) -> None:
            to.print()
            to.print(
                '[warning]The [item]--fail-fast / --ff[/item] flag should only be used for quick experimentation, '
                'and should not be trusted for full validation of the problem.[/warning]'
            )
            to.print(
                '[warning]The timing summary was omitted: a solution that stopped early '
                'is only timed on the testcases that ran.[/warning]'
            )

        if share is not None:
            rec = sharing.recording_console()
            await print_run_report(
                solution_result,
                rec,
                VerificationLevel(verification),
                detailed=detailed,
                skip_printing_limits=sanitized,
                timing=not fail_fast,
            )
            # The shared report is the copy that leaves this machine, and whoever
            # reads it never sees the warning printed below.
            if fail_fast:
                _print_fail_fast_warning(rec)
            sharing.capture_and_share(rec, fmt=share, title='rbx run report')

        if fail_fast:
            _print_fail_fast_warning(console.console)

        vscode_extension.print_outdated_hint()

        if not ok:
            raise typer.Exit(1)
    finally:
        # After every consumer of the deferreds -- the report, and the second,
        # recorded report `--share` prints -- because closing is what tells the
        # backend nothing more will be asked of it. In a `finally` because the
        # case that matters is the one that leaves early: a failing report, or a
        # Ctrl-C, on a backend that had already dispatched every solution.
        # `LocalRunner.close` is a no-op, so this costs a local run nothing.
        await solution_result.close()


@app.command(
    'summary, sum',
    rich_help_panel='Testing',
    help='Print a summary of the problem.',
)
@package.within_problem
@syncer.sync
async def summary_cmd(
    detailed: bool = typer.Option(
        False,
        '--detailed',
        '-d',
        help='Whether to print a detailed view of the tests using tables.',
    ),
):
    await summary.print_problem_summary(
        package.find_problem_package_or_die(), detailed=detailed
    )


@app.command(
    'time, t',
    rich_help_panel='Testing',
    help='Estimate a time limit for the problem using the timings of its solutions and the estimation strategy configured in the environment.',
)
@package.within_problem
@syncer.sync
async def time(
    check: bool = typer.Option(
        True,
        help='Whether to not build outputs for tests and run checker.',
    ),
    validate: bool = typer.Option(
        True,
        help='Whether to not validate outputs for tests.',
    ),
    detailed: bool = typer.Option(
        False,
        '--detailed',
        '-d',
        help='Whether to print a detailed view of the tests using tables.',
    ),
    strategy: Optional[str] = typer.Option(
        None,
        '--strategy',
        '-s',
        help='Strategy to use for time limit estimation (estimate, inherit, estimate_custom, custom).',
    ),
    auto: bool = typer.Option(
        False,
        '--auto',
        '-a',
        help='Whether to automatically estimate the time limit.',
    ),
    runs: int = typer.Option(
        0,
        '--runs',
        '-r',
        help='Number of runs to perform for each solution. Zero means the config default.',
    ),
    profile: str = typer.Option(
        'local',
        '--profile',
        '-p',
        help='Profile to use for time limit estimation.',
        autocompletion=annotations._adapt('profile'),  # noqa: SLF001
    ),
    integrate: bool = typer.Option(
        False,
        '--integrate',
        '-i',
        help='Integrate the given limits profile into the package.',
    ),
    runner: str = typer.Option(
        runners_registry.DEFAULT_RUNNER,
        '--runner',
        # Built from the table, never spelled out: this string is baked into
        # the committed completion spec, so a hard-coded list would be a second
        # copy of the runner names with nothing pinning it to the first.
        help=(
            f'Where to run the solutions being timed '
            f'({", ".join(runners_registry.runner_names())}).'
        ),
        autocompletion=annotations._adapt('runner'),  # noqa: SLF001
    ),
    share: Optional[str] = typer.Option(
        None,
        '--share',
        help='Capture the time report (run report + limits table) and copy it '
        'to the clipboard. Pass a format: --share png or --share text.',
    ),
    skip_slow: bool = typer.Option(
        False,
        '--skip-slow',
        help='Skip checking the estimated limit against the solutions expected to '
        'be too slow. The limit is written with its upper bound unchecked.',
    ),
    dry: bool = typer.Option(
        False,
        '--dry',
        help='Run the whole estimation but write nothing to the disk: the limits '
        'profile is printed instead of saved.',
    ),
):
    if share is not None and share not in ('png', 'text'):
        console.console.print(
            f'[error]Invalid --share format: {share!r} (use png or text).[/error]'
        )
        raise typer.Exit(1)

    # Resolved before anything is printed, built or run: naming a backend that
    # does not exist is a typo in the command line, and a typo should cost the
    # setter an error, not a build. `get_runner` raises `UnknownRunnerError`,
    # which `main.py` prints on its own -- naming the valid runners, so the fix
    # is in the message.
    #
    # The name selects the backend, and the limits profile deliberately does
    # not: a profile is the `limits/<name>.yml` file this command *writes*, so
    # binding a transport to it would leave no way to estimate MOJ limits from a
    # machine with no judge access. See `runners/registry.py`.
    solution_runner = runners_registry.get_runner(runner)

    current_profile = limits_info.get_display_limits_profile(profile)
    if current_profile is None:
        current_profile = limits_info.get_limits_profile(profile)
    limits_info.render_limits_table(
        current_profile, title=f'Current limits ({profile})'
    )
    console.console.print()
    if integrate:
        timing.integrate(profile, dry=dry)
        return

    if auto:
        strategy = 'estimate'

    import questionary

    choice = strategy
    if not choice:
        # What the environment (and any problem override) actually estimates
        # with: a formula, or the Kattis-like ratios. Resolved only to label the
        # menu, so a strategy passed with -s -- `inherit` in particular, which
        # estimates nothing -- never fails on a timing config it does not use.
        configured_strategy = timing_config.resolve_strategy(
            environment.get_environment().timing,
            package.find_problem_package_or_die().timing,
        )
        timing_choices = [
            questionary.Choice(
                f'Estimate time limits '
                f'{timing.describe_strategy_briefly(configured_strategy)} '
                f'(recommended)',
                value='estimate',
            ),
            questionary.Choice('Inherit from the package.', value='inherit'),
            questionary.Choice(
                'Estimate time limits based on a custom formula.',
                value='estimate_custom',
            ),
            questionary.Choice('Provide a custom time limit.', value='custom'),
        ]
        choice = await questionary.select(
            'Select how you want to define the time limits for the problem.',
            choices=timing_choices,
        ).ask_async()
    if choice is None:
        console.console.print(
            '[error]No time limit strategy selected. Exiting.[/error]'
        )
        raise typer.Exit(1)

    # Only the custom-formula escape hatch overrides the configured strategy;
    # left as None, the estimation resolves it again for itself.
    formula: Optional[str] = None

    if choice == 'inherit':
        timing.inherit_time_limits(profile=profile, dry=dry)
        return
    elif choice == 'custom':
        timelimit = await questionary.text(
            'Enter a custom time limit for the problem (ms).',
            validate=lambda x: x.isdigit() and int(x) > 0,
        ).ask_async()
        if timelimit is None:
            console.console.print(
                '[error]No custom time limit provided. Exiting.[/error]'
            )
            raise typer.Exit(1)
        timing.set_time_limit(int(timelimit), profile=profile, dry=dry)
        return

    if choice == 'estimate_custom':
        formula = await questionary.text(
            'Enter a custom formula for time limit estimation.'
        ).ask_async()
        if formula is None:
            console.console.print('[error]No custom formula provided. Exiting.[/error]')
            raise typer.Exit(1)
    main_solution = package.get_main_solution()
    if check and main_solution is None:
        console.console.print(
            '[warning]No main solution found, running without checkers.[/warning]'
        )
        check = False

    from rbx.box import builder

    verification = VerificationLevel.ALL_SOLUTIONS.value
    if not await builder.build(
        verification=verification, output=check, validate=validate, is_run=True
    ):
        raise typer.Exit(1)

    estimated = await timing.compute_time_limits(
        check,
        detailed,
        runs,
        formula=formula,
        profile=profile,
        auto=auto,
        share=share,
        skip_slow=skip_slow,
        runner=solution_runner,
        dry=dry,
    )
    if estimated is None:
        # Every failure of the estimation -- an unsatisfiable range, a solution
        # that bounds nothing, a failed run, a cancelled picker -- leaves the
        # limits profile untouched, and `rbx time` must not report success for a
        # limit it did not produce. The reasons were printed where they were
        # found; this only turns them into an exit code a pipeline can see.
        raise typer.Exit(1)


@app.command(
    'irun, ir',
    rich_help_panel='Testing',
    help='Build and run solution(s) by passing testcases in the CLI.',
)
@package.within_problem
@syncer.sync
async def irun(
    verification: environment.VerificationParam,
    solutions: Annotated[
        Optional[List[str]],
        PackagePath,
        typer.Argument(
            help='Path to solutions to run. If not specified, will run all solutions.',
            autocompletion=annotations._adapt('solutions', file=True),  # noqa: SLF001
        ),
    ] = None,
    outcome: Optional[str] = typer.Option(
        None,
        '--outcome',
        '-o',
        help='Include only solutions whose expected outcomes intersect with this.',
        autocompletion=annotations._adapt('outcome'),  # noqa: SLF001
    ),
    tags: Annotated[
        Optional[List[str]],
        typer.Option(
            '--tag',
            help='Include only solutions whose tags intersect with this.',
        ),
    ] = None,
    check: bool = typer.Option(
        True,
        help='Whether to not build outputs for tests and run checker.',
    ),
    validate: bool = typer.Option(
        True,
        help='Whether to validate inputs.',
    ),
    generator: Optional[str] = typer.Option(
        None,
        '--generator',
        '-g',
        help='Generator call to use to generate a single test for execution.',
    ),
    testcase: Optional[str] = typer.Option(
        None,
        '--testcase',
        '--test',
        '-tc',
        '-t',
        help='Testcase to run, in the format "[group]/[index]". If not specified, will run interactively.',
        autocompletion=annotations._adapt('testgroup'),  # noqa: SLF001
    ),
    output: bool = typer.Option(
        False,
        '--output',
        '-O',
        help='Whether to ask user for custom output.',
    ),
    visualize: bool = typer.Option(
        False,
        '--visualize',
        help='Whether to generate visualizations for inputs and outputs.',
    ),
    print: bool = typer.Option(
        False, '--print', '-p', help='Whether to print outputs to terminal.'
    ),
    merge_stderr: bool = typer.Option(
        False,
        '--merge-stderr',
        '-e',
        help='Interleave stderr with the solution output in true line order '
        '(colored distinctly). Requires -p. Default: stderr is shown in a '
        'separate section.',
    ),
    keep_checker_stderr: bool = typer.Option(
        False,
        '--keep-checker-stderr',
        help="Also keep each testcase's full checker stderr, as a `.checker.err` file "
        "next to its output. Only the checker's last line reaches the verdict, so "
        'this is how to read whatever it printed before that.',
    ),
    sanitized: bool = typer.Option(
        False,
        '--sanitized',
        '-s',
        help='Whether to compile the solutions with sanitizers enabled.',
    ),
    choice: bool = typer.Option(
        False,
        '--choice',
        '--choose',
        '-c',
        help='Whether to pick solutions interactively.',
    ),
    profile: Annotated[
        Optional[str],
        typer.Option(
            # No short flag: `-p` is already `--print` here, and stealing it
            # would silently change what an existing `rbx irun -p` does.
            '--profile',
            help='Timing profile to run the solutions against. Must exist in this problem.',
            autocompletion=annotations._adapt('profile'),  # noqa: SLF001
        ),
    ] = None,
):
    _set_timing_profile(profile)

    if not print:
        console.console.print(
            '[warning]Outputs will be written to files. If you wish to print them to the terminal, use the "-p" parameter.'
        )
    if verification < VerificationLevel.ALL_SOLUTIONS.value:
        console.console.print(
            '[warning]Verification level should be at least [item]all solutions (-v4)[/item] to run solutions interactively.'
        )
        return

    tracked_solutions: Optional[OrderedSet[str]] = None
    if outcome is not None or tags is not None:
        tracked_solutions = OrderedSet(
            str(solution.path)
            for solution in get_matching_solutions(
                expected_outcome=ExpectedOutcome(outcome)
                if outcome is not None
                else None,
                tags=tags or None,
            )
        )
    if solutions:
        tracked_solutions = OrderedSet(solutions)

    if choice:
        tracked_solutions = OrderedSet(
            await pick_solutions(
                tracked_solutions,
                extra_solutions=solutions,
            )
        )
        if not tracked_solutions:
            console.console.print('[error]No solutions selected. Exiting.[/error]')
            raise typer.Exit(1)

    # Recorded on the skeleton, not only printed: a client showing this run
    # cannot otherwise tell a list rbx shortened from the whole solution set.
    only_accepted = sanitized and tracked_solutions is None
    if only_accepted:
        console.console.print(
            '[warning]Sanitizers are running, and no solutions were specified to run. Will only run [item]ACCEPTED[/item] solutions.'
        )
        tracked_solutions = OrderedSet(
            str(solution.path)
            for solution in get_exact_matching_solutions(ExpectedOutcome.ACCEPTED)
        )

    with utils.StatusProgress('Running solutions...') as s:
        await run_and_print_interactive_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            verification=VerificationLevel(verification),
            generator=generators.get_call_from_string(generator)
            if generator is not None
            else None,
            testcase_entry=get_parsed_entry(testcase) if testcase else None,
            custom_output=output,
            print=print,
            merge_stderr=merge_stderr,
            keep_checker_stderr=keep_checker_stderr,
            sanitized=sanitized,
            only_accepted=only_accepted,
            validate=validate,
            visualize=visualize,
        )


@app.command(
    'create, c',
    rich_help_panel='Management',
    help='Create a new problem package.',
)
def create(
    name: Annotated[
        str,
        typer.Option(
            help='Name of the problem to create, which will be used as the name of the new folder. '
            'A path relative to the current directory may be given (e.g. "problems/my-problem"), '
            'in which case the problem name is the basename ("my-problem").',
            prompt='What should the problem be named? You may also give a path relative to the current directory (e.g. "problems/my-problem" creates a problem named "my-problem" in that directory)',
        ),
    ],
    preset: Annotated[
        Optional[str], typer.Option(help='Preset to use when creating the problem.')
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
    if find_contest_yaml() is not None:
        console.console.print(
            '[error]Cannot [item]rbx create[/item] a problem inside a contest.[/error]'
        )
        console.console.print(
            '[error]Instead, use [item]rbx contest add[/item] to add a problem to a contest.[/error]'
        )
        raise typer.Exit(1)

    creation.create(name, preset=preset, variant=variant, local=local)


@app.command(
    'stress',
    rich_help_panel='Testing',
    help='Run a stress test.',
)
@annotations.docs("""
    Runs stress testing on the current problem.

    Stress testing allows you to find counter-examples where your solution fails (or
    where two solutions differ).

    You usually provide a generator command (with random seed) and a reference
    solution (or validator/checker).
""")
@package.within_problem
@syncer.sync
async def stress(
    name: Annotated[
        Optional[str],
        typer.Argument(
            help='Name of the stress test to run (specified in problem.rbx.yml).'
        ),
    ] = None,
    generator_args: Annotated[
        Optional[str],
        typer.Option(
            '--generator',
            '-g',
            help='Generator call to use to generate a single test for execution.',
        ),
    ] = None,
    finder: Annotated[
        Optional[str],
        typer.Option(
            '--finder',
            '-f',
            help='Run a stress with this finder expression.',
            autocompletion=annotations._adapt('solutions', file=True),  # noqa: SLF001
        ),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option(
            '--timeout',
            '--time',
            '-t',
            help='For how many seconds to run the stress test.',
        ),
    ] = 10,
    findings: Annotated[
        int,
        typer.Option('--findings', '-n', help='How many breaking tests to look for.'),
    ] = 1,
    verbose: bool = typer.Option(
        False,
        '-v',
        '--verbose',
        help='Whether to print verbose output for checkers and finders.',
    ),
    sanitized: bool = typer.Option(
        False,
        '--sanitized',
        '-s',
        help='Whether to compile the solutions with sanitizers enabled.',
    ),
    description: Optional[str] = typer.Option(
        None,
        '--description',
        '-d',
        help='Optional description of the stress test.',
    ),
    print_descriptors: bool = typer.Option(
        False,
        '--descriptors',
        '-D',
        help='Whether to print descriptors of the stress test.',
        hidden=True,
    ),
    skip_invalid_testcases: bool = typer.Option(
        False,
        '--skip-invalid',
        '--skip',
        help='Whether to skip invalid testcases.',
    ),
    custom_timelimit: Annotated[
        Optional[int],
        typer.Option('--timelimit', '-T', help='Custom timelimit for the stress test.'),
    ] = None,
    double_timelimit: Annotated[
        bool,
        typer.Option(
            '--double-tl',
            help='Whether to use 2*TL as the timelimit for the stress test.',
        ),
    ] = False,
    find_slowest: Annotated[
        bool,
        typer.Option(
            '--slowest',
            help='Whether to find the slowest testcases. This removes the time limit of the solution '
            'executions and focus on finding the testcases that make them the slowest.',
        ),
    ] = False,
    fuzz: Annotated[
        bool,
        typer.Option(
            '--fuzz',
            help='Whether to fuzz generator calls from all testgroups.',
        ),
    ] = False,
    fuzz_on: Annotated[
        Optional[List[str]],
        typer.Option(
            '--fuzz-on',
            help='Testgroups to fuzz generator calls from.',
            autocompletion=annotations._adapt('testgroup'),  # noqa: SLF001
        ),
    ] = None,
    validate: bool = typer.Option(
        True,
        help='Whether to validate inputs.',
    ),
    reference_solution: Optional[str] = typer.Option(
        None,
        '--reference',
        '-r',
        help='Reference solution to use for the stress test.',
        autocompletion=annotations._adapt('solutions', file=True),  # noqa: SLF001
    ),
):
    if generator_args and (fuzz or fuzz_on):
        console.console.print(
            '[error]Options --generator/-g and --fuzz/--fuzz-on cannot be used together.[/error]'
        )
        raise typer.Exit(1)

    if generator_args and not finder:
        console.console.print(
            '[error]Option --generator/-g requires --finder/-f.[/error]'
        )
        raise typer.Exit(1)

    if finder and not generator_args and not (fuzz or fuzz_on):
        console.console.print(
            '[error]Option --finder/-f requires either --generator/-g or --fuzz/--fuzz-on.[/error]'
        )
        raise typer.Exit(1)

    fuzz_arg: Optional[Union[List[str], bool]] = None
    if fuzz_on:
        fuzz_arg = fuzz_on
    elif fuzz:
        fuzz_arg = True

    from rbx.box import stresses, tasks

    limits = tasks.get_limits_for_language(
        lang=None,
        timelimit_override=custom_timelimit,
        verification=VerificationLevel.FULL
        if double_timelimit
        else VerificationLevel.NONE,
    )

    with (
        utils.StatusProgress('Running stress...') as s,
        grading_context.stress(True),
        grading_context.cache_level(grading_context.CacheLevel.CACHE_COMPILATION),
    ):
        report = await stresses.run_stress(
            timeout,
            name=name,
            generator_call=generator_args,
            finder=finder,
            findings_limit=findings,
            progress=s,
            verbose=verbose,
            sanitized=sanitized,
            print_descriptors=print_descriptors,
            skip_invalid_testcases=skip_invalid_testcases,
            limits=limits,
            find_slowest=find_slowest,
            fuzz=fuzz_arg,
            validate=validate,
            reference_solution=reference_solution,
        )

    stresses.print_stress_report(report)

    if not report.findings:
        return

    # Add found tests.
    res = rich.prompt.Confirm.ask(
        'Do you want to add the tests that were found to a test group?',
        console=console.console,
    )
    if not res:
        return
    from rbx.box import promotion

    testgroup = None
    while testgroup is None or testgroup:
        groups_by_name = {
            name: group
            for name, group in package.get_test_groups_by_name().items()
            if group.generatorScript is not None
            and group.generatorScript.path.suffix == '.txt'
        }
        manual_groups = promotion.get_manual_groups_by_name()

        import questionary

        testgroup = await questionary.select(
            'Choose the testgroup to add the tests to.\n'
            'Script groups (.txt generatorScript) and manual (glob-backed) groups are shown below: ',
            choices=list(groups_by_name)
            + list(manual_groups)
            + [
                '(create new script)',
                '(create new manual group)',
                '(skip)',
            ],
        ).ask_async()

        if testgroup == '(create new manual group)':
            manual_target = await promotion.create_manual_group_interactively()
            if manual_target is None:
                # Aborted (Ctrl-C or empty input): write nothing, register nothing.
                break
            manual_groups[manual_target.name] = manual_target
            testgroup = manual_target.name

        if testgroup in manual_groups:
            manual_target = manual_groups[testgroup]
            findings_dir = package.get_problem_runs_dir() / '.stress' / 'findings'
            finding_paths = [
                findings_dir / f'{i}.in' for i in range(len(report.findings))
            ]
            missing = next(
                (i for i, p in enumerate(finding_paths) if not p.exists()), None
            )
            if missing is not None:
                console.console.print(
                    f'[error]Could not find the input file for finding {missing}; '
                    'aborting.[/error]'
                )
                break
            for p in finding_paths:
                promotion.promote_input_to_group(p, manual_target)
            console.console.print(
                f'[success]Added [item]{len(finding_paths)}[/item] static tests to manual test group [item]{testgroup}[/item] at {promotion.manual_group_dir(manual_target)}.[/success]'
            )
            # Break so the just-selected/created manual group is not re-processed
            # by the script-route code below.
            break

        if testgroup == '(create new script)':
            new_script_name = await questionary.text(
                'Enter the name of the new .txt generatorScript file: '
            ).ask_async()
            group = promotion.create_script_group(pathlib.Path(new_script_name))
            testgroup = group.name
            groups_by_name[testgroup] = group

        if testgroup not in groups_by_name:
            break
        try:
            subgroup = groups_by_name[testgroup]
            assert subgroup.generatorScript is not None
            generator_script = pathlib.Path(subgroup.generatorScript.path)
            handler = generator_script_handlers.get_generator_script_handler(
                generator_script.read_text(),
                generator_script_handlers.GeneratorScriptHandlerParams(
                    subgroup.generatorScript,
                ),
            )

            stress_text = f'Obtained by running `rbx {shlex.join(sys.argv[1:])}`'
            handler.append(
                [finding.generator for finding in report.findings],
                comment=stress_text,
            )
            generator_script.write_text(handler.script)

            console.console.print(
                f"Added [item]{len(report.findings)}[/item] tests to test group [item]{testgroup}[/item]'s generatorScript at {subgroup.generatorScript.href()}"
            )
        except typer.Exit:
            continue
        break


@app.command(
    'compile',
    rich_help_panel='Testing',
    help='Compile an asset given its path.',
)
@package.within_problem
@syncer.sync
async def compile_command(
    path: Annotated[
        Optional[str],
        PackagePath,
        typer.Argument(help='Path to the asset to compile.'),
    ] = None,
    sanitized: bool = typer.Option(
        False,
        '--sanitized',
        '-s',
        help='Whether to compile the asset with sanitizers enabled.',
    ),
    warnings: bool = typer.Option(
        False,
        '--warnings',
        '-w',
        help='Whether to compile the asset with warnings enabled.',
    ),
    all: bool = typer.Option(
        False,
        '--all',
        '-a',
        help='Whether to compile all assets.',
    ),
):
    if path is None and not all:
        import questionary

        path = await questionary.path("What's the path to your asset?").ask_async()
        if path is None:
            console.console.print('[error]No path specified.[/error]')
            raise typer.Exit(1)

    if all:
        for solution in package.get_solutions():
            await compile.any(str(solution.path), sanitized, warnings)
        if package.get_checker() is not None:
            await compile.any(str(package.get_checker().path), sanitized, warnings)
        if package.get_validator() is not None:
            await compile.any(str(package.get_validator().path), sanitized, warnings)
        if package.get_interactor() is not None:
            await compile.any(str(package.get_interactor().path), sanitized, warnings)

    if path is not None:
        await compile.any(path, sanitized, warnings)


@app.command(
    'validate',
    rich_help_panel='Testing',
    help='Run the validator in a one-off fashion, interactively.',
)
@package.within_problem
@syncer.sync
async def validate(
    path: Annotated[
        Optional[str],
        PackagePath,
        typer.Option('--path', '-p', help='Path to the testcase to validate.'),
    ] = None,
):
    all_validators = package.get_all_validators()
    if not all_validators:
        console.console.print('[error]No validator found for this problem.[/error]')
        raise typer.Exit(1)

    with utils.StatusProgress('Compiling validators...') as s:
        validators_digests = await validators.compile_validators(
            all_validators, progress=s
        )

    input = console.multiline_prompt('Testcase input')

    if path is None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = pathlib.Path(tmpdir) / '000.in'
            tmppath.write_text(input)

            infos = await validators.validate_one_off(
                pathlib.Path(tmppath), all_validators, validators_digests
            )
    else:
        infos = await validators.validate_one_off(
            pathlib.Path(path), all_validators, validators_digests
        )

    validators.print_validation_report(infos)


@app.command(
    'unit',
    rich_help_panel='Testing',
    help='Run unit tests for the validator and checker.',
)
@package.within_problem
@syncer.sync
async def unit_tests():
    from rbx.box import unit

    with utils.StatusProgress('Running unit tests...') as s:
        await unit.run_unit_tests(s)


@app.command(
    'header',
    rich_help_panel='Configuration',
    help='Generate the rbx.h header file.',
)
@package.within_problem
def header():
    generate_header()


# TODO: warn when using a preset (or show it)
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
    'stats',
    rich_help_panel='Management',
    help='Show stats about current and related packages.',
)
@cd.within_closest_package
def stats(
    transitive: bool = typer.Option(
        False,
        '--transitive',
        '-t',
        help='Show stats about all reachable packages.',
    ),
):
    from rbx.box import stats

    if transitive:
        stats.print_reachable_package_stats()
    else:
        stats.print_package_stats()


@app.command(
    'fix',
    rich_help_panel='Management',
    help='Format files of the current package.',
)
@cd.within_closest_wrapper
def fix(print_diff: bool = typer.Option(False, '--print-diff', '-p')):
    from rbx.box import linting

    linting.fix_package(print_diff=print_diff)


@app.command(
    'wizard',
    rich_help_panel='Management',
    help='Run the wizard.',
)
@cd.within_closest_package
def wizard():
    from rbx.box.wizard.server import run_server

    run_server()


def _clean_dir(path: pathlib.Path):
    if not path.exists():
        return
    console.console.print(f'Cleaning [item]{path}[/item]...')
    shutil.rmtree(path, ignore_errors=True)


def _clean_cache_dir(cache_path: pathlib.Path, name: str):
    """Empty a cache directory, waiting for other rbx processes to let go of it.

    The directory and its lock files stay in place: deleting them would pull the
    ground from under any process that still has the cache open, and would break
    mutual exclusion for every process that comes after (issue #700).
    """
    if not cache_path.is_dir():
        return
    console.console.print(f'Cleaning [item]{cache_path}[/item]...')

    def _on_wait():
        console.console.print(
            f'[warning]Waiting for other [item]rbx[/item] processes to release the {name.lower()}...[/warning]'
        )

    try:
        global_package.clear_cache_dir(cache_path, on_wait=_on_wait)
    except CacheBusyError:
        console.console.print(
            f'[error]{name} is being used by another [item]rbx[/item] process and was not cleared. '
            'Try again once it finishes.[/error]'
        )
        raise typer.Exit(1) from None


@cd.within_closest_package
def _clean_build_dirs():
    _clean_dir(pathlib.Path('build'))
    if cd.is_problem_package():
        _clean_dir(package.get_build_path())
    if cd.is_contest_package():
        # Deliberately unscoped: clean wipes every variant's subtree, so its
        # blast radius does not depend on whether -C was passed. It also works
        # in an unselected dispatcher, where the scoped accessor would die.
        _clean_dir(get_contest_root_build_path())


@cd.within_closest_package
def _clear_package_cache():
    console.console.print('Cleaning cache and build directories...')

    _clean_build_dirs()
    if cd.is_problem_package():
        _clean_cache_dir(package.get_problem_cache_path(), 'Cache')

    if cd.is_contest_package():
        console.console.print(
            '[warning]If you want to clear the problem caches of all problems in the contest, '
            'run [item]rbx contest each clean[/item].[/warning]'
        )


@app.command(
    'clear, clean',
    rich_help_panel='Management',
    help='Clears cache and build directories.',
)
def clear(global_cache: bool = typer.Option(False, '--global', '-g')):
    cleared = False
    if global_cache:
        console.console.print('Cleaning global cache...')
        _clean_cache_dir(global_package.get_global_cache_dir_path(), 'Global cache')
        cleared = True

    closest_package = cd.find_package()
    if closest_package is not None:
        _clear_package_cache()
        cleared = True

    if not cleared:
        console.console.print('[error]No cache or build directories to clean.[/error]')
