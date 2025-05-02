import pathlib
import shlex
import shutil
import sys
import tempfile
from typing import Annotated, Optional

import rich
import rich.prompt
import syncer
import typer

from rbx import annotations, config, console, utils
from rbx.box import (
    cd,
    compile,
    creation,
    download,
    environment,
    generators,
    package,
    presets,
    setter_config,
    state,
    validators,
)
from rbx.box.contest import main as contest
from rbx.box.contest.contest_package import find_contest_yaml
from rbx.box.environment import VerificationLevel, get_environment_path
from rbx.box.header import generate_header
from rbx.box.packaging import main as packaging
from rbx.box.schema import CodeItem, ExpectedOutcome, TestcaseGroup
from rbx.box.solutions import (
    estimate_time_limit,
    get_exact_matching_solutions,
    get_matching_solutions,
    pick_solutions,
    print_run_report,
    run_and_print_interactive_solutions,
    run_solutions,
)
from rbx.box.statements import build_statements
from rbx.box.testcase_utils import TestcaseEntry
from rbx.box.testcases import main as testcases

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)
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
    download.app,
    name='download',
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


@app.callback()
def main(
    sanitized: bool = typer.Option(
        False,
        '--sanitized',
        '-s',
        help='Whether to compile and run testlib components with sanitizers enabled. '
        'If you want to run the solutions with sanitizers enabled, use the "-s" flag in the corresponding run command.',
    ),
    debug_logs: bool = typer.Option(
        False,
        '--debug-logs',
        '--debug',
        '-d',
        help='Whether to save extra debug logs along with the evaluation results.',
    ),
):
    state.STATE.run_through_cli = True
    state.STATE.sanitized = sanitized
    if sanitized:
        console.console.print(
            '[warning]Sanitizers are running just for testlib components.\n'
            'If you want to run the solutions with sanitizers enabled, use the [item]-s[/item] flag in the corresponding run command.[/warning]'
        )
    state.STATE.debug_logs = debug_logs


@app.command('ui', hidden=True)
@package.within_problem
def ui():
    from rbx.box.ui import main as ui_pkg

    ui_pkg.start()


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
@package.within_problem
@syncer.sync
async def build(verification: environment.VerificationParam):
    from rbx.box import builder

    await builder.build(verification=verification)


@app.command(
    'run, r',
    rich_help_panel='Testing',
    help='Build and run solution(s).',
)
@package.within_problem
@syncer.sync
async def run(
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
    timeit: bool = typer.Option(
        False,
        '--time',
        '-t',
        help='Whether to use estimate a time limit based on accepted solutions.',
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
):
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

    if choice:
        tracked_solutions = set(await pick_solutions(tracked_solutions))
        if not tracked_solutions:
            console.console.print('[error]No solutions selected. Exiting.[/error]')
            raise typer.Exit(1)

    from rbx.box import builder

    if not await builder.build(verification=verification, output=check):
        return

    if verification <= VerificationLevel.VALIDATE.value:
        console.console.print(
            '[warning]Verification level is set to [item]validate (-v1)[/item], so rbx only build tests and validated them.[/warning]'
        )
        return

    override_tl = None
    if timeit:
        if sanitized:
            console.console.print(
                '[error]Sanitizers are known to be time-hungry, so they cannot be used for time estimation.\n'
                'Remove either the [item]-s[/item] flag or the [item]-t[/item] flag to run solutions without sanitizers.[/error]'
            )
            raise typer.Exit(1)

        # Never use sanitizers for time estimation.
        override_tl = await _time_impl(check=check, detailed=False)
        if override_tl is None:
            raise typer.Exit(1)

    if sanitized:
        console.console.print(
            '[warning]Sanitizers are running, so the time limit for the problem will be dropped, '
            'and the environment default time limit will be used instead.[/warning]'
        )

    if sanitized and tracked_solutions is None:
        console.console.print(
            '[warning]Sanitizers are running, and no solutions were specified to run. Will only run [item]ACCEPTED[/item] solutions.'
        )
        tracked_solutions = {
            str(solution.path)
            for solution in get_exact_matching_solutions(ExpectedOutcome.ACCEPTED)
        }

    with utils.StatusProgress('Running solutions...') as s:
        solution_result = run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            verification=VerificationLevel(verification),
            timelimit_override=override_tl,
            sanitized=sanitized,
        )

    console.console.print()
    console.console.rule('[status]Run report[/status]', style='status')
    await print_run_report(
        solution_result,
        console.console,
        VerificationLevel(verification),
        detailed=detailed,
        skip_printing_limits=sanitized,
    )


