"""`rbx stress`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import contextlib
import json
import pathlib
import shlex
import sys
from typing import Annotated, Any, Dict, List, Optional, Union

import rich.prompt
import syncer
import typer

from rbx import annotations, console, utils
from rbx.box import package, stress_manifest
from rbx.box.environment import VerificationLevel
from rbx.grading import grading_context

app = typer.Typer(cls=annotations.AliasGroup)


def _listing() -> Dict[str, Any]:
    """What a stress of this problem can use, as `--list --json` publishes it.

    Solutions come from `package.get_solutions()`, so globs are expanded the
    way a run sees them. Outcomes are `ExpectedOutcome` member *names*
    (`WRONG_ANSWER`), the spelling finder expressions use.
    """
    pkg = package.find_problem_package_or_die()
    return {
        'stresses': [
            {
                'name': stress.name,
                'generator': {
                    'name': stress.generator.name,
                    'args': stress.generator.args,
                },
                'finder': stress.finder,
            }
            for stress in pkg.stresses
        ],
        'solutions': [
            {
                'path': package.relpath(solution.path).as_posix(),
                'outcome': solution.outcome.name,
            }
            for solution in package.get_solutions()
        ],
        'generators': [generator.name for generator in pkg.generators],
        'groups': [group.name for group in pkg.testcases],
    }


def _print_listing(listing: Dict[str, Any]) -> None:
    out = console.console
    out.print('[bstatus]Stresses[/bstatus]')
    for stress in listing['stresses']:
        call = ' '.join(
            part
            for part in (stress['generator']['name'], stress['generator']['args'])
            if part
        )
        # No markup: finders and generator args are full of `[...]`.
        out.print(
            f'  {stress["name"]}: -g {shlex.quote(call)} '
            f'-f {shlex.quote(stress["finder"])}',
            markup=False,
        )
    if not listing['stresses']:
        out.print('  (none)')
    out.print('[bstatus]Solutions[/bstatus]')
    for solution in listing['solutions']:
        out.print(f'  {solution["path"]} ({solution["outcome"]})', markup=False)
    for title, key in (('Generators', 'generators'), ('Test groups', 'groups')):
        out.print(f'[bstatus]{title}[/bstatus]')
        out.print('  ' + (', '.join(listing[key]) or '(none)'), markup=False)


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
    no_promote: Annotated[
        bool,
        typer.Option(
            '--no-promote',
            help='Do not offer to add the findings to a test group when the stress ends.',
        ),
    ] = False,
    list_resources: Annotated[
        bool,
        typer.Option(
            '--list',
            help='List the stresses, solutions, generators and test groups a '
            'stress can use, then exit.',
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option(
            '--json', help='With --list, print the listing as JSON on stdout.'
        ),
    ] = False,
):
    if list_resources:
        if name or generator_args or finder or fuzz or fuzz_on:
            console.stderr_console.print(
                '[error]--list takes no stress name, --generator/-g, --finder/-f '
                'or fuzz options.[/error]'
            )
            raise typer.Exit(1)
        if not as_json:
            _print_listing(_listing())
            return
        # Whatever else gets printed on the way goes to stderr, so stdout
        # parses as JSON.
        json_out = sys.stdout
        with contextlib.redirect_stdout(sys.stderr):
            listing = _listing()
        print(json.dumps(listing), file=json_out)
        return
    if as_json:
        console.stderr_console.print('[error]--json only applies to --list.[/error]')
        raise typer.Exit(1)

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

    if no_promote or not report.findings:
        return

    # Add found tests.
    res = rich.prompt.Confirm.ask(
        'Do you want to add the tests that were found to a test group?',
        console=console.console,
    )
    if not res:
        return
    await _promote_findings(report)


async def _promote_findings(report) -> None:
    """Promote every finding of ``report`` into a group the setter picks.

    The same sinks and the same plan as `rbx testcases promote finding:K`; a
    script group gets the findings' generator calls, a glob group copies of
    their inputs.
    """
    import questionary

    from rbx.box import promotion, promotion_plan, promotion_sinks

    sources = [
        promotion_plan.Source(
            selector=f'finding:{i + 1}',
            recipe=finding.generator,
            input_path=stress_manifest.finding_input_path(i + 1),
            copy_only=True,
        )
        for i, finding in enumerate(report.findings)
    ]
    sinks_by_name = {sink.name: sink for sink in promotion_sinks.list_sinks()}
    choice = await questionary.select(
        'Choose the testgroup to add the tests to.\n'
        'Script groups (.txt generatorScript) and manual (glob-backed) groups are shown below: ',
        choices=list(sinks_by_name)
        + ['(create new script)', '(create new manual group)', '(skip)'],
    ).ask_async()
    if choice is None or choice == '(skip)':
        return

    sink: Optional[promotion_sinks.Sink] = None
    new_group: Optional[promotion_plan.NewGroup] = None
    if choice == '(create new manual group)':
        name = await questionary.text('Name for the new manual group:').ask_async()
        if name is None or not name.strip():
            # Aborted (Ctrl-C or empty input): write nothing, register nothing.
            return
        glob = await questionary.text(
            'Glob for the new manual group (e.g. tests/manual/corner/*.in):'
        ).ask_async()
        if glob is None or not glob.strip():
            return
        new_group = promotion_plan.NewGroup(name=name.strip(), glob=glob.strip())
    elif choice == '(create new script)':
        script = await questionary.text(
            'Enter the name of the new .txt generatorScript file: '
        ).ask_async()
        if script is None or not script.strip():
            return
        path = pathlib.Path(script.strip()).with_suffix('.txt')
        new_group = promotion_plan.NewGroup(name=path.stem, script=path)
    else:
        sink = sinks_by_name[choice]

    target = new_group.sink() if new_group is not None else sink
    assert target is not None
    error = promotion.group_name_error(target.name) if new_group else None
    if error is not None:
        console.console.print(f'[error]{error}[/error]')
        return
    if target.kind == promotion_sinks.GLOB:
        missing = next(
            (
                s.selector
                for s in sources
                if not (s.input_path or pathlib.Path()).is_file()
            ),
            None,
        )
        if missing is not None:
            console.console.print(
                f'[error]Could not find the input file for {missing}; aborting.[/error]'
            )
            return

    try:
        plan = await promotion_plan.plan_promotion(
            sources,
            sink,
            new_group=new_group,
            comment=f'Obtained by running `rbx {shlex.join(sys.argv[1:])}`',
        )
        promotion_plan.apply_plan(plan)
    except promotion_plan.PromotionError as e:
        console.console.print(f'[error]{e}[/error]')
        return
    console.console.print(
        f'[success]Added [item]{len(plan.promoted)}[/item] tests to test group '
        f'[item]{target.name}[/item] ([item]{target.path}[/item]).[/success]'
    )
