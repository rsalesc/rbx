import pathlib
import shlex
import shutil
from pathlib import PosixPath
from typing import Callable, Dict, List, Optional, Set

import typer

from rbx import console
from rbx.box import checkers, package, testcases, validators
from rbx.box.code import SanitizationLevel, compile_item, run_item
from rbx.box.environment import (
    EnvironmentSandbox,
    ExecutionConfig,
)
from rbx.box.schema import (
    CodeItem,
    Generator,
    GeneratorCall,
    Testcase,
    TestcaseSubgroup,
)
from rbx.box.stressing import generator_parser
from rbx.box.testcases import find_built_testcases
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.steps import (
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
)
from rbx.utils import StatusProgress


def _compile_generator(generator: CodeItem) -> str:
    return compile_item(generator, sanitized=SanitizationLevel.PREFER)


def _get_group_input(
    group_path: pathlib.Path, subgroup_prefix: str, i: int
) -> pathlib.Path:
    return group_path / f'{subgroup_prefix}{i:03d}.in'


def _get_group_output(
    group_path: pathlib.Path, subgroup_prefix: str, i: int
) -> pathlib.Path:
    return group_path / f'{subgroup_prefix}{i:03d}.out'


def _copy_testcase_over(
    testcase: Testcase, group_path: pathlib.Path, subgroup_prefix: str, i: int
):
    shutil.copy(
        str(testcase.inputPath),
        _get_group_input(group_path, subgroup_prefix, i),
    )
    if testcase.outputPath is not None and testcase.outputPath.is_file():
        shutil.copy(
            str(testcase.outputPath),
            _get_group_output(group_path, subgroup_prefix, i),
        )


def _run_generator(
    generator: Generator,
    args: Optional[str],
    compiled_digest: str,
    group_path: pathlib.Path,
    subgroup_prefix: str,
    i: int = 0,
):
    generation_stderr = DigestHolder()
    run_log = run_item(
        generator,
        DigestOrSource.create(compiled_digest),
        stdout=DigestOrDest.create(_get_group_input(group_path, subgroup_prefix, i)),
        stderr=DigestOrDest.create(generation_stderr),
        extra_args=args or None,
    )

    if not run_log or run_log.exitcode != 0:
        console.console.print(
            f'[error]Failed generating test {i} from group path {group_path}[/error]',
        )
        if run_log is not None:
            console.console.print(f'[error]Summary:[/error] {run_log.get_summary()}')
        if generation_stderr.value is not None:
            console.console.print('[error]Stderr:[/error]')
            console.console.print(
                package.get_digest_as_string(generation_stderr.value) or ''
            )
        raise typer.Exit(1)


def get_all_built_testcases() -> Dict[str, List[Testcase]]:
    pkg = package.find_problem_package_or_die()
    res = {group.name: find_built_testcases(group) for group in pkg.testcases}
    return res


def get_call_from_string(call_str: str) -> GeneratorCall:
    name, args = call_str.split(None, 1)
    return GeneratorCall(name=name, args=args)


def generate_output_for_testcase(
    main_solution_digest: str,
    testcase: Testcase,
    stderr_path: Optional[pathlib.Path] = None,
):
    assert testcase.outputPath is not None
    pkg = package.find_problem_package_or_die()
    main_solution = package.get_main_solution()
    if main_solution is None:
        return

    # Obey no limits when generating testcases.
    sandbox = EnvironmentSandbox()
    sandbox.fileSizeLimit = pkg.outputLimit
    extra_config = ExecutionConfig(sandbox=sandbox)

    try:
        run_log = run_item(
            main_solution,
            DigestOrSource.create(main_solution_digest),
            stdin=DigestOrSource.create(testcase.inputPath),
            stdout=DigestOrDest.create(testcase.outputPath),
            stderr=DigestOrDest.create(stderr_path)
            if stderr_path is not None
            else None,
            extra_config=extra_config,
        )
    except:
        console.console.print(
            '[error]Failed running main solution to generate testcase.[/error]'
        )
        raise

    if run_log is None or run_log.exitcode != 0:
        console.console.print(
            f'[error]Failed generating output for [item]{testcase.inputPath}[/item][/error]',
        )
        if run_log is not None:
            console.console.print(f'[error]Summary:[/error] {run_log.get_summary()}')
            checker_result = checkers.check_with_no_output(run_log)
            console.console.print(
                f'[warning]Verdict: [item]{checker_result.outcome.value}[/item][/warning]',
            )
            console.console.print(
                f'[warning]Message: [info]{checker_result.message}[/info][/warning]',
            )
            console.console.print(f'Input written at [item]{testcase.inputPath}[/item]')
            console.console.print(
                f'Output written at [item]{testcase.outputPath}[/item]'
            )
            console.console.print(f'Stderr written at [item]{stderr_path}[/item]')
        raise typer.Exit(1)


