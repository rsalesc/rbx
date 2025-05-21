import time
from shutil import rmtree
from typing import List, Optional

import async_lru
import syncer
import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import checkers, generators, package, validators
from rbx.box.code import SanitizationLevel, compile_item, run_item
from rbx.box.generators import (
    GenerationMetadata,
    expand_generator_call,
    generate_standalone,
)
from rbx.box.retries import Retrier
from rbx.box.schema import CodeItem, GeneratorCall, Stress, TaskType, Testcase
from rbx.box.solutions import compile_solutions, get_outcome_style_verdict
from rbx.box.stressing import finder_parser
from rbx.grading.steps import (
    DigestOrDest,
    DigestOrSource,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)
from rbx.utils import StatusProgress


class StressFinding(BaseModel):
    generator: GeneratorCall


class StressReport(BaseModel):
    findings: List[StressFinding] = []
    executed: int = 0


def _compile_finder(finder: CodeItem) -> str:
    try:
        digest = compile_item(finder)
    except Exception as e:
        console.console.print(
            f'[error]Failed compiling checker [item]{finder.path}[/item][/error]'
        )
        raise typer.Exit(1) from e
    return digest


async def run_stress(
    timeoutInSeconds: int,
    name: Optional[str] = None,
    finder: Optional[str] = None,
    generator_call: Optional[str] = None,
    findingsLimit: int = 1,
    verbose: bool = False,
    progress: Optional[StatusProgress] = None,
    sanitized: bool = False,
) -> StressReport:
    pkg = package.find_problem_package_or_die()
    if pkg.type == TaskType.COMMUNICATION:
        console.console.print(
            '[error]Communication problems do not support stress testing.[/error]'
        )
        raise typer.Exit(1)

    if finder:
        if generator_call is None:
            console.console.print(
                '[error]Generator arguments are required for stress testing. Specify them through the [item]-g[/item] flag.[/error]'
            )
            raise typer.Exit(1)
        generator = generators.get_call_from_string(generator_call)
        stress = Stress(
            name=f'{generator.name}',
            generator=generator,
            finder=finder,
        )
    else:
        if name is None:
            console.console.print(
                '[error]Invalid stress test paramaters. Either provide a stress test name, or provide a finder expression (-f) and generator arguments (-g).[/error]'
            )
            raise typer.Exit(1)
        stress = package.get_stress(name)

    call = stress.generator
    generator = package.get_generator(call.name)

    try:
        generator_digest = compile_item(generator, sanitized=SanitizationLevel.PREFER)
    except:
        console.console.print(
            f'[error]Failed compiling generator [item]{generator.name}[/item].[/error]'
        )
        raise

    # Finder expression parser
    parsed_finder = finder_parser.parse(stress.finder)

    solutions = finder_parser.get_all_solution_items(parsed_finder)
    finders = finder_parser.get_all_checker_items(parsed_finder)
    needs_expected_output = finder_parser.needs_expected_output(parsed_finder)

    solution_indices = {str(solution.path): i for i, solution in enumerate(solutions)}
    solutions_digest = compile_solutions(
        tracked_solutions=set(str(solution.path) for solution in solutions),
        sanitized=sanitized,
    )
    if progress:
        progress.update('Compiling finders...')
    finders_digest = {str(finder.path): _compile_finder(finder) for finder in finders}

    compiled_validator = validators.compile_main_validator()

    # Erase old stress directory
    runs_dir = package.get_problem_runs_dir()
    stress_dir = runs_dir / '.stress'
    rmtree(str(stress_dir), ignore_errors=True)
    stress_dir.mkdir(parents=True, exist_ok=True)
    empty_path = runs_dir / '.stress' / '.empty'
    empty_path.write_text('')

    startTime = time.monotonic()

    executed = 0
    findings = []

    while len(findings) < findingsLimit:
        if time.monotonic() - startTime > timeoutInSeconds:
            break

        executed += 1

        if progress:
            seconds = timeoutInSeconds - int(time.monotonic() - startTime)
            progress.update(
                f'Stress testing: found [item]{len(findings)}[/item] tests, '
                f'executed [item]{executed}[/item], '
                f'[item]{seconds}[/item] second(s) remaining...'
            )

        input_path = runs_dir / '.stress' / 'input'
        input_path.parent.mkdir(parents=True, exist_ok=True)

        expanded_generator_call = expand_generator_call(stress.generator)
        await generate_standalone(
            GenerationMetadata(
                generator_call=expanded_generator_call,
                copied_to=Testcase(inputPath=input_path),
            ),
            generator_digest=generator_digest,
            validator_digest=compiled_validator[1]
            if compiled_validator is not None
            else None,
        )

        @async_lru.alru_cache
        async def run_solution_fn(
            solution: str,
            retry_index: Optional[int] = None,
            input_path=input_path,
        ) -> TestcaseLog:
            index = solution_indices[solution]
            sol = solutions[index]
            output_path = input_path.with_stem(f'{index}').with_suffix('.out')
            stderr_path = output_path.with_suffix('.err')

            run_log = await run_item(
                sol,
                DigestOrSource.create(solutions_digest[sol.path]),
                stdin=DigestOrSource.create(input_path),
                stdout=DigestOrDest.create(output_path),
                stderr=DigestOrDest.create(stderr_path),
                retry_index=retry_index,
            )

            return TestcaseLog(
                **(run_log.model_dump() if run_log is not None else {}),
                stdout_absolute_path=output_path.absolute(),
                stderr_absolute_path=stderr_path.absolute(),
            )

        # Get main solution output.
        expected_output_path = empty_path
        if needs_expected_output:
            main_testcase_log = await run_solution_fn(str(solutions[0].path))
            main_checker_result = checkers.check_with_no_output(main_testcase_log)
            if main_checker_result.outcome != Outcome.ACCEPTED:
                console.console.print(
                    '[error]Error while generating main solution output.[/error]'
                )
                console.console.print(f'Input written at [item]{input_path}[/item]')
                console.console.print(
                    f'Output written at [item]{main_testcase_log.stdout_absolute_path}[/item]'
                )
                console.console.print(
                    f'Stderr written at [item]{main_testcase_log.stderr_absolute_path}[/item]'
                )
                console.console.print()
                console.console.print(
                    "[warning]If you don't want reference outputs to be generated for the tests, you should "
                    "use the two-way modifier in your finder expression (':2')."
                )
                raise typer.Exit(1)
            expected_output_path = main_testcase_log.stdout_absolute_path

        @async_lru.alru_cache
        async def run_solution_and_checker_fn(
            call: finder_parser.FinderCall,
            input_path=input_path,
            expected_output_path=expected_output_path,
        ) -> finder_parser.FinderResult:
            async def run_fn(retry_index: int) -> Evaluation:
                solution = call.solution
                checker = call.checker

                testcase_log = await run_solution_fn(solution, retry_index=retry_index)
                assert testcase_log.stdout_absolute_path is not None

                if checker is None:
                    checker_result = checkers.check_with_no_output(testcase_log)
                else:
                    checker_digest = finders_digest[checker.path]
                    checker_result = await checkers.check(
                        checker_digest,
                        testcase_log,
                        Testcase(inputPath=input_path, outputPath=expected_output_path),
                        program_output=testcase_log.stdout_absolute_path,
                    )

                return Evaluation(
                    result=checker_result,
                    testcase=TestcaseIO(
                        index=0,
                        input=input_path,
                        output=expected_output_path,
                    ),
                    log=testcase_log,
                )

            retrier = Retrier(is_stress=True)
            eval = await retrier.repeat(run_fn)

            return finder_parser.FinderResult(
                solution=call.solution,
                outcome=eval.result.outcome,
                checker=call.checker,
                solution_log=eval.log,
                checker_result=eval.result,
            )

        @syncer.sync
        async def run_fn(*args, **kwargs):
            # Wrap the runner in a syncer.sync to make it work with the finder parser.
            return await run_solution_and_checker_fn(*args, **kwargs)

        runner = finder_parser.FinderTreeRunner(runner=run_fn)
        finder_outcome: finder_parser.FinderOutcome = runner.transform(parsed_finder)

        internal_error_results = [
            result
            for result in finder_outcome.results
            if result.outcome == Outcome.INTERNAL_ERROR
        ]

        if internal_error_results:
            console.console.print(
                f'[error]Checkers failed during stress test [item]{stress.name}[/item] with args [info]{expanded_generator_call.name} {expanded_generator_call.args}[/info][/error]'
            )
            for internal_error_result in internal_error_results:
                assert internal_error_result.checker is not None
                assert internal_error_result.checker_result is not None
                internal_error_checker_name = internal_error_result.checker.path
                console.console.print(
                    f'[warning]Checker [item]{internal_error_checker_name}[/item] failed with message:'
                )
                console.console.print(internal_error_result.checker_result.message)
            raise typer.Exit(1)

        if not finder_outcome.truth_value:
            continue

        findings_dir = stress_dir / 'findings'
        findings_dir.mkdir(parents=True, exist_ok=True)
        finding_index = len(findings)

        finding_path = findings_dir / f'{finding_index}.in'
        finding_path.write_bytes(input_path.read_bytes())

        if progress:
            console.console.print(
                f'[error]FINDING[/error] Generator args are "[status]{expanded_generator_call.name} {expanded_generator_call.args}[/status]"'
            )
            seen_finder_results = set()
            for finder_result in finder_outcome.results:
                style = get_outcome_style_verdict(finder_result.outcome)
                finder_result_key = (finder_result.solution, finder_result.checker)
                if finder_result_key in seen_finder_results:
                    continue
                seen_finder_results.add(finder_result_key)
                finder_result_report_line = f'{finder_result.solution} = [{style}]{finder_result.outcome.name}[/{style}]'
                if finder_result.checker is not None:
                    finder_result_report_line += (
                        f' [item]ON[/item] {finder_result.checker.path}'
                    )
                console.console.print(finder_result_report_line)

        findings.append(
            StressFinding(
                generator=expanded_generator_call,
            )
        )

        # Be cooperative.
        time.sleep(0.001)

    return StressReport(findings=findings, executed=executed)


def print_stress_report(report: StressReport):
    console.console.rule('Stress test report', style='status')
    console.console.print(f'Executed [item]{report.executed}[/item] tests.')
    if not report.findings:
        console.console.print('No stress test findings.')
        return
    console.console.print(f'Found [item]{len(report.findings)}[/item] testcases.')

    findings_dir = package.get_problem_runs_dir() / '.stress' / 'findings'
    console.console.print(f'Findings: {findings_dir.resolve()}')
    console.console.print()

    for i, finding in enumerate(report.findings):
        console.console.print(f'[error]Finding {i + 1}[/error]')
        console.console.print(
            f'Generator: [status]{finding.generator.name} {finding.generator.args}[/status]'
        )
        console.console.print()
