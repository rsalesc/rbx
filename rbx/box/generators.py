import asyncio
import collections
import functools
import pathlib
import shutil
from typing import Dict, List, Optional, Set

import typer
from rich.console import Console

from rbx import console, utils
from rbx.box import (
    checkers,
    package,
    setter_config,
    testcase_utils,
    validators,
)
from rbx.box.code import SanitizationLevel, compile_item, run_item
from rbx.box.exception import RbxException
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.parallel import live_tasks
from rbx.box.schema import (
    CodeItem,
    GeneratorCall,
    TaskType,
    Testcase,
)
from rbx.box.tasks import run_solution_on_testcase
from rbx.box.testcase_extractors import (
    TestcaseGroupVisitor,
    extract_generation_testcases,
    run_testcase_visitor,
)
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testcase_utils import (
    fill_output_for_defined_testcase,
)
from rbx.grading.async_executor import AsyncStreamer, IdentifiedResult
from rbx.grading.judge.digester import digest_file
from rbx.grading.steps import (
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
    Evaluation,
    Outcome,
)
from rbx.utils import StatusProgress


class ValidationError(RbxException):
    pass


class GenerationError(RbxException):
    pass


async def _compile_generator(generator: CodeItem) -> str:
    return await compile_item(generator, sanitized=SanitizationLevel.PREFER)


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
    crlf_check: bool = True,
) -> bool:
    dest_output_path.parent.mkdir(parents=True, exist_ok=True)

    src_path = src_output_path.with_suffix(suffix)
    if not src_path.is_file():
        return False

    if dry_run:
        return True

    if crlf_check:
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

    if _copy_testcase_output_over(
        reference_path, dest.outputPath, '.interaction', dry_run=dry_run
    ):
        has_copied = True

    return has_copied


def _copy_testcase_companions_over(
    src: Testcase,
    dest: Testcase,
):
    # assert dest.outputPath is not None
    # dest.outputPath.parent.mkdir(parents=True, exist_ok=True)

    # reference_path = src.outputPath or src.inputPath
    # _copy_testcase_output_over(
    #     reference_path, dest.outputPath, '.tex', crlf_check=False
    # )
    pass


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


class GeneratorCompilationTask(live_tasks.CompilationTask):
    generator_name: str

    def __init__(self, generator_name: str, item: CodeItem):
        super().__init__(item)
        self.generator_name = generator_name


