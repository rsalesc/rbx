from __future__ import generators

import collections
import dataclasses
import pathlib
import shutil
from collections.abc import Iterator
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import rich
import rich.live
import rich.markup
import rich.table
import rich.text
import typer
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import checkers, environment, package, remote, state
from rbx.box.code import (
    SanitizationLevel,
    compile_item,
    find_language_name,
)
from rbx.box.deferred import Deferred
from rbx.box.environment import (
    VerificationLevel,
)
from rbx.box.formatting import get_formatted_memory, get_formatted_time, href
from rbx.box.generators import (
    GenerationMetadata,
    expand_generator_call,
    generate_output_for_testcase,
    generate_standalone,
)
from rbx.box.schema import (
    ExpectedOutcome,
    GeneratorCall,
    Solution,
    TaskType,
    Testcase,
    TestcaseGroup,
)
from rbx.box.tasks import (
    get_limits_for_language,
    run_solution_on_testcase,
)
from rbx.box.testcase_extractors import extract_generation_testcases
from rbx.box.testcase_utils import (
    TestcaseEntry,
    find_built_testcases,
    parse_interaction,
    print_interaction,
)
from rbx.grading.limits import Limits
from rbx.grading.steps import (
    Evaluation,
    Outcome,
)
from rbx.utils import StatusProgress

StructuredEvaluation = Dict[str, Dict[str, List[Optional[Deferred[Evaluation]]]]]


@dataclasses.dataclass(frozen=True)
class EvaluationItem:
    solution: Solution
    testcase_entry: TestcaseEntry
    eval: Deferred[Evaluation]


class GroupSkeleton(BaseModel):
    name: str
    testcases: List[Testcase]


class SolutionSkeleton(Solution):
    runs_dir: pathlib.Path

    def get_entry_prefix(self, entry: TestcaseEntry) -> pathlib.Path:
        return self.runs_dir / entry.group / f'{entry.index:03d}'


class SolutionReportSkeleton(BaseModel):
    solutions: List[SolutionSkeleton]
    entries: List[TestcaseEntry]
    groups: List[GroupSkeleton]
    limits: Dict[str, Limits]
    verification: VerificationLevel
    capture_pipes: bool = False

    def find_group_skeleton(self, group_name: str) -> Optional[GroupSkeleton]:
        groups = [group for group in self.groups if group.name == group_name]
        if not groups:
            return None
        return groups[0]

    def find_solution_skeleton(self, solution: Solution) -> Optional[SolutionSkeleton]:
        for sol in self.solutions:
            if sol.path == solution.path:
                return sol
        return None

    def find_solution_skeleton_index(self, solution: Solution) -> Optional[int]:
        for i, sol in enumerate(self.solutions):
            if sol.path == solution.path:
                return i
        return None

    def get_solution_path_set(self) -> Set[str]:
        return set(str(sol.path) for sol in self.solutions)

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
    return not solution.outcome.is_slow()


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

    if tracked_solutions is None:
        tracked_solutions = set(str(sol.path) for sol in pkg.solutions)

    for solution in expand_solutions(list(tracked_solutions)):
        if progress:
            progress.update(f'Compiling solution {href(solution.path)}...')
        try:
            compiled_solutions[solution.path] = compile_item(
                solution,
                sanitized=SanitizationLevel.FORCE
                if sanitized
                else SanitizationLevel.NONE,
            )
        except:
            console.console.print(
                f'[error]Failed compiling solution {href(solution.path)}.[/error]'
            )
            raise

    return compiled_solutions


def _run_solution(
    solution: Solution,
    compiled_digest: str,
    checker_digest: Optional[str],
    runs_dir: pathlib.Path,
    group_name: str,
    interactor_digest: Optional[str] = None,
    progress: Optional[StatusProgress] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    timelimit_override: Optional[int] = None,
) -> List[Deferred[Evaluation]]:
    group = package.get_testgroup(group_name)
    testcases = find_built_testcases(group)
    res: List[Deferred[Evaluation]] = []
    for i, testcase in enumerate(testcases):
        assert testcase.outputPath is not None
        output_path = runs_dir / group.name
        output_path.mkdir(parents=True, exist_ok=True)

        if progress:
            progress.update(
                f'Running solution {href(solution.path)} on test [item]{group.name}[/item] / [item]{i}[/item]...'
            )

        async def run_fn(i=i, testcase=testcase, output_path=output_path):
            return await run_solution_on_testcase(
                solution,
                compiled_digest,
                checker_digest,
                testcase,
                output_dir=output_path,
                interactor_digest=interactor_digest,
                testcase_index=i,
                verification=verification,
                timelimit_override=timelimit_override,
            )

        res.append(Deferred(run_fn))

    return res


