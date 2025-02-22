from __future__ import generators

import collections
import dataclasses
import pathlib
import shutil
from collections.abc import Iterator
from typing import Dict, Iterable, List, Optional, Set, Tuple

import questionary
import rich
import rich.live
import rich.markup
import rich.table
import rich.text
import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import checkers, package
from rbx.box.code import SanitizationLevel, compile_item, find_language_name, run_item
from rbx.box.deferred import Deferred
from rbx.box.environment import (
    EnvironmentSandbox,
    ExecutionConfig,
    VerificationLevel,
)
from rbx.box.generators import generate_output_for_testcase, generate_standalone
from rbx.box.schema import (
    ExpectedOutcome,
    GeneratorCall,
    Limits,
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
    limits: Dict[str, Limits]

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
                solution,
                sanitized=SanitizationLevel.FORCE
                if sanitized
                else SanitizationLevel.NONE,
            )
        except:
            console.console.print(
                f'[error]Failed compiling solution [item]{solution.path}[/item][/error]'
            )
            raise

    return compiled_solutions


def get_limits_for_language(
    lang: Optional[str],
    verification: VerificationLevel,
    timelimit_override: Optional[int],
) -> Limits:
    pkg = package.find_problem_package_or_die()
    time = timelimit_override or pkg.timelimit_for_language(lang)
    isDoubleTL = verification.value >= VerificationLevel.FULL.value
    memory = pkg.memorylimit_for_language(lang)
    return Limits(
        time=time, memory=memory, output=pkg.outputLimit, isDoubleTL=isDoubleTL
    )


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
    actual_sandbox = package.get_singleton_sandbox()

    limits = get_limits_for_language(
        solution.language, verification, timelimit_override
    )

    sandbox = EnvironmentSandbox()
    sandbox.timeLimit = limits.time
    if limits.isDoubleTL and sandbox.timeLimit is not None:
        # Double TL.
        sandbox.timeLimit = sandbox.timeLimit * 2
    sandbox.wallTimeLimit = sandbox.timeLimit
    if sandbox.timeLimit is not None and actual_sandbox.use_soft_timeout():
        sandbox.wallTimeLimit = sandbox.timeLimit * 2
    sandbox.memoryLimit = limits.memory
    sandbox.fileSizeLimit = limits.output
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
    timelimit_override: Optional[int] = None,
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

    langs = set(find_language_name(solution) for solution in solutions)
    limits = {
        lang: get_limits_for_language(lang, verification, timelimit_override)
        for lang in langs
        if lang is not None
    }

    groups = []
    for group in pkg.testcases:
        testcases = find_built_testcases(group)
        groups.append(GroupSkeleton(name=group.name, testcases=testcases))
    return SolutionReportSkeleton(
        solutions=solutions,
        groups=groups,
        limits=limits,
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
        skeleton=_get_report_skeleton(
            tracked_solutions,
            verification=verification,
            timelimit_override=timelimit_override,
        ),
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
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    generator: Optional[GeneratorCall] = None,
    check: bool = True,
    print: bool = False,
    sanitized: bool = False,
) -> Iterator[EvaluationItem]:
    pkg = package.find_problem_package_or_die()
    main_solution = package.get_main_solution()
    check = check and main_solution is not None

    checker_digest = checkers.compile_checker() if check else None
    compiled_solutions = compile_solutions(
        progress=progress, tracked_solutions=tracked_solutions, sanitized=sanitized
    )

    main_solution_digest = None
    if check and main_solution is not None:
        try:
            main_solution_digest = compile_item(
                main_solution,
                sanitized=SanitizationLevel.FORCE
                if sanitized
                else SanitizationLevel.NONE,
            )
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

    irun_dir = package.get_problem_iruns_dir()
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
        if print:
            console.console.print(input_path.read_text())
        else:
            console.console.print(
                f'Input was written to [item]{input_path.resolve()}[/item]'
            )
        console.console.print()
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
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    generator: Optional[GeneratorCall] = None,
    check: bool = True,
    print: bool = False,
    sanitized: bool = False,
):
    pkg = package.find_problem_package_or_die()
    items = _run_interactive_solutions(
        progress=progress,
        tracked_solutions=tracked_solutions,
        verification=verification,
        check=check,
        generator=generator,
        sanitized=sanitized,
        print=print,
    )

    if progress:
        progress.stop()

    for item in items:
        sol = pkg.solutions[item.solution_index]
        _print_solution_header(sol, console.console, is_irun=True)

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
            console.console.print(f'[status]Output:[/status] {stdout_path}')
            if eval.log.stderr_absolute_path is not None:
                console.console.print(
                    f'[status]Stderr:[/status] {eval.log.stderr_absolute_path}'
                )
            console.console.print()