async def compile_generators(
    tracked_generators: Set[str],
) -> Dict[str, str]:
    generator_to_compiled_digest = {}

    with live_tasks.LiveTasks[GeneratorCompilationTask](
        title='Generators',
        progress_message='[info]Compiling [item]{processed}[/item] / [item]{total}[/item] generators...[/info]',
        final_message='[info]Compiled [item]{total}[/item] generators...[/info]',
    ) as live:

        class GeneratorCompilationStreamer(
            AsyncStreamer[GeneratorCompilationTask, str]
        ):
            async def post_signaled(self, key: GeneratorCompilationTask) -> None:
                live.update()

            async def scheduled(self, key: GeneratorCompilationTask) -> None:
                key.status = live_tasks.CompilationStatus.RUNNING

            async def succeeded(
                self, key: GeneratorCompilationTask, value: str
            ) -> None:
                generator_to_compiled_digest[key.generator_name] = value
                key.status = live_tasks.CompilationStatus.SUCCESS

            async def failed(
                self, key: GeneratorCompilationTask, exception: BaseException
            ) -> None:
                key.status = live_tasks.CompilationStatus.FAILED
                raise exception

        streamer = GeneratorCompilationStreamer(
            setter_config.get_async_executor(detach=True)
        )
        for generator_name in tracked_generators:
            generator = package.get_generator(generator_name)
            task = GeneratorCompilationTask(generator_name, generator)
            live.append(task)
            await streamer.submit(task, _compile_generator, task.item)

        await streamer.stream()

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
    validators_digests: Optional[Dict[str, str]] = None,
    progress: Optional[StatusProgress] = None,
):
    def _print_error_header(console: Console, text: Optional[str] = None):
        prefix = 'Failed generating test'
        if group_entry is not None:
            prefix += (
                f' [item]{group_entry.group}[/item]/[item]{group_entry.index}[/item]'
            )
        suffix = '.'
        if text:
            suffix = f': {text}'
        if spec.generator_call is not None:
            console.print(
                f'[error]{prefix} using generator call [info]{spec.generator_call.name} {spec.generator_call.args}[/info]{suffix}[/error]'
            )
        else:
            console.print(f'[error]{prefix}{suffix}[/error]')

    if spec.generator_call is not None:
        call = spec.generator_call

        generation_stderr = DigestHolder()

        # Get generator item
        generator = package.get_generator(call.name)
        if generator_digest is None:
            if progress:
                progress.update(f'Compiling generator {generator.name}...')
            generator_digest = await _compile_generator(generator)

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
            with GenerationError() as err:
                _print_error_header(err.console)
                if generation_log is not None:
                    err.print(f'[error]Summary:[/error] {generation_log.get_summary()}')
                if generation_stderr.value is not None:
                    err.print('[error]Stderr:[/error]')
                    err.print(
                        package.get_digest_as_string(generation_stderr.value) or '',
                    )
    elif spec.content is not None:
        spec.copied_to.inputPath.parent.mkdir(parents=True, exist_ok=True)
        spec.copied_to.inputPath.write_text(spec.content)
    elif spec.copied_from is not None:
        _copy_testcase_over(spec.copied_from, spec.copied_to)

    all_validators = package.get_all_validators()
    # Run validator, if it is available.
    if validate and all_validators:
        validators_digests = validators_digests or {}
        for validator in all_validators:
            # Compile validator if not already compiled.
            if str(validator.path) not in validators_digests:
                validators_digests[str(validator.path)] = (
                    await validators.compile_validators([validator], progress=progress)
                )[str(validator.path)]

        if progress:
            progress.update('Validating test...')
        validation_infos = await validators.validate_one_off(
            spec.copied_to.inputPath,
            all_validators,
            validators_digests,
            generation_metadata=spec,
            testcase_entry=group_entry,
        )
        if not all(info.ok for info in validation_infos):
            with ValidationError() as err:
                _print_error_header(err.console, 'failed validating testcase.')
                for info in validation_infos:
                    if info.ok:
                        continue
                    err.print(
                        f'[error]Validator {info.validator.href()} failed validation:[/error]'
                    )
                    if info.message is not None:
                        err.print(
                            f'[error]Message:[/error] {utils.escape_markup(info.message.strip())}'
                        )
                    err.print(
                        f'Testcase written at [item]{spec.copied_to.inputPath}[/item]'
                    )


