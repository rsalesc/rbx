import functools
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


@functools.cache
def _warn_once_about_crlf():
    console.console.print(
        '[warning]It seems a few files have CRLF (\\r\\n) line endings.[/warning]'
    )
    console.console.print(
        '[warning]This usually happens when the file is created on Windows. Please convert the file to LF (\\n) line endings.[/warning]'
    )
    console.console.print(
        '[warning]If you are in VSCode, you can make sure LF (\\n) line endings are used by changing the [item]"files.eol"[/item] setting.[/warning]'
    )


@functools.cache
def _warn_about_crlf(path: pathlib.Path):
    _warn_once_about_crlf()
    console.console.print(
        f'[warning]Testcase file [item]{path}[/item] has CRLF (\\r\\n) line endings, converting to LF (\\n).[/warning]'
    )


def _check_crlf(path: pathlib.Path):
    should_fix = False
    with open(path, 'rb') as f:
        for line in f:
            if line.endswith(b'\r\n'):
                _warn_about_crlf(path)
                should_fix = True
                break

    if should_fix:
        path.write_text('\n'.join(path.read_text().splitlines()) + '\n')


def _copy_testcase_over(
    testcase: Testcase,
    dest: Testcase,
):
    testcase = fill_output_for_defined_testcase(testcase)
    dest.inputPath.parent.mkdir(parents=True, exist_ok=True)
    _check_crlf(testcase.inputPath)
    shutil.copy(
        str(testcase.inputPath),
        str(dest.inputPath),
    )
    if (
        testcase.outputPath is not None
        and testcase.outputPath.is_file()
        and dest.outputPath is not None
    ):
        _check_crlf(testcase.outputPath)
        dest.outputPath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(
            str(testcase.outputPath),
            str(dest.outputPath),
        )


def _copy_testcase_output_over(
    src_output_path: pathlib.Path,
    dest_output_path: pathlib.Path,
    suffix: str,
    dry_run: bool = False,
) -> bool:
    dest_output_path.parent.mkdir(parents=True, exist_ok=True)

    src_path = src_output_path.with_suffix(suffix)
    if not src_path.is_file():
        return False

    if dry_run:
        return True

    _check_crlf(src_path)
    shutil.copy(str(src_path), str(dest_output_path.with_suffix(suffix)))
    return True


def _copy_testcase_outputs_over(
    testcase: Testcase,
    dest: Testcase,
    pipes: bool = False,
    only_pipes: bool = False,
    dry_run: bool = False,
):
    if only_pipes:
        pipes = True
    assert dest.outputPath is not None
    if not dry_run:
        dest.outputPath.parent.mkdir(parents=True, exist_ok=True)

    has_copied = False

    if (
        not only_pipes
        and testcase.outputPath is not None
        and testcase.outputPath.is_file()
    ):
        if not dry_run:
            _check_crlf(testcase.outputPath)
            shutil.copy(str(testcase.outputPath), str(dest.outputPath))
        has_copied = True

    if not pipes:
        return has_copied

    reference_path = testcase.outputPath or testcase.inputPath
    if _copy_testcase_output_over(
        reference_path, dest.outputPath, '.pin', dry_run=dry_run
    ):
        has_copied = True

    if _copy_testcase_output_over(
        reference_path, dest.outputPath, '.pout', dry_run=dry_run
    ):
        has_copied = True

    if _copy_testcase_output_over(
        reference_path, dest.outputPath, '.pio', dry_run=dry_run
    ):
        has_copied = True

    return has_copied


def _needs_output(generation_entries: List[GenerationTestcaseEntry]) -> bool:
    for entry in generation_entries:
        tc = entry.metadata.copied_to
        if not tc.inputPath.is_file():
            continue
        if entry.metadata.copied_from is not None and _copy_testcase_outputs_over(
            entry.metadata.copied_from, tc, dry_run=True
        ):
            continue
        return True
    return False


def get_all_built_testcases() -> Dict[str, List[Testcase]]:
    pkg = package.find_problem_package_or_die()
    res = {group.name: find_built_testcases(group) for group in pkg.testcases}
    return res


def get_call_from_string(call_str: str) -> GeneratorCall:
    try:
        name, args = call_str.split(None, 1)
    except ValueError:
        return GeneratorCall(name=call_str, args='')
    return GeneratorCall(name=name, args=args)


