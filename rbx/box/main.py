# flake8: noqa
from gevent import monkey

monkey.patch_all()

import tempfile
import shlex
import sys
import typing

from rbx.box.schema import CodeItem, ExpectedOutcome


import pathlib
import shutil
from typing import Annotated, List, Optional

import rich
import rich.prompt
import typer
import questionary

from rbx import annotations, config, console, utils
from rbx.box import (
    builder,
    cd,
    creation,
    download,
    environment,
    generators,
    package,
    compile,
    presets,
    stresses,
    validators,
)
from rbx.box.contest import main as contest
from rbx.box.environment import VerificationLevel, get_environment_path
from rbx.box.packaging import main as packaging
from rbx.box.solutions import (
    get_matching_solutions,
    print_run_report,
    run_and_print_interactive_solutions,
    run_solutions,
)
from rbx.box.statements import build_statements
from rbx.box.ui import main as ui_pkg

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)
app.add_typer(
    build_statements.app,
    name='statements, st',
    cls=annotations.AliasGroup,
    help='Manage statements.',
)
app.add_typer(
    download.app,
    name='download',
    cls=annotations.AliasGroup,
    help='Download an asset from supported repositories.',
)
app.add_typer(
    presets.app, name='presets', cls=annotations.AliasGroup, help='Manage presets.'
)
app.add_typer(
    packaging.app,
    name='package, pkg',
    cls=annotations.AliasGroup,
    help='Build problem packages.',
)
app.add_typer(
    contest.app, name='contest', cls=annotations.AliasGroup, help='Contest management.'
)


@app.command('ui', hidden=True)
@package.within_problem
def ui():
    ui_pkg.start()


@app.command('edit, e', help='Open problem.rbx.yml in your default editor.')
@package.within_problem
def edit():
    console.console.print('Opening problem definition in editor...')
    # Call this function just to raise exception in case we're no in
    # a problem package.
    package.find_problem()
    config.open_editor(package.find_problem_yaml() or pathlib.Path())


@app.command('build, b', help='Build all tests for the problem.')
@package.within_problem
def build(verification: environment.VerificationParam):
    builder.build(verification=verification)


@app.command('run, r', help='Build and run solution(s).')
@package.within_problem
def run(
    verification: environment.VerificationParam,
    solution: Annotated[
        Optional[str],
        typer.Argument(
            help='Path to solution to run. If not specified, will run all solutions.'
        ),
    ] = None,
    outcome: Optional[str] = typer.Option(
        None,
        '--outcome',
        '-o',
        help='Include only solutions whose expected outcomes intersect with this.',
    ),
    check: bool = typer.Option(
        True,
        '--nocheck',
        flag_value=False,
        help='Whether to not build outputs for tests and run checker.',
    ),
    detailed: bool = typer.Option(
        False,
        '--detailed',
        '-d',
        help='Whether to print a detailed view of the tests using tables.',
    ),
):
    main_solution = package.get_main_solution()
    if check and main_solution is None:
        console.console.print(
            '[warning]No main solution found, running without checkers.[/warning]'
        )
        check = False

    if not builder.build(verification=verification, output=check):
        return

    if verification <= VerificationLevel.VALIDATE.value:
        console.console.print(
            '[warning]Verification level is set to [item]validate (-v1)[/item], so rbx only build tests and validated them.[/warning]'
        )
        return

    with utils.StatusProgress('Running solutions...') as s:
        tracked_solutions = None
        if outcome is not None:
            tracked_solutions = {
                str(solution.path)
                for solution in get_matching_solutions(ExpectedOutcome(outcome))
            }
        if solution:
            tracked_solutions = {solution}
        solution_result = run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            group_first=detailed,
            verification=VerificationLevel(verification),
        )

    console.console.print()
    console.console.rule('[status]Run report[/status]', style='status')
    print_run_report(
        solution_result,
        console.console,
        verification,
        detailed=detailed,
    )