def generate_outputs_for_testcases(
    progress: Optional[StatusProgress] = None, groups: Optional[Set[str]] = None
):
    def step():
        if progress is not None:
            progress.step()

    pkg = package.find_problem_package_or_die()

    built_testcases = get_all_built_testcases()
    main_solution = package.get_main_solution()
    solution_digest: Optional[str] = None

    if main_solution is not None:
        if progress:
            progress.update('Compiling main solution...')
        try:
            solution_digest = compile_item(main_solution)
        except:
            console.console.print('[error]Failed compiling main solution.[/error]')
            raise

    gen_runs_dir = package.get_problem_runs_dir() / '.gen'
    shutil.rmtree(str(gen_runs_dir), ignore_errors=True)
    gen_runs_dir.mkdir(parents=True, exist_ok=True)

    for group in pkg.testcases:
        if groups is not None and group.name not in groups:
            continue
        group_testcases = built_testcases[group.name]

        for testcase in group_testcases:
            stderr_path = gen_runs_dir / 'main.stderr'

            assert testcase.outputPath is not None
            if main_solution is None or solution_digest is None:
                console.console.print(
                    '[error]No main solution found to generate outputs for testcases.[/error]',
                )
                raise typer.Exit(1)

            generate_output_for_testcase(solution_digest, testcase, stderr_path)
            step()


def _run_generator_script(testcase: TestcaseSubgroup, cacher: FileCacher) -> str:
    assert testcase.generatorScript is not None

    if not testcase.generatorScript.path.is_file():
        console.console.print(
            f'[error]Generator script not found: [item]{testcase.generatorScript.path}[/item][/error]'
        )
        raise typer.Exit(1)

    script_digest = DigestHolder()
    if testcase.generatorScript.path.suffix == '.txt':
        script_digest.value = cacher.put_file_from_path(testcase.generatorScript.path)
    else:
        try:
            compiled_digest = compile_item(testcase.generatorScript)
        except:
            console.console.print(
                f'[error]Failed compiling generator script for group [item]{testcase.name}[/item].[/error]'
            )
            raise

        run_stderr = DigestHolder()
        run_log = run_item(
            testcase.generatorScript,
            DigestOrSource.create(compiled_digest),
            stdout=DigestOrDest.create(script_digest),
            stderr=DigestOrDest.create(run_stderr),
        )

        if run_log is None or run_log.exitcode != 0:
            console.console.print(
                f'Could not run generator script for group {testcase.name}'
            )
            if run_log is not None:
                console.console.print(
                    f'[error]Summary:[/error] {run_log.get_summary()}'
                )
            if run_stderr.value is not None:
                console.console.print('[error]Stderr:[/error]')
                console.console.print(
                    package.get_digest_as_string(run_stderr.value) or ''
                )
            raise typer.Exit(1)

    assert script_digest.value
    script = cacher.get_file_content(script_digest.value).decode()
    return script


def _extract_script_lines(script: str):
    lines = script.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        yield shlex.split(line)[0], shlex.join(shlex.split(line)[1:])


def _get_necessary_generators(groups: Set[str], cacher: FileCacher) -> Set[str]:
    pkg = package.find_problem_package_or_die()
    existing_generators = set(generator.name for generator in pkg.generators)

    necessary_generators = set()
    for group in pkg.testcases:
        if groups is not None and group.name not in groups:
            continue

        for generator_call in group.generators:
            necessary_generators.add(generator_call.name)

        if group.generatorScript is not None:
            script = _run_generator_script(group, cacher)
            for generator_name, _ in _extract_script_lines(script):
                necessary_generators.add(generator_name)

    return existing_generators.intersection(necessary_generators)


def compile_generators(
    progress: Optional[StatusProgress] = None,
    tracked_generators: Optional[Set[str]] = None,
) -> Dict[str, str]:
    def update_status(text: str):
        if progress is not None:
            progress.update(text)

    pkg = package.find_problem_package_or_die()

    generator_to_compiled_digest = {}

    for generator in pkg.generators:
        if tracked_generators is not None and generator.name not in tracked_generators:
            continue
        update_status(f'Compiling generator [item]{generator.name}[/item]')
        try:
            generator_to_compiled_digest[generator.name] = _compile_generator(generator)
        except:
            console.console.print(
                f'[error]Failed compiling generator [item]{generator.name}[/item].[/error]'
            )
            raise

    return generator_to_compiled_digest