async def _get_necessary_generators_for_groups(
    groups: Optional[Set[str]] = None,
) -> Set[str]:
    necessary_generators = set()

    class NecessaryGeneratorsVisitor(TestcaseGroupVisitor):
        async def visit(self, entry: GenerationTestcaseEntry):
            if entry.metadata.generator_call is not None:
                if (
                    package.get_generator_or_nil(entry.metadata.generator_call.name)
                    is None
                ):
                    console.console.print(
                        f'[error]Generator [item]{entry.metadata.generator_call.name}[/item] is not present in the package.[/error]'
                    )
                    if entry.metadata.generator_script is not None:
                        console.console.print(
                            f'[error]This generator is referenced from [item]{entry.metadata.generator_script}[/item].[/error]'
                        )
                    raise typer.Exit(1)
                necessary_generators.add(entry.metadata.generator_call.name)

    await run_testcase_visitor(NecessaryGeneratorsVisitor(groups))

    return necessary_generators


def compile_generators(
    tracked_generators: Set[str],
    progress: Optional[StatusProgress] = None,
) -> Dict[str, str]:
    def update_status(text: str):
        if progress is not None:
            progress.update(text)

    generator_to_compiled_digest = {}

    for generator_name in tracked_generators:
        generator = package.get_generator(generator_name)
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
        tracked_generators=await _get_necessary_generators_for_groups(groups),
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
    model_solution: CodeItem,
    model_solution_digest: str,
    testcase: Testcase,
    interactor_digest: Optional[str] = None,
    capture_pipes: Optional[bool] = None,
):
    assert testcase.outputPath is not None
    testcase.inputPath.parent.mkdir(parents=True, exist_ok=True)
    testcase.outputPath.parent.mkdir(parents=True, exist_ok=True)

    eval: Evaluation = await run_solution_on_testcase(
        model_solution,
        model_solution_digest,
        None,
        testcase,
        interactor_digest=interactor_digest,
        use_retries=False,
        use_timelimit=False,
        capture_pipes=capture_pipes,
    )

    if eval.result.outcome.is_slow() and eval.result.no_tle_outcome == Outcome.ACCEPTED:
        console.console.print(
            f'[warning]Testcase [item]{testcase.inputPath}[/item] finished in TLE, but test was generated successfully.[/warning]'
        )
    elif eval.result.outcome != Outcome.ACCEPTED:
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

    generation_entries = await extract_generation_testcases(entries)
    needs_output = _needs_output(generation_entries)

    main_solution = package.get_main_solution()
    solution_digest_map = {}

    pkg = package.find_problem_package_or_die()

    if pkg.type == TaskType.COMMUNICATION and needs_output:
        interactor_digest = checkers.compile_interactor(progress)
    else:
        interactor_digest = None

    if main_solution is not None and needs_output:
        if progress:
            progress.update('Compiling main solution...')
        try:
            solution_digest_map[main_solution.path] = compile_item(main_solution)
        except:
            console.console.print('[error]Failed compiling main solution.[/error]')
            raise

    for entry in generation_entries:
        if (
            entry.model_solution is not None
            and entry.model_solution.path not in solution_digest_map
        ):
            if progress:
                progress.update(
                    f'Compiling model solution [item]{entry.model_solution.path}[/item]...'
                )
            try:
                solution_digest_map[entry.model_solution.path] = compile_item(
                    entry.model_solution
                )
            except:
                console.console.print(
                    f'[error]Failed compiling model solution [item]{entry.model_solution.path}[/item].[/error]'
                )
                raise

    gen_runs_dir = package.get_problem_runs_dir() / '.gen'
    shutil.rmtree(str(gen_runs_dir), ignore_errors=True)
    gen_runs_dir.mkdir(parents=True, exist_ok=True)

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

        assert needs_output
        model_solution = entry.model_solution or main_solution
        if (
            model_solution is None or model_solution.path not in solution_digest_map
        ) and not tc.outputPath.is_file():
            console.console.print(
                '[error]No main/model solution found to generate outputs for testcases.[/error]',
            )
            raise typer.Exit(1)

        assert model_solution is not None
        model_solution_digest = solution_digest_map[model_solution.path]
        capture_pipes = None
        if (
            pkg.type == TaskType.COMMUNICATION
            and entry.metadata.copied_from is not None
        ):
            # If some pipe file is already specified, we don't need to capture the pipes
            # when running the program.
            capture_pipes = not _copy_testcase_outputs_over(
                entry.metadata.copied_from, tc, only_pipes=True, dry_run=True
            )

        await generate_output_for_testcase(
            model_solution,
            model_solution_digest,
            tc,
            interactor_digest=interactor_digest,
            capture_pipes=capture_pipes,
        )
        if entry.metadata.copied_from is not None:
            # Copy remaining pipe files.
            _copy_testcase_outputs_over(entry.metadata.copied_from, tc, pipes=True)
        step()
