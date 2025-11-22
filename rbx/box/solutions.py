from __future__ import generators

import collections
import dataclasses
import pathlib
import shutil
import typing
from collections.abc import Iterator
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

import rich
import rich.live
import rich.markup
import rich.table
import rich.text
import typer
from ordered_set import OrderedSet
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import checkers, code, limits_info, package, remote, state
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
from rbx.box.generation_schema import TestcaseOrScriptEntry
from rbx.box.generators import (
    GenerationMetadata,
    expand_generator_call,
    generate_output_for_testcase,
    generate_standalone,
)
from rbx.box.rendering import CellSlot, Throttling
from rbx.box.sanitizers import issue_stack
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
from rbx.box.testcase_extractors import (
    extract_generation_testcases_from_generic_entries,
)
from rbx.box.testcase_utils import (
    TestcaseEntry,
    TestcaseInteractionParsingError,
    find_built_testcases,
    parse_interaction,
    print_interaction,
)
from rbx.grading import grading_context, steps
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

    def runs_dir_href(self) -> str:
        relpath = self.runs_dir.relative_to(package.find_problem())
        return href(self.runs_dir, str(relpath), style='bright_black')


class SolutionReportSkeleton(BaseModel):
    solutions: List[SolutionSkeleton]
    entries: List[TestcaseEntry]
    groups: List[GroupSkeleton]
    limits: Dict[str, Limits]
    compiled_solutions: Dict[str, str]
    verification: VerificationLevel
    capture_pipes: bool = False

    def get_solution_limits(self, solution: Solution) -> Limits:
        lang = code.find_language_name(solution)
        if lang is None:
            return limits_info.get_package_limits(self.verification)
        return self.limits[lang]

    def get_solution_limits_from_disk(self, solution: Solution) -> Limits:
        lang = code.find_language_name(solution)
        return limits_info.get_limits(
            language=lang,
            profile=self.get_solution_limits(solution).profile,
            verification=self.verification,
        )

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

    def get_solution_compiled_digest(self, solution: Solution) -> str:
        return self.compiled_solutions[str(solution.path)]

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


class FailedSolutionIssue(issue_stack.Issue):
    def __init__(self, solution: Solution):
        self.solution = solution

    def get_detailed_section(self) -> Tuple[str, ...]:
        return ('solutions',)

    def get_detailed_message(self) -> str:
        return f'{self.solution.href()} has an unexpected outcome.'


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


class FailedToCompileSolutionIssue(issue_stack.Issue):
    def __init__(self, solution: Solution):
        self.solution = solution

    def get_detailed_section(self) -> Tuple[str, ...]:
        return ('solutions',)

    def get_detailed_message(self) -> str:
        return f'{self.solution.href()} could not be compiled and was skipped.'


def compile_solutions(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Set[str]] = None,
    sanitized: bool = False,
    fail_if_one: bool = True,
    skip_if_fail: bool = False,
) -> Dict[pathlib.Path, str]:
    compiled_solutions = {}

    if tracked_solutions is None:
        tracked_solutions = set(str(sol.path) for sol in package.get_solutions())

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
        except steps.CompilationError:
            if fail_if_one and len(tracked_solutions) <= 1:
                raise
            if not skip_if_fail:
                raise
            issue_stack.add_issue(FailedToCompileSolutionIssue(solution))
        except:
            console.console.print(
                f'[error]Failed compiling solution {solution.href()}.[/error]'
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
    nruns: int = 0,
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
                nruns=nruns,
            )

        res.append(Deferred(run_fn))

    return res


async def convert_list_of_solution_evaluations_to_dict(
    skeleton: SolutionReportSkeleton,
    items: Iterable[EvaluationItem],
) -> List[Dict[str, List[Evaluation]]]:
    res: List[Dict[str, List[Evaluation]]] = [
        collections.defaultdict(list) for _ in package.get_solutions()
    ]

    for item in items:
        sol_idx = skeleton.find_solution_skeleton_index(item.solution)
        if sol_idx is not None:
            to_append = await item.eval()
            res[sol_idx][item.testcase_entry.group].append(to_append)

    return res


