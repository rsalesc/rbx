import abc
import pathlib
import shlex
import shutil
from pathlib import PosixPath
from typing import Dict, List, Optional, Set

import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import checkers, package, testcases, validators
from rbx.box.code import SanitizationLevel, compile_item, run_item
from rbx.box.environment import (
    EnvironmentSandbox,
    ExecutionConfig,
)
from rbx.box.schema import (
    CodeItem,
    GeneratorCall,
    Testcase,
    TestcaseSubgroup,
)
from rbx.box.stressing import generator_parser
from rbx.box.testcases import TestcaseEntry, find_built_testcases
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


def _fill_output_for_testcase(testcase: Testcase) -> Testcase:
    res = testcase.model_copy()
    if res.outputPath is not None:
        return res
    output_path = res.inputPath.with_suffix('.out')
    if output_path.is_file():
        res.outputPath = output_path
    return res


def _copy_testcase_over(
    testcase: Testcase,
    dest: Testcase,
):
    testcase = _fill_output_for_testcase(testcase)
    dest.inputPath.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        str(testcase.inputPath),
        str(dest.inputPath),
    )
    if (
        testcase.outputPath is not None
        and testcase.outputPath.is_file()
        and dest.outputPath is not None
    ):
        dest.outputPath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(
            str(testcase.outputPath),
            str(dest.outputPath),
        )


def get_all_built_testcases() -> Dict[str, List[Testcase]]:
    pkg = package.find_problem_package_or_die()
    res = {group.name: find_built_testcases(group) for group in pkg.testcases}
    return res


def get_call_from_string(call_str: str) -> GeneratorCall:
    name, args = call_str.split(None, 1)
    return GeneratorCall(name=name, args=args)


def _run_generator_script(testcase: TestcaseSubgroup) -> str:
    assert testcase.generatorScript is not None

    cacher = package.get_file_cacher()

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


class GenerationMetadata(BaseModel):
    copied_to: Testcase

    copied_from: Optional[Testcase] = None
    generator_call: Optional[GeneratorCall] = None


class GenerationTestcaseEntry(BaseModel):
    group_entry: TestcaseEntry
    subgroup_entry: TestcaseEntry

    metadata: GenerationMetadata


class TestcaseVisitor(abc.ABC):
    @abc.abstractmethod
    def visit(self, entry: GenerationTestcaseEntry):
        pass

    def should_visit_group(self, group_name: str) -> bool:
        return True

    def should_visit_subgroup(self, subgroup_path: str) -> bool:
        return True

    def should_visit_generator_scripts(
        self, group_name: str, subgroup_path: str
    ) -> bool:
        return True


class TestcaseGroupVisitor(TestcaseVisitor):
    def __init__(self, groups: Optional[Set[str]] = None):
        self.groups = groups

    def should_visit_group(self, group_name: str) -> bool:
        return self.groups is None or group_name in self.groups