async def convert_list_of_solution_evaluations_to_dict(
    skeleton: SolutionReportSkeleton,
    items: Iterable[EvaluationItem],
) -> List[Dict[str, List[Evaluation]]]:
    pkg = package.find_problem_package_or_die()
    res: List[Dict[str, List[Evaluation]]] = [
        collections.defaultdict(list) for _ in pkg.solutions
    ]

    for item in items:
        sol_idx = skeleton.find_solution_skeleton_index(item.solution)
        if sol_idx is not None:
            to_append = await item.eval()
            res[sol_idx][item.testcase_entry.group].append(to_append)

    return res


def _get_solutions_for_skeleton(
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> List[Solution]:
    pkg = package.find_problem_package_or_die()
    solutions = [
        sol
        for sol in pkg.solutions
        if verification.value >= VerificationLevel.ALL_SOLUTIONS.value or is_fast(sol)
    ]
    if tracked_solutions is not None:
        solutions = expand_solutions(list(tracked_solutions))
    return solutions


def _get_report_skeleton(
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    timelimit_override: Optional[int] = None,
) -> SolutionReportSkeleton:
    pkg = package.find_problem_package_or_die()
    solutions = _get_solutions_for_skeleton(tracked_solutions, verification)

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
    entries = [
        TestcaseEntry(group=group.name, index=i)
        for group in groups
        for i in range(len(group.testcases))
    ]

    # Prepare directory.
    runs_dir = package.get_problem_runs_dir()
    shutil.rmtree(str(runs_dir), ignore_errors=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    skeleton = SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(
                **solution.model_dump(),
                runs_dir=package.get_problem_runs_dir() / f'{i}',
            )
            for i, solution in enumerate(solutions)
        ],
        groups=groups,
        limits=limits,
        entries=entries,
        verification=verification,
        capture_pipes=state.STATE.debug_logs,
    )

    skeleton_file = runs_dir / 'skeleton.yml'
    skeleton_file.write_text(utils.model_to_yaml(skeleton))

    return skeleton


def _produce_solution_items(
    skeleton: SolutionReportSkeleton,
    progress: Optional[StatusProgress] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    timelimit_override: Optional[int] = None,
    sanitized: bool = False,
) -> List[EvaluationItem]:
    pkg = package.find_problem_package_or_die()

    if pkg.type == TaskType.COMMUNICATION:
        checker_digest = (
            checkers.compile_checker() if check and pkg.checker is not None else None
        )
        interactor_digest = checkers.compile_interactor()
    else:
        checker_digest = checkers.compile_checker() if check else None
        interactor_digest = None

    compiled_solutions = compile_solutions(
        progress=progress,
        tracked_solutions=skeleton.get_solution_path_set(),
        sanitized=sanitized,
    )

    def yield_items(
        solution: SolutionSkeleton, group_name: str
    ) -> List[EvaluationItem]:
        res: List[EvaluationItem] = []
        for i, eval in enumerate(
            _run_solution(
                solution,
                compiled_solutions[solution.path],
                checker_digest,
                solution.runs_dir,
                group_name,
                interactor_digest=interactor_digest,
                progress=progress,
                verification=verification,
                timelimit_override=timelimit_override,
            )
        ):
            res.append(
                EvaluationItem(
                    solution=solution,
                    testcase_entry=TestcaseEntry(group=group_name, index=i),
                    eval=eval,
                )
            )

        return res

    res: List[EvaluationItem] = []

    groups = pkg.testcases
    for solution in skeleton.solutions:
        for group in groups:
            res.extend(yield_items(solution, group.name))

    return res


def print_best_output(output_files: List[pathlib.Path], empty_warning: bool = False):
    for output_file in output_files:
        if not output_file.is_file():
            continue
        if output_file.suffix == '.pio':
            print_interaction(parse_interaction(output_file))
        else:
            console.console.print(output_file.read_text())
        return
    if empty_warning:
        console.console.print('[warning]Solution produced no output.[/warning]')