def _get_solution_repr(sol: Solution) -> List[Tuple[str, str]]:
    fg_color = sol.outcome.style().replace('lnumber', 'cyan')
    return [
        ('', f'{str(sol.path)} '),
        (f'fg:{fg_color}', sol.outcome.name),
    ]


def pick_solutions(tracked_solutions: Optional[Set[str]]) -> List[str]:
    pkg = package.find_problem_package_or_die()
    if tracked_solutions is None:
        tracked_solutions = set(str(sol.path) for sol in pkg.solutions)

    # Store in a separate list to maintain order with the package declaration.
    choices = [
        questionary.Choice(title=_get_solution_repr(sol), value=str(sol.path))
        for sol in pkg.solutions
        if str(sol.path) in tracked_solutions
    ]

    picked = questionary.checkbox('Select solutions', choices=choices).ask()
    if picked is None:
        raise typer.Abort()
    return picked


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


def get_outcome_markup_verdict(outcome: Outcome) -> str:
    res = '✓'
    if outcome != Outcome.ACCEPTED:
        res = '✗'
    if outcome == Outcome.TIME_LIMIT_EXCEEDED:
        res = '⧖'
    if outcome == Outcome.RUNTIME_ERROR:
        res = '✗'
    style = get_outcome_style_verdict(outcome)
    res = f'[{style}]{res}[/{style}]'
    return res


def get_testcase_markup_verdict(eval: Evaluation) -> str:
    # if eval.log.stdout_absolute_path:
    #     output_path = eval.log.stdout_absolute_path.resolve()
    #     output_link = f'file://{output_path}'
    #     res = f'[link={output_link}]{res}[/link]'
    return get_outcome_markup_verdict(eval.result.outcome)


def _get_evals_time_in_ms(evals: List[Evaluation]) -> int:
    if not evals:
        return 0
    return max(int((eval.log.time or 0.0) * 1000) for eval in evals)


def _get_evals_memory_in_bytes(evals: List[Evaluation]) -> int:
    if not evals:
        return 0
    return max(int(eval.log.memory or 0) for eval in evals)


def get_formatted_time(time_in_ms: int) -> str:
    return f'{time_in_ms} ms'


def get_evals_formatted_time(evals: List[Evaluation]) -> str:
    max_time = _get_evals_time_in_ms(evals)
    return get_formatted_time(max_time)


def get_capped_evals_formatted_time(
    solution: Solution, evals: List[Evaluation], verification: VerificationLevel
) -> str:
    pkg = package.find_problem_package_or_die()

    max_time = _get_evals_time_in_ms(evals)
    has_tle = any(eval.result.outcome == Outcome.TIME_LIMIT_EXCEEDED for eval in evals)
    timelimits = [
        eval.log.metadata.timeLimit
        for eval in evals
        if eval.log.metadata is not None and eval.log.metadata.timeLimit is not None
    ]
    tl = None
    if timelimits:
        tl = min(timelimits)
    if tl is None:
        tl = pkg.timelimit_for_language(solution.language)

        if verification.value >= VerificationLevel.FULL.value:
            # Using double TL for verification.
            tl = tl * 2

    if has_tle and max_time >= tl:
        return f'>{tl} ms'
    return f'{max_time} ms'