def run_testcase_visitor(visitor: TestcaseVisitor):
    pkg = package.find_problem_package_or_die()

    def _explore_subgroup(
        subgroup: TestcaseSubgroup, subgroup_index: int, prefix: List[str]
    ):
        assert prefix and len(prefix) >= 1 and len(prefix) <= 2
        group_path = prefix[0]
        subgroup_path = '/'.join(prefix)
        if not visitor.should_visit_subgroup(subgroup_path):
            return

        def _entry(i: int) -> TestcaseEntry:
            return TestcaseEntry(group=group_path, index=i)

        def _sub_entry(i: int) -> TestcaseEntry:
            return TestcaseEntry(group=subgroup_path, index=i)

        def _copied_to(i: int) -> Testcase:
            group_fs_path = package.get_build_testgroup_path(group_path)
            group_prefix = ''
            if len(prefix) == 2:
                group_prefix = f'{subgroup_index}-{prefix[1]}-'
            return Testcase(
                inputPath=_get_group_input(group_fs_path, group_prefix, i),
                outputPath=_get_group_output(group_fs_path, group_prefix, i),
            )

        # Go through testcases.
        i = 0
        # Individual testcases.
        for tc in subgroup.testcases or []:
            visitor.visit(
                GenerationTestcaseEntry(
                    group_entry=_entry(i),
                    subgroup_entry=_sub_entry(i),
                    metadata=GenerationMetadata(
                        copied_from=_fill_output_for_testcase(tc),
                        copied_to=_copied_to(i),
                    ),
                )
            )
            i += 1

        # Glob testcases.
        if subgroup.testcaseGlob:
            matched_inputs = sorted(PosixPath().glob(subgroup.testcaseGlob))

            for input_path in matched_inputs:
                if not input_path.is_file() or input_path.suffix != '.in':
                    continue

                tc = Testcase(inputPath=input_path)
                visitor.visit(
                    GenerationTestcaseEntry(
                        group_entry=_entry(i),
                        subgroup_entry=_sub_entry(i),
                        metadata=GenerationMetadata(
                            copied_from=_fill_output_for_testcase(tc),
                            copied_to=_copied_to(i),
                        ),
                    )
                )
                i += 1

        # Single generators.
        for generator_call in subgroup.generators:
            visitor.visit(
                GenerationTestcaseEntry(
                    group_entry=_entry(i),
                    subgroup_entry=_sub_entry(i),
                    metadata=GenerationMetadata(
                        generator_call=generator_call,
                        copied_to=_copied_to(i),
                    ),
                )
            )
            i += 1

        if not visitor.should_visit_generator_scripts(group_path, subgroup_path):
            return

        # Run generator script.
        if subgroup.generatorScript is not None:
            script = _run_generator_script(subgroup)

            # Run each line from generator script.
            for generator_name, args in _extract_script_lines(script):
                call = GeneratorCall(name=generator_name, args=args)
                visitor.visit(
                    GenerationTestcaseEntry(
                        group_entry=_entry(i),
                        subgroup_entry=_sub_entry(i),
                        metadata=GenerationMetadata(
                            generator_call=call,
                            copied_to=_copied_to(i),
                        ),
                    )
                )
                i += 1

    for group in pkg.testcases:
        if not visitor.should_visit_group(group.name):
            continue

        _explore_subgroup(group, 0, [group.name])

        for i, subgroup in enumerate(group.subgroups):
            _explore_subgroup(subgroup, i, [group.name, subgroup.name])


def _get_necessary_generators_for_groups(
    groups: Optional[Set[str]] = None,
) -> Set[str]:
    pkg = package.find_problem_package_or_die()
    existing_generators = set(generator.name for generator in pkg.generators)
    necessary_generators = set()

    class NecessaryGeneratorsVisitor(TestcaseGroupVisitor):
        def visit(self, entry: GenerationTestcaseEntry):
            if entry.metadata.generator_call is not None:
                necessary_generators.add(entry.metadata.generator_call.name)

    run_testcase_visitor(NecessaryGeneratorsVisitor(groups))

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


def expand_generator_call(call: GeneratorCall) -> GeneratorCall:
    vars = package.find_problem_package_or_die().expanded_vars
    generator_for_args = generator_parser.Generator(vars)
    parsed_args = generator_parser.parse(call.args or '')
    return call.model_copy(update={'args': generator_for_args.generate(parsed_args)})


