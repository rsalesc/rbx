import pathlib
import shutil
from typing import Dict, List, Optional, Set

import typer

from rbx import console
from rbx.box import checkers, package, testcase_utils, validators
from rbx.box.code import SanitizationLevel, compile_item, run_item
from rbx.box.schema import (
    CodeItem,
    GeneratorCall,
    TaskType,
    Testcase,
)
from rbx.box.tasks import run_solution_on_testcase
from rbx.box.testcase_extractors import (
    GenerationMetadata,
    GenerationTestcaseEntry,
    TestcaseGroupVisitor,
    extract_generation_testcases,
    run_testcase_visitor,
)
from rbx.box.testcase_utils import (
    TestcaseEntry,
    fill_output_for_defined_testcase,
    find_built_testcases,
)
from rbx.grading.steps import (
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
    Evaluation,
    Outcome,
)
from rbx.utils import StatusProgress


def _compile_generator(generator: CodeItem) -> str:
    return compile_item(generator, sanitized=SanitizationLevel.PREFER)


def _copy_testcase_over(
    testcase: Testcase,
    dest: Testcase,
):
    testcase = fill_output_for_defined_testcase(testcase)
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


def _copy_testcase_output_over(
    src_output_path: pathlib.Path, dest_output_path: pathlib.Path, suffix: str
) -> bool:
    dest_output_path.parent.mkdir(parents=True, exist_ok=True)

    src_path = src_output_path.with_suffix(suffix)
    if not src_path.is_file():
        return False

    shutil.copy(str(src_path), str(dest_output_path.with_suffix(suffix)))
    return True


def _copy_testcase_outputs_over(
    testcase: Testcase, dest: Testcase, pipes: bool = False
):
    assert dest.outputPath is not None
    dest.outputPath.parent.mkdir(parents=True, exist_ok=True)

    has_copied = False

    if testcase.outputPath is not None and testcase.outputPath.is_file():
        shutil.copy(str(testcase.outputPath), str(dest.outputPath))
        has_copied = True

    if not pipes:
        return has_copied

    reference_path = testcase.outputPath or testcase.inputPath
    if _copy_testcase_output_over(reference_path, dest.outputPath, '.pin'):
        has_copied = True

    if _copy_testcase_output_over(reference_path, dest.outputPath, '.pout'):
        has_copied = True

    if _copy_testcase_output_over(reference_path, dest.outputPath, '.pio'):
        has_copied = True

    return has_copied


def get_all_built_testcases() -> Dict[str, List[Testcase]]:
    pkg = package.find_problem_package_or_die()
    res = {group.name: find_built_testcases(group) for group in pkg.testcases}
    return res


def get_call_from_string(call_str: str) -> GeneratorCall:
    name, args = call_str.split(None, 1)
    return GeneratorCall(name=name, args=args)


async def _get_necessary_generators_for_groups(
    groups: Optional[Set[str]] = None,
) -> Set[str]:
    pkg = package.find_problem_package_or_die()
    existing_generators = set(generator.name for generator in pkg.generators)
    necessary_generators = set()

    class NecessaryGeneratorsVisitor(TestcaseGroupVisitor):
        async def visit(self, entry: GenerationTestcaseEntry):
            if entry.metadata.generator_call is not None:
                necessary_generators.add(entry.metadata.generator_call.name)

    await run_testcase_visitor(NecessaryGeneratorsVisitor(groups))

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
    from rbx.box.stressing import generator_parser

    vars = package.find_problem_package_or_die().expanded_vars
    generator_for_args = generator_parser.Generator(vars)
    parsed_args = generator_parser.parse(call.args or '')
    return call.model_copy(update={'args': generator_for_args.generate(parsed_args)})


