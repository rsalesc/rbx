from __future__ import generators

import collections
import dataclasses
import pathlib
import shutil
from collections.abc import Iterator
from typing import Dict, Iterable, List, Optional, Set

import rich
import rich.live
import rich.table
from pydantic import BaseModel

from rbx import console
from rbx.box import checkers, environment, package
from rbx.box.code import compile_item, find_language_name, run_item
from rbx.box.deferred import Deferred
from rbx.box.environment import EnvironmentSandbox, ExecutionConfig, VerificationLevel
from rbx.box.generators import generate_output_for_testcase, generate_standalone
from rbx.box.schema import (
    ExpectedOutcome,
    GeneratorCall,
    Solution,
    Testcase,
    TestcaseGroup,
)
from rbx.box.testcases import find_built_testcases
from rbx.grading.steps import (
    DigestOrDest,
    DigestOrSource,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)
from rbx.utils import StatusProgress, model_to_yaml

StructuredEvaluation = Dict[str, Dict[str, List[Optional[Deferred[Evaluation]]]]]


@dataclasses.dataclass(frozen=True)
class EvaluationItem:
    solution_index: int
    group_name: str
    testcase_index: int
    eval: Deferred[Evaluation]


class GroupSkeleton(BaseModel):
    name: str
    testcases: List[Testcase]


class SolutionReportSkeleton(BaseModel):
    solutions: List[Solution]
    groups: List[GroupSkeleton]

    def find_group_skeleton(self, group_name: str) -> Optional[GroupSkeleton]:
        groups = [group for group in self.groups if group.name == group_name]
        if not groups:
            return None
        return groups[0]

    def empty_structured_evaluation(self) -> StructuredEvaluation:
        res: StructuredEvaluation = {}
        for solution in self.solutions:
            res[str(solution.path)] = {}
            for group in self.groups:
                res[str(solution.path)][group.name] = [None for _ in group.testcases]
        return res


@dataclasses.dataclass
class RunSolutionResult:
    skeleton: SolutionReportSkeleton
    items: List[EvaluationItem]

    def empty_structured_evaluation(self) -> StructuredEvaluation:
        return self.skeleton.empty_structured_evaluation()


def is_fast(solution: Solution) -> bool:
    # If solution has TLE tag, it is considered slow.
    return not solution.outcome.match(Outcome.TIME_LIMIT_EXCEEDED)


def get_matching_solutions(expected_outcome: ExpectedOutcome) -> List[Solution]:
    res = []
    for solution in package.get_solutions():
        if not solution.outcome.intersect(expected_outcome):
            continue
        res.append(solution)
    return res


def get_exact_matching_solutions(expected_outcome: ExpectedOutcome) -> List[Solution]:
    res = []
    for solution in package.get_solutions():
        if solution.outcome == expected_outcome:
            res.append(solution)
    return res


def compile_solutions(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Set[str]] = None,
    sanitized: bool = False,
) -> Dict[pathlib.Path, str]:
    pkg = package.find_problem_package_or_die()

    compiled_solutions = {}

    for solution in pkg.solutions:
        if (
            tracked_solutions is not None
            and str(solution.path) not in tracked_solutions
        ):
            continue
        if progress:
            progress.update(f'Compiling solution [item]{solution.path}[/item]...')
        try:
            compiled_solutions[solution.path] = compile_item(
                solution, sanitized=sanitized
            )
        except:
            console.console.print(
                f'[error]Failed compiling solution [item]{solution.path}[/item][/error]'
            )
            raise

    return compiled_solutions