@app.command(
    'irun, ir', help='Build and run solution(s) by passing testcases in the CLI.'
)
@package.within_problem
def irun(
    verification: environment.VerificationParam,
    solution: Annotated[
        Optional[str],
        typer.Argument(
            help='Path to solution to run. If not specified, will run all solutions.'
        ),
    ] = None,
    outcome: Optional[str] = typer.Option(
        None,
        '--outcome',
        '-o',
        help='Include only solutions whose expected outcomes intersect with this.',
    ),
    check: bool = typer.Option(
        True,
        '--nocheck',
        flag_value=False,
        help='Whether to not build outputs for tests and run checker.',
    ),
    generator: Optional[str] = typer.Option(
        None,
        '--generator',
        '-g',
        help='Generator call to use to generate a single test for execution.',
    ),
    print: bool = typer.Option(
        False, '--print', '-p', help='Whether to print outputs to terminal.'
    ),
):
    if not print:
        console.console.print(
            '[warning]Outputs will be written to files. If you wish to print them to the terminal, use the "-p" parameter.'
        )
    if verification < VerificationLevel.ALL_SOLUTIONS.value:
        console.console.print(
            '[warning]Verification level should be at least [item]all solutions (-v4)[/item] to run solutions interactively.'
        )
        return

    main_solution = package.get_main_solution()
    if check and main_solution is None:
        console.console.print(
            '[warning]No main solution found, running without checkers.[/warning]'
        )
        check = False

    tracked_solutions = None
    if outcome is not None:
        tracked_solutions = {
            str(solution.path)
            for solution in get_matching_solutions(ExpectedOutcome(outcome))
        }
    if solution:
        tracked_solutions = {solution}
    run_and_print_interactive_solutions(
        tracked_solutions=tracked_solutions,
        check=check,
        verification=VerificationLevel(verification),
        generator=generators.get_call_from_string(generator)
        if generator is not None
        else None,
        print=print,
    )


@app.command('create, c', help='Create a new problem package.')
def create(
    name: str,
    preset: Annotated[
        Optional[str], typer.Option(help='Preset to use when creating the problem.')
    ] = None,
):
    if preset is not None:
        creation.create(name, preset=preset)
        return
    creation.create(name)


