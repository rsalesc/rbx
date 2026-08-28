"""`rbx run`, `rbx irun` and `rbx summary`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

from typing import Annotated, List, Optional

import rich.console
import syncer
import typer
from ordered_set import OrderedSet

from rbx import annotations, console, utils
from rbx.annotations import PackagePath
from rbx.box import (
    benchmark as benchmark_module,
)
from rbx.box import (
    environment,
    generators,
    limits_info,
    package,
    sharing,
    summary,
)
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import get_parsed_entry
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
from rbx.box.vscode import extension as vscode_extension

app = typer.Typer(cls=annotations.AliasGroup)


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
    # Ahead of every optional parameter because it carries no default of its
    # own -- `BenchmarkParam` supplies one through `default_factory`, exactly as
    # `VerificationParam` above does. It is an option, so where it sits in the
    # signature says nothing about the command line.
    benchmark_level: benchmark_module.BenchmarkParam,
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
    # Parsed here, beside the profile and for the same reason: a level rbx
    # cannot report on is a mistake in the command line, and a mistake should
    # cost the setter an error rather than a whole build.
    benchmark = benchmark_module.parse_level(benchmark_level)

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
            benchmark_level=benchmark,
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
                # Benchmarked too: a shared copy silently missing a block the
                # setter asked for reads as a run that had nothing to report.
                benchmark_level=benchmark,
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