def _get_solutions_for_skeleton(
    tracked_solutions: Optional[Iterable[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> List[Solution]:
    solutions = [
        sol
        for sol in package.get_solutions()
        if verification.value >= VerificationLevel.ALL_SOLUTIONS.value or is_fast(sol)
    ]
    if tracked_solutions is not None:
        solutions = expand_solutions(list(tracked_solutions))
    return solutions


def _get_compiled_solutions_for_skeleton(
    tracked_solutions: Optional[Iterable[str]] = None,
    progress: Optional[StatusProgress] = None,
    sanitized: bool = False,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> Tuple[List[Solution], Dict[str, str]]:
    solutions_to_compile = _get_solutions_for_skeleton(tracked_solutions, verification)

    compiled_solutions = compile_solutions(
        progress=progress,
        tracked_solutions=set(str(solution.path) for solution in solutions_to_compile),
        sanitized=sanitized,
        skip_if_fail=True,
    )

    # TODO: Handle solutions that failed to compile.
    solutions = [
        solution
        for solution in solutions_to_compile
        if solution.path in compiled_solutions
    ]

    return solutions, {
        str(solution_path): digest
        for solution_path, digest in compiled_solutions.items()
    }


def _get_report_skeleton(
    tracked_solutions: Optional[Iterable[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    timelimit_override: Optional[int] = None,
    progress: Optional[StatusProgress] = None,
    sanitized: bool = False,
) -> SolutionReportSkeleton:
    pkg = package.find_problem_package_or_die()

    solutions, compiled_solutions = _get_compiled_solutions_for_skeleton(
        tracked_solutions=tracked_solutions,
        verification=verification,
        progress=progress,
        sanitized=sanitized,
    )

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
        compiled_solutions=compiled_solutions,
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
    nruns: int = 0,
) -> List[EvaluationItem]:
    pkg = package.find_problem_package_or_die()

    if pkg.type == TaskType.COMMUNICATION:
        checker_digest = (
            checkers.compile_checker()
            if check and package.get_checker_or_nil() is not None
            else None
        )
        interactor_digest = checkers.compile_interactor()
    else:
        checker_digest = checkers.compile_checker() if check else None
        interactor_digest = None

    def yield_items(
        solution: SolutionSkeleton, group_name: str
    ) -> List[EvaluationItem]:
        res: List[EvaluationItem] = []
        for i, eval in enumerate(
            _run_solution(
                solution,
                skeleton.get_solution_compiled_digest(solution),
                checker_digest,
                solution.runs_dir,
                group_name,
                interactor_digest=interactor_digest,
                progress=progress,
                verification=verification,
                timelimit_override=timelimit_override,
                nruns=nruns,
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
            try:
                print_interaction(parse_interaction(output_file))
            except TestcaseInteractionParsingError:
                # Ignore parsing errors and proceed to next file.
                continue
        else:
            console.console.print(output_file.read_text())
        return
    if empty_warning:
        console.console.print('[warning]Solution produced no output.[/warning]')


def run_solutions(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Iterable[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    timelimit_override: Optional[int] = None,
    sanitized: bool = False,
    nruns: int = 0,
) -> RunSolutionResult:
    skeleton = _get_report_skeleton(
        progress=progress,
        tracked_solutions=tracked_solutions,
        verification=verification,
        timelimit_override=timelimit_override,
        sanitized=sanitized,
    )
    result = RunSolutionResult(
        skeleton=skeleton,
        items=_produce_solution_items(
            skeleton=skeleton,
            progress=progress,
            verification=verification,
            check=check,
            timelimit_override=timelimit_override,
            nruns=nruns,
        ),
    )
    return result


async def _generate_testcase_interactively(
    progress: Optional[StatusProgress] = None,
    generator: Optional[GeneratorCall] = None,
    testcase_entry: Optional[TestcaseOrScriptEntry] = None,
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
        extracted = await extract_generation_testcases_from_generic_entries(
            [testcase_entry]
        )
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
                f'Input was written to {href(package.relpath(testcase.inputPath))}'
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
        if main_solution is not None:
            await generate_output_for_testcase(
                main_solution,
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
) -> Iterator[EvaluationItem]:
    pkg = package.find_problem_package_or_die()

    if pkg.type == TaskType.COMMUNICATION:
        checker_digest = checkers.compile_checker() if check else None
        interactor_digest = checkers.compile_interactor()
    else:
        checker_digest = checkers.compile_checker() if check else None
        interactor_digest = None

    if progress:
        progress.update('Running solutions...')

    for solution in skeleton.solutions:
        output_dir = solution.runs_dir

        async def run_fn(solution=solution, output_dir=output_dir):
            return await run_solution_on_testcase(
                solution,
                skeleton.get_solution_compiled_digest(solution),
                checker_digest,
                testcase,
                output_dir=output_dir,
                interactor_digest=interactor_digest,
                verification=verification,
                capture_pipes=True,
            )

        yield EvaluationItem(
            solution=solution,
            testcase_entry=TestcaseEntry.make_interactive(),
            eval=Deferred(run_fn),
        )


def _get_interactive_skeleton(
    tracked_solutions: Optional[Iterable[str]] = None,
    progress: Optional[StatusProgress] = None,
    sanitized: bool = False,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> SolutionReportSkeleton:
    solutions, compiled_solutions = _get_compiled_solutions_for_skeleton(
        tracked_solutions,
        verification=verification,
        progress=progress,
        sanitized=sanitized,
    )

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
        # Entry does not correspond to a real test.
        # TODO: RECONSIDER THIS
        entries=[TestcaseEntry.make_interactive()],
        verification=verification,
        compiled_solutions=compiled_solutions,
        capture_pipes=True,
    )

    skeleton_file = irun_dir / 'skeleton.yml'
    skeleton_file.write_text(utils.model_to_yaml(skeleton))

    return skeleton


async def run_and_print_interactive_solutions(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Iterable[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    generator: Optional[GeneratorCall] = None,
    testcase_entry: Optional[TestcaseOrScriptEntry] = None,
    check: bool = True,
    custom_output: bool = False,
    print: bool = False,
    sanitized: bool = False,
):
    pkg = package.find_problem_package_or_die()
    skeleton = _get_interactive_skeleton(
        tracked_solutions=tracked_solutions,
        verification=verification,
        sanitized=sanitized,
        progress=progress,
    )

    should_cache = testcase_entry is not None
    with grading_context.cache_level(
        grading_context.CacheLevel.CACHE_COMPILATION, when=not should_cache
    ):
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
        )

    for item in items:
        sol = skeleton.find_solution_skeleton(item.solution)
        assert sol is not None

        if progress:
            progress.update(f'Running [item]{sol.path}[/item]...')

        eval = await item.eval()

        with utils.no_progress(progress):
            _print_solution_header(sol, console.console)
            _print_solution_outcome(
                sol, skeleton, [eval], console.console, verification, subset=True
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
                console.console.print(
                    f'[status]Output:[/status] {href(package.relpath(stdout_path))}'
                )
            if stdout_path.with_suffix('.pio').is_file():
                console.console.print(
                    f'[status]Interaction:[/status] {href(package.relpath(stdout_path.with_suffix(".pio")))}'
                )
            if eval.log.stderr_absolute_path is not None:
                console.console.print(
                    f'[status]Stderr:[/status] {href(package.relpath(eval.log.stderr_absolute_path))}'
                )
            console.console.print()


def _get_solution_repr(sol: Solution) -> List[Tuple[str, str]]:
    fg_color = sol.outcome.style()
    return [
        ('', f'{str(sol.path)} '),
        (f'fg:{fg_color}', sol.outcome.name),
    ]


def expand_solutions_with_source(sols: List[str]) -> List[Tuple[Solution, bool]]:
    pkg_sols = {str(sol.path): sol for sol in package.get_solutions()}

    # Download remote sols.
    path_sols = remote.expand_files(sols)

    # Ensure sols exist.
    for sol in path_sols:
        if not sol.is_file():
            console.console.print(
                f'[error]Solution [item]{sol}[/item] could not be found.[/error]'
            )
            raise typer.Exit(1)

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
    tracked_solutions: Optional[OrderedSet[str]],
    extra_solutions: Optional[List[str]] = None,
) -> List[str]:
    # Store in a separate list to maintain order with the package declaration.
    import questionary

    solutions = package.get_solutions()

    choices = [
        questionary.Choice(
            title=_get_solution_repr(sol),
            value=str(sol.path),
            checked=tracked_solutions is None or str(sol.path) in tracked_solutions,
        )
        for sol in solutions
    ]

    seen_sols = set(str(sol.path) for sol in solutions)

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
    if outcome == Outcome.COMPILATION_ERROR:
        return 'blue'
    return 'magenta'


def get_ui_friendly_outcome_style_verdict(outcome: Outcome) -> str:
    style = get_outcome_style_verdict(outcome)
    if style == 'magenta':
        return 'white on magenta'
    return style


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


def get_full_outcome_markup_verdict(outcome: Outcome, styled: bool = True) -> str:
    icon = get_outcome_markup_verdict(outcome)
    name = outcome.name
    if styled:
        style = get_outcome_style_verdict(outcome)
        name = f'[{style}]{name}[/{style}]'
    return f'{icon} {name}'


def get_full_ui_friendly_outcome_markup_verdict(
    outcome: Outcome, styled: bool = True
) -> str:
    icon = get_outcome_markup_verdict(outcome)
    name = outcome.name
    if styled:
        style = get_ui_friendly_outcome_style_verdict(outcome)
        name = f'[{style}]{name}[/{style}]'
    return f'{icon} {name}'


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
    limits: Limits,
    evals: List[Evaluation],
    verification: VerificationLevel,
) -> str:
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
        tl = limits.time

        if tl is not None and verification.value >= VerificationLevel.FULL.value:
            # Using double TL for verification.
            tl = tl * 2

    if tl is not None and has_tle and max_time >= tl or has_ile:
        return f'>{tl} ms'
    return f'{max_time} ms'


def get_evals_formatted_memory(evals: List[Evaluation]) -> str:
    max_memory = _get_evals_memory_in_bytes(evals)
    return get_formatted_memory(max_memory)


def get_worst_outcome(evals: List[Evaluation]) -> Outcome:
    return Outcome.worst_outcome(eval.result.outcome for eval in evals)


def get_truncated_message(message: str, max_length: int = 100) -> str:
    if len(message) > max_length:
        return message[:max_length] + '... (truncated)'
    return message


class SolutionOutcomeReport(BaseModel):
    solution: Solution
    limits: Limits
    evals: List[Evaluation]
    ok: bool
    message: Optional[Tuple[TestcaseEntry, str]]
    expectedOutcome: Optional[ExpectedOutcome]
    gotVerdicts: Set[Outcome]
    runUnderDoubleTl: bool
    doubleTlVerdicts: Set[Outcome]
    sanitizerWarnings: bool
    verification: VerificationLevel

    def get_verdict_markup(self, incomplete: bool = False, subset: bool = False) -> str:
        success_str = '[bold green]OK[/] '
        if subset:
            success_str = ''
        if not self.ok:
            success_str = '[bold white on red]FAILED[/] '
        if incomplete:
            success_str = '[bold white on yellow]INCOMPLETE[/] '

        gotVerdicts = self.gotVerdicts if not incomplete else {}

        got_verdict_names = ' '.join(v.name for v in self.gotVerdicts)
        verdict_str = ''
        if self.expectedOutcome is not None:
            verdict_str = f'Expected: {self.expectedOutcome}'
            if gotVerdicts:
                verdict_str += f', got: {got_verdict_names}'
        elif gotVerdicts:
            verdict_str = f'Got: {got_verdict_names}'
        return f'{success_str}{verdict_str}'

    def get_verdict_markup_with_warnings(self, subset: bool = False) -> str:
        res = self.get_verdict_markup(subset=subset)
        if self.runUnderDoubleTl:
            if self.doubleTlVerdicts:
                res += f'\n[bold yellow]WARNING[/bold yellow] The solution still passed in double TL, but failed with [item]{" ".join(v.name for v in self.doubleTlVerdicts)}[/item].'
            else:
                res += '\n[bold yellow]WARNING[/bold yellow] The solution still passed in double TL.'
        if self.sanitizerWarnings:
            res += '\n[bold yellow]WARNING[/bold yellow] The solution had sanitizer errors or warnings, marked with [bold yellow]*[/bold yellow]. See their stderr for more details.'
        return res

    def get_outcome_markup(
        self, subset: bool = False, print_message: bool = True
    ) -> str:
        res = self.get_verdict_markup_with_warnings(subset=subset)
        res += f'\nTime: {get_capped_evals_formatted_time(self.limits, self.evals, self.verification)}'
        res += f'\nMemory: {get_evals_formatted_memory(self.evals)}'
        if print_message and self.message is not None:
            tc, msg = self.message
            if msg:
                msg = get_truncated_message(msg)
                res += f'\nMessage for {utils.escape_markup(str(tc))}: {utils.escape_markup(msg)}'
        return res


def get_solution_outcome_report(
    solution: Solution,
    skeleton: SolutionReportSkeleton,
    evals: List[Evaluation],
    verification: VerificationLevel = VerificationLevel.NONE,
    subset: bool = False,
) -> SolutionOutcomeReport:
    has_plain_tle = False
    all_verdicts = set()
    bad_verdicts = set()
    no_tle_bad_verdicts = set()
    has_sanitizer_warnings = False
    message: Optional[Tuple[TestcaseEntry, str]] = None
    for eval, entry in zip(evals, skeleton.entries):
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
        if (
            eval.result.outcome
            in [
                Outcome.WRONG_ANSWER,
                Outcome.JUDGE_FAILED,
            ]
            and message is None
        ):
            message = (entry, eval.result.message)

    unmatched_bad_verdicts = set(
        v for v in bad_verdicts if not solution.outcome.match(v)
    )
    matched_bad_verdicts = bad_verdicts - unmatched_bad_verdicts
    expected_outcome_is_bad = not solution.outcome.match(Outcome.ACCEPTED)

    has_failed = unmatched_bad_verdicts or (
        expected_outcome_is_bad and not matched_bad_verdicts and not subset
    )

    report_expected_outcome = solution.outcome
    report_got_verdicts = set()
    report_run_under_double_tl = False
    report_double_tl_verdicts = set()
    report_sanitizer_warnings = False
    if subset and not has_failed:
        report_got_verdicts = all_verdicts

    if has_failed:
        if unmatched_bad_verdicts:
            report_got_verdicts = unmatched_bad_verdicts
        elif expected_outcome_is_bad and not matched_bad_verdicts and not subset:
            report_got_verdicts = {Outcome.ACCEPTED}

    evals_time = _get_evals_time_in_ms(evals)
    expected_outcome_is_tle = solution.outcome.matches_tle_and_is_incorrect()
    limits = skeleton.get_solution_limits(solution)
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
        and limits.time is not None
        and evals_time < limits.time * 2
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
        limits=skeleton.get_solution_limits(solution),
        evals=evals,
        ok=not has_failed,
        message=message,
        expectedOutcome=report_expected_outcome,
        gotVerdicts=report_got_verdicts,
        runUnderDoubleTl=report_run_under_double_tl,
        doubleTlVerdicts=report_double_tl_verdicts,
        sanitizerWarnings=report_sanitizer_warnings,
        verification=verification,
    )


def _print_solution_outcome(
    solution: Solution,
    skeleton: SolutionReportSkeleton,
    evals: List[Evaluation],
    console: rich.console.Console,
    verification: VerificationLevel = VerificationLevel.NONE,
    subset: bool = False,
    print_message: bool = True,
) -> bool:
    report = get_solution_outcome_report(
        solution, skeleton, evals, verification, subset
    )
    if not report.ok:
        issue_stack.add_issue(FailedSolutionIssue(solution))
    console.print(report.get_outcome_markup(subset=subset, print_message=print_message))
    return report.ok


def consume_and_key_evaluation_items(
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
    console.print(solution.href(), end=' ')
    console.print(f'({solution.runs_dir_href()})')


@dataclasses.dataclass
class SolutionTiming:
    time: int
    solution: Solution


@dataclasses.dataclass
class TimingSummary:
    slowest_good: Optional[SolutionTiming] = None
    slowest_pass: Optional[SolutionTiming] = None
    fastest_slow: Optional[SolutionTiming] = None

    def add_good(self, time: int, solution: Solution):
        if self.slowest_good is None or time > self.slowest_good.time:
            self.slowest_good = SolutionTiming(time, solution)

    def add_slow(self, time: int, solution: Solution):
        if self.fastest_slow is None or time < self.fastest_slow.time:
            self.fastest_slow = SolutionTiming(time, solution)

    def add_pass(self, time: int, solution: Solution):
        if self.slowest_pass is None or time > self.slowest_pass.time:
            self.slowest_pass = SolutionTiming(time, solution)

    def has_timings(self) -> bool:
        return (
            self.slowest_good is not None
            or self.slowest_pass is not None
            or self.fastest_slow is not None
        )

    def print(
        self,
        console: rich.console.Console,
        tl: Optional[int] = None,
        expanded_tl: Optional[int] = None,
    ):
        if tl is not None:
            console.print(
                f'Time limit: [hilite]{get_formatted_time(tl)}[/hilite]', end=''
            )
            if expanded_tl is not None and expanded_tl != tl:
                console.print(
                    f' (actual: [hilite]{get_formatted_time(expanded_tl)}[/hilite])',
                    end='',
                )
            console.print()
        if self.slowest_good is not None:
            console.print(
                f'Slowest [success]AC[/success] solution: {get_formatted_time(self.slowest_good.time)}, {self.slowest_good.solution.href()}'
            )
        if self.slowest_pass is not None:
            console.print(
                f'Slowest [success][not bold]AC or TLE[/][/success] solution: {get_formatted_time(self.slowest_pass.time)}, {self.slowest_pass.solution.href()}'
            )
        if self.fastest_slow is not None:
            fastest_slow = get_formatted_time(self.fastest_slow.time)
            if expanded_tl is not None and self.fastest_slow.time >= expanded_tl:
                fastest_slow = f'>{get_formatted_time(expanded_tl)}'
            slow_style = ExpectedOutcome.TIME_LIMIT_EXCEEDED.style()
            console.print(
                f'Fastest [{slow_style}]slow[/] solution: {fastest_slow}, {self.fastest_slow.solution.href()}'
            )


async def _print_timing(
    console: rich.console.Console,
    skeleton: SolutionReportSkeleton,
    evaluations: StructuredEvaluation,
):
    summary = TimingSummary()
    summary_per_language = collections.defaultdict(TimingSummary)
    tls_per_language = {}
    expanded_tls_per_language = {}
    all_tls = set()
    all_expanded_tls = set()
    for solution in skeleton.solutions:
        all_evals: List[Evaluation] = []
        for evals in evaluations[str(solution.path)].values():
            all_evals.extend([await eval() for eval in evals if eval is not None])
        if not all_evals:
            continue

        # Get solution TL.
        solution_time = _get_evals_time_in_ms(all_evals)
        tls = [
            eval.log.metadata.limits.time
            for eval in all_evals
            if eval.log.metadata is not None
            and eval.log.metadata.limits is not None
            and eval.log.metadata.limits.time is not None
        ]
        expanded_tls = [
            eval.log.metadata.limits.get_expanded_tl()
            for eval in all_evals
            if eval.log.metadata is not None
        ]
        expanded_tls = [tl for tl in expanded_tls if tl is not None]

        tl = 0
        expanded_tl = 0
        if expanded_tls:
            tl = min(tls)
            expanded_tl = min(expanded_tls)
        else:
            limits = skeleton.get_solution_limits(solution)
            if limits.time is None:
                limits = skeleton.get_solution_limits_from_disk(solution)
            assert limits.time is not None
            tl = limits.time
            expanded_tl = limits.time
            if limits.isDoubleTL:
                expanded_tl = expanded_tl * 2
        all_tls.add(tl)
        all_expanded_tls.add(expanded_tl)
        for eval in all_evals:
            eval_language = eval.log.get_run_language()
            if eval_language is not None:
                tls_per_language[eval_language] = tl
                expanded_tls_per_language[eval_language] = expanded_tl

        language = find_language_name(solution)
        # Get solution timings.
        if solution.outcome == ExpectedOutcome.ACCEPTED:
            summary.add_good(solution_time, solution)
            summary_per_language[language].add_good(solution_time, solution)
        if solution.outcome in [
            ExpectedOutcome.ACCEPTED,
            ExpectedOutcome.ACCEPTED_OR_TLE,
        ]:
            summary.add_pass(solution_time, solution)
            summary_per_language[language].add_pass(solution_time, solution)
        if solution.outcome.is_slow():
            summary.add_slow(solution_time, solution)
            summary_per_language[language].add_slow(solution_time, solution)

    if not summary.has_timings():
        return

    all_languages = set(summary_per_language)
    all_tl = min(all_tls) if all_tls else None
    all_expanded_tl = min(all_expanded_tls) if all_expanded_tls else None
    console.print('[bold][status]Timing summary:[/status][/bold]')

    if len(all_languages) <= 1 or (len(all_tls) <= 1 and len(all_expanded_tls) <= 1):
        summary.print(console, tl=all_tl, expanded_tl=all_expanded_tl)
        return

    # Otherwise, print per language.
    # TODO: reconsider having the concept of a global language time limit.
    for eval_language in sorted(all_languages):
        cur_tl = tls_per_language.get(eval_language) or all_tl
        cur_expanded_tl = (
            expanded_tls_per_language.get(eval_language) or all_expanded_tl
        )
        console.print(f'[status]{eval_language}[/status]')
        summary_per_language[eval_language].print(
            console,
            tl=cur_tl,
            expanded_tl=cur_expanded_tl,
        )


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


def _render_padded_column(column: List[Tuple[str, ...]]) -> List[rich.text.Text]:
    max_widths_per_column = _max_pointwise(_length_pointwise(cell) for cell in column)
    return [
        rich.text.Text(' ').join(
            _get_indented_text(item, width)
            for item, width in zip(cell, max_widths_per_column, strict=True)
        )
        for cell in column
    ]


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

    limits_per_solution = {
        str(solution.path): skeleton.get_solution_limits(solution)
        for solution in skeleton.solutions
    }
    structured_renderables: Dict[str, List[CellSlot]] = collections.defaultdict(list)
    structured_cells: Dict[str, List[Tuple[str, ...]]] = collections.defaultdict(list)

    async def generate_initial_table() -> rich.table.Table:
        table = rich.table.Table()
        for solution in skeleton.solutions:
            table.add_column(f'{solution.href()}', justify='full', no_wrap=True)

        padded_rows: List[List[Tuple[str, ...]]] = []

        for tc, _ in enumerate(group_skeleton.testcases):
            row: List[Tuple[str, ...]] = []
            for solution in skeleton.solutions:
                entry = (f'[info]#{tc}[/info]', '', '...', '', '', '')
                structured_cells[str(solution.path)].append(entry)
                row.append(entry)
            padded_rows.append(row)

        if padded_rows:
            summary_row: List[Tuple[str, ...]] = []
            for solution in skeleton.solutions:
                entry = ('', '', '...', '', '', '')
                structured_cells[str(solution.path)].append(entry)
                summary_row.append(entry)
            padded_rows.append(summary_row)

        for padded_row in _render_padded_rows(padded_rows):
            padded_slots = []
            for cell, solution in zip(
                padded_row,
                skeleton.solutions,
                strict=True,
            ):
                slot = CellSlot(cell)
                structured_renderables[str(solution.path)].append(slot)
                padded_slots.append(slot)
            table.add_row(*padded_slots)

        if padded_rows:
            table.rows[-2].end_section = True
        return table

    async def update_table(
        structured_evaluations: StructuredEvaluation,
        group_name: str,
        solution: SolutionSkeleton,
        tc: int,
    ):
        cells = structured_cells[str(solution.path)]
        renderables = structured_renderables[str(solution.path)]
        eval = structured_evaluations[str(solution.path)][group_name][tc]
        if eval is None or eval.peek() is None:
            cells[tc] = (f'[info]#{tc}[/info]', '', '...', '', '', '')
        else:
            eval = eval.peek()
            assert eval is not None
            verdict = get_testcase_markup_verdict(eval)
            limits = limits_per_solution[str(solution.path)]
            time = get_capped_evals_formatted_time(limits, [eval], verification)
            memory = get_evals_formatted_memory([eval])
            full_item = (f'[info]#{tc}[/info]', verdict, time, '/', memory, '')
            if eval.result.sanitizer_warnings:
                full_item = (*full_item[:-1], '[warning]*[/warning]')
            cells[tc] = full_item

        evals = structured_evaluations[str(solution.path)][group.name]
        non_null_evals = typing.cast(
            List[Evaluation],
            [
                eval.peek()
                for eval in evals
                if eval is not None and eval.peek() is not None
            ],
        )
        if non_null_evals:
            limits = limits_per_solution[str(solution.path)]
            formatted_time = get_capped_evals_formatted_time(
                limits, non_null_evals, verification
            )
            formatted_memory = get_evals_formatted_memory(non_null_evals)
            worst_outcome = get_worst_outcome(non_null_evals)
            verdict = get_outcome_markup_verdict(worst_outcome)
            cells[-1] = ('', verdict, formatted_time, '/', formatted_memory, '')

        for i, padded_column in enumerate(_render_padded_column(cells)):
            renderables[i].update(padded_column)

    with rich.live.Live(
        await generate_initial_table(),
        auto_refresh=False,
        console=console,
    ) as live:
        throttled_update = Throttling(live.refresh, 0.3)
        for solution in skeleton.solutions:
            for tc, _ in enumerate(group_skeleton.testcases):
                eval = structured_evaluations[str(solution.path)][group.name][tc]
                if eval is None:
                    continue
                await eval()
                await update_table(structured_evaluations, group.name, solution, tc)
                throttled_update()


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
            result.skeleton,
            all_evals,
            console,
            verification=verification,
        )
        ok = ok and cur_ok
        console.print()

    console.print()

    if timing:
        await _print_timing(
            console,
            result.skeleton,
            structured_evaluations,
        )
    return ok


def _print_limits(limits: Dict[str, Limits]):
    console.console.print(
        '[bold][success]Running with the following limits (per language):[/success][/bold]'
    )
    for lang, limit in limits.items():
        extracted_from = ' (extracted from package)'
        if limit.profile:
            extracted_from = f' (extracted from profile [item]{limit.profile}[/item])'
        console.console.print(f'[bold][status]{lang}[/status][/bold]{extracted_from}')
        time = (
            '<No time limit>' if limit.time is None else get_formatted_time(limit.time)
        )
        memory = (
            '<No memory limit>'
            if limit.memory is None
            else get_formatted_memory(limit.memory * 1024 * 1024)
        )
        console.console.print(f'[status]Time: [hilite]{time}[/hilite][/status]')
        console.console.print(f'[status]Memory: [hilite]{memory}[/hilite][/status]')
        if limit.isDoubleTL:
            console.console.print('[warning]Running with 2*TL[/warning]')
    console.console.print()


class TraditionalRunReporter:
    def __init__(
        self,
        result: RunSolutionResult,
        verification: VerificationLevel,
        console: rich.console.Console,
    ):
        self.result = result
        self.console = console
        self.verification = verification
        self.structured_evaluations = consume_and_key_evaluation_items(
            result.items, result.skeleton
        )
        self.limits_per_solution = {
            str(solution.path): result.skeleton.get_solution_limits(solution)
            for solution in result.skeleton.solutions
        }
        self.current_solution = None
        self.current_group = None
        self.current_index = None
        self.current_solution_evals: List[Evaluation] = []
        self.current_group_evals: List[Evaluation] = []
        self.current_group_evals_per_index: Dict[int, Evaluation] = {}

    def get_limits(self, solution: Solution) -> Limits:
        return self.limits_per_solution[str(solution.path)]

    def get_current_limits(self) -> Limits:
        if self.current_solution is None:
            raise ValueError('No current solution')
        return self.get_limits(self.current_solution)

    def get_evaluation(
        self, solution: Solution, group: Union[GroupSkeleton, TestcaseGroup], index: int
    ) -> Optional[Deferred[Evaluation]]:
        return self.structured_evaluations[str(solution.path)][group.name][index]

    def get_current_evaluation(self) -> Optional[Deferred[Evaluation]]:
        if (
            self.current_solution is None
            or self.current_group is None
            or self.current_index is None
        ):
            return None
        return self.get_evaluation(
            self.current_solution, self.current_group, self.current_index
        )

    def start_solution(self, solution: Solution):
        self.current_solution = solution
        self.render_solution(solution)

    def render_solution(self, solution: Solution):
        pass

    def finish_solution(self) -> bool:
        assert self.current_solution is not None
        ok = self.render_solution_end(self.current_solution)
        self.current_solution = None
        self.current_solution_evals = []
        return ok

    def render_solution_end(self, solution: Solution) -> bool:
        return True

    def start_group(self, group: GroupSkeleton):
        self.current_group = group
        self.render_group(group)

    def render_group(self, group: GroupSkeleton):
        pass

    def finish_group(self):
        assert self.current_group is not None
        self.render_group_end(self.current_group)
        self.current_group = None
        self.current_group_evals = []
        self.current_group_evals_per_index = {}

    def render_group_end(self, group: GroupSkeleton):
        pass

    def start_testcase(self, index: int):
        self.current_index = index
        self.render_pre_evaluation(index)

    def render_pre_evaluation(self, index: int):
        pass

    def finish_testcase(self, evaluation: Optional[Evaluation]):
        assert self.current_index is not None
        if evaluation is not None:
            self.current_group_evals.append(evaluation)
            self.current_solution_evals.append(evaluation)
            self.current_group_evals_per_index[self.current_index] = evaluation
            self.render_post_evaluation(self.current_index, evaluation)
        self.current_index = None

    def render_post_evaluation(self, index: int, evaluation: Optional[Evaluation]):
        pass


class FullRunReporter(TraditionalRunReporter):
    def render_solution(self, solution: Solution):
        solution_skeleton = self.result.skeleton.find_solution_skeleton(solution)
        assert solution_skeleton is not None
        _print_solution_header(
            solution_skeleton,
            self.console,
        )

    def render_solution_end(self, solution: Solution) -> bool:
        ok = _print_solution_outcome(
            solution,
            self.result.skeleton,
            self.current_solution_evals,
            self.console,
            verification=self.verification,
            print_message=True,
        )
        self.console.print()
        return ok

    def render_group(self, group: GroupSkeleton):
        self.console.print(
            f'[bold][status]{group.name} ({len(group.testcases)})[/status][/bold]',
            end='',
        )

    def render_group_end(self, group: GroupSkeleton):
        self.console.print(
            f'[info]({get_capped_evals_formatted_time(self.get_current_limits(), self.current_group_evals, self.verification)}, {get_evals_formatted_memory(self.current_group_evals)})[/info]',
        )

    def render_pre_evaluation(self, index: int):
        self.console.print(f'[info]{index}/[/info]', end='')

    def render_post_evaluation(self, index: int, evaluation: Optional[Evaluation]):
        if evaluation is None:
            self.console.print('x ', end='')
            return
        self.console.print(get_testcase_markup_verdict(evaluation), end='')
        if evaluation.result.sanitizer_warnings:
            self.console.print('[warning]*[/warning]', end='')
        self.console.print(' ', end='')


class LiveRunReporter(FullRunReporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.live: Optional[rich.live.Live] = None
        self.pre_evaluated = 0
        self.post_evaluated = 0

    def _update_live(self):
        if self.live is None:
            return
        assert self.current_group is not None
        renderable = rich.text.Text.from_markup(
            f'[bold bright_white]{self.current_group.name} ({len(self.current_group.testcases)})[/bold bright_white] '
        )
        for i in range(self.pre_evaluated):
            if i >= self.post_evaluated:
                # Was not evaluated yet.
                renderable.append(
                    rich.text.Text(f'{i}/.. ', style='bright_black', end='')
                )
                continue
            if i not in self.current_group_evals_per_index:
                continue
            eval = self.current_group_evals_per_index[i]
            if (
                eval.result.outcome == Outcome.ACCEPTED
                and not eval.result.sanitizer_warnings
            ):
                # Skip accepted verdicts with no warnings.
                continue
            renderable.append(rich.text.Text(f'{i}/', style='bright_black', end=''))
            renderable.append(
                rich.text.Text.from_markup(get_testcase_markup_verdict(eval), end='')
            )
            if eval.result.sanitizer_warnings:
                renderable.append(
                    rich.text.Text.from_markup('[warning]*[/warning]', end='')
                )
            renderable.append(rich.text.Text(' ', end=''))

        renderable.append(
            rich.text.Text.from_markup(
                f'({get_capped_evals_formatted_time(self.get_current_limits(), self.current_group_evals, self.verification)}, {get_evals_formatted_memory(self.current_group_evals)})',
                style='bright_black',
                end='',
            )
        )
        self.live.update(renderable, refresh=True)

    def render_group(self, group: GroupSkeleton):
        self.pre_evaluated = 0
        self.post_evaluated = 0
        self.live = rich.live.Live(console=self.console, auto_refresh=False)
        self.live.start()
        self._update_live()

    def render_group_end(self, group: GroupSkeleton):
        assert self.live is not None
        self.live.stop()
        self.live = None

    def render_pre_evaluation(self, index: int):
        self.pre_evaluated = index + 1
        self._update_live()

    def render_post_evaluation(self, index: int, evaluation: Optional[Evaluation]):
        self.post_evaluated = index + 1
        self._update_live()


class SingleSolutionRunReporter(TraditionalRunReporter):
    def render_solution(self, solution: Solution):
        solution_skeleton = self.result.skeleton.find_solution_skeleton(solution)
        assert solution_skeleton is not None
        _print_solution_header(solution_skeleton, self.console)
        self.console.print()

    def render_solution_end(self, solution: Solution) -> bool:
        ok = _print_solution_outcome(
            solution,
            self.result.skeleton,
            self.current_solution_evals,
            self.console,
            verification=self.verification,
            print_message=False,
        )
        self.console.print()
        return ok

    def render_group_end(self, group: GroupSkeleton):
        self.console.print(f'  [status]{group.name}[/status]', end=' ')
        self.console.print(
            f'({get_capped_evals_formatted_time(self.get_current_limits(), self.current_group_evals, self.verification)}, {get_evals_formatted_memory(self.current_group_evals)})',
        )
        self.console.print()

    def render_post_evaluation(self, index: int, evaluation: Optional[Evaluation]):
        if evaluation is None:
            return
        assert self.current_group is not None
        self.console.print(get_testcase_markup_verdict(evaluation), end=' ')
        self.console.print(f'{self.current_group.name}/{index}', end='')
        if evaluation.result.sanitizer_warnings:
            self.console.print('[warning]*[/warning]', end='')
        time = get_capped_evals_formatted_time(
            self.get_current_limits(), [evaluation], self.verification
        )
        memory = get_evals_formatted_memory([evaluation])
        self.console.print(f' ({time}, {memory})', end='')
        checker_msg = evaluation.result.message
        if checker_msg:
            checker_msg = get_truncated_message(checker_msg, 150)
            self.console.print(f': [i]{utils.escape_markup(checker_msg)}[/i]', end='')
        self.console.print()


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

    single_solution = len(result.skeleton.solutions) == 1
    report_cls = SingleSolutionRunReporter if single_solution else LiveRunReporter
    reporter = report_cls(result, verification, console)

    if detailed:
        return await _print_detailed_run_report(
            result,
            console,
            reporter.structured_evaluations,
            verification=verification,
            timing=timing,
        )

    ok = True

    for solution in result.skeleton.solutions:
        reporter.start_solution(solution)
        for group in result.skeleton.groups:
            reporter.start_group(group)
            for i, _ in enumerate(group.testcases):
                reporter.start_testcase(i)
                eval = reporter.get_current_evaluation()
                evaled = None
                if eval is not None:
                    evaled = await eval()
                reporter.finish_testcase(evaled)
            reporter.finish_group()
        cur_ok = reporter.finish_solution()
        ok = ok and cur_ok

    if not single_solution:
        await _print_timing(
            console,
            result.skeleton,
            reporter.structured_evaluations,
        )

    return ok
