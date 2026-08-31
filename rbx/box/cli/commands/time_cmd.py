"""`rbx time` and `rbx preship`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

from typing import Annotated, Optional

import syncer
import typer

from rbx import annotations, console
from rbx.box import (
    benchmark,
    environment,
    estimation_checksum,
    limits_info,
    package,
    timing,
    timing_config,
)
from rbx.box.environment import VerificationLevel
from rbx.box.runners import registry as runners_registry

app = typer.Typer(cls=annotations.AliasGroup)

# The options `rbx time` and `rbx preship` share. Declared once, as annotated
# types, because the two commands differ only in which of them they *offer*:
# spelling each option twice would leave two help strings to keep in step, and
# the completion spec is generated from them.
_Check = Annotated[
    bool,
    typer.Option(help='Whether to not build outputs for tests and run checker.'),
]
_Validate = Annotated[
    bool,
    typer.Option(help='Whether to not validate outputs for tests.'),
]
_Detailed = Annotated[
    bool,
    typer.Option(
        '--detailed',
        '-d',
        help='Whether to print a detailed view of the tests using tables.',
    ),
]
_Runs = Annotated[
    int,
    typer.Option(
        '--runs',
        '-r',
        help='Number of runs to perform for each solution. Zero means the config default.',
    ),
]
_Profile = Annotated[
    str,
    typer.Option(
        '--profile',
        '-p',
        help='Profile to use for time limit estimation.',
        autocompletion=annotations._adapt('profile'),  # noqa: SLF001
    ),
]
_Runner = Annotated[
    str,
    typer.Option(
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
]
_Share = Annotated[
    Optional[str],
    typer.Option(
        '--share',
        help='Capture the time report (run report + limits table) and copy it '
        'to the clipboard. Pass a format: --share png or --share text.',
    ),
]
_SkipSlow = Annotated[
    bool,
    typer.Option(
        '--skip-slow',
        help='Skip checking the estimated limit against the solutions expected to '
        'be too slow. The limit is written with its upper bound unchecked.',
    ),
]
_Dry = Annotated[
    bool,
    typer.Option(
        '--dry',
        help='Run the whole estimation but write nothing to the disk: the limits '
        'profile is printed instead of saved.',
    ),
]
_KeepCheckerStderr = Annotated[
    bool,
    typer.Option(
        '--keep-checker-stderr',
        help="Also keep each testcase's full checker stderr, as a `.checker.err` file "
        "next to its output. Only the checker's last line reaches the verdict, so "
        'this is how to read whatever it printed before that.',
    ),
]
_FailFast = Annotated[
    bool,
    typer.Option(
        '--fail-fast',
        '--ff',
        help='Whether to stop running a solution as soon as it gets a non-accepted '
        'verdict. Applies only to the solutions run after the estimation, and is '
        'only meant for quick experimentation, as the remaining tests are reported '
        'as failed.',
    ),
]


async def _estimate(
    *,
    check: bool,
    validate: bool,
    detailed: bool,
    strategy: Optional[str],
    auto: bool,
    runs: int,
    profile: str,
    integrate: bool,
    runner: str,
    share: Optional[str],
    skip_slow: bool,
    dry: bool,
    run_all: bool,
    fail_fast: bool,
    benchmark_level: int,
    keep_checker_stderr: bool,
) -> None:
    """The body of `rbx time`, shared with `rbx preship`.

    `rbx preship` is the same command with `--auto` and `--run-all` fixed on, so
    the two are one implementation and two signatures rather than one signature
    with a mode flag: what distinguishes them is which options they *offer*, and
    that is a property of the signature.
    """
    # Parsed before anything is built, for the same reason `rbx run` parses it
    # there: a level rbx cannot report on is a mistake in the command line, and a
    # mistake should cost the setter an error rather than a whole estimation.
    level = benchmark.parse_level(benchmark_level)

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
    # Ahead of the `--integrate` branch below, which is the one path here where
    # this is a warning to act on rather than context: `integrate` copies the
    # saved limit into `problem.rbx.yml` without re-estimating anything, so a
    # stale number is about to become the package's own. On every other path the
    # command is about to replace the estimate anyway.
    estimation_checksum.warn_if_stale(profile)
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
        run_all=run_all,
        fail_fast=fail_fast,
        benchmark_level=level,
        keep_checker_stderr=keep_checker_stderr,
    )
    if estimated is None:
        # Every failure of the estimation -- an unsatisfiable range, a solution
        # that bounds nothing, a failed run, a cancelled picker -- leaves the
        # limits profile untouched, and `rbx time` must not report success for a
        # limit it did not produce. The reasons were printed where they were
        # found; this only turns them into an exit code a pipeline can see.
        raise typer.Exit(1)


@app.command(
    'time, t',
    rich_help_panel='Testing',
    help='Estimate a time limit for the problem using the timings of its solutions and the estimation strategy configured in the environment.',
)
@package.within_problem
@syncer.sync
async def time(
    # Ahead of every parameter carrying a Python-level default, for the same
    # reason as in `rbx run`: `BenchmarkParam` supplies its default through
    # `default_factory` and so has none of its own, and tidying it further down
    # the list is a `SyntaxError` raised when this module is imported. It is an
    # option either way, so its position says nothing about the command line.
    benchmark_level: benchmark.BenchmarkParam,
    check: _Check = True,
    validate: _Validate = True,
    detailed: _Detailed = False,
    strategy: Annotated[
        Optional[str],
        typer.Option(
            '--strategy',
            '-s',
            help='Strategy to use for time limit estimation (estimate, inherit, estimate_custom, custom).',
        ),
    ] = None,
    auto: Annotated[
        bool,
        typer.Option(
            '--auto',
            '-a',
            help='Whether to automatically estimate the time limit.',
        ),
    ] = False,
    runs: _Runs = 0,
    profile: _Profile = 'local',
    integrate: Annotated[
        bool,
        typer.Option(
            '--integrate',
            '-i',
            help='Integrate the given limits profile into the package.',
        ),
    ] = False,
    runner: _Runner = runners_registry.DEFAULT_RUNNER,
    share: _Share = None,
    skip_slow: _SkipSlow = False,
    dry: _Dry = False,
    run_all: Annotated[
        bool,
        typer.Option(
            '--run-all',
            help='After the estimation, also run every solution it did not need -- the '
            'ones expected to be wrong, and any slow one that was never checked -- '
            'against the estimated time limit.',
        ),
    ] = False,
    fail_fast: _FailFast = False,
    keep_checker_stderr: _KeepCheckerStderr = False,
):
    await _estimate(
        check=check,
        validate=validate,
        detailed=detailed,
        strategy=strategy,
        auto=auto,
        runs=runs,
        profile=profile,
        integrate=integrate,
        runner=runner,
        share=share,
        skip_slow=skip_slow,
        dry=dry,
        run_all=run_all,
        fail_fast=fail_fast,
        benchmark_level=benchmark_level,
        keep_checker_stderr=keep_checker_stderr,
    )


@app.command(
    'preship',
    rich_help_panel='Testing',
    help='Estimate a time limit and check the whole package against it: every solution '
    'is run, and every one of them has to behave as problem.rbx.yml says it does.',
)
@package.within_problem
@syncer.sync
async def preship(
    # First for the same reason as in `rbx time` above: it carries no default of
    # its own.
    benchmark_level: benchmark.BenchmarkParam,
    check: _Check = True,
    validate: _Validate = True,
    detailed: _Detailed = False,
    runs: _Runs = 0,
    profile: _Profile = 'local',
    runner: _Runner = runners_registry.DEFAULT_RUNNER,
    share: _Share = None,
    skip_slow: _SkipSlow = False,
    dry: _Dry = False,
    fail_fast: _FailFast = False,
    keep_checker_stderr: _KeepCheckerStderr = False,
):
    # `rbx time --auto --run-all` under a name that says what it is for. The
    # three options it does not offer are the ones `--auto` and `--run-all`
    # settle: `--strategy` (auto forces `estimate`), `--auto` itself, and
    # `--integrate`, which writes the package instead of estimating anything.
    #
    # It offers the `rbx run` flags that are about how a run is *reported* and
    # what it leaves behind -- `-b`, `--keep-checker-stderr`, `--detailed`,
    # `--share`, `--fail-fast` -- and none of the ones that would change what is
    # measured or which solutions run. `--sanitized` inflates every timing the
    # estimate rests on; `--verification-level` is pinned at ALL_SOLUTIONS so
    # `isDoubleTL` stays off; and a solution filter would leave the solutions it
    # skipped looking checked. See `test_timing_run_flags_omitted.py`.
    await _estimate(
        check=check,
        validate=validate,
        detailed=detailed,
        strategy=None,
        auto=True,
        runs=runs,
        profile=profile,
        integrate=False,
        runner=runner,
        share=share,
        skip_slow=skip_slow,
        dry=dry,
        run_all=True,
        fail_fast=fail_fast,
        benchmark_level=benchmark_level,
        keep_checker_stderr=keep_checker_stderr,
    )
