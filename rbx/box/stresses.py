import heapq
import pathlib
import shutil
import time
from shutil import rmtree
from typing import List, Optional

import async_lru
import syncer
import typer
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import checkers, generators, package, tasks, validators
from rbx.box.code import SanitizationLevel, compile_item
from rbx.box.formatting import get_formatted_time, href
from rbx.box.generators import (
    GenerationError,
    GenerationMetadata,
    ValidationError,
    expand_generator_call,
    generate_standalone,
)
from rbx.box.schema import (
    Checker,
    ExpectedOutcome,
    GeneratorCall,
    Stress,
    TaskType,
    Testcase,
)
from rbx.box.solutions import compile_solutions, get_outcome_style_verdict
from rbx.box.stressing import finder_parser
from rbx.grading.steps import (
    Evaluation,
    Outcome,
)
from rbx.utils import StatusProgress


class StressFinding(BaseModel):
    generator: GeneratorCall
    duration: Optional[int] = None


class StressReport(BaseModel):
    findings: List[StressFinding] = []
    executed: int = 0
    skipped: int = 0


def _compile_finder(finder: Checker) -> str:
    try:
        digest = checkers.compile_checker(custom_checker=finder)
    except:
        console.console.print(
            f'[error]Failed compiling checker {finder.href()}.[/error]'
        )
        raise
    return digest