def generate_standalone(
    spec: GenerationMetadata,
    validate: bool = True,
    group_entry: Optional[TestcaseEntry] = None,
    generator_digest: Optional[str] = None,
    validator_digest: Optional[str] = None,
    progress: Optional[StatusProgress] = None,
):
    def _print_error_header(text: Optional[str] = None):
        prefix = 'Failed generating test'
        if group_entry is not None:
            prefix += (
                f' [item]{group_entry.group}[/item]/[item]{group_entry.index}[/item]'
            )
        suffix = '.'
        if text:
            suffix = f': {text}'
        if spec.generator_call is not None:
            console.console.print(
                f'[error]{prefix} using generator call [info]{spec.generator_call.name} {spec.generator_call.args}[/info]{suffix}[/error]'
            )
        else:
            console.console.print(f'[error]{prefix}{suffix}[/error]')

    if spec.generator_call is not None:
        call = spec.generator_call

        generation_stderr = DigestHolder()

        # Get generator item
        generator = package.get_generator(call.name)
        if generator_digest is None:
            if progress:
                progress.update(f'Compiling generator {generator.name}...')
            generator_digest = _compile_generator(generator)

        if progress:
            progress.update(
                f'Generating testcase [status]{generator.name} {call.args}[/status]...'
            )
        generation_log = run_item(
            generator,
            DigestOrSource.create(generator_digest),
            stdout=DigestOrDest.create(spec.copied_to.inputPath),
            stderr=DigestOrDest.create(generation_stderr),
            extra_args=call.args or None,
        )
        if not generation_log or generation_log.exitcode != 0:
            _print_error_header()
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
    elif spec.copied_from is not None:
        _copy_testcase_over(spec.copied_from, spec.copied_to)

    validator = package.get_validator_or_nil()
    # Run validator, if it is available.
    if validator is not None and validate:
        if validator_digest is None:
            if progress:
                progress.update('Compiling validator...')
            validator_tp = validators.compile_main_validator()
            assert validator_tp is not None
            _, validator_digest = validator_tp
        if progress:
            progress.update('Validating test...')
        ok, message, *_ = validators.validate_test(
            spec.copied_to.inputPath,
            validator,
            validator_digest,
        )
        if not ok:
            _print_error_header('Failed validating testcase.')
            console.console.print(f'[error]Message:[/error] {message}')
            console.console.print(
                f'Testcase written at [item]{spec.copied_to.inputPath}[/item]'
            )
            raise typer.Exit(1)


def generate_testcases(
    progress: Optional[StatusProgress] = None, groups: Optional[Set[str]] = None
):
    def step():
        if progress is not None:
            progress.step()

    compiled_generators = compile_generators(
        progress=progress,
        tracked_generators=_get_necessary_generators_for_groups(groups)
        if groups is not None
        else None,
    )

    testcases.clear_built_testcases()

    class BuildTestcaseVisitor(TestcaseGroupVisitor):
        def visit(self, entry: GenerationTestcaseEntry):
            if entry.metadata.copied_from is not None:
                _copy_testcase_over(
                    entry.metadata.copied_from,
                    entry.metadata.copied_to,
                )

            if entry.metadata.generator_call is not None:
                generate_standalone(
                    entry.metadata,
                    group_entry=entry.group_entry,
                    validate=False,
                    generator_digest=compiled_generators[
                        entry.metadata.generator_call.name
                    ],
                )
            step()

    run_testcase_visitor(BuildTestcaseVisitor(groups))


def generate_output_for_testcase(
    main_solution_digest: str,
    testcase: Testcase,
    stderr_path: Optional[pathlib.Path] = None,
):
    assert testcase.outputPath is not None

    if testcase.outputPath.is_file():
        # Output file was already copied over from manual tests.
        return

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

    class GenerateOutputsVisitor(TestcaseGroupVisitor):
        def visit(self, entry: GenerationTestcaseEntry):
            tc = entry.metadata.copied_to
            if not tc.inputPath.is_file():
                return
            assert tc.outputPath is not None

            if (
                main_solution is None or solution_digest is None
            ) and not tc.outputPath.is_file():
                console.console.print(
                    '[error]No main solution found to generate outputs for testcases.[/error]',
                )
                raise typer.Exit(1)

            assert solution_digest is not None
            generate_output_for_testcase(
                solution_digest,
                tc,
                gen_runs_dir / 'main.stderr',
            )
            step()

    run_testcase_visitor(GenerateOutputsVisitor(groups))


def extract_generation_testcases(
    entries: List[TestcaseEntry],
) -> List[GenerationTestcaseEntry]:
    # TODO: support subgroups.
    groups = set(entry.group for entry in entries)
    entry_keys = set(entry.key() for entry in entries)

    res: List[GenerationTestcaseEntry] = []

    class ExtractGenerationTestcasesVisitor(TestcaseVisitor):
        def should_visit_group(self, group_name: str) -> bool:
            return group_name in groups

        def visit(self, entry: GenerationTestcaseEntry):
            # TODO: support subgroups.
            if entry.group_entry.key() not in entry_keys:
                return
            res.append(entry)

    run_testcase_visitor(ExtractGenerationTestcasesVisitor())
    return res