def _run_solution_on_testcase(
    solution: Solution,
    compiled_digest: str,
    checker_digest: Optional[str],
    testcase: Testcase,
    output_dir: pathlib.Path,
    testcase_index: int = 0,
    verification: VerificationLevel = VerificationLevel.NONE,
    timelimit_override: Optional[int] = None,
) -> Evaluation:
    pkg = package.find_problem_package_or_die()
    actual_sandbox = package.get_singleton_sandbox()

    timelimit = timelimit_override or pkg.timelimit_for_language(solution.language)

    sandbox = EnvironmentSandbox()
    sandbox.timeLimit = timelimit
    if verification.value >= VerificationLevel.FULL.value:
        # Use double TL.
        sandbox.timeLimit = sandbox.timeLimit * 2
    sandbox.wallTimeLimit = (
        timelimit * 2 if actual_sandbox.use_soft_timeout() else sandbox.timeLimit
    )
    sandbox.memoryLimit = pkg.memorylimit_for_language(solution.language)
    sandbox.fileSizeLimit = pkg.outputLimit
    extra_config = ExecutionConfig(sandbox=sandbox)

    output_path = output_dir / testcase.inputPath.with_suffix('.out').name
    error_path = output_path.with_suffix('.err')
    log_path = output_path.with_suffix('.log')
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_log = run_item(
        solution,
        DigestOrSource.create(compiled_digest),
        stdin=DigestOrSource.create(testcase.inputPath),
        stdout=DigestOrDest.create(output_path),
        stderr=DigestOrDest.create(error_path),
        extra_config=extra_config,
    )

    if checker_digest is not None:
        checker_result = checkers.check(
            checker_digest,
            run_log,
            testcase,
            program_output=output_path,
        )
    else:
        checker_result = checkers.check_with_no_output(run_log)

    eval = Evaluation(
        result=checker_result,
        testcase=TestcaseIO(
            index=testcase_index, input=testcase.inputPath, output=testcase.outputPath
        ),
        log=TestcaseLog(
            **(run_log.model_dump() if run_log is not None else {}),
            stdout_absolute_path=output_path.absolute(),
            stderr_absolute_path=error_path.absolute(),
            log_absolute_path=log_path.absolute(),
        ),
    )

    log_path.write_text(model_to_yaml(eval))
    return eval


def _run_solution(
    solution: Solution,
    compiled_digest: str,
    checker_digest: Optional[str],
    solution_index: int,
    group_name: str,
    progress: Optional[StatusProgress] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    timelimit_override: Optional[int] = None,
) -> List[Deferred[Evaluation]]:
    runs_dir = package.get_problem_runs_dir()

    group = package.get_testgroup(group_name)
    testcases = find_built_testcases(group)
    res: List[Deferred[Evaluation]] = []
    for i, testcase in enumerate(testcases):
        assert testcase.outputPath is not None
        output_path = runs_dir / f'{solution_index}' / group.name

        if progress:
            progress.update(
                f'Running solution [item]{solution.path}[/item] on test [item]{group.name}[/item] / [item]{i}[/item]...'
            )

        async def run_fn(i=i, testcase=testcase, output_path=output_path):
            return _run_solution_on_testcase(
                solution,
                compiled_digest,
                checker_digest,
                testcase,
                output_path,
                testcase_index=i,
                verification=verification,
                timelimit_override=timelimit_override,
            )

        res.append(Deferred(run_fn))

    return res


async def convert_list_of_solution_evaluations_to_dict(
    items: Iterable[EvaluationItem],
) -> List[Dict[str, List[Evaluation]]]:
    pkg = package.find_problem_package_or_die()
    res: List[Dict[str, List[Evaluation]]] = [
        collections.defaultdict(list) for _ in pkg.solutions
    ]

    for item in items:
        res[item.solution_index][item.group_name].append(await item.eval())

    return res