async def generate_standalone(
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
        generation_log = await run_item(
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
        validation_info = await validators.validate_one_off(
            spec.copied_to.inputPath,
            validator,
            validator_digest,
        )
        if not validation_info.ok:
            _print_error_header('failed validating testcase.')
            console.console.print(f'[error]Message:[/error] {validation_info.message}')
            console.console.print(
                f'Testcase written at [item]{spec.copied_to.inputPath}[/item]'
            )
            raise typer.Exit(1)


async def generate_testcases(
    progress: Optional[StatusProgress] = None, groups: Optional[Set[str]] = None
):
    def step():
        if progress is not None:
            progress.step()

    compiled_generators = compile_generators(
        progress=progress,
        tracked_generators=await _get_necessary_generators_for_groups(groups)
        if groups is not None
        else None,
    )

    testcase_utils.clear_built_testcases()

    class BuildTestcaseVisitor(TestcaseGroupVisitor):
        async def visit(self, entry: GenerationTestcaseEntry):
            if entry.metadata.copied_from is not None:
                _copy_testcase_over(
                    entry.metadata.copied_from,
                    entry.metadata.copied_to,
                )

            if entry.metadata.generator_call is not None:
                await generate_standalone(
                    entry.metadata,
                    group_entry=entry.group_entry,
                    validate=False,
                    generator_digest=compiled_generators[
                        entry.metadata.generator_call.name
                    ],
                )
            step()

    await run_testcase_visitor(BuildTestcaseVisitor(groups))


async def generate_output_for_testcase(
    main_solution_digest: str,
    testcase: Testcase,
    interactor_digest: Optional[str] = None,
):
    assert testcase.outputPath is not None
    testcase.inputPath.parent.mkdir(parents=True, exist_ok=True)
    testcase.outputPath.parent.mkdir(parents=True, exist_ok=True)

    main_solution = package.get_main_solution()
    if main_solution is None:
        return

    eval: Evaluation = await run_solution_on_testcase(
        main_solution,
        main_solution_digest,
        None,
        testcase,
        interactor_digest=interactor_digest,
        use_retries=False,
        use_timelimit=False,
        capture_pipes=True,
    )

    if eval.result.outcome != Outcome.ACCEPTED:
        console.console.print(
            f'[error]Failed generating output for [item]{testcase.inputPath}[/item][/error]',
        )
        console.console.print(f'[error]Summary:[/error] {eval.log.get_summary()}')
        console.console.print(
            f'[warning]Verdict: [item]{eval.result.outcome.value}[/item][/warning]',
        )
        console.console.print(
            f'[warning]Message: [info]{eval.result.message}[/info][/warning]',
        )
        console.console.print(f'Input written at [item]{testcase.inputPath}[/item]')
        console.console.print(f'Output written at [item]{testcase.outputPath}[/item]')
        if eval.log.stderr_absolute_path is not None:
            console.console.print(
                f'Stderr written at [item]{eval.log.stderr_absolute_path}[/item]'
            )

        raise typer.Exit(1)


async def generate_outputs_for_testcases(
    entries: List[TestcaseEntry],
    progress: Optional[StatusProgress] = None,
):
    def step():
        if progress is not None:
            progress.step()

    main_solution = package.get_main_solution()
    solution_digest: Optional[str] = None

    pkg = package.find_problem_package_or_die()

    if pkg.type == TaskType.COMMUNICATION:
        interactor_digest = checkers.compile_interactor(progress)
    else:
        interactor_digest = None

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

    generation_entries = await extract_generation_testcases(entries)

    for entry in generation_entries:
        tc = entry.metadata.copied_to
        if not tc.inputPath.is_file():
            return
        assert tc.outputPath is not None

        if entry.metadata.copied_from is not None and _copy_testcase_outputs_over(
            entry.metadata.copied_from, tc
        ):
            # Copy remaining pipe files.
            _copy_testcase_outputs_over(entry.metadata.copied_from, tc, pipes=True)
            step()
            continue

        if (
            main_solution is None or solution_digest is None
        ) and not tc.outputPath.is_file():
            console.console.print(
                '[error]No main solution found to generate outputs for testcases.[/error]',
            )
            raise typer.Exit(1)

        assert solution_digest is not None
        await generate_output_for_testcase(
            solution_digest,
            tc,
            interactor_digest=interactor_digest,
        )
        if entry.metadata.copied_from is not None:
            # Copy remaining pipe files.
            _copy_testcase_outputs_over(entry.metadata.copied_from, tc, pipes=True)
        step()