def generate_standalone(
    call: GeneratorCall,
    output: pathlib.Path,
    validate: bool = True,
    generator_digest: Optional[str] = None,
    validator_digest: Optional[str] = None,
) -> GeneratorCall:
    # Generator args parser
    parsed_args = generator_parser.parse(call.args or '')
    vars = package.find_problem_package_or_die().expanded_vars
    generator_for_args = generator_parser.Generator(vars)
    expanded_args_str = generator_for_args.generate(parsed_args)

    generation_stderr = DigestHolder()

    # Get generator item
    generator = package.get_generator(call.name)
    if generator_digest is None:
        generator_digest = _compile_generator(generator)

    generation_log = run_item(
        generator,
        DigestOrSource.create(generator_digest),
        stdout=DigestOrDest.create(output),
        stderr=DigestOrDest.create(generation_stderr),
        extra_args=expanded_args_str or None,
    )
    if not generation_log or generation_log.exitcode != 0:
        console.console.print(
            f'[error]Failed generating test using generator call [info]{call.name} {expanded_args_str}[/info][/error]',
        )
        if generation_log is not None:
            console.console.print(
                f'[error]Summary:[/error] {generation_log.get_summary()}'
            )
        if generation_stderr.value is not None:
            console.console.print('[error]Stderr:[/error]')
            console.console.print(
                package.get_digest_as_string(generation_stderr.value) or ''
            )

        raise typer.Exit(1)

    validator = package.get_validator_or_nil()
    # Run validator, if it is available.
    if validator is not None and validate:
        if validator_digest is None:
            validator_tp = validators.compile_main_validator()
            assert validator_tp is not None
            _, validator_digest = validator_tp
        ok, message, *_ = validators.validate_test(output, validator, validator_digest)
        if not ok:
            console.console.print(
                f'[error]Failed validating testcase generated by call [info]{call.name} {expanded_args_str}[/info][/error]'
            )
            console.console.print(f'[error]Message:[/error] {message}')
            console.console.print(f'Testcase written at [item]{output}[/item]')
            raise typer.Exit(1)

    return call.model_copy(update={'args': expanded_args_str})


def _generate_testcases_for_subgroup(
    subgroup: TestcaseSubgroup,
    group_path: pathlib.Path,
    subgroup_prefix: str,
    compiled_generators: Dict[str, str],
    step: Callable,
):
    cacher = package.get_file_cacher()

    group_path.mkdir(parents=True, exist_ok=True)

    i = 0
    # Individual testcases.
    for tc in subgroup.testcases or []:
        _copy_testcase_over(tc, group_path, subgroup_prefix, i)
        i += 1
        step()

    # Glob testcases.
    if subgroup.testcaseGlob:
        matched_inputs = sorted(PosixPath().glob(subgroup.testcaseGlob))

        for input_path in matched_inputs:
            if not input_path.is_file() or input_path.suffix != '.in':
                continue
            output_path = input_path.parent / f'{input_path.stem}.out'
            tc = Testcase(inputPath=input_path, outputPath=output_path)
            _copy_testcase_over(tc, group_path, subgroup_prefix, i)
            i += 1
            step()

    # Run single generators.
    for generator_call in subgroup.generators:
        generator = package.get_generator(generator_call.name)
        if generator.name not in compiled_generators:
            console.console.print(f'Generator {generator.name} not compiled')
            raise typer.Exit(1)

        _run_generator(
            generator,
            generator_call.args,
            compiled_generators[generator.name],
            group_path,
            subgroup_prefix,
            i,
        )
        i += 1
        step()

    # Run generator script.
    if subgroup.generatorScript is not None:
        script = _run_generator_script(subgroup, cacher)

        # Run each line from generator script.
        for generator_name, args in _extract_script_lines(script):
            generator = package.get_generator(generator_name)
            if generator.name not in compiled_generators:
                console.console.print(f'Generator {generator.name} not compiled')
                raise typer.Exit(1)

            _run_generator(
                generator,
                args,
                compiled_generators[generator.name],
                group_path,
                subgroup_prefix,
                i,
            )
            i += 1
            step()


def generate_testcases(
    progress: Optional[StatusProgress] = None, groups: Optional[Set[str]] = None
):
    def step():
        if progress is not None:
            progress.step()

    pkg = package.find_problem_package_or_die()
    cacher = package.get_file_cacher()

    compiled_generators = compile_generators(
        progress=progress,
        tracked_generators=_get_necessary_generators(groups, cacher)
        if groups is not None
        else None,
    )

    testcases.clear_built_testcases()

    for testcase in pkg.testcases:
        if groups is not None and testcase.name not in groups:
            continue
        group_path = package.get_build_testgroup_path(testcase.name)

        if not testcase.subgroups:
            # Testcase group is itself a test subgroup.
            _generate_testcases_for_subgroup(
                testcase, group_path, '', compiled_generators, step
            )
            continue

        renamed_testcase = testcase.model_copy(update={'name': 'main'})
        subgroups = [renamed_testcase] + testcase.subgroups
        for i, subgroup in enumerate(subgroups):
            # Test subgroups were specified, use them.
            _generate_testcases_for_subgroup(
                subgroup, group_path, f'{i}-{subgroup.name}-', compiled_generators, step
            )