def get_formatted_memory(memory_in_bytes: int) -> str:
    if memory_in_bytes < 1024 * 1024:
        if memory_in_bytes < 1024:
            return f'{memory_in_bytes} B'
        return f'{memory_in_bytes // 1024} KiB'
    return f'{memory_in_bytes // (1024 * 1024)} MiB'


def get_evals_formatted_memory(evals: List[Evaluation]) -> str:
    max_memory = _get_evals_memory_in_bytes(evals)
    return get_formatted_memory(max_memory)


def get_worst_outcome(evals: List[Evaluation]) -> Outcome:
    return Outcome.worst_outcome(eval.result.outcome for eval in evals)


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
    has_sanitizer_warnings = False
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
        has_sanitizer_warnings = (
            has_sanitizer_warnings or eval.result.sanitizer_warnings
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

    if has_sanitizer_warnings:
        console.print(
            '[warning]WARNING[/warning] The solution had sanitizer errors or warnings, marked with [warning]*[/warning]. See their stderr for more details.'
        )

    console.print(
        f'Time: {get_capped_evals_formatted_time(solution, evals, verification)}'
    )
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


def _print_solution_header(
    solution: Solution, console: rich.console.Console, is_irun: bool = False
):
    solutions = package.get_solutions()
    solution_index = [
        i for i, sol in enumerate(solutions) if sol.path == solution.path
    ][0]
    solution_testdir = (
        package.get_problem_iruns_dir() / f'{solution_index}'
        if is_irun
        else package.get_problem_runs_dir() / f'{solution_index}'
    )
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


def _length_markup(markup: str) -> int:
    text = rich.markup.render(markup)
    return text.cell_len


def _length_pointwise(ls: Iterable[str]) -> Tuple[int, ...]:
    return tuple(_length_markup(x) for x in ls)


def _max_pointwise(ls: Iterable[Tuple[int, ...]]) -> Tuple[int, ...]:
    return tuple(max(x) for x in zip(*ls))


def _get_indented_text(s: str, width: int):
    text = rich.markup.render(s)
    text.align('right', width=width)
    return text


def _render_padded_rows(
    rows: List[List[Tuple[str, ...]]],
) -> List[List[rich.text.Text]]:
    max_widths_per_column = [
        _max_pointwise(_length_pointwise(cell) for cell in col) for col in zip(*rows)
    ]
    res = []
    for row in rows:
        acc_row = []
        for i, cell in enumerate(row):
            acc_row.append(
                rich.text.Text(' ').join(
                    _get_indented_text(item, width)
                    for item, width in zip(cell, max_widths_per_column[i])
                )
            )
        res.append(acc_row)
    return res


async def _render_detailed_group_table(
    group: TestcaseGroup,
    skeleton: SolutionReportSkeleton,
    structured_evaluations: StructuredEvaluation,
    console: rich.console.Console,
    verification: VerificationLevel = VerificationLevel.NONE,
):
    group_skeleton = skeleton.find_group_skeleton(group.name)
    assert group_skeleton is not None

    async def generate_table(
        structured_evaluation: StructuredEvaluation, group_name: str
    ) -> rich.table.Table:
        table = rich.table.Table()
        for solution in skeleton.solutions:
            table.add_column(f'[item]{solution.path}[/item]', justify='full')

        padded_rows = []

        evals_per_solution = collections.defaultdict(list)
        for tc, _ in enumerate(group_skeleton.testcases):
            row = []
            for solution in skeleton.solutions:
                eval = structured_evaluation[str(solution.path)][group_name][tc]
                if eval is None:
                    row.append((f'[info]#{tc}[/info]', '', '...', '', '', ''))
                    continue
                eval = eval.peek()
                if eval is None:
                    row.append((f'[info]#{tc}[/info]', '', '...', '', '', ''))
                    continue

                evals_per_solution[str(solution.path)].append(eval)

                verdict = get_testcase_markup_verdict(eval)
                time = get_capped_evals_formatted_time(solution, [eval], verification)
                memory = get_evals_formatted_memory([eval])
                full_item = (f'[info]#{tc}[/info]', verdict, time, '/', memory, '')
                if eval.result.sanitizer_warnings:
                    full_item = (*full_item[:-1], '[warning]*[/warning]')

                row.append(full_item)
            padded_rows.append(row)

        if padded_rows:
            summary_row = []
            for solution in skeleton.solutions:
                evals = evals_per_solution[str(solution.path)]
                non_null_evals = [eval for eval in evals if eval is not None]
                if not non_null_evals:
                    summary_row.append('...')
                    continue
                formatted_time = get_capped_evals_formatted_time(
                    solution, non_null_evals, verification
                )
                formatted_memory = get_evals_formatted_memory(non_null_evals)
                worst_outcome = get_worst_outcome(non_null_evals)
                verdict = get_outcome_markup_verdict(worst_outcome)
                summary_row.append(
                    ('', verdict, formatted_time, '/', formatted_memory, '')
                )
            padded_rows.append(summary_row)

        for row in _render_padded_rows(padded_rows):
            table.add_row(*row)

        if padded_rows:
            table.rows[-2].end_section = True
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
    verification: VerificationLevel = VerificationLevel.NONE,
):
    for group in result.skeleton.groups:
        console.print(f'[bold][status]{group.name}[/status][/bold]')

        await _render_detailed_group_table(
            package.get_testgroup(group.name),
            result.skeleton,
            structured_evaluations,
            console,
            verification=verification,
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
            verification=verification,
        )
        ok = ok and cur_ok
        console.print()

    console.print()

    if timing:
        await _print_timing(console, result.skeleton, structured_evaluations)
    return ok