def _get_report_skeleton(
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> SolutionReportSkeleton:
    pkg = package.find_problem_package_or_die()
    solutions = [
        sol
        for sol in pkg.solutions
        if verification.value >= VerificationLevel.ALL_SOLUTIONS.value or is_fast(sol)
    ]
    if tracked_solutions is not None:
        solutions = [
            solution
            for solution in solutions
            if str(solution.path) in tracked_solutions
        ]

    groups = []
    for group in pkg.testcases:
        testcases = find_built_testcases(group)
        groups.append(GroupSkeleton(name=group.name, testcases=testcases))
    return SolutionReportSkeleton(
        solutions=solutions,
        groups=groups,
    )


def _produce_solution_items(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    timelimit_override: Optional[int] = None,
    sanitized: bool = False,
) -> List[EvaluationItem]:
    pkg = package.find_problem_package_or_die()

    checker_digest = checkers.compile_checker() if check else None
    compiled_solutions = compile_solutions(
        progress=progress, tracked_solutions=tracked_solutions, sanitized=sanitized
    )

    # Clear run directory and rely on cache to
    # repopulate it.
    runs_dir = package.get_problem_runs_dir()
    shutil.rmtree(str(runs_dir), ignore_errors=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    solutions = list(
        (i, sol)
        for i, sol in enumerate(pkg.solutions)
        if verification.value >= VerificationLevel.ALL_SOLUTIONS.value or is_fast(sol)
    )
    if tracked_solutions is not None:
        solutions = [
            (i, sol) for i, sol in solutions if str(sol.path) in tracked_solutions
        ]

    def yield_items(
        solution_index: int, solution: Solution, group_name: str
    ) -> List[EvaluationItem]:
        res: List[EvaluationItem] = []
        for i, eval in enumerate(
            _run_solution(
                solution,
                compiled_solutions[solution.path],
                checker_digest,
                solution_index,
                group_name,
                progress=progress,
                verification=verification,
                timelimit_override=timelimit_override,
            )
        ):
            res.append(
                EvaluationItem(
                    solution_index=solution_index,
                    group_name=group_name,
                    testcase_index=i,
                    eval=eval,
                )
            )

        return res

    res: List[EvaluationItem] = []

    groups = pkg.testcases
    for i, solution in solutions:
        for group in groups:
            res.extend(yield_items(i, solution, group.name))

    return res


def run_solutions(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    timelimit_override: Optional[int] = None,
    sanitized: bool = False,
) -> RunSolutionResult:
    return RunSolutionResult(
        skeleton=_get_report_skeleton(tracked_solutions, verification=verification),
        items=_produce_solution_items(
            progress=progress,
            tracked_solutions=tracked_solutions,
            verification=verification,
            check=check,
            timelimit_override=timelimit_override,
            sanitized=sanitized,
        ),
    )


def _run_interactive_solutions(
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    generator: Optional[GeneratorCall] = None,
    check: bool = True,
    sanitized: bool = False,
) -> Iterator[EvaluationItem]:
    pkg = package.find_problem_package_or_die()
    main_solution = package.get_main_solution()
    check = check and main_solution is not None

    checker_digest = checkers.compile_checker() if check else None
    compiled_solutions = compile_solutions(
        tracked_solutions=tracked_solutions, sanitized=sanitized
    )

    main_solution_digest = None
    if check and main_solution is not None:
        try:
            main_solution_digest = compile_item(main_solution, sanitized=sanitized)
        except:
            console.console.print(
                '[error]Failed compiling main solution. If you do not want to check against a main solution, run with --nocheck flag.[/error]'
            )
            raise

    solutions = list(enumerate(pkg.solutions))
    if tracked_solutions is not None:
        solutions = [
            (i, sol) for i, sol in solutions if str(sol.path) in tracked_solutions
        ]

    irun_dir = package.get_problem_runs_dir() / '.irun'
    shutil.rmtree(str(irun_dir), ignore_errors=True)
    irun_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir = irun_dir / 'inputs'
    inputs_dir.mkdir(parents=True, exist_ok=True)
    input_path = inputs_dir / '000.in'
    output_path = input_path.with_suffix('.out')

    if generator is not None:
        expanded_call = generate_standalone(generator, input_path)
        console.console.print(
            f'Using input from generator call [item]{expanded_call.name} {expanded_call.args}[/item].'
        )
    else:
        input = console.multiline_prompt('Testcase input')
        input_path.write_text(input)
    testcase = Testcase(inputPath=input_path, outputPath=output_path if check else None)

    if main_solution_digest is not None:
        # TODO: Add stderr path
        generate_output_for_testcase(main_solution_digest, testcase)

    for i, solution in solutions:
        output_dir = irun_dir / f'{i}'

        async def run_fn(solution=solution, output_dir=output_dir):
            return _run_solution_on_testcase(
                solution,
                compiled_solutions[solution.path],
                checker_digest,
                testcase,
                output_dir,
                verification=verification,
            )

        yield EvaluationItem(
            solution_index=i,
            group_name='irun',
            testcase_index=0,
            eval=Deferred(run_fn),
        )


async def run_and_print_interactive_solutions(
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    generator: Optional[GeneratorCall] = None,
    check: bool = True,
    print: bool = False,
    sanitized: bool = False,
):
    pkg = package.find_problem_package_or_die()
    items = _run_interactive_solutions(
        tracked_solutions=tracked_solutions,
        verification=verification,
        check=check,
        generator=generator,
        sanitized=sanitized,
    )

    for item in items:
        sol = pkg.solutions[item.solution_index]
        _print_solution_header(sol, console.console)

        eval = await item.eval()

        stdout_path = eval.log.stdout_absolute_path
        if print:
            if (
                eval.testcase.output is not None
                and stdout_path is not None
                and stdout_path.is_file()
            ):
                console.console.print(stdout_path.read_text())
            else:
                console.console.print('[warning]Solution produced no output.[/warning]')
        elif stdout_path is not None:
            console.console.print(f'Output: {stdout_path}.')
            console.console.print()


def get_outcome_style_verdict(outcome: Outcome) -> str:
    if outcome == Outcome.ACCEPTED:
        return 'green'
    if outcome == Outcome.WRONG_ANSWER:
        return 'red'
    if outcome == Outcome.TIME_LIMIT_EXCEEDED:
        return 'yellow'
    if outcome == Outcome.RUNTIME_ERROR:
        return 'lnumber'
    if outcome == Outcome.MEMORY_LIMIT_EXCEEDED:
        return 'cyan'
    return 'magenta'


def get_testcase_markup_verdict(eval: Evaluation) -> str:
    res = '✓'
    if eval.result.outcome != Outcome.ACCEPTED:
        res = '✗'
    if eval.result.outcome == Outcome.TIME_LIMIT_EXCEEDED:
        res = '⧖'
    if eval.result.outcome == Outcome.RUNTIME_ERROR:
        res = '✗'
    style = get_outcome_style_verdict(eval.result.outcome)
    res = f'[{style}]{res}[/{style}]'
    # if eval.log.stdout_absolute_path:
    #     output_path = eval.log.stdout_absolute_path.resolve()
    #     output_link = f'file://{output_path}'
    #     res = f'[link={output_link}]{res}[/link]'
    return res


def _get_evals_time_in_ms(evals: List[Evaluation]) -> int:
    if not evals:
        return 0
    return max(int((eval.log.time or 0.0) * 1000) for eval in evals)


def _get_evals_memory_in_bytes(evals: List[Evaluation]) -> int:
    if not evals:
        return 0
    return max(int(eval.log.memory or 0) for eval in evals)


def get_evals_formatted_time(evals: List[Evaluation]) -> str:
    max_time = _get_evals_time_in_ms(evals)
    return f'{max_time} ms'


def get_evals_formatted_memory(evals: List[Evaluation]) -> str:
    max_memory = _get_evals_memory_in_bytes(evals)
    if max_memory < 1024 * 1024:
        if max_memory < 1024:
            return f'{max_memory} B'
        return f'{max_memory // 1024} KiB'
    return f'{max_memory // (1024 * 1024)} MiB'


def _print_solution_outcome(
    solution: Solution,
    evals: List[Evaluation],
    console: rich.console.Console,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> bool:
    pkg = package.find_problem_package_or_die()

    has_plain_tle = False
    bad_verdicts = set()
    no_tle_bad_verdicts = set()
    for eval in evals:
        if eval.result.outcome != Outcome.ACCEPTED:
            bad_verdicts.add(eval.result.outcome)
        if (
            eval.result.no_tle_outcome is not None
            and eval.result.no_tle_outcome != Outcome.ACCEPTED
        ):
            no_tle_bad_verdicts.add(eval.result.no_tle_outcome)
        has_plain_tle = has_plain_tle or (
            eval.result.outcome == Outcome.TIME_LIMIT_EXCEEDED
            and eval.result.no_tle_outcome is None
        )

    unmatched_bad_verdicts = set(
        v for v in bad_verdicts if not solution.outcome.match(v)
    )
    matched_bad_verdicts = bad_verdicts - unmatched_bad_verdicts
    expected_outcome_is_bad = not solution.outcome.match(Outcome.ACCEPTED)

    if unmatched_bad_verdicts or (expected_outcome_is_bad and not matched_bad_verdicts):
        console.print('[error]FAILED[/error]', end=' ')
    else:
        console.print('[success]OK[/success]', end=' ')

    console.print(f'Expected: {solution.outcome}', end='')

    if unmatched_bad_verdicts:
        unmatched_bad_verdicts_names = set(v.name for v in unmatched_bad_verdicts)
        console.print(f', got: {" ".join(unmatched_bad_verdicts_names)}', end='')
    elif expected_outcome_is_bad and not matched_bad_verdicts:
        console.print(f', got: {Outcome.ACCEPTED.name}', end='')

    console.print()
    evals_time = _get_evals_time_in_ms(evals)
    expected_outcome_is_tle = solution.outcome.match(
        Outcome.TIME_LIMIT_EXCEEDED
    ) and not solution.outcome.match(Outcome.ACCEPTED)
    if (
        # Running verification with double TL.
        verification.value >= VerificationLevel.FULL.value
        # Solution expects a TLE.
        and expected_outcome_is_tle
        # Solution does not have a plain TLE.
        and not has_plain_tle
        # A TLE has happened.
        and Outcome.TIME_LIMIT_EXCEEDED in matched_bad_verdicts
        # The solution runs in double TL.
        and evals_time < pkg.timelimit_for_language(solution.language) * 2
    ):
        other_verdicts = (bad_verdicts | no_tle_bad_verdicts) - {
            Outcome.TIME_LIMIT_EXCEEDED
        }
        if not other_verdicts:
            # The solution has no other bad verdicts except for TLEs in double TL.
            console.print(
                '[yellow]WARNING[/yellow] The solution still passed in double TL.'
            )
        elif not (bad_verdicts - {Outcome.TIME_LIMIT_EXCEEDED}):
            # The solution has other bad soft TLE outcomes.
            other_verdicts_names = ' '.join(v.name for v in other_verdicts)
            console.print(
                f'[yellow]WARNING[/yellow] The solution could still run under double TL, but failed with [item]{other_verdicts_names}[/item].'
            )
    console.print(f'Time: {get_evals_formatted_time(evals)}')
    console.print(f'Memory: {get_evals_formatted_memory(evals)}')
    return len(unmatched_bad_verdicts) == 0


def _consume_and_key_evaluation_items(
    items: Iterable[EvaluationItem],
    skeleton: SolutionReportSkeleton,
) -> StructuredEvaluation:
    """
    Consumes EvaluationItems from a run_solutions call and build a view
    with them, possibly marking with optional unprocessed items.
    """
    pkg = package.find_problem_package_or_die()
    res = skeleton.empty_structured_evaluation()

    for item in items:
        solution = pkg.solutions[item.solution_index]
        res[str(solution.path)][item.group_name][item.testcase_index] = item.eval

    return res


def _print_solution_header(solution: Solution, console: rich.console.Console):
    solutions = package.get_solutions()
    solution_index = [
        i for i, sol in enumerate(solutions) if sol.path == solution.path
    ][0]
    solution_testdir = package.get_problem_runs_dir() / f'{solution_index}'
    console.print(f'[item]{solution.path}[/item]', end=' ')
    console.print(f'({solution_testdir})')


async def _print_timing(
    console: rich.console.Console,
    skeleton: SolutionReportSkeleton,
    evaluations: StructuredEvaluation,
):
    slowest_good = None
    fastest_slow = None
    for solution in skeleton.solutions:
        all_evals = []
        for evals in evaluations[str(solution.path)].values():
            all_evals.extend([await eval() for eval in evals if eval is not None])
        solution_time = _get_evals_time_in_ms(all_evals)
        if solution.outcome.match(Outcome.ACCEPTED):
            if slowest_good is None or solution_time > slowest_good:
                slowest_good = solution_time
        if solution.outcome.is_slow():
            if fastest_slow is None or solution_time < fastest_slow:
                fastest_slow = solution_time

    if slowest_good is None and fastest_slow is None:
        return

    console.print('[status]Timing summary:[/status]')
    if slowest_good is not None:
        console.print(f'Slowest [success]OK[/success] solution: {slowest_good} ms')
    if fastest_slow is not None:
        console.print(f'Fastest [error]slow[/error] solution: {fastest_slow} ms')


async def _render_detailed_group_table(
    group: TestcaseGroup,
    skeleton: SolutionReportSkeleton,
    structured_evaluations: StructuredEvaluation,
    console: rich.console.Console,
):
    group_skeleton = skeleton.find_group_skeleton(group.name)
    assert group_skeleton is not None

    async def generate_table(
        structured_evaluation: StructuredEvaluation, group_name: str
    ) -> rich.table.Table:
        table = rich.table.Table()
        for solution in skeleton.solutions:
            table.add_column(f'[item]{solution.path}[/item]', justify='full')

        evals_per_solution = collections.defaultdict(list)
        for tc, _ in enumerate(group_skeleton.testcases):
            row = []
            for solution in skeleton.solutions:
                eval = structured_evaluation[str(solution.path)][group_name][tc]
                if eval is None:
                    row.append('...')
                    continue
                eval = eval.peek()
                if eval is None:
                    row.append('...')
                    continue

                verdict = get_testcase_markup_verdict(eval)
                time = get_evals_formatted_time([eval])
                evals_per_solution[str(solution.path)].append(eval)
                row.append(f'{verdict} {time}')
            table.add_row(*row)

        if table.row_count > 0:
            summary_row = []
            for solution in skeleton.solutions:
                evals = evals_per_solution[str(solution.path)]
                non_null_evals = [eval for eval in evals if eval is not None]
                if not non_null_evals:
                    summary_row.append('...')
                    continue
                summary_row.append('  ' + get_evals_formatted_time(non_null_evals))
            table.add_section()
            table.add_row(*summary_row)
        return table

    with rich.live.Live(
        await generate_table(skeleton.empty_structured_evaluation(), group.name),
        refresh_per_second=5,
        console=console,
    ) as live:
        for solution in skeleton.solutions:
            for tc, _ in enumerate(group_skeleton.testcases):
                eval = structured_evaluations[str(solution.path)][group.name][tc]
                if eval is None:
                    continue
                await eval()
                live.update(await generate_table(structured_evaluations, group.name))
                live.refresh()


async def _print_detailed_run_report(
    result: RunSolutionResult,
    console: rich.console.Console,
    structured_evaluations: StructuredEvaluation,
    timing: bool = True,
):
    for group in result.skeleton.groups:
        console.print(f'[bold][status]{group.name}[/status][/bold]')

        await _render_detailed_group_table(
            package.get_testgroup(group.name),
            result.skeleton,
            structured_evaluations,
            console,
        )
        continue

    ok = True
    for solution in result.skeleton.solutions:
        all_evals = []
        for evals in structured_evaluations[str(solution.path)].values():
            all_evals.extend(evals)

        # Resolve futures.
        all_evals = [await eval() for eval in all_evals if eval is not None]
        _print_solution_header(solution, console)
        cur_ok = _print_solution_outcome(
            solution,
            all_evals,
            console,
        )
        ok = ok and cur_ok
        console.print()

    console.print()

    if timing:
        await _print_timing(console, result.skeleton, structured_evaluations)
    return ok


async def print_run_report(
    result: RunSolutionResult,
    console: rich.console.Console,
    verification: environment.VerificationParam,
    detailed: bool = False,
    timing: bool = True,
) -> bool:
    structured_evaluations = _consume_and_key_evaluation_items(
        result.items, result.skeleton
    )
    if detailed:
        return await _print_detailed_run_report(
            result, console, structured_evaluations, timing=timing
        )

    ok = True

    for solution in result.skeleton.solutions:
        _print_solution_header(solution, console)
        solution_evals = []
        for group in result.skeleton.groups:
            console.print(f'[bold][status]{group.name}[/status][/bold] ', end='')
            group_evals = []
            for i, _ in enumerate(group.testcases):
                eval = structured_evaluations[str(solution.path)][group.name][i]
                if eval is None:
                    continue
                eval = await eval()
                console.print(f'{i}/', end='')
                console.print(get_testcase_markup_verdict(eval), end=' ')
                group_evals.append(eval)
                solution_evals.append(eval)

            console.print(
                f'({get_evals_formatted_time(group_evals)}, {get_evals_formatted_memory(group_evals)})',
                end='',
            )
            console.print()

        ok = ok and _print_solution_outcome(
            solution,
            solution_evals,
            console,
            verification=VerificationLevel(verification),
        )
        console.print()

    await _print_timing(console, result.skeleton, structured_evaluations)

    return ok


async def estimate_time_limit(
    console: rich.console.Console,
    result: RunSolutionResult,
) -> Optional[int]:
    structured_evaluations = _consume_and_key_evaluation_items(
        result.items, result.skeleton
    )

    timing_per_solution = {}
    timing_per_language = {}

    if not result.skeleton.solutions:
        console.print('[error]No solutions to estimate time limit from.[/error]')
        return None

    for solution in result.skeleton.solutions:
        timings = []
        for evals in structured_evaluations[str(solution.path)].values():
            for eval in evals:
                if eval is None:
                    continue
                eval = await eval()
                if eval.log.time is not None:
                    timings.append(int(eval.log.time * 1000))

        if not timings:
            console.print(
                f'[warning]No timings for solution [item]{solution.path}[/item].[/warning]'
            )
            continue

        timing_per_solution[str(solution.path)] = max(timings)
        lang = find_language_name(solution)
        if lang not in timing_per_language:
            timing_per_language[lang] = 0
        timing_per_language[lang] = max(timing_per_language[lang], max(timings))

    console.rule('[status]Time estimation[/status]', style='status')

    fastest_time = min(timing_per_solution.values())
    slowest_time = max(timing_per_solution.values())

    console.print(f'Fastest solution: {fastest_time} ms')
    console.print(f'Slowest solution: {slowest_time} ms')

    if len(timing_per_language) > 0:
        timing_language_list = [(t, lang) for lang, t in timing_per_language.items()]
        fastest_language_time, fastest_language = min(timing_language_list)
        slowest_language_time, slowest_language = max(timing_language_list)

        console.print(
            f'Fastest language: {fastest_language} ({fastest_language_time} ms)'
        )
        console.print(
            f'Slowest language: {slowest_language} ({slowest_language_time} ms)'
        )

    estimated_tl = int(max(fastest_time * 3, slowest_time * 1.5))
    console.print(f'[success]Estimated time limit:[/success] {estimated_tl} ms')

    return estimated_tl
