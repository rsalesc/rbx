"""`rbx time`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

from typing import Optional

import syncer
import typer

from rbx import annotations, console
from rbx.box import (
    environment,
    limits_info,
    package,
    timing,
    timing_config,
)
from rbx.box.environment import VerificationLevel
from rbx.box.runners import registry as runners_registry

app = typer.Typer(cls=annotations.AliasGroup)


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