def run_solutions(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    timelimit_override: Optional[int] = None,
    sanitized: bool = False,
) -> RunSolutionResult:
    skeleton = _get_report_skeleton(
        tracked_solutions,
        verification=verification,
        timelimit_override=timelimit_override,
    )
    result = RunSolutionResult(
        skeleton=skeleton,
        items=_produce_solution_items(
            skeleton=skeleton,
            progress=progress,
            verification=verification,
            check=check,
            timelimit_override=timelimit_override,
            sanitized=sanitized,
        ),
    )
    return result


async def _generate_testcase_interactively(
    progress: Optional[StatusProgress] = None,
    generator: Optional[GeneratorCall] = None,
    testcase_entry: Optional[TestcaseEntry] = None,
    check: bool = True,
    custom_output: bool = False,
    sanitized: bool = False,
    print: bool = False,
) -> Testcase:
    main_solution = package.get_main_solution()
    irun_dir = package.get_problem_iruns_dir()
    inputs_dir = irun_dir / 'inputs'
    inputs_dir.mkdir(parents=True, exist_ok=True)
    testcase = Testcase(
        inputPath=inputs_dir / '000.in',
        outputPath=(inputs_dir / '000.out') if check else None,
    )

    is_manual = False
    is_output_manual = False
    generation_metadata = None
    if generator is not None:
        generation_metadata = GenerationMetadata(
            generator_call=expand_generator_call(generator),
            copied_to=testcase,
        )
    elif testcase_entry is not None:
        extracted = await extract_generation_testcases([testcase_entry])
        if not extracted:
            console.console.print(
                f'[error]Failed searching for testcase [item]{testcase_entry}[/item].[/error]'
            )
            raise typer.Exit(1)
        generation_metadata = extracted[0].metadata
        # Replace destination with the irun testcase we're using.
        generation_metadata.copied_to = testcase
    else:
        with utils.no_progress(progress):
            input = console.multiline_prompt('Testcase input')
        testcase.inputPath.write_text(input)
        console.console.print()

        if (
            testcase.outputPath is not None
            and not testcase.outputPath.is_file()
            and (main_solution is None or custom_output)
        ):
            with utils.no_progress(progress):
                output = console.multiline_prompt('Testcase output')
                testcase.outputPath.write_text(output)
                console.console.print()
            is_output_manual = True

        generation_metadata = GenerationMetadata(
            copied_to=testcase,
        )
        is_manual = True

    # 1. Generate testcase.
    if generation_metadata is not None:
        await generate_standalone(
            generation_metadata,
            progress=progress,
            validate=True,
        )
        if testcase_entry is not None:
            console.console.print(
                f'Using input from testcase [item]{testcase_entry}[/item].'
            )
        elif generation_metadata.generator_call is not None:
            console.console.print(
                f'Using input from generator call [item]{generation_metadata.generator_call.name} {generation_metadata.generator_call.args}[/item].'
            )
        if print and not is_manual:
            console.console.print(testcase.inputPath.read_text())
        else:
            console.console.print(
                f'Input was written to [item]{testcase.inputPath.resolve()}[/item]'
            )
        console.console.print()

    # 2. Generate test output from reference
    main_solution_digest = None
    if check and not (
        testcase.outputPath is not None and testcase.outputPath.is_file()
    ):
        if main_solution is None:
            console.console.print(
                '[error]Checking is enabled but no main solution or custom output was specified.[/error]'
            )
            raise typer.Exit(1)

        if progress:
            progress.update('Compiling main solution...')
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

    if main_solution_digest is not None and not is_output_manual:
        pkg = package.find_problem_package_or_die()
        if pkg.type == TaskType.COMMUNICATION:
            interactor_digest = checkers.compile_interactor(progress)
        else:
            interactor_digest = None

        if progress:
            progress.update('Generating output for test...')
        # TODO: Add stderr path
        await generate_output_for_testcase(
            main_solution_digest,
            testcase,
            interactor_digest=interactor_digest,
        )

    if check and testcase.outputPath is not None and not testcase.outputPath.is_file():
        # Output was not created, throw an error.
        console.console.print(
            '[error]Checking is enabled but no output could be generated for this testcase.[/error]'
        )
        console.console.print(
            '[error]Either specify it explicitly or provide a main solution.[/error]'
        )
        raise typer.Exit(1)

    return testcase