async def _time_impl(check: bool, detailed: bool) -> Optional[int]:
    if package.get_main_solution() is None:
        console.console.print(
            '[warning]No main solution found, so cannot estimate a time limit.[/warning]'
        )
        return None

    verification = VerificationLevel.ALL_SOLUTIONS.value

    with utils.StatusProgress('Running ACCEPTED solutions...') as s:
        tracked_solutions = {
            str(solution.path)
            for solution in get_exact_matching_solutions(ExpectedOutcome.ACCEPTED)
        }
        solution_result = run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            verification=VerificationLevel(verification),
            timelimit_override=-1,  # Unlimited for time limit estimation
        )

    console.console.print()
    console.console.rule(
        '[status]Run report (for time estimation)[/status]', style='status'
    )
    ok = await print_run_report(
        solution_result,
        console.console,
        VerificationLevel(verification),
        detailed=detailed,
        skip_printing_limits=True,
    )

    if not ok:
        console.console.print(
            '[error]Failed to run ACCEPTED solutions, so cannot estimate a reliable time limit.[/error]'
        )
        return None

    console.console.print()
    return await estimate_time_limit(console.console, solution_result)


@app.command(
    'time, t',
    rich_help_panel='Testing',
    help='Estimate a time limit for the problem based on a time limit formula and timings of accepted solutions.',
)
@package.within_problem
@syncer.sync
async def time(
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

    from rbx.box import builder

    verification = VerificationLevel.ALL_SOLUTIONS.value
    if not await builder.build(verification=verification, output=check):
        return None

    await _time_impl(check, detailed)


@app.command(
    'irun, ir',
    rich_help_panel='Testing',
    help='Build and run solution(s) by passing testcases in the CLI.',
)
@package.within_problem
@syncer.sync
async def irun(
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
    testcase: Optional[str] = typer.Option(
        None,
        '--testcase',
        '--test',
        '-tc',
        '-t',
        help='Testcase to run, in the format "[group]/[index]". If not specified, will run interactively.',
    ),
    output: bool = typer.Option(
        False,
        '--output',
        '-o',
        help='Whether to ask user for custom output.',
    ),
    print: bool = typer.Option(
        False, '--print', '-p', help='Whether to print outputs to terminal.'
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

    tracked_solutions = None
    if outcome is not None:
        tracked_solutions = {
            str(solution.path)
            for solution in get_matching_solutions(ExpectedOutcome(outcome))
        }
    if solution:
        tracked_solutions = {solution}

    if choice:
        tracked_solutions = set(await pick_solutions(tracked_solutions))
        if not tracked_solutions:
            console.console.print('[error]No solutions selected. Exiting.[/error]')
            raise typer.Exit(1)

    if sanitized and tracked_solutions is None:
        console.console.print(
            '[warning]Sanitizers are running, and no solutions were specified to run. Will only run [item]ACCEPTED[/item] solutions.'
        )
        tracked_solutions = {
            str(solution.path)
            for solution in get_exact_matching_solutions(ExpectedOutcome.ACCEPTED)
        }

    with utils.StatusProgress('Running solutions...') as s:
        await run_and_print_interactive_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            verification=VerificationLevel(verification),
            generator=generators.get_call_from_string(generator)
            if generator is not None
            else None,
            testcase_entry=TestcaseEntry.parse(testcase) if testcase else None,
            custom_output=output,
            print=print,
            sanitized=sanitized,
        )


@app.command(
    'create, c',
    rich_help_panel='Management',
    help='Create a new problem package.',
)
def create(
    name: str,
    preset: Annotated[
        Optional[str], typer.Option(help='Preset to use when creating the problem.')
    ] = None,
):
    if find_contest_yaml() is not None:
        console.console.print(
            '[error]Cannot [item]rbx create[/item] a problem inside a contest.[/error]'
        )
        console.console.print(
            '[error]Instead, use [item]rbx contest add[/item] to add a problem to a contest.[/error]'
        )
        raise typer.Exit(1)

    if preset is not None:
        creation.create(name, preset=preset)
        return
    creation.create(name)


@app.command(
    'stress',
    rich_help_panel='Testing',
    help='Run a stress test.',
)
@package.within_problem
@syncer.sync
async def stress(
    name: Annotated[
        str,
        typer.Argument(
            help='Name of the stress test to run (specified in problem.rbx.yml), '
            'or the generator to run, in case -g is specified.'
        ),
    ],
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
    sanitized: bool = typer.Option(
        False,
        '--sanitized',
        '-s',
        help='Whether to compile the solutions with sanitizers enabled.',
    ),
):
    if finder and not generator_args or generator_args and not finder:
        console.console.print(
            '[error]Options --generator/-g and --finder/-f should be specified together.'
        )
        raise typer.Exit(1)

    from rbx.box import stresses

    with utils.StatusProgress('Running stress...') as s:
        report = await stresses.run_stress(
            name,
            timeout,
            args=generator_args,
            finder=finder,
            findingsLimit=findings,
            progress=s,
            verbose=verbose,
            sanitized=sanitized,
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

        import questionary

        testgroup = await questionary.select(
            'Choose the testgroup to add the tests to.\nOnly test groups that have a .txt generatorScript are shown below: ',
            choices=list(groups_by_name) + ['(create new script)', '(skip)'],
        ).ask_async()

        if testgroup == '(create new script)':
            new_script_name = await questionary.text(
                'Enter the name of the new .txt generatorScript file: '
            ).ask_async()
            new_script_path = pathlib.Path(new_script_name).with_suffix('.txt')
            new_script_path.parent.mkdir(parents=True, exist_ok=True)
            new_script_path.touch()

            # Temporarily create a new testgroup with the new script.
            testgroup = new_script_path.stem
            groups_by_name[testgroup] = TestcaseGroup(
                name=testgroup, generatorScript=CodeItem(path=new_script_path)
            )
            ru, problem_yml = package.get_ruyaml()
            if 'testcases' not in problem_yml:
                problem_yml['testcases'] = []
            problem_yml['testcases'].append(
                {
                    'name': testgroup,
                    'generatorScript': new_script_path.name,
                }
            )
            dest = package.find_problem_yaml()
            assert dest is not None
            utils.save_ruyaml(dest, ru, problem_yml)
            package.clear_package_cache()

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
                f"Added [item]{len(report.findings)}[/item] tests to test group [item]{testgroup}[/item]'s generatorScript at [item]{subgroup.generatorScript.path}[/item]"
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
):
    if path is None:
        import questionary

        path = await questionary.path("What's the path to your asset?").ask_async()
        if path is None:
            console.console.print('[error]No path specified.[/error]')
            raise typer.Exit(1)

    compile.any(path, sanitized, warnings)


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

            info = await validators.validate_one_off(
                pathlib.Path(tmppath), validator, validator_digest
            )
    else:
        info = await validators.validate_one_off(
            pathlib.Path(path), validator, validator_digest
        )

    validators.print_validation_report([info])


@app.command(
    'unit',
    rich_help_panel='Testing',
    help='Run unit tests for the validator and checker.',
)
@package.within_problem
def unit_tests():
    from rbx.box import unit

    with utils.StatusProgress('Running unit tests...') as s:
        unit.run_unit_tests(s)


@app.command(
    'header',
    rich_help_panel='Configuration',
    help='Generate the rbx.h header file.',
)
@package.within_problem
def header():
    generate_header()


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
    rich_help_panel='Configuration',
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
            f'[item]{language.name}[/item], aka [item]{language.readable_name or language.name}[/item]:'
        )
        console.console.print(language)
        console.console.print()


@app.command(
    'clear, clean',
    rich_help_panel='Management',
    help='Clears cache and build directories.',
)
@cd.within_closest_package
def clear():
    console.console.print('Cleaning cache and build directories...')
    shutil.rmtree('.box', ignore_errors=True)
    shutil.rmtree('build', ignore_errors=True)
