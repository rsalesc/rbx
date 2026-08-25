"""`rbx stress`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.
"""

import pathlib
import shlex
import sys
from typing import Annotated, List, Optional, Union

import rich.prompt
import syncer
import typer

from rbx import annotations, console, utils
from rbx.box import (
    generator_script_handlers,
    package,
)
from rbx.box.environment import VerificationLevel
from rbx.grading import grading_context

app = typer.Typer(cls=annotations.AliasGroup)


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