def _print_limits(limits: Dict[str, Limits]):
    console.console.print(
        '[bold][success]Running with the following limits (per language):[/success][/bold]'
    )
    for lang, limit in limits.items():
        console.console.print(f'[bold][status]{lang}[/status][/bold]')
        time = (
            '<No time limit>' if limit.time is None else get_formatted_time(limit.time)
        )
        memory = (
            '<No memory limit>'
            if limit.memory is None
            else get_formatted_memory(limit.memory * 1024 * 1024)
        )
        console.console.print(f'Time: {time}')
        console.console.print(f'Memory: {memory}')
        if limit.isDoubleTL:
            console.console.print('[warning]Running with 2*TL[/warning]')
    console.console.print()


async def print_run_report(
    result: RunSolutionResult,
    console: rich.console.Console,
    verification: VerificationLevel,
    detailed: bool = False,
    timing: bool = True,
    skip_printing_limits: bool = False,
) -> bool:
    if not skip_printing_limits:
        _print_limits(result.skeleton.limits)

    structured_evaluations = _consume_and_key_evaluation_items(
        result.items, result.skeleton
    )
    if detailed:
        return await _print_detailed_run_report(
            result,
            console,
            structured_evaluations,
            verification=verification,
            timing=timing,
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
                console.print(get_testcase_markup_verdict(eval), end='')
                if eval.result.sanitizer_warnings:
                    console.print('[warning]*[/warning]', end='')
                console.print('', end=' ')
                group_evals.append(eval)
                solution_evals.append(eval)

            console.print(
                f'({get_capped_evals_formatted_time(solution, group_evals, verification)}, {get_evals_formatted_memory(group_evals)})',
                end='',
            )
            console.print()

        cur_ok = _print_solution_outcome(
            solution,
            solution_evals,
            console,
            verification=verification,
        )
        ok = ok and cur_ok
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