def _renumber_slowest_findings(
    findings_dir: pathlib.Path, slowest_findings: List
) -> None:
    temp_dir = findings_dir.parent / '.temp_findings'
    rmtree(str(temp_dir), ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Move all candidates to temp directory
    for _, _, old_file_index, _ in slowest_findings:
        old_path = findings_dir / f'{old_file_index}.in'
        temp_path = temp_dir / f'{old_file_index}.in'
        if old_path.exists():
            shutil.move(str(old_path), str(temp_path))

    # Clean findings directory to avoid leftovers
    rmtree(str(findings_dir), ignore_errors=True)
    findings_dir.mkdir(parents=True, exist_ok=True)

    # Move back with new numbering
    for i, (_, _, old_file_index, _) in enumerate(slowest_findings):
        temp_path = temp_dir / f'{old_file_index}.in'
        new_path = findings_dir / f'{i}.in'
        if temp_path.exists():
            shutil.move(str(temp_path), str(new_path))

    rmtree(str(temp_dir), ignore_errors=True)


async def run_stress(
    timeout_in_seconds: int,
    name: Optional[str] = None,
    finder: Optional[str] = None,
    generator_call: Optional[str] = None,
    findings_limit: int = 1,
    verbose: bool = False,
    progress: Optional[StatusProgress] = None,
    sanitized: bool = False,
    print_descriptors: bool = False,
    skip_invalid_testcases: bool = False,
    limits: Optional[tasks.Limits] = None,
    find_slowest: bool = False,
) -> StressReport:
    pkg = package.find_problem_package_or_die()

    if finder:
        if generator_call is None:
            console.console.print(
                '[error]Generator arguments are required for stress testing. Specify them through the [item]-g[/item] flag.[/error]'
            )
            raise typer.Exit(1)
        generator = generators.get_call_from_string(generator_call)
        stress = Stress(
            name=f'{pathlib.Path(generator.name).stem}',
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

    if progress:
        progress.update('Compiling generator...')
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
    eval_only_outcome = (
        ExpectedOutcome.ANY if find_slowest else ExpectedOutcome.INCORRECT
    )

    solution_indices = {str(solution.path): i for i, solution in enumerate(solutions)}
    solutions_digest = compile_solutions(
        tracked_solutions=set(str(solution.path) for solution in solutions),
        sanitized=sanitized,
        progress=progress,
    )
    if progress:
        progress.update('Compiling finders...')
    finders_digest = {str(finder.path): _compile_finder(finder) for finder in finders}

    interactor_digest = None
    if pkg.type == TaskType.COMMUNICATION:
        interactor_digest = checkers.compile_interactor(progress=progress)

    all_validators = package.get_all_validators()
    if progress:
        progress.update('Compiling validators...')
    validators_digests = validators.compile_validators(
        all_validators, progress=progress
    )

    # Use limits if we are not in find_slowest mode or if we have double TL explicitly
    # specified.
    use_timelimit = not find_slowest or (limits is not None and limits.isDoubleTL)

    if limits is not None:
        if not use_timelimit:
            limits.time = None
        console.console.print(
            '[bright_white]Running stress tests with the following limits:[/bright_white]'
        )
        console.console.print(limits)

    # Erase old stress directory
    runs_dir = package.get_problem_runs_dir()
    stress_dir = runs_dir / '.stress'
    rmtree(str(stress_dir), ignore_errors=True)
    stress_dir.mkdir(parents=True, exist_ok=True)
    empty_path = runs_dir / '.stress' / '.empty'
    empty_path.write_text('')

    startTime = time.monotonic()

    executed = 0
    skipped = 0
    findings = []
    only_call: Optional[str] = None
    has_diff_call = False
    duplicate_call_error = False
    finding_counter = 0

    # Min-heap to store the top `findings_limit` slowest findings.
    # Elements are (duration, executed_index, file_index, generator_call)
    # We use executed_index as tie breaker (prefer newer distinct findings mostly for determinism)
    slowest_findings = []

    try:
        while True:
            # Check for timeout first
            if time.monotonic() - startTime > timeout_in_seconds:
                break

            # If not in find_slowest mode, check if we reached the limit
            if not find_slowest and len(findings) >= findings_limit:
                break

            if print_descriptors:
                utils.print_open_fd_count()

            executed += 1

            if progress:
                seconds = timeout_in_seconds - int(time.monotonic() - startTime)
                skipped_str = f'skipped [item]{skipped}[/item], ' if skipped else ''
                progress.update(
                    f'Stress testing: found [item]{len(findings)}[/item] tests, '
                    f'executed [item]{executed}[/item], '
                    f'{skipped_str}'
                    f'[item]{seconds}[/item] second(s) remaining...'
                )

            input_path = runs_dir / '.stress' / 'input'
            input_path.parent.mkdir(parents=True, exist_ok=True)

            expanded_generator_call = expand_generator_call(stress.generator)
            if only_call is not None and str(expanded_generator_call) != only_call:
                has_diff_call = True
            only_call = str(expanded_generator_call)

            if not has_diff_call and executed % 10 == 0:
                console.console.print(
                    f'[warning]Generator call [item]{only_call}[/item] was repeated [item]{executed}[/item] times.[/warning]'
                )
                if not duplicate_call_error:
                    duplicate_call_error = True
                    console.console.print(
                        '[warning]This might mean your generator expression is not generating different testcases.[/warning]'
                    )
                    console.console.print(
                        '[warning]You should add [item]@[/item] to your generator expression.[/warning]'
                    )

            try:
                await generate_standalone(
                    GenerationMetadata(
                        generator_call=expanded_generator_call,
                        copied_to=Testcase(inputPath=input_path),
                    ),
                    generator_digest=generator_digest,
                    validators_digests=validators_digests,
                )
            except (ValidationError, GenerationError) as err:
                if skip_invalid_testcases:
                    skipped += 1
                    continue
                with err:
                    err.print('[warning]Invalid testcase generated.[/warning]')
                    err.print(
                        '[warning]You can use the [item]--skip[/item] flag to skip invalid testcases without halting.[/warning]'
                    )

            @async_lru.alru_cache(maxsize=None)
            async def run_solution_fn(
                solution: str,
                checker_digest: Optional[str] = None,
                input_path=input_path,
                output_path: Optional[pathlib.Path] = None,
            ) -> Evaluation:
                index = solution_indices[solution]
                sol = solutions[index]
                return await tasks.run_solution_on_testcase(
                    solutions[index],
                    compiled_digest=solutions_digest[sol.path],
                    checker_digest=checker_digest,
                    interactor_digest=interactor_digest,
                    testcase=Testcase(inputPath=input_path, outputPath=output_path),
                    output_dir=input_path.parent,
                    filestem=f'{index}',
                    is_stress=True,
                    limits_override=limits,
                    use_timelimit=use_timelimit,
                )

            # Get main solution output.
            expected_output_path = empty_path
            if needs_expected_output:
                eval = await run_solution_fn(str(solutions[0].path))
                if eval.result.outcome != Outcome.ACCEPTED:
                    console.console.print(
                        '[error]Error while generating main solution output.[/error]'
                    )
                    console.console.print(f'Input written at [item]{input_path}[/item]')
                    console.console.print(
                        f'Output written at [item]{eval.log.stdout_absolute_path}[/item]'
                    )
                    console.console.print(
                        f'Stderr written at [item]{eval.log.stderr_absolute_path}[/item]'
                    )
                    console.console.print()
                    console.console.print(
                        "[warning]If you don't want reference outputs to be generated for the tests, you should "
                        "use the two-way modifier in your finder expression (':2')."
                    )
                    raise typer.Exit(1)
                if eval.log.stdout_absolute_path is not None:
                    expected_output_path = input_path.with_suffix('.ans')
                    shutil.copyfile(eval.log.stdout_absolute_path, expected_output_path)
                else:
                    expected_output_path = None

            @async_lru.alru_cache(maxsize=None)
            async def run_solution_and_checker_fn(
                call: finder_parser.FinderCall,
                expected_output_path=expected_output_path,
            ) -> finder_parser.FinderResult:
                async def run_fn() -> Evaluation:
                    solution = call.solution
                    checker = call.checker

                    checker_digest = (
                        finders_digest[checker.path] if checker is not None else None
                    )
                    return await run_solution_fn(
                        solution,
                        checker_digest=checker_digest,
                        output_path=expected_output_path,
                    )

                eval = await run_fn()

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
                return await run_solution_and_checker_fn(*args, **kwargs)  # pyright: ignore[reportGeneralTypeIssues]

            runner = finder_parser.FinderTreeRunner(
                runner=run_fn, eval_only_outcome=eval_only_outcome
            )
            finder_outcome: finder_parser.FinderOutcome = runner.transform(
                parsed_finder
            )

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

            # Calculate max duration for this finding
            max_duration = 0
            for finder_result in finder_outcome.results:
                if finder_result.solution_log and finder_result.solution_log.time:
                    max_duration = max(
                        max_duration, int(finder_result.solution_log.time * 1000)
                    )

            if find_slowest:
                if len(slowest_findings) >= findings_limit:
                    if max_duration <= slowest_findings[0][0]:
                        # Faster than the fastest of our slow tests, skip it.
                        continue

            findings_dir = stress_dir / 'findings'
            findings_dir.mkdir(parents=True, exist_ok=True)

            # Use 'finding_counter' as file index to ensure uniqueness over time.
            # We will relabel them at the end.
            finding_file_index = finding_counter
            finding_counter += 1

            finding_path = findings_dir / f'{finding_file_index}.in'
            finding_path.write_bytes(input_path.read_bytes())

            if find_slowest:
                heap_item = (
                    max_duration,
                    executed,
                    finding_file_index,
                    expanded_generator_call,
                )
                if len(slowest_findings) < findings_limit:
                    heapq.heappush(slowest_findings, heap_item)
                else:
                    removed_item = heapq.heappushpop(slowest_findings, heap_item)
                    # Remove the file associated with the removed item
                    removed_file_index = removed_item[2]
                    (findings_dir / f'{removed_file_index}.in').unlink(missing_ok=True)

            if not find_slowest:
                findings.append(
                    StressFinding(
                        generator=expanded_generator_call,  # pyright: ignore
                        duration=max_duration,
                    )
                )

            if progress:
                status_header = '[error]FINDING[/error]'
                if find_slowest:
                    status_header = (
                        f'[error]CANDIDATE ({get_formatted_time(max_duration)})[/error]'
                    )

                console.console.print(
                    f'{status_header} Generator args are "[status]{expanded_generator_call.name} {expanded_generator_call.args}[/status]"'  # pyright: ignore
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

            # Be cooperative.
            time.sleep(0.001)

    except KeyboardInterrupt:
        pass

    if find_slowest and slowest_findings:
        # Sort by duration descending
        slowest_findings.sort(key=lambda x: x[0], reverse=True)

        findings_dir = stress_dir / 'findings'
        findings_dir.mkdir(parents=True, exist_ok=True)
        _renumber_slowest_findings(findings_dir, slowest_findings)

        for duration, _, _, generator_call in slowest_findings:
            findings.append(
                StressFinding(
                    generator=generator_call,  # pyright: ignore
                    duration=duration,
                )
            )

    return StressReport(findings=findings, executed=executed, skipped=skipped)


def print_stress_report(report: StressReport):
    console.console.rule('Stress test report', style='status')
    console.console.print(f'Executed [item]{report.executed}[/item] tests.')
    if report.skipped:
        console.console.print(f'Skipped [item]{report.skipped}[/item] invalid tests.')
    if not report.findings:
        console.console.print('No stress test findings.')
        return
    console.console.print(f'Found [item]{len(report.findings)}[/item] testcases.')

    findings_dir = package.get_problem_runs_dir() / '.stress' / 'findings'
    console.console.print(f'Findings: {href(package.relpath(findings_dir))}')
    console.console.print()

    for i, finding in enumerate(report.findings):
        console.console.print(f'[error]Finding {i + 1}[/error]')
        if finding.duration is not None:
            console.console.print(
                f'Execution time: [item]{get_formatted_time(finding.duration)}[/item]'
            )
        console.console.print(
            f'Generator: [status]{finding.generator.name} {finding.generator.args}[/status]'
        )
        console.console.print()