def _run_interactive_solutions(
    testcase: Testcase,
    skeleton: SolutionReportSkeleton,
    progress: Optional[StatusProgress] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    sanitized: bool = False,
) -> Iterator[EvaluationItem]:
    pkg = package.find_problem_package_or_die()

    if pkg.type == TaskType.COMMUNICATION:
        checker_digest = checkers.compile_checker() if check else None
        interactor_digest = checkers.compile_interactor()
    else:
        checker_digest = checkers.compile_checker() if check else None
        interactor_digest = None

    compiled_solutions = compile_solutions(
        progress=progress,
        tracked_solutions=skeleton.get_solution_path_set(),
        sanitized=sanitized,
    )

    if progress:
        progress.update('Running solutions...')

    for solution in skeleton.solutions:
        output_dir = solution.runs_dir

        async def run_fn(solution=solution, output_dir=output_dir):
            return await run_solution_on_testcase(
                solution,
                compiled_solutions[solution.path],
                checker_digest,
                testcase,
                output_dir=output_dir,
                interactor_digest=interactor_digest,
                verification=verification,
                capture_pipes=True,
            )

        yield EvaluationItem(
            solution=solution,
            testcase_entry=TestcaseEntry(group='irun', index=0),
            eval=Deferred(run_fn),
        )


def _get_interactive_skeleton(
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> SolutionReportSkeleton:
    solutions = _get_solutions_for_skeleton(tracked_solutions, verification)

    langs = set(find_language_name(solution) for solution in solutions)
    limits = {
        lang: get_limits_for_language(lang, verification, timelimit_override=None)
        for lang in langs
        if lang is not None
    }

    # Ensure path is new.
    irun_dir = package.get_problem_iruns_dir()
    shutil.rmtree(str(irun_dir), ignore_errors=True)
    irun_dir.mkdir(parents=True, exist_ok=True)

    skeleton = SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(
                **solution.model_dump(),
                runs_dir=irun_dir / f'{i}',
            )
            for i, solution in enumerate(solutions)
        ],
        groups=[],
        limits=limits,
        entries=[],
        verification=verification,
        capture_pipes=True,
    )

    skeleton_file = irun_dir / 'skeleton.yml'
    skeleton_file.write_text(utils.model_to_yaml(skeleton))

    return skeleton