async def generate_testcases(
    progress: Optional[StatusProgress] = None, groups: Optional[Set[str]] = None
):
    def step():
        if progress is not None:
            progress.step()

    compiled_generators = await compile_generators(
        tracked_generators=await _get_necessary_generators_for_groups(groups),
    )

    testcase_utils.clear_built_testcases()

    executor = setter_config.get_async_executor(detach=True)
    futures: List[asyncio.Future[IdentifiedResult[GenerationTestcaseEntry, str]]] = []

    class BuildTestcaseVisitor(TestcaseGroupVisitor):
        async def visit(self, entry: GenerationTestcaseEntry):
            _, completed = executor.submit_with_identity(entry, self._visit, entry)
            futures.append(completed)

        async def _visit(self, entry: GenerationTestcaseEntry) -> str:
            if entry.metadata.copied_from is not None:
                _copy_testcase_over(
                    entry.metadata.copied_from,
                    entry.metadata.copied_to,
                )
            elif entry.metadata.content is not None:
                entry.metadata.copied_to.inputPath.parent.mkdir(
                    parents=True, exist_ok=True
                )
                entry.metadata.copied_to.inputPath.write_text(entry.metadata.content)
            elif entry.metadata.generator_call is not None:
                await generate_standalone(
                    entry.metadata,
                    group_entry=entry.group_entry,
                    validate=False,
                    generator_digest=compiled_generators[
                        entry.metadata.generator_call.name
                    ],
                )
            else:
                raise ValueError(f'Invalid generation metadata: {entry.metadata}')
            assert entry.metadata.copied_to.inputPath.is_file()
            return digest_file(entry.metadata.copied_to.inputPath)

    visitor = BuildTestcaseVisitor(groups)
    await run_testcase_visitor(visitor)

    # Wait for all testcases to be generated (in original order), and process exceptions and duplicates.
    test_calls: Dict[str, List[GenerationTestcaseEntry]] = collections.defaultdict(list)
    test_digests: Dict[str, List[GenerationTestcaseEntry]] = collections.defaultdict(
        list
    )
    for future in futures:
        identified_result = await future
        entry = identified_result.key

        # Check for duplicates by generator call.
        same_call = False
        if entry.metadata.generator_call is not None:
            tests_with_same_call = test_calls[str(entry.metadata.generator_call)]
            if tests_with_same_call:
                same_call = True
                ref_entry = tests_with_same_call[0]
                console.console.print(
                    f'[warning]Test [item]{entry}[/item] '
                    f'is generated by the same call as [item]{ref_entry}[/item].'
                )
                console.console.print(
                    f'[warning]The call is [item]{entry.metadata.generator_call}[/item].[/warning]'
                )
            tests_with_same_call.append(entry)

        digest = identified_result.result()

        # Check for duplicates by digest, only if the testcase is not a duplicate by generator call.
        if not same_call:
            tests_with_same_digest = test_digests[digest]
            if tests_with_same_digest:
                ref_entry = tests_with_same_digest[0]
                console.console.print(
                    f'[warning]Test [item]{entry.full_repr()}[/item] '
                    f'is a hash duplicate of [item]{ref_entry.full_repr()}[/item].'
                )
            tests_with_same_digest.append(entry)
        step()


async def generate_output_for_testcase(
    model_solution: CodeItem,
    model_solution_digest: str,
    testcase: Testcase,
    interactor_digest: Optional[str] = None,
    capture_pipes: Optional[bool] = None,
    line_capture: bool = False,
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
        line_capture=line_capture,
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
        interactor_digest = await checkers.compile_interactor(progress)
    else:
        interactor_digest = None

    if main_solution is not None and needs_output:
        console.console.print(
            f'Using {main_solution.href()} as solution for generating outputs.'
        )
        if progress:
            progress.update('Compiling main solution...')
        try:
            solution_digest_map[main_solution.path] = await compile_item(main_solution)
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
                    f'Compiling model solution {entry.model_solution.href()}...'
                )
            try:
                solution_digest_map[entry.model_solution.path] = await compile_item(
                    entry.model_solution
                )
            except:
                console.console.print(
                    f'[error]Failed compiling model solution {entry.model_solution.href()}.[/error]'
                )
                raise

    gen_runs_dir = package.get_problem_runs_dir() / '.gen'
    shutil.rmtree(str(gen_runs_dir), ignore_errors=True)
    gen_runs_dir.mkdir(parents=True, exist_ok=True)

    async def _process_entry(entry: GenerationTestcaseEntry):
        tc = entry.metadata.copied_to
        if not tc.inputPath.is_file():
            return
        assert tc.outputPath is not None

        if entry.metadata.copied_from is not None:
            _copy_testcase_companions_over(entry.metadata.copied_from, tc)

        if entry.metadata.copied_from is not None and _copy_testcase_outputs_over(
            entry.metadata.copied_from, tc
        ):
            return

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

        await generate_output_for_testcase(
            model_solution,
            model_solution_digest,
            tc,
            interactor_digest=interactor_digest,
            # Always capture pipes for samples
            capture_pipes=True if entry.is_sample() else None,
            line_capture=entry.is_sample(),
        )

    executor = setter_config.get_async_executor(detach=True)
    futures: List[asyncio.Future] = []
    for entry in generation_entries:
        _, completed = executor.submit(_process_entry, entry)
        futures.append(completed)

    # Wait for all outputs to be generated, and process exceptions.
    for future in futures:
        await future
        step()