@app.command('stress', help='Run a stress test.')
@package.within_problem
def stress(
    name: str,
    generator_args: Annotated[
        Optional[str],
        typer.Option(
            '--generator',
            '-g',
            help='Run generator [name] with these args.',
        ),
    ] = None,
    finder: Annotated[
        Optional[str],
        typer.Option(
            '--finder',
            '-f',
            help='Run a stress with this finder expression.',
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
):
    if finder and not generator_args or generator_args and not finder:
        console.console.print(
            '[error]Options --generator/-g and --finder/-f should be specified together.'
        )
        raise typer.Exit(1)

    with utils.StatusProgress('Running stress...') as s:
        report = stresses.run_stress(
            name,
            timeout,
            args=generator_args,
            finder=finder,
            findingsLimit=findings,
            progress=s,
            verbose=verbose,
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
    testgroup = None
    while testgroup is None or testgroup:
        groups_by_name = {
            name: group
            for name, group in package.get_test_groups_by_name().items()
            if group.generatorScript is not None
            and group.generatorScript.path.suffix == '.txt'
        }

        testgroup = questionary.select(
            'Choose the testgroup to add the tests to.\nOnly test groups that have a .txt generatorScript are shown below: ',
            choices=list(groups_by_name) + ['(skip)'],
        ).ask()

        if testgroup not in groups_by_name:
            break
        try:
            subgroup = groups_by_name[testgroup]
            assert subgroup.generatorScript is not None
            generator_script = pathlib.Path(subgroup.generatorScript.path)

            finding_lines = []
            for finding in report.findings:
                line = finding.generator.name
                if finding.generator.args is not None:
                    line = f'{line} {finding.generator.args}'
                finding_lines.append(line)

            with generator_script.open('a') as f:
                stress_text = f'# Obtained by running `rbx {shlex.join(sys.argv[1:])}`'
                finding_text = '\n'.join(finding_lines)
                f.write(f'\n{stress_text}\n{finding_text}\n')

            console.console.print(
                f"Added [item]{len(report.findings)}[/item] tests to test group [item]{testgroup}[/item]'s generatorScript at [item]{subgroup.generatorScript.path}[/item]."
            )
        except typer.Exit:
            continue
        break


@app.command('compile', help='Compile an asset given its path.')
@package.within_problem
def compile_command(
    path: Annotated[str, typer.Argument(help='Path to the asset to compile.')],
):
    compile.any(path)


@app.command('validate', help='Run the validator in a one-off fashion, interactively.')
@package.within_problem
def validate(
    path: Annotated[
        Optional[str],
        typer.Option('--path', '-p', help='Path to the testcase to validate.'),
    ] = None,
):
    validator_tuple = validators.compile_main_validator()
    if validator_tuple is None:
        console.console.print('[error]No validator found for this problem.[/error]')
        raise typer.Exit(1)

    validator, validator_digest = validator_tuple

    input = console.multiline_prompt('Testcase input')

    if path is None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = pathlib.Path(tmpdir) / '000.in'
            tmppath.write_text(input)

            info = validators.validate_one_off(
                pathlib.Path(tmppath), validator, validator_digest
            )
    else:
        info = validators.validate_one_off(
            pathlib.Path(path), validator, validator_digest
        )

    validators.print_validation_report([info])


@app.command('environment, env', help='Set or show the current box environment.')
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
        cfg = config.get_config()
        console.console.print(f'Current environment: [item]{cfg.boxEnvironment}[/item]')
        console.console.print(
            f'Location: {environment.get_environment_path(cfg.boxEnvironment)}'
        )
        return
    if install_from is not None:
        environment.install_environment(env, pathlib.Path(install_from))
    if not get_environment_path(env).is_file():
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
        f'Changing box environment from [item]{cfg.boxEnvironment}[/item] to [item]{env}[/item]...'
    )
    cfg.boxEnvironment = env
    config.save_config(cfg)

    # Also clear cache when changing environments.
    clear()


@app.command(
    'activate',
    help='Activate the environment of the current preset used by the package.',
)
@cd.within_closest_package
def activate():
    preset_lock = presets.get_preset_lock()
    if preset_lock is None:
        console.console.print(
            '[warning]No configured preset to be activated for this package.[/warning]'
        )
        raise typer.Exit(1)

    preset = presets.get_installed_preset_or_null(preset_lock.preset_name)
    if preset is None:
        if preset_lock.uri is None:
            console.console.print(
                '[error]Preset is not installed. Install it manually, or specify a URI in [item].preset-lock.yml[/item].[/error]'
            )
            raise typer.Exit(1)
        presets.install(preset_lock.uri)

    preset = presets.get_installed_preset(preset_lock.preset_name)

    # Install the environment from the preset if it's not already installed.
    presets.optionally_install_environment_from_preset(
        preset, root=presets.get_preset_installation_path(preset_lock.name)
    )

    # Activate the environment.
    if preset.env is not None:
        environment_command(preset.name)

    console.console.print(f'[success]Preset [item]{preset.name}[/item] is activated.')


@app.command('languages', help='List the languages available in this environment')
def languages():
    env = environment.get_environment()

    console.console.print(
        f'[success]There are [item]{len(env.languages)}[/item] language(s) available.'
    )

    for language in env.languages:
        console.console.print(
            f'[item]{language.name}[/item], aka [item]{language.readable_name or language.name}[/item]:'
        )
        console.console.print(language)
        console.console.print()


@app.command('clear, clean', help='Clears cache and build directories.')
@cd.within_closest_package
def clear():
    console.console.print('Cleaning cache and build directories...')
    shutil.rmtree('.box', ignore_errors=True)
    shutil.rmtree('build', ignore_errors=True)


@app.callback()
def callback():
    pass