async def run_and_print_interactive_solutions(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Set[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    generator: Optional[GeneratorCall] = None,
    testcase_entry: Optional[TestcaseEntry] = None,
    check: bool = True,
    custom_output: bool = False,
    print: bool = False,
    sanitized: bool = False,
):
    pkg = package.find_problem_package_or_die()
    skeleton = _get_interactive_skeleton(
        tracked_solutions,
        verification=verification,
    )
    testcase = await _generate_testcase_interactively(
        progress=progress,
        generator=generator,
        testcase_entry=testcase_entry,
        check=check,
        custom_output=custom_output,
        sanitized=sanitized,
        print=print,
    )
    items = _run_interactive_solutions(
        testcase,
        skeleton=skeleton,
        progress=progress,
        verification=verification,
        check=check,
        sanitized=sanitized,
    )

    for item in items:
        sol = skeleton.find_solution_skeleton(item.solution)
        assert sol is not None

        if progress:
            progress.update(f'Running [item]{sol.path}[/item]...')

        eval = await item.eval()

        with utils.no_progress(progress):
            console.console.print(get_testcase_markup_verdict(eval), end=' ')
            _print_solution_header(sol, console.console)
            _print_solution_outcome(
                sol, [eval], console.console, verification, subset=True
            )

        stdout_path = eval.log.stdout_absolute_path
        if print and stdout_path is not None:
            if pkg.type == TaskType.COMMUNICATION:
                console.console.rule('Interaction', style='status')
                output_files = [
                    stdout_path.with_suffix('.pio'),
                    stdout_path.with_suffix('.pout'),
                ]
                print_best_output(output_files, empty_warning=True)

            console.console.rule('Output', style='status')
            output_files = [stdout_path]
            print_best_output(output_files, empty_warning=True)
        elif stdout_path is not None:
            if stdout_path.with_suffix('.pout').is_file():
                stdout_path = stdout_path.with_suffix('.pout')

            if stdout_path.is_file():
                console.console.print(f'[status]Output:[/status] {stdout_path}')
            if stdout_path.with_suffix('.pio').is_file():
                console.console.print(
                    f'[status]Interaction:[/status] {stdout_path.with_suffix(".pio")}'
                )
            if eval.log.stderr_absolute_path is not None:
                console.console.print(
                    f'[status]Stderr:[/status] {eval.log.stderr_absolute_path}'
                )
            console.console.print()


def _get_solution_repr(sol: Solution) -> List[Tuple[str, str]]:
    fg_color = sol.outcome.style()
    return [
        ('', f'{str(sol.path)} '),
        (f'fg:{fg_color}', sol.outcome.name),
    ]


def expand_solutions_with_source(sols: List[str]) -> List[Tuple[Solution, bool]]:
    pkg = package.find_problem_package_or_die()
    pkg_sols = {str(sol.path): sol for sol in pkg.solutions}

    # Download remote sols.
    path_sols = remote.expand_files(sols)

    # Ensure sols exist.
    path_sols = [sol for sol in path_sols if sol.is_file()]

    seen_sols = set()
    res: List[Tuple[Solution, bool]] = []
    for sol in path_sols:
        if str(sol) in seen_sols:
            # This solution was already added.
            continue
        if str(sol) in pkg_sols:
            # This solution is in the package.
            res.append((pkg_sols[str(sol)], False))
        else:
            # This solution is fetched from some source.
            res.append((Solution(path=sol, outcome=ExpectedOutcome.ANY), True))
        seen_sols.add(str(sol))
    return res


def expand_solutions(sols: List[str]) -> List[Solution]:
    return [sol for sol, _ in expand_solutions_with_source(sols)]


async def pick_solutions(
    tracked_solutions: Optional[Set[str]],
    extra_solutions: Optional[List[str]] = None,
) -> List[str]:
    pkg = package.find_problem_package_or_die()
    # Store in a separate list to maintain order with the package declaration.
    import questionary

    choices = [
        questionary.Choice(
            title=_get_solution_repr(sol),
            value=str(sol.path),
            checked=tracked_solutions is None or str(sol.path) in tracked_solutions,
        )
        for sol in pkg.solutions
    ]

    seen_sols = set(str(sol.path) for sol in pkg.solutions)

    if extra_solutions is not None:
        # Add only new solutions.
        choices.extend(
            questionary.Choice(
                title=_get_solution_repr(sol),
                value=str(sol.path),
                checked=True,
            )
            for sol in expand_solutions(extra_solutions)
            if str(sol.path) not in seen_sols
        )

    picked = await questionary.checkbox('Select solutions', choices=choices).ask_async()
    if picked is None:
        raise typer.Abort()
    return picked


def get_outcome_style_verdict(outcome: Outcome) -> str:
    if outcome == Outcome.ACCEPTED:
        return 'green'
    if outcome == Outcome.WRONG_ANSWER:
        return 'red'
    if outcome.is_slow():
        return 'yellow'
    if outcome == Outcome.RUNTIME_ERROR:
        return 'blue'
    if outcome == Outcome.MEMORY_LIMIT_EXCEEDED:
        return 'yellow'
    return 'magenta'


def get_outcome_markup_verdict(outcome: Outcome) -> str:
    res = '✓'
    if outcome != Outcome.ACCEPTED:
        res = '✗'
    if outcome.is_slow():
        res = '⧖'
    if outcome == Outcome.RUNTIME_ERROR:
        res = '✗'
    style = get_outcome_style_verdict(outcome)
    res = f'[{style}]{res}[/{style}]'
    return res


def get_full_outcome_markup_verdict(outcome: Outcome) -> str:
    style = get_outcome_style_verdict(outcome)
    res = f'[{style}]{outcome.name}[/{style}]'
    return res


def get_testcase_markup_verdict(eval: Evaluation) -> str:
    # if eval.log.stdout_absolute_path:
    #     output_path = eval.log.stdout_absolute_path.resolve()
    #     output_link = f'file://{output_path}'
    #     res = f'[link={output_link}]{res}[/link]'
    return get_outcome_markup_verdict(eval.result.outcome)


def get_full_testcase_markup_verdict(eval: Evaluation) -> str:
    return get_full_outcome_markup_verdict(eval.result.outcome)


def _get_evals_time_in_ms(evals: List[Evaluation]) -> int:
    if not evals:
        return 0
    evals_with_ile = [
        eval for eval in evals if eval.result.outcome == Outcome.IDLENESS_LIMIT_EXCEEDED
    ]
    for eval in evals_with_ile:
        # Try every way of estimating a ILE max timelimit.
        if eval.log.metadata is None:
            continue
        if eval.log.metadata.limits is not None:
            expanded_tl = eval.log.metadata.limits.get_expanded_tl()
            if expanded_tl is not None:
                return expanded_tl
        if eval.log.metadata.timeLimit is not None:
            return eval.log.metadata.timeLimit
    return max(int((eval.log.time or 0.0) * 1000) for eval in evals)


def _get_evals_memory_in_bytes(evals: List[Evaluation]) -> int:
    if not evals:
        return 0
    return max(int(eval.log.memory or 0) for eval in evals)


def get_evals_formatted_time(evals: List[Evaluation]) -> str:
    max_time = _get_evals_time_in_ms(evals)
    return get_formatted_time(max_time)


def get_capped_evals_formatted_time(
    solution: Solution, evals: List[Evaluation], verification: VerificationLevel
) -> str:
    pkg = package.find_problem_package_or_die()

    max_time = _get_evals_time_in_ms(evals)
    has_tle = any(eval.result.outcome.is_slow() for eval in evals)
    has_ile = any(
        eval.result.outcome == Outcome.IDLENESS_LIMIT_EXCEEDED for eval in evals
    )
    timelimits = [
        eval.log.metadata.limits.get_expanded_tl()
        for eval in evals
        if eval.log.metadata is not None
    ]
    timelimits = [tl for tl in timelimits if tl is not None]

    tl = None
    if timelimits:
        tl = min(timelimits)
    if tl is None:
        tl = pkg.timelimit_for_language(solution.language)

        if verification.value >= VerificationLevel.FULL.value:
            # Using double TL for verification.
            tl = tl * 2

    if has_tle and max_time >= tl or has_ile:
        return f'>{tl} ms'
    return f'{max_time} ms'


def get_evals_formatted_memory(evals: List[Evaluation]) -> str:
    max_memory = _get_evals_memory_in_bytes(evals)
    return get_formatted_memory(max_memory)


def get_worst_outcome(evals: List[Evaluation]) -> Outcome:
    return Outcome.worst_outcome(eval.result.outcome for eval in evals)


class SolutionOutcomeReport(BaseModel):
    solution: Solution
    evals: List[Evaluation]
    ok: bool
    expectedOutcome: Optional[ExpectedOutcome]
    gotVerdicts: Set[Outcome]
    runUnderDoubleTl: bool
    doubleTlVerdicts: Set[Outcome]
    sanitizerWarnings: bool
    verification: VerificationLevel

    def get_verdict_markup(self, incomplete: bool = False) -> str:
        success_str = '[bold green]OK[/bold green]'
        if not self.ok:
            success_str = '[bold red]FAILED[/bold red]'
        if incomplete:
            success_str = '[bold yellow]INCOMPLETE[/bold yellow]'

        gotVerdicts = self.gotVerdicts if not incomplete else {}

        got_verdict_names = ' '.join(v.name for v in self.gotVerdicts)
        verdict_str = ''
        if self.expectedOutcome is not None:
            verdict_str = f'Expected: {self.expectedOutcome}'
            if gotVerdicts:
                verdict_str += f', got: {got_verdict_names}'
        elif gotVerdicts:
            verdict_str = f'Got: {got_verdict_names}'
        return f'{success_str} {verdict_str}'

    def get_verdict_markup_with_warnings(self) -> str:
        res = self.get_verdict_markup()
        if self.runUnderDoubleTl:
            if self.doubleTlVerdicts:
                res += f'\n[bold yellow]WARNING[/bold yellow] The solution still passed in double TL, but failed with [item]{" ".join(v.name for v in self.doubleTlVerdicts)}[/item].'
            else:
                res += '\n[bold yellow]WARNING[/bold yellow] The solution still passed in double TL.'
        if self.sanitizerWarnings:
            res += '\n[bold yellow]WARNING[/bold yellow] The solution had sanitizer errors or warnings, marked with [bold yellow]*[/bold yellow]. See their stderr for more details.'
        return res

    def get_outcome_markup(self) -> str:
        res = self.get_verdict_markup_with_warnings()
        res += f'\nTime: {get_capped_evals_formatted_time(self.solution, self.evals, self.verification)}'
        res += f'\nMemory: {get_evals_formatted_memory(self.evals)}'
        return res


def get_solution_outcome_report(
    solution: Solution,
    evals: List[Evaluation],
    verification: VerificationLevel = VerificationLevel.NONE,
    subset: bool = False,
) -> SolutionOutcomeReport:
    pkg = package.find_problem_package_or_die()

    has_plain_tle = False
    all_verdicts = set()
    bad_verdicts = set()
    no_tle_bad_verdicts = set()
    has_sanitizer_warnings = False
    for eval in evals:
        all_verdicts.add(eval.result.outcome)
        if eval.result.outcome != Outcome.ACCEPTED:
            bad_verdicts.add(eval.result.outcome)
        if (
            eval.result.no_tle_outcome is not None
            and eval.result.no_tle_outcome != Outcome.ACCEPTED
        ):
            no_tle_bad_verdicts.add(eval.result.no_tle_outcome)
        has_plain_tle = has_plain_tle or (
            eval.result.outcome.is_slow() and eval.result.no_tle_outcome is None
        )
        has_sanitizer_warnings = (
            has_sanitizer_warnings or eval.result.sanitizer_warnings
        )
    unmatched_bad_verdicts = set(
        v for v in bad_verdicts if not solution.outcome.match(v)
    )
    matched_bad_verdicts = bad_verdicts - unmatched_bad_verdicts
    expected_outcome_is_bad = not solution.outcome.match(Outcome.ACCEPTED)

    has_failed = unmatched_bad_verdicts or (
        expected_outcome_is_bad and not matched_bad_verdicts and not subset
    )

    report_expected_outcome = None
    report_got_verdicts = set()
    report_run_under_double_tl = False
    report_double_tl_verdicts = set()
    report_sanitizer_warnings = False
    if has_failed or not subset:
        report_expected_outcome = solution.outcome
    elif subset:
        report_got_verdicts = all_verdicts

    if has_failed or not subset:
        # Only print verdicts if not subset.
        if unmatched_bad_verdicts:
            report_got_verdicts = unmatched_bad_verdicts
        elif expected_outcome_is_bad and not matched_bad_verdicts and not subset:
            report_got_verdicts = {Outcome.ACCEPTED}

    evals_time = _get_evals_time_in_ms(evals)
    expected_outcome_is_tle = solution.outcome.matches_tle_and_is_incorrect()
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
            report_run_under_double_tl = True
        elif not (bad_verdicts - {Outcome.TIME_LIMIT_EXCEEDED}):
            # The solution has other bad soft TLE outcomes.
            report_double_tl_verdicts = other_verdicts

    if has_sanitizer_warnings:
        report_sanitizer_warnings = True

    return SolutionOutcomeReport(
        solution=solution,
        evals=evals,
        ok=not has_failed,
        expectedOutcome=report_expected_outcome,
        gotVerdicts=report_got_verdicts,
        runUnderDoubleTl=report_run_under_double_tl,
        doubleTlVerdicts=report_double_tl_verdicts,
        sanitizerWarnings=report_sanitizer_warnings,
        verification=verification,
    )


def _print_solution_outcome(
    solution: Solution,
    evals: List[Evaluation],
    console: rich.console.Console,
    verification: VerificationLevel = VerificationLevel.NONE,
    subset: bool = False,
) -> bool:
    report = get_solution_outcome_report(solution, evals, verification, subset)
    console.print(report.get_outcome_markup())
    return report.ok


def _consume_and_key_evaluation_items(
    items: Iterable[EvaluationItem],
    skeleton: SolutionReportSkeleton,
) -> StructuredEvaluation:
    """
    Consumes EvaluationItems from a run_solutions call and build a view
    with them, possibly marking with optional unprocessed items.
    """
    res = skeleton.empty_structured_evaluation()

    for item in items:
        res[str(item.solution.path)][item.testcase_entry.group][
            item.testcase_entry.index
        ] = item.eval

    return res


def _print_solution_header(
    solution: SolutionSkeleton,
    console: rich.console.Console,
):
    console.print(f'{href(solution.path)}', end=' ')
    console.print(f'({href(solution.runs_dir, style="info")})')


@dataclasses.dataclass
class SolutionTiming:
    time: int
    solution: Solution


@dataclasses.dataclass
class TimingSummary:
    slowest_good: Optional[SolutionTiming] = None
    fastest_slow: Optional[SolutionTiming] = None

    def add_good(self, time: int, solution: Solution):
        if self.slowest_good is None or time > self.slowest_good.time:
            self.slowest_good = SolutionTiming(time, solution)

    def add_slow(self, time: int, solution: Solution):
        if self.fastest_slow is None or time < self.fastest_slow.time:
            self.fastest_slow = SolutionTiming(time, solution)

    def print(self, console: rich.console.Console, tl: Optional[int] = None):
        if self.slowest_good is not None:
            console.print(
                f'Slowest [success]OK[/success] solution: {self.slowest_good.time} ms, {href(self.slowest_good.solution.path)}'
            )
        if self.fastest_slow is not None:
            fastest_slow = self.fastest_slow.time
            if tl is not None and self.fastest_slow.time > tl:
                fastest_slow = f'>{tl}'
            console.print(
                f'Fastest [error]slow[/error] solution: {fastest_slow} ms, {href(self.fastest_slow.solution.path)}'
            )


async def _print_timing(
    console: rich.console.Console,
    skeleton: SolutionReportSkeleton,
    evaluations: StructuredEvaluation,
    verification: VerificationLevel,
):
    pkg = package.find_problem_package_or_die()
    summary = TimingSummary()
    summary_per_language = collections.defaultdict(TimingSummary)
    tls_per_language = {}
    all_tls = set()
    for solution in skeleton.solutions:
        all_evals: List[Evaluation] = []
        for evals in evaluations[str(solution.path)].values():
            all_evals.extend([await eval() for eval in evals if eval is not None])
        if not all_evals:
            continue

        # Get solution TL.
        solution_time = _get_evals_time_in_ms(all_evals)
        solution_tls = [
            eval.log.metadata.limits.get_expanded_tl()
            for eval in all_evals
            if eval.log.metadata is not None
        ]
        solution_tls = [tl for tl in solution_tls if tl is not None]

        solution_tl = 0
        if solution_tls:
            solution_tl = min(solution_tls)
        else:
            solution_tl = pkg.timelimit_for_language(solution.language)
            if verification.value >= VerificationLevel.FULL.value:
                solution_tl = solution_tl * 2
        all_tls.add(solution_tl)
        for eval in all_evals:
            if eval.log.get_run_language() is not None:
                tls_per_language[eval.log.get_run_language()] = solution_tl

        # Get solution timings.
        if solution.outcome.match(Outcome.ACCEPTED):
            summary.add_good(solution_time, solution)
            summary_per_language[solution.language].add_good(solution_time, solution)
        if solution.outcome.is_slow():
            summary.add_slow(solution_time, solution)
            summary_per_language[solution.language].add_slow(solution_time, solution)

    if summary.slowest_good is None and summary.fastest_slow is None:
        return

    all_languages = set(summary_per_language)
    all_tl = min(all_tls) if all_tls else None
    console.print('[status]Timing summary:[/status]')

    if len(all_languages) <= 1 or len(all_tls) <= 1:
        summary.print(console, tl=all_tl)
        return

    # Otherwise, print per language.
    for lang in sorted(all_languages):
        console.print(f'[status]{lang}[/status]')
        summary_per_language[lang].print(
            console, tl=tls_per_language.get(lang) or all_tl
        )
        console.print()


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
            table.add_column(f'{href(solution.path)}', justify='full')

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
        await _print_timing(
            console, result.skeleton, structured_evaluations, verification=verification
        )
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

    await _print_timing(
        console, result.skeleton, structured_evaluations, verification=verification
    )

    return ok


def _step_up(x: Any, step: int) -> int:
    x = int(x)
    return (x + step - 1) // step * step


def _step_down(x: Any, step: int) -> int:
    x = int(x)
    return x // step * step


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
            for ev in evals:
                if ev is None:
                    continue
                ev = await ev()
                if ev.log.time is not None:
                    timings.append(int(ev.log.time * 1000))

        if not timings:
            console.print(
                f'[warning]No timings for solution {href(solution.path)}.[/warning]'
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

    env = environment.get_environment()
    estimated_tl = int(
        eval(
            env.timing.formula,
            {
                'fastest': fastest_time,
                'slowest': slowest_time,
                'step_up': _step_up,
                'step_down': _step_down,
            },
        )
    )

    console.print(f'Using formula: {env.timing.formula}')
    console.print(f'[success]Estimated time limit:[/success] {estimated_tl} ms')
    return estimated_tl
