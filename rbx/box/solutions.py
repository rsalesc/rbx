from __future__ import generators

import collections
import dataclasses
import pathlib
import shutil
import typing
from collections.abc import AsyncIterator
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Callable,
    Collection,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Union,
)

import rich
import rich.live
import rich.markup
import rich.padding
import rich.table
import rich.text
import typer
from ordered_set import OrderedSet
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import (
    checkers,
    code,
    compilation_findings,
    limits_info,
    package,
    remote,
    retries,
    run_report,
    setter_config,
    visualizers,
)
from rbx.box.code import (
    SanitizationLevel,
    compile_item,
    find_language_name,
)
from rbx.box.deferred import Deferred
from rbx.box.environment import (
    VerificationLevel,
)
from rbx.box.formatting import (
    get_formatted_memory,
    get_formatted_time,
    get_formatted_time_in_seconds,
    href,
)
from rbx.box.generation_schema import GenerationTestcaseEntry, TestcaseOrScriptEntry
from rbx.box.generators import (
    expand_generator_call,
    generate_output_for_testcase,
    generate_standalone,
)
from rbx.box.parallel import live_tasks
from rbx.box.rendering import CellSlot, Throttling

# Imported eagerly, unlike `runners.local` below: `runners.base` reaches back
# into this module for type names only, under TYPE_CHECKING, so there is no cycle
# to break -- and the board has to be a real class here, not a string, because a
# dataclass default_factory is evaluated at runtime.
from rbx.box.runners.base import RunProgress
from rbx.box.sanitizers import compilation_warnings, issue_stack
from rbx.box.schema import (
    ExpectedOutcome,
    GeneratorCall,
    InferenceRole,
    ScoreType,
    Solution,
    TaskType,
    Testcase,
    TestcaseGroup,
)
from rbx.box.tasks import (
    get_limits_for_language,
    get_testcase_output_path,
    run_solution_on_testcase,
    should_capture_pipes,
    write_evaluation,
)
from rbx.box.testcase_extractors import (
    extract_generation_testcases_from_generic_entries,
    extract_generation_testcases_from_groups,
    find_built_testcases,
)
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testcase_utils import (
    get_all_interaction_files,
    get_best_interaction_file,
    print_best_output,
    print_stderr_section,
)
from rbx.grading import grading_context, steps
from rbx.grading.async_executor import AsyncStreamer
from rbx.grading.limits import Limits
from rbx.grading.steps import (
    CheckerResult,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)
from rbx.utils import StatusProgress

if TYPE_CHECKING:
    # `runners.local` reads this module's abort/skip machinery, so the runner
    # types can only be named here, never imported at run time.
    from rbx.box.runners.base import RunContext, RunPurpose, SolutionRunner

StructuredEvaluation = Dict[str, Dict[str, List[Optional[Deferred[Evaluation]]]]]

# The enforced time limit for a run: one limit for every language, or one per
# language. The per-language form exists because a time-limit estimate assigns a
# different limit to each language group (see `rbx/box/timing.py`).
TimelimitOverride = Union[int, Mapping[str, int]]


def resolve_timelimit_override(
    override: Optional[TimelimitOverride],
    lang: Optional[str],
) -> Optional[int]:
    """The limit this language runs under, or None to keep the profile's own.

    A mapping that does not mention the language -- or a language that could not
    be identified at all -- resolves to None rather than to some other language's
    limit.
    """
    if override is None or isinstance(override, int):
        return override
    if lang is None:
        return None
    return override.get(lang)


@dataclasses.dataclass(frozen=True)
class EvaluationItem:
    solution: Solution
    testcase_entry: TestcaseEntry
    eval: Deferred[Evaluation]


class GroupSkeleton(BaseModel):
    name: str
    score: int
    deps: List[str]
    testcases: List[Testcase]


@dataclasses.dataclass(frozen=True)
class AbortContext:
    """What a caller may use to decide that a solution's remaining testcases
    cannot change its outcome."""

    solution: Solution
    group: GroupSkeleton
    entry: TestcaseEntry
    expected_outcome: ExpectedOutcome
    group_expected_outcome: Optional[ExpectedOutcome]
    evaluation: Evaluation


AbortPredicate = Callable[[AbortContext], bool]


def fail_fast_abort_predicate(context: AbortContext) -> bool:
    """Stops running a solution's group as soon as a testcase is not accepted.

    This is a deliberately coarse predicate: a non-accepted verdict does not
    necessarily doom the group (a solution expected to be WA is *supposed* to
    fail some testcase), so the skipped testcases are reported as failed even
    though they were never measured. It exists to cut the wall clock of a quick
    experimental run, and its report must not be trusted to validate a problem.
    """
    return context.evaluation.result.outcome != Outcome.ACCEPTED


class _AbortGate:
    """Tracks which groups of a single solution must no longer run.

    A mutable gate is only correct because every consumer forces the deferred
    evaluations sequentially, in entry order: `print_run_report`,
    `_print_detailed_run_report`/`_render_detailed_group_table` and
    `convert_list_of_solution_evaluations_to_dict`. Parallelizing any of those
    loops would let a testcase run before the verdict that should have skipped
    it -- the producer's own sequencing is not what makes this safe.

    The caller's predicate must only trip on an outcome that already dooms the
    group -- the skipped groups are reported as failed, not as unmeasured.
    """

    def __init__(self, groups: List[GroupSkeleton], scoring: ScoreType):
        self.groups = groups
        self.scoring = scoring
        self.skipped_groups: Set[str] = set()
        # The group graph is fixed for the gate's lifetime, so the reverse
        # adjacency is built once here rather than on every trip.
        self.dependents: Dict[str, List[str]] = collections.defaultdict(list)
        for group in groups:
            for dep in group.deps:
                self.dependents[dep].append(group.name)

    def is_skipped(self, group_name: str) -> bool:
        return group_name in self.skipped_groups

    def trip(self, group_name: str) -> None:
        if self.scoring != ScoreType.POINTS:
            # `deps` only exist under POINTS, and a binary verdict is
            # all-or-nothing, so nothing later can change the outcome.
            self.skipped_groups.update(group.name for group in self.groups)
            return
        self.skipped_groups.add(group_name)
        self.skipped_groups.update(self._dependents_of(group_name))

    def _dependents_of(self, group_name: str) -> Set[str]:
        """Groups that depend on `group_name`, directly or indirectly.

        They would score 0 anyway -- `_check_deps` zeroes a group whenever any
        of its dependencies failed.
        """
        res: Set[str] = set()
        stack = list(self.dependents[group_name])
        while stack:
            name = stack.pop()
            if name in res:
                continue
            res.add(name)
            stack.extend(self.dependents[name])
        return res


def _resolve_solution_limits(
    solution: Solution,
    limits: Dict[str, Limits],
    verification: VerificationLevel,
) -> Limits:
    """The limits one solution is judged under, given the per-language table.

    Shared by the skeleton's own accessor and by the per-solution copy stamped
    onto each ``SolutionSkeleton``, so the two can never disagree about which
    time limit a solution ran with.
    """
    lang = code.find_language_name(solution)
    if lang is None:
        return limits_info.get_package_limits(verification)
    return limits[lang]


class SolutionSkeleton(Solution):
    runs_dir: pathlib.Path
    # The limits this solution is judged under, already resolved through its
    # language.
    #
    # ``SolutionReportSkeleton.limits`` is keyed by language, and mapping a
    # solution onto one of its entries needs ``find_language_name`` -- a lookup
    # over the environment's language table that an external reader of
    # ``skeleton.yml`` has no way to perform. Stamping the answer here is what
    # lets such a reader show a time limit beside a measured time without
    # reimplementing language resolution.
    #
    # Optional so a skeleton written by an older rbx still parses.
    limits: Optional[Limits] = None

    def get_entry_prefix(
        self, entry: TestcaseEntry, stem: Optional[str] = None
    ) -> pathlib.Path:
        if stem is None:
            stem = f'{entry.index:03d}'
        return self.runs_dir / entry.group / stem

    def runs_dir_href(self) -> str:
        relpath = self.runs_dir.relative_to(package.find_problem())
        return href(self.runs_dir, str(relpath), style='bright_black')


class SolutionReportSkeleton(BaseModel):
    solutions: List[SolutionSkeleton]
    entries: List[GenerationTestcaseEntry]
    groups: List[GroupSkeleton]
    limits: Dict[str, Limits]
    compiled_solutions: Dict[str, str]
    # What the compile phase had to say, for the solutions it had anything to
    # say about. A solution that failed to compile is absent from `solutions`
    # and from `compiled_solutions` -- this is the only record that it exists.
    # See `rbx.box.compilation_findings`.
    compilation: List[compilation_findings.SolutionCompilation] = []
    verification: VerificationLevel
    capture_pipes: bool = False
    # When set (irun -e), the solution's stderr is interleaved with its output in
    # true line order. Riding on the skeleton keeps a toggled flag from ever
    # serving a stale merged capture (irun only caches with an explicit
    # --testcase).
    merge_stderr: bool = False

    def get_solution_limits(self, solution: Solution) -> Limits:
        return _resolve_solution_limits(solution, self.limits, self.verification)

    def find_group_skeleton(self, group_name: str) -> Optional[GroupSkeleton]:
        groups = [group for group in self.groups if group.name == group_name]
        if not groups:
            return None
        return groups[0]

    def get_entries_for_group(self, group_name: str) -> List[GenerationTestcaseEntry]:
        return [
            entry for entry in self.entries if entry.group_entry.group == group_name
        ]

    def get_entry_stem(self, entry: TestcaseEntry) -> str:
        # The on-disk .eval/.out/.log filename stem comes from
        # ``Testcase.inputPath.stem`` (see ``rbx/box/tasks.py``), which for
        # subgroup-generated tests is e.g. ``1-gen-000`` rather than the
        # zero-padded group index. Resolve the actual stem via the matching
        # GenerationTestcaseEntry; fall back to ``{idx:03d}`` for legacy
        # packages that emit flat numeric filenames.
        for e in self.entries:
            if e.group_entry == entry:
                return e.metadata.copied_to.inputPath.stem
        return f'{entry.index:03d}'

    def get_solution_entry_prefix(
        self, solution: 'SolutionSkeleton', entry: TestcaseEntry
    ) -> pathlib.Path:
        return solution.get_entry_prefix(entry, stem=self.get_entry_stem(entry))

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
    # The backend that produced `items`, so whoever consumes them can tell it
    # when it is done. Optional because a result can be built without a run at
    # all -- the reporting tests do exactly that -- and a result with no backend
    # has nothing to close.
    runner: Optional['SolutionRunner'] = None
    # The board the backend writes what it is doing on, per solution, read by the
    # reporter every time it paints a solution header. Defaulted so a result
    # built without a run at all -- which every reporting test does -- reads back
    # empty rather than needing a guard at the one place that reads it.
    progress_board: 'RunProgress' = dataclasses.field(default_factory=RunProgress)

    def empty_structured_evaluation(self) -> StructuredEvaluation:
        return self.skeleton.empty_structured_evaluation()

    async def close(self) -> None:
        """Tell the backend this batch is over. Idempotent.

        `await` it from a `finally` around the *consumption* of `items`, which is
        the only moment at which this can be correct: a backend may dispatch work
        ahead of the consumer, so anything still outstanding when consumption
        ends is work whose result nobody will ever read. `SolutionRunner.close`
        explains at length why this is not the `finalize` hook the seam started
        with -- that one fired while every job was still in flight -- and why it
        ends the *batch* rather than the runner, which a second `run_solutions`
        on the same object is free to reuse.

        Every consumer of a `RunSolutionResult` should do this, including the
        ones that only ever run locally: `LocalRunner.close` is a no-op, so the
        cost is nothing and the alternative is a call site that silently breaks
        the day someone points it at a remote backend.
        """
        if self.runner is None:
            return
        await self.runner.close()


class FailedSolutionIssue(issue_stack.Issue):
    def __init__(self, solution: Solution):
        self.solution = solution

    def get_detailed_section(self) -> Tuple[str, ...]:
        return ('solutions',)

    def get_detailed_message(self) -> str:
        return f'{self.solution.href()} has an unexpected outcome.'


def is_fast(solution: Solution) -> bool:
    # A solution expected to be slow anywhere -- for the whole testset or for a
    # single group -- is not a fast solution.
    return not any(outcome.is_slow() for outcome in solution.all_expected_outcomes())


def is_good(solution: Solution) -> bool:
    # A solution is good when every expectation it declares -- for the whole
    # testset or for a single group -- is a plain AC.
    return all(
        outcome == ExpectedOutcome.ACCEPTED
        for outcome in solution.all_expected_outcomes()
    )


def inference_role_of(solution: Solution) -> Optional[InferenceRole]:
    """Which bound this solution contributes to during time limit inference.

    Mirrors the classification ``TimingSummary`` already uses: a solution that is
    accepted everywhere bounds from below, a solution expected to be slow
    anywhere bounds from above, and everything else -- notably
    ``accepted-or-tle``, which is neither good nor slow -- bounds neither.
    """
    if solution.inference is False:
        return None
    if solution.inference is not None:
        return solution.inference
    if is_good(solution):
        return InferenceRole.LOWER
    if not is_fast(solution):
        return InferenceRole.UPPER
    return None


def get_inference_solutions(role: InferenceRole) -> List[Solution]:
    return [
        solution
        for solution in package.get_solutions()
        if inference_role_of(solution) == role
    ]


def get_matching_solutions(
    expected_outcome: Optional[ExpectedOutcome] = None,
    tags: Optional[List[str]] = None,
) -> List[Solution]:
    res = []
    for solution in package.get_solutions():
        if expected_outcome is not None and not solution.outcome.intersect(
            expected_outcome
        ):
            continue
        if tags is not None and not set(tags).issubset(solution.tags):
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
    def __init__(self, solution: Solution, exception: Optional[BaseException] = None):
        self.solution = solution
        self.exception = exception

    def get_detailed_section(self) -> Tuple[str, ...]:
        return ('solutions',)

    def _reason(self) -> Optional[str]:
        if (
            isinstance(self.exception, steps.CompilationError)
            and self.exception.not_found_executable
        ):
            return f"'{self.exception.not_found_executable}' was not found"
        return None

    def get_detailed_message(self) -> str:
        reason = self._reason()
        if reason is not None:
            return (
                f'{self.solution.href()} could not be compiled ({reason}) '
                'and was skipped.'
            )
        return f'{self.solution.href()} could not be compiled and was skipped.'


class SolutionCompilationTask(live_tasks.CompilationTask):
    solution: Solution

    def __init__(self, solution: Solution):
        super().__init__(solution)
        self.solution = solution

    def render(self) -> Optional[live_tasks.TaskRenderable]:
        rendered = super().render()
        if rendered is None:
            return None
        if self.status == live_tasks.CompilationStatus.SKIPPED:
            status_text = rich.text.Text.from_markup('[error]FAILED, skipped[/error]')
            if self.skip_reason:
                status_text.append(f' ({self.skip_reason})', style='status')
            rendered.columns[1] = status_text

        return rendered


async def compile_solutions(
    tracked_solutions: Optional[Collection[str]] = None,
    sanitized: bool = False,
    fail_if_one: bool = True,
    skip_if_fail: bool = False,
    failures: Optional[Dict[pathlib.Path, BaseException]] = None,
) -> Dict[pathlib.Path, str]:
    """Compile solutions, returning the digest of each one that compiled.

    ``failures`` is an optional out-parameter: when given, every solution that
    was skipped because it did not compile is recorded in it, along with the
    exception that says why. The return value stays what it was -- the
    solutions that *did* compile -- because that is what every caller runs.
    """
    compiled_solutions = {}

    if tracked_solutions is None:
        tracked_solutions = [str(sol.path) for sol in package.get_solutions()]

    expanded_solutions = expand_solutions(list(tracked_solutions))
    should_fail = (fail_if_one and len(expanded_solutions) <= 1) or not skip_if_fail

    with live_tasks.LiveTasks(
        title='Solutions',
        progress_message='[info]Compiled [item]{processed}[/item] / [item]{total}[/item] solutions...[/info]',
        final_message='[info]Compiled [item]{total}[/item] solutions...[/info]',
        flexible_columns=SolutionCompilationTask.FLEXIBLE_COLUMN_INDICES,
    ) as live:

        class SolutionCompilationStreamer(AsyncStreamer[SolutionCompilationTask, str]):
            async def post_signaled(self, key: SolutionCompilationTask) -> None:
                live.update()

            async def scheduled(self, key: SolutionCompilationTask) -> None:
                key.status = live_tasks.CompilationStatus.RUNNING

            async def succeeded(self, key: SolutionCompilationTask, value: str) -> None:
                compiled_solutions[key.solution.path] = value
                key.status = live_tasks.CompilationStatus.SUCCESS
                compilation_warnings.apply_warning_status(key)

            async def failed(
                self, key: SolutionCompilationTask, exception: BaseException
            ) -> None:
                key.status = live_tasks.CompilationStatus.SKIPPED
                if not isinstance(exception, steps.CompilationError) or should_fail:
                    key.status = live_tasks.CompilationStatus.FAILED
                    raise exception
                key.exception = exception
                if failures is not None:
                    failures[key.solution.path] = exception
                if exception.not_found_executable:
                    key.skip_reason = f"'{exception.not_found_executable}' not found"
                issue_stack.add_issue(
                    FailedToCompileSolutionIssue(key.solution, exception=exception)
                )

        streamer = SolutionCompilationStreamer(
            setter_config.get_async_executor(detach=True)
        )
        for solution in expanded_solutions:
            task = SolutionCompilationTask(solution)
            live.append(task)
            await streamer.submit(
                task,
                compile_item,
                task.solution,
                sanitized=SanitizationLevel.FORCE
                if sanitized
                else SanitizationLevel.NONE,
            )

        await streamer.stream()

    return compiled_solutions


def _record_skipped_evaluation(
    testcase: Testcase, index: int, output_dir: pathlib.Path
) -> Evaluation:
    """Build the evaluation of a testcase that was never run, and persist it."""
    eval = Evaluation(
        result=CheckerResult(
            outcome=Outcome.SKIPPED,
            message='Skipped: an earlier testcase already decided this run.',
        ),
        testcase=TestcaseIO(
            index=index, input=testcase.inputPath, output=testcase.outputPath
        ),
        # No time/memory: this never ran, and the timing consumers must not
        # read a 0 out of it. The exit fields are spelled out for the same
        # reason -- `RunLog` defaults to a zero exit code and a 'sandbox error'
        # status, neither of which happened here.
        log=TestcaseLog(
            exitcode=-1,
            exitstatus='skipped',
            time=None,
            wall_time=None,
            memory=None,
        ),
    )
    # The run explorer reads `.eval` files, not the in-memory evaluations, and
    # takes a missing one as 'never ran'. Persisting through the same helper the
    # real runs use keeps the skipped artifact at the very path it looks at.
    #
    # Only the `.eval` is written, unlike the real run paths, which also write a
    # `.log`. The sibling artifacts (`.log`, `.err`, `.out`) are the output of a
    # sandbox run, and there was none: an empty one would claim otherwise. The
    # log viewer already renders a missing file as '(does not exist)'.
    write_evaluation(eval, get_testcase_output_path(testcase, output_dir))
    return eval


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


async def _get_compiled_solutions_for_skeleton(
    tracked_solutions: Optional[Iterable[str]] = None,
    progress: Optional[StatusProgress] = None,
    sanitized: bool = False,
    verification: VerificationLevel = VerificationLevel.NONE,
) -> Tuple[
    List[Solution], Dict[str, str], List[Solution], Dict[pathlib.Path, BaseException]
]:
    solutions_to_compile = _get_solutions_for_skeleton(tracked_solutions, verification)

    failures: Dict[pathlib.Path, BaseException] = {}
    compiled_solutions = await compile_solutions(
        tracked_solutions=[str(solution.path) for solution in solutions_to_compile],
        sanitized=sanitized,
        skip_if_fail=True,
        failures=failures,
    )

    # A solution that did not compile never enters the run: it has no digest to
    # run and no limits to run under. It is not forgotten, though -- it is
    # reported through the skeleton's `compilation`, which is built from
    # `solutions_to_compile` and so still knows it was declared.
    solutions = [
        solution
        for solution in solutions_to_compile
        if solution.path in compiled_solutions
    ]

    return (
        solutions,
        {
            str(solution_path): digest
            for solution_path, digest in compiled_solutions.items()
        },
        solutions_to_compile,
        failures,
    )


async def _get_report_skeleton(
    tracked_solutions: Optional[Iterable[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    timelimit_override: Optional[TimelimitOverride] = None,
    progress: Optional[StatusProgress] = None,
    sanitized: bool = False,
) -> SolutionReportSkeleton:
    pkg = package.find_problem_package_or_die()

    (
        solutions,
        compiled_solutions,
        solutions_to_compile,
        compilation_failures,
    ) = await _get_compiled_solutions_for_skeleton(
        tracked_solutions=tracked_solutions,
        verification=verification,
        progress=progress,
        sanitized=sanitized,
    )

    langs = set(find_language_name(solution) for solution in solutions)
    limits = {
        lang: get_limits_for_language(
            lang, verification, resolve_timelimit_override(timelimit_override, lang)
        )
        for lang in langs
        if lang is not None
    }

    # TODO: add filter for groups?
    built_entries = find_built_testcases(
        await extract_generation_testcases_from_groups()
    )
    testcases_per_group: Dict[str, List[Testcase]] = collections.defaultdict(list)
    for entry in built_entries:
        testcases_per_group[entry.group_entry.group].append(entry.metadata.copied_to)

    groups = []
    for group in pkg.testcases:
        if group.name not in testcases_per_group:
            continue
        groups.append(
            GroupSkeleton(
                name=group.name,
                score=group.score,
                deps=group.deps,
                testcases=testcases_per_group[group.name],
            )
        )

    # Prepare directory.
    runs_dir = package.get_problem_runs_dir()
    shutil.rmtree(str(runs_dir), ignore_errors=True)
    runs_dir.mkdir(parents=True, exist_ok=True)

    # After the wipe above, so the logs live for exactly as long as the run they
    # describe -- like every other artifact under `.rbx/runs`.
    compilation = compilation_findings.build_solution_compilations(
        solutions_to_compile,
        compilation_failures,
        runs_dir,
    )

    skeleton = SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(
                **solution.model_dump(),
                runs_dir=package.get_problem_runs_dir() / f'{i}',
                limits=_resolve_solution_limits(solution, limits, verification),
            )
            for i, solution in enumerate(solutions)
        ],
        groups=groups,
        limits=limits,
        entries=built_entries,
        compiled_solutions=compiled_solutions,
        compilation=compilation,
        verification=verification,
        capture_pipes=should_capture_pipes(package.get_interactor_or_nil()),
    )

    skeleton_file = runs_dir / 'skeleton.yml'
    skeleton_file.write_text(utils.model_to_yaml(skeleton))
    # A new skeleton is what marks a new run. Drop the previous run's report so
    # an interrupted run cannot leave stale verdicts that a reader would take
    # for current ones.
    run_report.clear_report(runs_dir)

    return skeleton


async def _compile_checking_digests(check: bool) -> Tuple[Optional[str], Optional[str]]:
    """The (checker, interactor) digests a run judges its outputs with."""
    pkg = package.find_problem_package_or_die()

    if pkg.type == TaskType.COMMUNICATION:
        checker_digest = (
            await checkers.compile_checker()
            if check and package.get_checker_or_nil() is not None
            else None
        )
        interactor_digest = await checkers.compile_interactor()
    else:
        checker_digest = await checkers.compile_checker() if check else None
        interactor_digest = None

    return checker_digest, interactor_digest


def _gated_evaluation(
    inner: Deferred[Evaluation],
    gate: _AbortGate,
    abort_on: AbortPredicate,
    solution: SolutionSkeleton,
    entry: GenerationTestcaseEntry,
    group: GroupSkeleton,
    output_dir: pathlib.Path,
) -> Deferred[Evaluation]:
    """Wrap one backend evaluation in the abort gate.

    Deliberately here and not in the backend: skipping is a decision about the
    *run*, not about where a testcase executes, and a copy of it in every runner
    is a copy that can drift. `Deferred` is lazy, so a gate that has already
    tripped means `inner` is never awaited and the testcase never dispatches --
    the saving is real, not just cosmetic.
    """
    group_name = group.name

    async def run_fn() -> Evaluation:
        if gate.is_skipped(group_name):
            # The skipped `.eval` still has to land somewhere, and this is the one
            # path where nothing else guarantees the directory: `LocalRunner` mkdirs
            # it eagerly, but a batch backend that never ran this testcase has no
            # reason to have created it.
            output_dir.mkdir(parents=True, exist_ok=True)
            return _record_skipped_evaluation(
                entry.metadata.copied_to, entry.group_entry.index, output_dir
            )
        evaluation = await inner()
        context = AbortContext(
            solution=solution,
            group=group,
            entry=entry.group_entry,
            expected_outcome=solution.outcome,
            group_expected_outcome=solution.expected_outcome_for_group(group_name),
            evaluation=evaluation,
        )
        if abort_on(context):
            gate.trip(group_name)
        return evaluation

    return Deferred(run_fn)


def _check_capabilities(
    runner: 'SolutionRunner',
    *,
    nruns: int,
    sanitized: bool,
    check: bool,
) -> None:
    """Refuse up front what the backend cannot do, naming it.

    Refusing beats silently downgrading: a caller who asked for three runs and
    got one would read a single noisy measurement as a stable one, and would have
    no way to tell. The same goes for a sanitizer that was never applied or an
    interactor that was never driven -- each would produce a plausible-looking
    report that answers a different question than the one asked.

    Called before `prepare`, so nothing is compiled, uploaded or submitted on a
    run that cannot mean what it says.
    """
    # Locally imported for the same reason as everywhere else in this module:
    # `runners.base` reaches back here for the skeleton types, so an eager import
    # would close the cycle.
    from rbx.box.runners.base import RunnerCapabilityError

    caps = runner.caps

    # These messages are printed with a bare `print(str(e))` (`main.py`), not
    # through the rich console, so rich markup would reach the setter as literal
    # `[item]` tags. Backticks, like `TimingStrategyError` and `MojNamingError`.
    #
    # TODO(runner-selection): each message ends with "run this on a backend
    # that ...", deliberately vague, because there is no way for a setter to pick
    # one yet -- the backend is chosen in code. Name the `--runner` flag here once
    # it exists; until then, naming it would be advice they cannot act on.

    if not caps.supports_nruns:
        # The *resolved* count, not the raw parameter: `nruns=0` means "whatever
        # the setter configured", which is both the default for every caller and
        # a value that can be greater than one. Trusting the parameter would let
        # the commonest route -- `repeats.reps` set once in `setter_config.yml`
        # for stable timings -- past the guard, and hand back a single
        # measurement under the name of the average that was asked for.
        reps = retries.get_retrier_config(nruns).reps
        if reps > 1:
            # Which of the two causes it was decides which file the setter has to
            # open; naming the wrong one sends them to edit something irrelevant,
            # so each cause gets its whole sentence rather than a shared template.
            explicitly_requested = nruns > 0
            if explicitly_requested:
                cause = (
                    f'`--runs {reps}` asked for {reps} runs per testcase. '
                    f'Drop `--runs`/`-r`'
                )
            else:
                cause = (
                    f'`repeats.reps` in your `setter_config.yml` is {reps}. '
                    f'Set it back to 1'
                )
            raise RunnerCapabilityError(
                f'Runner `{runner.name}` runs each testcase exactly once, but '
                f'{cause}, or run this on a backend that can repeat.'
            )

    if sanitized and not caps.supports_sanitizers:
        raise RunnerCapabilityError(
            f'Runner `{runner.name}` cannot run solutions under a sanitizer. '
            f'Drop the sanitizer, or run this on a backend that supports one.'
        )

    if not check and not caps.supports_unchecked:
        # Refused rather than quietly upgraded to a checked run, for the same
        # reason as every other refusal here: the report would look like an
        # answer to `--no-check` and be an answer to something else. On a remote
        # judge there is no third option -- it checks with the packaged checker,
        # and a package cannot even be built without the answers `--no-check`
        # skips building.
        raise RunnerCapabilityError(
            f'Runner `{runner.name}` always judges with the packaged checker, so '
            f'it cannot honour `--no-check`. Drop `--no-check`, or run this on a '
            f'backend that can skip checking.'
        )

    pkg = package.find_problem_package_or_die()
    if pkg.type == TaskType.COMMUNICATION and not caps.supports_interactive:
        raise RunnerCapabilityError(
            f'Runner `{runner.name}` cannot drive an interactor, but this problem '
            f'is of type `communication`. Run this on a backend that can drive '
            f'one.'
        )


def _produce_solution_items(
    runner: 'SolutionRunner',
    ctx: 'RunContext',
) -> List[EvaluationItem]:
    skeleton = ctx.skeleton
    groups_by_name = {group.name: group for group in skeleton.groups}
    res: List[EvaluationItem] = []

    for solution in skeleton.solutions:
        # One gate per solution: a solution that dooms its own run must not
        # decide anything about the solutions that follow it.
        #
        # A backend declaring `supports_abort=False` is left ungated even when
        # the run asked to abort. That is a correctness rule, not a missing
        # optimization: such a backend runs the whole submission at once, so by
        # the time rbx sees anything every testcase already has a real verdict.
        # Gating would replace those verdicts with SKIPPED -- discarding results
        # the judge genuinely produced and making the report claim work did not
        # happen. Aborting exists to save work; there is none left to save here,
        # and real verdicts always beat skip markers.
        #
        # Note this ignores `abort_on` rather than refusing the run by name, which
        # is the opposite of what `_check_capabilities` does for repeats, a
        # sanitizer or an interactor. The asymmetry is deliberate: dropping those
        # changes what the report *means*, so a run that quietly dropped them
        # would answer a different question than the one asked. Dropping the abort
        # loses nothing -- the caller gets every verdict it would have got, and
        # more -- so there is nothing to warn about.
        gate = (
            _AbortGate(skeleton.groups, package.get_scoring())
            if ctx.abort_on is not None and runner.caps.supports_abort
            else None
        )
        # The whole testset in one call, flattened in `skeleton.groups` order --
        # which is the (solution, group) order the report renders. A backend that
        # submits to a remote judge gets one submission per solution this way,
        # instead of one per group.
        entries = [
            entry
            for group in skeleton.groups
            for entry in skeleton.get_entries_for_group(group.name)
        ]
        evals = runner.run_solution(solution, entries, ctx)
        # The protocol says one deferred per entry, in entry order. Zipping a
        # short list would silently drop that solution's last testcases.
        assert len(evals) == len(entries), (
            f'runner {runner.name} returned {len(evals)} evaluations '
            f'for {len(entries)} testcases'
        )

        for entry, eval in zip(entries, evals):
            if gate is not None:
                assert ctx.abort_on is not None
                # Every entry belongs to a group of the skeleton. Assert rather
                # than skip: a refactor that broke this would silently turn the
                # abort off instead of failing.
                group = groups_by_name.get(entry.group_entry.group)
                assert group is not None
                eval = _gated_evaluation(
                    eval,
                    gate,
                    ctx.abort_on,
                    solution,
                    entry,
                    group,
                    solution.runs_dir / group.name,
                )
            res.append(
                EvaluationItem(
                    solution=solution,
                    testcase_entry=entry.group_entry,
                    eval=eval,
                )
            )

    return res


async def run_solutions(
    progress: Optional[StatusProgress] = None,
    tracked_solutions: Optional[Iterable[str]] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    timelimit_override: Optional[TimelimitOverride] = None,
    sanitized: bool = False,
    nruns: int = 0,
    abort_on: Optional[AbortPredicate] = None,
    runner: Optional['SolutionRunner'] = None,
    purpose: Optional['RunPurpose'] = None,
) -> RunSolutionResult:
    # Imported here, not at module scope: `runners.local` imports this module
    # back -- for `run_solution_on_testcase` and for `SolutionSkeleton` -- so an
    # eager import would close the cycle. Untangling that means lifting the
    # skeleton types out of this 2185-line module, which is its own change.
    from rbx.box.runners.base import RunContext, RunPurpose
    from rbx.box.runners.local import LocalRunner

    if runner is None:
        runner = LocalRunner()
    if purpose is None:
        # Defaulted here rather than in the signature so the annotation does not
        # have to be a live import: `runners.base` reaches back into this module,
        # so importing it at module scope would close the cycle.
        purpose = RunPurpose.RUN

    # Before anything is compiled or dispatched: a run that cannot mean what it
    # says should cost nothing and fail by name.
    _check_capabilities(runner, nruns=nruns, sanitized=sanitized, check=check)

    skeleton = await _get_report_skeleton(
        progress=progress,
        tracked_solutions=tracked_solutions,
        verification=verification,
        timelimit_override=timelimit_override,
        sanitized=sanitized,
    )

    checker_digest, interactor_digest = await _compile_checking_digests(check)

    # One board for the whole run, handed to the backend here and to the reporter
    # on the result below. It cannot be created by either of them: the reporter
    # does not exist until this function has returned.
    progress_board = RunProgress()

    ctx = RunContext(
        skeleton=skeleton,
        checker_digest=checker_digest,
        interactor_digest=interactor_digest,
        verification=verification,
        timelimit_override=timelimit_override,
        nruns=nruns,
        progress=progress,
        abort_on=abort_on,
        purpose=purpose,
        progress_board=progress_board,
    )

    await runner.prepare(ctx)
    items = _produce_solution_items(runner=runner, ctx=ctx)

    return RunSolutionResult(
        skeleton=skeleton,
        items=items,
        runner=runner,
        progress_board=progress_board,
    )


async def _generate_testcase_interactively(
    progress: Optional[StatusProgress] = None,
    generator: Optional[GeneratorCall] = None,
    testcase_entry: Optional[TestcaseOrScriptEntry] = None,
    validate: bool = True,
    check: bool = True,
    custom_output: bool = False,
    visualize: bool = False,
    sanitized: bool = False,
    print: bool = False,
) -> GenerationTestcaseEntry:
    main_solution = package.get_main_solution()
    testcase = _get_interactive_testcase(check)
    interactive_entry = GenerationTestcaseEntry.make_interactive(copied_to=testcase)
    entry_for_validation: Optional[GenerationTestcaseEntry] = None

    is_manual = False
    is_output_manual = False
    if generator is not None:
        interactive_entry.metadata.generator_call = expand_generator_call(generator)
    elif testcase_entry is not None:
        extracted = await extract_generation_testcases_from_generic_entries(
            [testcase_entry]
        )
        if not extracted:
            console.console.print(
                f'[error]Failed searching for testcase [item]{testcase_entry}[/item].[/error]'
            )
            raise typer.Exit(1)
        extracted_entry = extracted[0]
        interactive_entry = extracted_entry.model_copy(deep=True)
        # Replace destination with the irun testcase we're using.
        interactive_entry.metadata.copied_to = testcase
        # Validate against this test's own validators (group-level overrides,
        # extra validators), not just the package-level ones.
        entry_for_validation = interactive_entry
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

        is_manual = True

    # 1. Generate testcase.
    should_print_testcase = False
    if interactive_entry.metadata is not None:
        await generate_standalone(
            interactive_entry.metadata,
            entry=entry_for_validation,
            progress=progress,
            validate=validate,
        )
        if print and not is_manual:
            should_print_testcase = True
        else:
            console.console.print(
                f'Input was written to {href(package.relpath(testcase.inputPath))}'
            )

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
            main_solution_digest = await compile_item(
                main_solution,
                sanitized=SanitizationLevel.FORCE
                if sanitized
                else SanitizationLevel.NONE,
            )
        except:
            console.console.print(
                '[error]Failed compiling main solution. If you do not want to check against a main solution, run with --no-check flag.[/error]'
            )
            raise

    if main_solution_digest is not None and not is_output_manual:
        pkg = package.find_problem_package_or_die()
        if pkg.type == TaskType.COMMUNICATION:
            interactor_digest = await checkers.compile_interactor(progress)
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

    # 3. Generate visualizations
    if visualize:
        visualization_path = await visualizers.run_visualizers_for_testcase(
            testcase,
            progress=progress,
        )
        if visualization_path is not None and visualization_path.is_file():
            console.console.print(
                f'Input visualization was written to {href(package.relpath(visualization_path))}'
            )

    # 4. Print testcase
    if should_print_testcase:
        console.console.print(testcase.inputPath.read_text())
        console.console.print()

    if check and testcase.outputPath is not None and not testcase.outputPath.is_file():
        # Output was not created, throw an error.
        console.console.print(
            '[error]Checking is enabled but no output could be generated for this testcase.[/error]'
        )
        console.console.print(
            '[error]Either specify it explicitly or provide a main solution.[/error]'
        )
        raise typer.Exit(1)

    return interactive_entry


async def _run_interactive_solutions(
    entry: GenerationTestcaseEntry,
    skeleton: SolutionReportSkeleton,
    progress: Optional[StatusProgress] = None,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    visualize: bool = False,
) -> AsyncIterator[EvaluationItem]:
    pkg = package.find_problem_package_or_die()

    if pkg.type == TaskType.COMMUNICATION:
        checker_digest = await checkers.compile_checker() if check else None
        interactor_digest = await checkers.compile_interactor()
    else:
        checker_digest = await checkers.compile_checker() if check else None
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
                entry.metadata.copied_to,
                output_dir=output_dir,
                interactor_digest=interactor_digest,
                verification=verification,
                capture_pipes=skeleton.capture_pipes,
                merge_stderr=skeleton.merge_stderr,
            )

        yield EvaluationItem(
            solution=solution,
            testcase_entry=entry.group_entry,
            eval=Deferred(run_fn),
        )


def _get_interactive_testcase(check: bool) -> Testcase:
    irun_dir = package.get_problem_iruns_dir()
    inputs_dir = irun_dir / 'inputs'
    inputs_dir.mkdir(parents=True, exist_ok=True)
    testcase = Testcase(
        inputPath=inputs_dir / '000.in',
        outputPath=(inputs_dir / '000.out') if check else None,
    )
    return testcase


async def _get_interactive_skeleton(
    entry: GenerationTestcaseEntry,
    tracked_solutions: Optional[Iterable[str]] = None,
    progress: Optional[StatusProgress] = None,
    sanitized: bool = False,
    verification: VerificationLevel = VerificationLevel.NONE,
    check: bool = True,
    merge_stderr: bool = False,
) -> SolutionReportSkeleton:
    solutions, compiled_solutions, _, _ = await _get_compiled_solutions_for_skeleton(
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

    skeleton = SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(
                **solution.model_dump(),
                runs_dir=irun_dir / f'{i}',
                limits=_resolve_solution_limits(solution, limits, verification),
            )
            for i, solution in enumerate(solutions)
        ],
        groups=[],
        limits=limits,
        entries=[entry],
        verification=verification,
        compiled_solutions=compiled_solutions,
        capture_pipes=should_capture_pipes(package.get_interactor_or_nil()),
        merge_stderr=merge_stderr,
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
    merge_stderr: bool = False,
    sanitized: bool = False,
    validate: bool = True,
    visualize: bool = False,
):
    pkg = package.find_problem_package_or_die()

    # Interleaving stderr only changes what is rendered, which only happens with
    # -p. Warn (don't fail) if -e is given without -p.
    if merge_stderr and not print:
        console.console.print(
            '[warning]--merge-stderr/-e has no effect without --print/-p; '
            'stderr will be written to its file as usual.[/warning]'
        )
        merge_stderr = False

    # Refresh irun dir.
    irun_dir = package.get_problem_iruns_dir()
    shutil.rmtree(str(irun_dir), ignore_errors=True)
    irun_dir.mkdir(parents=True, exist_ok=True)

    should_cache = testcase_entry is not None
    with grading_context.cache_level(
        grading_context.CacheLevel.CACHE_COMPILATION, when=not should_cache
    ):
        entry = await _generate_testcase_interactively(
            progress=progress,
            generator=generator,
            testcase_entry=testcase_entry,
            check=check,
            custom_output=custom_output,
            sanitized=sanitized,
            print=print,
            validate=validate,
            visualize=visualize,
        )
        skeleton = await _get_interactive_skeleton(
            entry,
            tracked_solutions=tracked_solutions,
            verification=verification,
            sanitized=sanitized,
            progress=progress,
            check=check,
            merge_stderr=merge_stderr,
        )
        items = _run_interactive_solutions(
            entry,
            skeleton=skeleton,
            progress=progress,
            verification=verification,
            check=check,
            visualize=visualize,
        )

    async for item in items:
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
        merged_path = (
            stdout_path.with_suffix('.pio') if stdout_path is not None else None
        )
        if (
            print
            and skeleton.merge_stderr
            and merged_path is not None
            and merged_path.is_file()
        ):
            # Interleaved view: the merged capture already weaves stderr (red)
            # into the output/interaction in true line order, so render it in
            # place of the plain Output + separate Stderr sections.
            rule = 'Interaction' if pkg.type == TaskType.COMMUNICATION else 'Output'
            console.console.rule(rule, style='status')
            print_best_output(
                [merged_path],
                pkg.type,
                empty_warning=True,
                capture_pipes=skeleton.capture_pipes,
            )
        elif print and stdout_path is not None:
            if pkg.type == TaskType.COMMUNICATION:
                console.console.rule('Interaction', style='status')
                output_files = get_all_interaction_files(stdout_path) + [
                    stdout_path.with_suffix('.pout'),
                ]
                print_best_output(
                    output_files,
                    pkg.type,
                    empty_warning=True,
                    capture_pipes=skeleton.capture_pipes,
                )

            console.console.rule('Output', style='status')
            output_files = [stdout_path]
            print_best_output(output_files, pkg.type, empty_warning=True)

            if eval.log.stderr_absolute_path is not None:
                print_stderr_section(eval.log.stderr_absolute_path)
        elif stdout_path is not None:
            if stdout_path.with_suffix('.pout').is_file():
                stdout_path = stdout_path.with_suffix('.pout')

            if stdout_path.is_file():
                console.console.print(
                    f'[status]Output:[/status] {href(package.relpath(stdout_path))}'
                )
            interaction_path = get_best_interaction_file(stdout_path)
            if interaction_path is not None:
                console.console.print(
                    f'[status]Interaction:[/status] {href(package.relpath(interaction_path))}'
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
    if outcome == Outcome.OUTPUT_LIMIT_EXCEEDED:
        return 'orange1'
    if outcome == Outcome.COMPILATION_ERROR:
        return 'blue'
    if outcome == Outcome.SKIPPED:
        return 'bright_black'
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
    if outcome == Outcome.SKIPPED:
        res = '⊘'
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


def _get_evals_time_in_ms(evals: List[Evaluation]) -> Optional[int]:
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
    # An evaluation without a time never ran -- a skipped testcase, most
    # notably. Coalescing it to zero would report 'instant' for a run that did
    # not happen, so it contributes nothing to the maximum instead.
    times = [eval.log.time for eval in evals if eval.log.time is not None]
    if not times:
        return None
    return max(int(time * 1000) for time in times)


def _get_evals_judging_time_in_seconds(evals: List[Evaluation]) -> float:
    if not evals:
        return 0
    return sum((eval.log.wall_time or 0.0) for eval in evals)


def _get_evals_memory_in_bytes(evals: List[Evaluation]) -> Optional[int]:
    memories = [eval.log.memory for eval in evals if eval.log.memory is not None]
    if not memories:
        return None
    return max(int(memory) for memory in memories)


# What a formatted time or memory reads as when nothing was measured at all.
_UNMEASURED = '-'


def get_evals_formatted_time(evals: List[Evaluation]) -> str:
    max_time = _get_evals_time_in_ms(evals)
    if max_time is None:
        return _UNMEASURED
    return get_formatted_time(max_time)


def get_evals_formatted_judging_time(evals: List[Evaluation]) -> str:
    total_time = _get_evals_judging_time_in_seconds(evals)
    return get_formatted_time_in_seconds(total_time)


def get_capped_evals_formatted_time(
    limits: Limits,
    evals: List[Evaluation],
    verification: VerificationLevel,
) -> str:
    max_time = _get_evals_time_in_ms(evals)
    if max_time is None:
        return _UNMEASURED
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
    if max_memory is None:
        return _UNMEASURED
    return get_formatted_memory(max_memory)


def get_worst_outcome(evals: List[Evaluation]) -> Outcome:
    return Outcome.worst_outcome(eval.result.outcome for eval in evals)


def get_truncated_message(message: str, max_length: int = 100) -> str:
    if len(message) > max_length:
        return message[:max_length] + '... (truncated)'
    return message


def get_expected_score_repr(range: Tuple[int, int]) -> str:
    if range[0] == range[1]:
        return str(range[0])
    if range[1] == 10**9:
        return f'{range[0]}..'
    return f'{range[0]}..{range[1]}'


def get_expected_score_markup(range: Tuple[int, int]) -> str:
    score_repr = get_expected_score_repr(range)
    return f'[item]{score_repr}[/item]'


def get_expected_score_in_phrase(range: Tuple[int, int]) -> str:
    score_markup = get_expected_score_markup(range)
    if range[0] == range[1]:
        return f'{score_markup}'
    return f'in {score_markup}'


def fulfills_expected_score(range: Tuple[int, int], score: int) -> bool:
    return score >= range[0] and score <= range[1]


def get_solution_score_style(score: int, max_score: Optional[int] = None) -> str:
    if max_score is None:
        max_score = 1
    if score >= max_score:
        return 'success'
    if score > 0:
        return 'warning'
    return 'error'


def get_solution_score_markup(
    score: int, max_score: Optional[int] = None, pts: bool = False
) -> str:

    res = f'{score}'
    if max_score is not None:
        res += f'/{max_score}'
    if pts:
        res += ' pts'
    style = get_solution_score_style(score, max_score)
    return f'[{style}][{res}][/{style}]'


def _on_groups_markup(names: List[str]) -> str:
    """Markup fragment attributing a warning to the groups it came from.

    Empty when no group is involved, so a pooled-only report keeps its original
    wording.
    """
    if not names:
        return ''
    groups = ', '.join(utils.escape_markup(name) for name in names)
    return f' on [item]{groups}[/item]'


class SolutionOutcomeStatus(Enum):
    OK = 'OK'
    UNEXPECTED_SCORE = 'UNEXPECTED_SCORE'
    UNEXPECTED_VERDICTS = 'UNEXPECTED_VERDICTS'

    def __bool__(self) -> bool:
        return self == SolutionOutcomeStatus.OK

    def ok(self) -> bool:
        return self == SolutionOutcomeStatus.OK


class GroupOutcomeReport(BaseModel):
    """How one testcase group fared against its own expected outcome."""

    expectedOutcome: ExpectedOutcome
    gotVerdicts: Set[Outcome]
    status: SolutionOutcomeStatus
    runUnderDoubleTl: bool
    doubleTlVerdicts: Set[Outcome]
    # The no-TLE verdicts in this group that NEITHER layer accepts.
    #
    # Already the intersection with the pooled layer's, so a reader needs no
    # second lookup: a verdict the solution's own ``outcome`` covers is not
    # surfaced here even when this group's ``outcomePerGroup`` would not have
    # covered it, and vice versa. See ``unexpectedNoTleVerdicts``.
    unexpectedNoTleVerdicts: Set[Outcome]


def _failed_group_names(per_group: Dict[str, GroupOutcomeReport]) -> List[str]:
    """The groups that did not meet their own expectation, in ``per_group`` order.

    Shared by ``SolutionOutcomeReport.failedGroups`` and the aggregate status,
    which must never disagree about what failed.
    """
    return [name for name, report in per_group.items() if not report.status.ok()]


class SolutionOutcomeReport(BaseModel):
    """The result of checking one solution's evaluations against its expectations.

    A solution declares its expectations in two layers, and both must hold:

    - ``Solution.outcome`` is checked against every evaluation *pooled* together,
      over the whole testset. Its result is ``pooledStatus``, and the values it
      was computed from are the unprefixed ``expectedOutcome``/``gotVerdicts``:
      they are the pooled layer's, since that layer is the only one every
      solution has and the only one that predates per-group expectations.
    - ``Solution.outcomePerGroup`` is checked against each group's evaluations
      alone. Those results live in ``perGroup``, one record per group.

    ``status`` is the aggregate: OK only when the pooled layer passed and no
    group failed (and, under POINTS scoring, it becomes UNEXPECTED_SCORE when
    the score is out of the expected range, which takes precedence).
    """

    solution: Solution
    limits: Limits
    evals: List[Evaluation]
    status: SolutionOutcomeStatus
    message: Optional[Tuple[GenerationTestcaseEntry, str]]
    expectedOutcome: ExpectedOutcome
    gotVerdicts: Set[Outcome]
    # Status of the pooled ``outcome`` layer on its own.
    pooledStatus: SolutionOutcomeStatus
    # Only groups that carry an expectation AND were evaluated appear here. The
    # order is the order their first evaluation arrived in, which today is
    # testset order because both come from ``skeleton.entries``.
    perGroup: Dict[str, GroupOutcomeReport] = {}
    expectedScore: Optional[Tuple[int, int]]
    gotScore: int
    gotScorePerGroup: Dict[str, int]
    maxScore: int
    runUnderDoubleTl: bool
    doubleTlVerdicts: Set[Outcome]
    # The verdicts a soft TLE hid that the pooled ``outcome`` does not accept.
    #
    # A solution judged at 2x its time limit is reported TLE the moment it
    # crosses 1x, and the verdict it *would* have got is kept in
    # ``no_tle_outcome``. Most of those are uninteresting -- a solution declared
    # slow being wrong in a way the declaration already allows says nothing --
    # so only the ones no expectation covers are collected, and ACCEPTED never
    # is: a correct answer underneath a soft TLE is the good case, and it is
    # already reported by ``runUnderDoubleTl``.
    #
    # Deciding this needs ``ExpectedOutcome.match``, which is why it is computed
    # here rather than by whoever renders it.
    unexpectedNoTleVerdicts: Set[Outcome]
    sanitizerWarnings: bool
    verification: VerificationLevel
    scoring: ScoreType

    @property
    def failedGroups(self) -> List[str]:
        return _failed_group_names(self.perGroup)

    def _group_failure_lines(self) -> List[str]:
        lines = []
        for name, group in self.perGroup.items():
            if group.status.ok():
                continue
            got = ' '.join(sorted(v.name for v in group.gotVerdicts))
            line = (
                f'[item]{utils.escape_markup(name)}[/item]: '
                f'expected {group.expectedOutcome}'
            )
            if got:
                line += f', got: {got}'
            lines.append(line)
        return lines

    def get_verdict_markup(self, incomplete: bool = False, subset: bool = False) -> str:
        success_str = '[success]OK[/success] '
        if subset:
            success_str = ''
        if not self.status.ok():
            success_str = '[ierror]FAILED[/ierror] '
        if incomplete:
            success_str = '[iwarning]INCOMPLETE[/iwarning] '

        gotVerdicts = self.gotVerdicts if not incomplete else {}

        got_verdict_names = ' '.join(v.name for v in self.gotVerdicts)
        verdict_str = ''
        if self.scoring == ScoreType.POINTS:
            if self.expectedScore is not None:
                verdict_str = (
                    f'Expected score {get_expected_score_markup(self.expectedScore)}, '
                    f'got {get_solution_score_markup(self.gotScore, self.maxScore, pts=True)}'
                )
            else:
                verdict_str = f'Got {get_solution_score_markup(self.gotScore, self.maxScore, pts=True)}'

        # Only speak for the pooled layer when the pooled layer is what failed;
        # otherwise "Expected: X" would accuse an expectation that was met.
        if (
            self.status == SolutionOutcomeStatus.UNEXPECTED_VERDICTS
            and not self.pooledStatus.ok()
        ):
            if self.expectedOutcome != ExpectedOutcome.ANY:
                verdict_str = f'Expected: {self.expectedOutcome}'
                if gotVerdicts:
                    verdict_str += f', got: {got_verdict_names}'
            elif gotVerdicts:
                verdict_str = f'Got: {got_verdict_names}'

        group_lines = [] if incomplete else self._group_failure_lines()
        if not verdict_str and group_lines:
            # Fold the first group into the FAILED line instead of leaving it bare.
            verdict_str = group_lines.pop(0)
        res = f'{success_str}{verdict_str}'
        if group_lines:
            # Say FAILED once: the remaining groups line up under the first one
            # instead of repeating the prefix on every row.
            indent = ' ' * _length_markup(success_str)
            for line in group_lines:
                res += f'\n{indent}{line}'
        return res

    def get_verdict_markup_with_warnings(self, subset: bool = False) -> str:
        res = self.get_verdict_markup(subset=subset)
        # The two double-TL facts are independent, so each is its own sentence
        # naming its own groups. A single layer either passed *within* 2x TL or
        # finished within it with other (soft-TLE) verdicts, never both -- but
        # both aggregate fields are unions over the pooled layer and every group,
        # so two different groups can each contribute one fact. Reporting them
        # together would have to attribute both to a single group list, and
        # gating one on the other is how the second was lost entirely (#607).
        if self.runUnderDoubleTl:
            where = _on_groups_markup(
                [
                    name
                    for name, group in self.perGroup.items()
                    if group.runUnderDoubleTl
                ]
            )
            res += f'\n[warning]WARNING[/warning] The solution still passed in double TL{where}.'
        if self.doubleTlVerdicts:
            where = _on_groups_markup(
                [
                    name
                    for name, group in self.perGroup.items()
                    if group.doubleTlVerdicts
                ]
            )
            verdicts = ' '.join(sorted(v.name for v in self.doubleTlVerdicts))
            res += f'\n[warning]WARNING[/warning] The solution still finished in double TL, but failed with [item]{verdicts}[/item]{where}.'
        if self.sanitizerWarnings:
            res += '\n[warning]WARNING[/warning] The solution had sanitizer errors or warnings, marked with [item]*[/item]. See their stderr for more details.'
        return res

    def get_outcome_markup(
        self,
        skeleton: SolutionReportSkeleton,
        subset: bool = False,
        print_message: bool = True,
        print_scoring: bool = False,
    ) -> str:
        res = self.get_verdict_markup_with_warnings(subset=subset)
        if print_scoring and self.scoring == ScoreType.POINTS:
            # Print pretty scoring for each group.
            scoring_res = ''
            for group in skeleton.groups:
                if group.score > 0:
                    group_res = f'[bstatus]{group.name}[/bstatus]'
                    got_score = self.gotScorePerGroup.get(group.name, 0)
                    group_res += f' {get_solution_score_markup(got_score, group.score, pts=True)}'
                    scoring_res += group_res + '\n'
            res = scoring_res + res
        res += f'\nTime: {get_capped_evals_formatted_time(self.limits, self.evals, self.verification)}'
        res += f'\nMemory: {get_evals_formatted_memory(self.evals)}'
        # res += f'\nJudging time: {get_evals_formatted_judging_time(self.evals)}'
        if print_message and self.message is not None:
            entry, msg = self.message
            if msg:
                msg = get_truncated_message(msg)
                res += f'\nMessage for {utils.escape_markup(str(entry))}: {utils.escape_markup(msg)}'
        return res


class VerdictReport(BaseModel):
    all_verdicts: Set[Outcome]
    bad_verdicts: Set[Outcome]
    no_tle_bad_verdicts: Set[Outcome]
    has_plain_tle: bool
    has_sanitizer_warnings: bool

    got_verdicts: Set[Outcome]
    double_tl_verdicts: Set[Outcome]
    run_under_double_tl: bool
    unexpected_no_tle_verdicts: Set[Outcome]
    expected_outcome: ExpectedOutcome
    ok: bool

    def passed(self) -> bool:
        return not bool(self.bad_verdicts)

    def has_unmatched_slow_verdict(self):
        matches_slow_expectation = self.expected_outcome.matches_tle_and_is_incorrect()
        is_slow_expectation = self.expected_outcome.is_slow()
        has_slow_verdict = any(v.is_slow() for v in self.bad_verdicts)
        if matches_slow_expectation and has_slow_verdict and not is_slow_expectation:
            return False
        return has_slow_verdict != is_slow_expectation


def _get_verdict_report(
    skeleton: SolutionReportSkeleton,
    evals: List[Evaluation],
    solution: Solution,
    expected_outcome: ExpectedOutcome,
    subset: bool,
    verification: VerificationLevel,
) -> VerdictReport:
    has_plain_tle = False
    has_skipped = False
    all_verdicts = set()
    bad_verdicts = set()
    no_tle_bad_verdicts = set()
    has_sanitizer_warnings = False
    # Verdicts a soft TLE hid that this layer's expectation does not accept.
    # ACCEPTED is never one of them: a correct answer underneath a soft TLE is
    # the good case, and ``run_under_double_tl`` already reports it.
    unexpected_no_tle_verdicts = set()
    for eval in evals:
        all_verdicts.add(eval.result.outcome)
        has_skipped = has_skipped or eval.result.outcome == Outcome.SKIPPED
        if eval.result.outcome != Outcome.ACCEPTED:
            bad_verdicts.add(eval.result.outcome)
        if (
            eval.result.no_tle_outcome is not None
            and eval.result.no_tle_outcome != Outcome.ACCEPTED
        ):
            no_tle_bad_verdicts.add(eval.result.no_tle_outcome)
            if not expected_outcome.match(eval.result.no_tle_outcome):
                unexpected_no_tle_verdicts.add(eval.result.no_tle_outcome)
        has_plain_tle = has_plain_tle or (
            eval.result.outcome.is_slow() and eval.result.no_tle_outcome is None
        )
        has_sanitizer_warnings = (
            has_sanitizer_warnings or eval.result.sanitizer_warnings
        )

    unmatched_bad_verdicts = set(
        v for v in bad_verdicts if not expected_outcome.match(v)
    )
    matched_bad_verdicts = bad_verdicts - unmatched_bad_verdicts
    expected_outcome_is_bad = not expected_outcome.match(Outcome.ACCEPTED)

    has_failed = unmatched_bad_verdicts or (
        expected_outcome_is_bad and not matched_bad_verdicts and not subset
    )

    report_expected_outcome = expected_outcome
    report_got_verdicts = set()
    report_run_under_double_tl = False
    report_double_tl_verdicts = set()
    if subset and not has_failed:
        report_got_verdicts = all_verdicts

    if has_failed:
        if unmatched_bad_verdicts:
            report_got_verdicts = unmatched_bad_verdicts
        elif expected_outcome_is_bad and not matched_bad_verdicts and not subset:
            report_got_verdicts = {Outcome.ACCEPTED}

    evals_time = _get_evals_time_in_ms(evals)
    expected_outcome_is_tle = expected_outcome.matches_tle_and_is_incorrect()
    limits = skeleton.get_solution_limits(solution)
    if (
        # Running verification with double TL.
        verification.value >= VerificationLevel.FULL.value
        # Solution expects a TLE.
        and expected_outcome_is_tle
        # Solution does not have a plain TLE.
        and not has_plain_tle
        # Every testcase of the report actually ran. A skipped one leaves the
        # measurement a lower bound over a prefix of the testset, and a testcase
        # that never ran could well be the one that does not fit in double TL.
        # SKIPPED also lands in `other_verdicts` below, which suppresses both
        # messages anyway -- this states the reason instead of relying on it.
        and not has_skipped
        # A TLE has happened.
        and Outcome.TIME_LIMIT_EXCEEDED in matched_bad_verdicts
        # The solution runs in double TL.
        and limits.time is not None
        # Without a measured run there is no evidence it fits in double TL.
        and evals_time is not None
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

    return VerdictReport(
        all_verdicts=all_verdicts,
        bad_verdicts=bad_verdicts,
        no_tle_bad_verdicts=no_tle_bad_verdicts,
        has_plain_tle=has_plain_tle,
        has_sanitizer_warnings=has_sanitizer_warnings,
        got_verdicts=report_got_verdicts,
        double_tl_verdicts=report_double_tl_verdicts,
        run_under_double_tl=report_run_under_double_tl,
        unexpected_no_tle_verdicts=unexpected_no_tle_verdicts,
        expected_outcome=report_expected_outcome,
        ok=not has_failed,
    )


def _get_evals_per_group(
    evals: List[Evaluation], skeleton: SolutionReportSkeleton
) -> Dict[str, List[Evaluation]]:
    """Bucket evaluations by the group of the entry at the same position.

    Assumes ``evals`` is a prefix of ``skeleton.entries`` with no gaps -- true for
    every caller today, since the reporters append in entry order and a partial
    run is always a prefix. A gap would silently shift every later verdict into
    the wrong group, and per-group verdicts now drive expectations, not just
    cosmetics: a caller that can skip an entry must pass the entry alongside its
    evaluation instead of relying on position.
    """
    res = {}
    for eval, entry in zip(evals, skeleton.entries):
        if entry.group_entry.group not in res:
            res[entry.group_entry.group] = []
        res[entry.group_entry.group].append(eval)
    return res


class TimingIssue(issue_stack.Issue):
    def __init__(self):
        pass

    def get_detailed_section(self) -> Optional[Tuple[str, ...]]:
        return ('timing',)

    def get_detailed_message(self) -> str:
        return (
            'A few solutions in your problem have failed expectations either '
            'because they were too fast or too slow. The limits for this problem '
            'are being consumed from the package and might not be tuned to your machine. '
            'Consider running [item]rbx time[/item] if you need more accurate limits '
            'for your hardware.'
        )

    def get_severity(self) -> issue_stack.IssueSeverity:
        return issue_stack.IssueSeverity.WARNING


def get_solution_outcome_report(
    solution: Solution,
    skeleton: SolutionReportSkeleton,
    evals: List[Evaluation],
    verification: VerificationLevel = VerificationLevel.NONE,
    subset: bool = False,
    report_issues: bool = True,
) -> SolutionOutcomeReport:
    """Check one solution's evaluations against its declared expectations.

    Pass ``report_issues=False`` when the report is a *partial* one, computed
    mid-run over the evaluations collected so far purely to render something. The
    timing heuristic reads "too fast / too slow" off the evals it is given, and a
    group that has run clean while the slow one has not started yet looks too
    fast in isolation -- so a partial report must not push issues that the final
    report would not.
    """
    # Even if the scoring is points, we use binary scoring for subsets/interactive tests.
    scoring = package.get_scoring() if not subset else ScoreType.BINARY
    expected_score = (
        solution.expected_score_range() if scoring == ScoreType.POINTS else None
    )

    verdict_report = _get_verdict_report(
        skeleton, evals, solution, solution.outcome, subset, verification
    )
    pooled_status = (
        SolutionOutcomeStatus.OK
        if verdict_report.ok
        else SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    )
    message: Optional[Tuple[GenerationTestcaseEntry, str]] = None
    for eval, entry in zip(evals, skeleton.entries):
        if eval.result.outcome in [
            Outcome.WRONG_ANSWER,
            Outcome.JUDGE_FAILED,
        ]:
            message = (entry, eval.result.message)
            break

    evals_per_group = _get_evals_per_group(evals, skeleton)

    # Only groups that are part of the testset carry expectations. This is the
    # same set `Package.check_outcome_per_group_names` accepts as explicit keys,
    # so `'*'` expands over exactly those groups and no others -- in particular
    # not over the synthetic `interactive` group of `rbx irun`, whose skeleton
    # declares no groups at all.
    declared_groups = {group.name for group in skeleton.groups}

    # Per-group expectation layer, for groups that both carry an expectation and
    # have at least one evaluation. The empty-evals guard only keeps a group that
    # has not started from failing the "at least one bad verdict must exist"
    # rule; a partially evaluated group IS checked, so per-group status is only
    # meaningful once the group is complete and should be rendered at group end.
    per_group_expectation_reports: Dict[str, VerdictReport] = {
        name: _get_verdict_report(
            skeleton, group_evals, solution, expected, subset, verification
        )
        for name, group_evals in evals_per_group.items()
        if group_evals
        and name in declared_groups
        and (expected := solution.expected_outcome_for_group(name)) is not None
    }
    per_group = {
        name: GroupOutcomeReport(
            expectedOutcome=report.expected_outcome,
            gotVerdicts=report.got_verdicts,
            status=SolutionOutcomeStatus.OK
            if report.ok
            else SolutionOutcomeStatus.UNEXPECTED_VERDICTS,
            runUnderDoubleTl=report.run_under_double_tl,
            doubleTlVerdicts=report.double_tl_verdicts,
            # Intersected with the pooled layer's: a verdict either layer
            # accepts is not worth surfacing, and testing both here means
            # nobody downstream has to know there were two.
            unexpectedNoTleVerdicts=(
                report.unexpected_no_tle_verdicts
                & verdict_report.unexpected_no_tle_verdicts
            ),
        )
        for name, report in per_group_expectation_reports.items()
    }
    failed_groups = _failed_group_names(per_group)

    has_unmatched_slow_verdict = verdict_report.has_unmatched_slow_verdict() or any(
        report.has_unmatched_slow_verdict()
        for report in per_group_expectation_reports.values()
    )
    status = (
        SolutionOutcomeStatus.OK
        if pooled_status.ok() and not failed_groups
        else SolutionOutcomeStatus.UNEXPECTED_VERDICTS
    )

    run_under_double_tl = verdict_report.run_under_double_tl or any(
        report.run_under_double_tl for report in per_group_expectation_reports.values()
    )
    double_tl_verdicts = set(verdict_report.double_tl_verdicts)
    for report in per_group_expectation_reports.values():
        double_tl_verdicts |= report.double_tl_verdicts

    max_score = 0
    got_score = 0
    got_score_per_group = {}
    if scoring == ScoreType.POINTS:
        # ``passed()`` only inspects bad verdicts, never the expectation, so a
        # report computed for the per-group layer is reusable here as-is.
        verdict_report_per_group: Dict[str, VerdictReport] = {}
        for group in skeleton.groups:
            max_score += group.score
            group_report = per_group_expectation_reports.get(group.name)
            if group_report is None:
                group_report = _get_verdict_report(
                    skeleton,
                    evals_per_group.get(group.name, []),
                    solution,
                    solution.outcome,
                    subset,
                    verification,
                )
                has_unmatched_slow_verdict = (
                    has_unmatched_slow_verdict
                    or group_report.has_unmatched_slow_verdict()
                )
            verdict_report_per_group[group.name] = group_report

        def _check_deps(group: GroupSkeleton):
            for dep in group.deps:
                dep_group = skeleton.find_group_skeleton(dep)
                if dep_group is None:
                    return False
                if not _check_deps(dep_group):
                    return False
            return verdict_report_per_group[group.name].passed()

        for group in skeleton.groups:
            if _check_deps(group):
                got_score += group.score
                got_score_per_group[group.name] = group.score

        if expected_score is not None and not fulfills_expected_score(
            expected_score, got_score
        ):
            status = SolutionOutcomeStatus.UNEXPECTED_SCORE

    limits = skeleton.get_solution_limits(solution)
    # A truncated run is read the same way a partial one is (see the docstring):
    # a solution expected to be slow that failed early for another reason never
    # reaches the testcase that would have timed out, so it looks "too fast" only
    # because the rest never ran. Blaming the limits for that is misleading.
    has_skipped_eval = any(eval.result.outcome == Outcome.SKIPPED for eval in evals)
    if (
        report_issues
        and not has_skipped_eval
        and limits.profile is None
        and has_unmatched_slow_verdict
    ):
        issue_stack.add_issue(TimingIssue())

    return SolutionOutcomeReport(
        solution=solution,
        limits=limits,
        evals=evals,
        status=status,
        pooledStatus=pooled_status,
        message=message,
        expectedOutcome=verdict_report.expected_outcome,
        gotVerdicts=verdict_report.got_verdicts,
        perGroup=per_group,
        expectedScore=expected_score,
        gotScore=got_score,
        gotScorePerGroup=got_score_per_group,
        maxScore=max_score,
        runUnderDoubleTl=run_under_double_tl,
        doubleTlVerdicts=double_tl_verdicts,
        unexpectedNoTleVerdicts=verdict_report.unexpected_no_tle_verdicts,
        sanitizerWarnings=verdict_report.has_sanitizer_warnings,
        verification=verification,
        scoring=scoring,
    )


def _print_solution_outcome(
    solution: Solution,
    skeleton: SolutionReportSkeleton,
    evals: List[Evaluation],
    console: rich.console.Console,
    verification: VerificationLevel = VerificationLevel.NONE,
    subset: bool = False,
    print_message: bool = True,
    print_scoring: bool = False,
) -> SolutionOutcomeReport:
    report = get_solution_outcome_report(
        solution, skeleton, evals, verification, subset
    )
    if not report.status:
        issue_stack.add_issue(FailedSolutionIssue(solution))
    console.print(
        report.get_outcome_markup(
            skeleton=skeleton,
            subset=subset,
            print_message=print_message,
            print_scoring=print_scoring,
        )
    )
    return report


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
        # A skipped testcase never ran, so it measures nothing: it is the
        # consequence of an earlier verdict, not evidence about how long this
        # solution takes. Dropping it here also keeps a fully skipped solution
        # out of the summary rather than reporting it as instant.
        all_evals = [
            eval for eval in all_evals if eval.result.outcome != Outcome.SKIPPED
        ]
        if not all_evals:
            continue

        # Get solution TL.
        solution_time = _get_evals_time_in_ms(all_evals)
        if solution_time is None:
            # Nothing measurable is left to summarize for this solution.
            continue
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
            # No measured runs to read the enforced TL from: fall back to the
            # solution's declared time limit. ``display_time`` keeps this value
            # even when the limit would not be enforced for a run, so there is no
            # need to re-resolve the profile from disk.
            limits = skeleton.get_solution_limits(solution)
            display_tl = limits.display_time()
            assert display_tl is not None
            tl = display_tl
            expanded_tl = display_tl
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
        # Consider every expectation the solution declares, pooled and per-group.
        # Without `outcomePerGroup` this is exactly the previous behavior, since
        # the set is then just `{solution.outcome}`.
        expectations = solution.all_expected_outcomes()
        # Get solution timings.
        if is_good(solution):
            summary.add_good(solution_time, solution)
            summary_per_language[language].add_good(solution_time, solution)
        if all(
            outcome
            in [
                ExpectedOutcome.ACCEPTED,
                ExpectedOutcome.ACCEPTED_OR_TLE,
            ]
            for outcome in expectations
        ):
            summary.add_pass(solution_time, solution)
            summary_per_language[language].add_pass(solution_time, solution)
        if any(outcome.is_slow() for outcome in expectations):
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
    gating_solutions: Optional[Set[str]] = None,
) -> bool:
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
    # `--detailed` bypasses the reporters entirely, so it has to publish the
    # report itself or `rbx run -d` would leave none behind.
    report_writer = run_report.RunReportWriter(package.get_problem_runs_dir())
    for index, solution in enumerate(result.skeleton.solutions):
        all_evals = []
        for evals in structured_evaluations[str(solution.path)].values():
            all_evals.extend(evals)

        # Resolve futures.
        all_evals = [await eval() for eval in all_evals if eval is not None]
        _print_solution_header(solution, console)
        report = _print_solution_outcome(
            solution,
            result.skeleton,
            all_evals,
            console,
            verification=verification,
            print_scoring=True,
        )
        report_writer.add(
            run_report.build_solution_report(index, result.skeleton, report)
        )
        if _gates_report(solution, gating_solutions):
            ok = ok and report.status.ok()
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


# How many lines a solution block costs beyond its group lines: the header, plus
# one row of slack for a header long enough to wrap. Used by the height guard in
# `LiveRunReporter._fits_as_block`.
_BLOCK_CHROME_LINES = 3


class TraditionalRunReporter:
    result: RunSolutionResult
    console: rich.console.Console
    verification: VerificationLevel
    structured_evaluations: StructuredEvaluation
    limits_per_solution: Dict[str, Limits]

    current_solution: Optional[Solution]
    current_group: Optional[GroupSkeleton]
    current_entry: Optional[GenerationTestcaseEntry]
    current_solution_evals: List[Evaluation]
    current_group_evals: List[Evaluation]
    current_group_evals_per_index: Dict[int, Evaluation]

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
        self.current_entry = None
        self.current_solution_evals = []
        self.current_group_evals = []
        self.current_group_evals_per_index = {}
        self.report_writer = run_report.RunReportWriter(package.get_problem_runs_dir())

    def get_limits(self, solution: Solution) -> Limits:
        return self.limits_per_solution[str(solution.path)]

    def get_current_limits(self) -> Limits:
        if self.current_solution is None:
            raise ValueError('No current solution')
        return self.get_limits(self.current_solution)

    def get_partial_report(
        self, group: GroupSkeleton
    ) -> Optional[SolutionOutcomeReport]:
        """The solution's report so far, or None when no renderer needs it.

        Computed only when something will actually be displayed from it, which is
        the group's score under POINTS scoring. Per-group expectations are not
        rendered on the group line -- the solution's verdict names the groups
        that missed theirs.

        Rendering-only, hence ``report_issues=False``: the final report at
        solution end is the one that gets to speak about the run.
        """
        if self.current_solution is None:
            return None
        if group.score <= 0:
            return None
        return get_solution_outcome_report(
            self.current_solution,
            self.result.skeleton,
            self.current_solution_evals,
            verification=self.verification,
            report_issues=False,
        )

    def get_evaluation(
        self, solution: Solution, entry: GenerationTestcaseEntry
    ) -> Optional[Deferred[Evaluation]]:
        return self.structured_evaluations[str(solution.path)][entry.group_entry.group][
            entry.group_entry.index
        ]

    def get_current_evaluation(self) -> Optional[Deferred[Evaluation]]:
        if self.current_solution is None or self.current_entry is None:
            return None
        return self.get_evaluation(self.current_solution, self.current_entry)

    def start_solution(self, solution: Solution):
        self.current_solution = solution
        self.render_solution(solution)

    def render_solution(self, solution: Solution):
        pass

    def finish_solution(self) -> bool:
        assert self.current_solution is not None
        report = self.render_solution_end(self.current_solution)
        if report is not None:
            self.report_writer.add(
                run_report.build_solution_report(
                    self.solution_index(self.current_solution),
                    self.result.skeleton,
                    report,
                )
            )
        self.current_solution = None
        self.current_solution_evals = []
        return report is None or report.status.ok()

    def render_solution_end(
        self, solution: Solution
    ) -> Optional[SolutionOutcomeReport]:
        """Render the solution's verdict, and hand back the report it rendered.

        The report is returned rather than reduced to a boolean because
        ``finish_solution`` publishes it (see ``run_report``). Recomputing it
        there instead would push every issue onto the stack a second time --
        ``get_solution_outcome_report`` reports issues unless told not to.
        """
        return None

    def solution_index(self, solution: Solution) -> int:
        """Position in the skeleton, which is also the runs directory name.

        Clients resolve artifact paths from it, so a wrong index would point at
        another solution's output -- hence the assert rather than a default.
        """
        for index, candidate in enumerate(self.result.skeleton.solutions):
            if str(candidate.path) == str(solution.path):
                return index
        raise ValueError(f'Solution {solution.path} is not in the skeleton')

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

    def start_testcase(self, entry: GenerationTestcaseEntry):
        self.current_entry = entry
        self.render_pre_evaluation(entry)

    def render_pre_evaluation(self, entry: GenerationTestcaseEntry):
        pass

    def finish_testcase(self, evaluation: Optional[Evaluation]):
        assert self.current_entry is not None
        if evaluation is not None:
            self.current_group_evals.append(evaluation)
            self.current_solution_evals.append(evaluation)
            self.current_group_evals_per_index[self.current_entry.group_entry.index] = (
                evaluation
            )
            self.render_post_evaluation(self.current_entry, evaluation)
        self.current_entry = None

    def render_post_evaluation(
        self, entry: GenerationTestcaseEntry, evaluation: Optional[Evaluation]
    ):
        pass

    def close(self) -> None:
        """Drop any live display this reporter still owns.

        Called from a `finally` around the report loop, because the loop does not
        always reach the end of a solution: a deferred can raise (a judge that
        never answered, a `Ctrl-C`), and that unwinds straight through the
        reporter. A `rich.live.Live` left started keeps the cursor hidden and
        overwrites the first lines of whatever is printed next -- which, on that
        path, is the traceback explaining what went wrong.
        """


class _SolutionBlock:
    """The live region, rebuilt from scratch on every frame that is drawn.

    `rich.live.Live` redraws the renderable it was **handed**, not one it asks
    for: `Live.refresh` re-renders `self.renderable`, the object passed to
    `update()`. Handing it a `Text` built from the clock and the board therefore
    freezes both at the moment of that call, and the display only changes when
    something calls `update()` again -- which, in this reporter, is an evaluation
    resolving.

    On a remote run that is precisely the wrong moment. The first evaluation does
    not resolve until the judge has finished the whole testrun, so the header sat
    on whatever the backend last said before the wait began -- `waiting for a
    slot` -- and then jumped straight to finished, with a clock that had never
    left `0.0s`. The entire span the setter is watching is the span in which
    nothing called `update()`.

    So `Live` is handed *this* instead: an object that renders the block afresh
    each time it is asked. The refresh thread then produces a frame that shows
    what is true now, without the reporter having to know when the interesting
    changes happen -- which it cannot know, because they happen on someone else's
    task.
    """

    def __init__(self, reporter: 'LiveRunReporter') -> None:
        self._reporter = reporter

    def __rich_console__(
        self,
        console: rich.console.Console,
        options: rich.console.ConsoleOptions,
    ) -> rich.console.RenderResult:
        yield self._reporter.block_renderable()


class LiveRunReporter(TraditionalRunReporter):
    """The reporter used whenever more than one solution is run.

    The live region spans a whole **solution**, not a group. The header line
    carries things that only become true *while* the solution runs -- how long it
    has been going, and whatever the backend running it wants said -- and a
    header printed once, before the first group, could never show any of them.
    Group lines accumulate underneath it, so the block a setter watches animate
    is the same block that ends up in scrollback.

    Non-terminal consoles (the recorded console behind ``--share``, e2e goldens,
    asciinema casts) go through this same code: ``rich.live.Live`` emits nothing
    until ``stop()`` there, so the whole solution finalizes as one frame instead
    of one frame per group. Wall-clock chips are suppressed on those consoles --
    see ``_header_chips`` -- because an elapsed time would be a diff on every
    single run.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.live: Optional[rich.live.Live] = None
        self.pre_evaluated = 0
        self.post_evaluated = 0
        # Whether this solution is being drawn as one block. False falls back to
        # the per-group Live this class used to be; see `_fits_as_block`.
        self._block = False
        self._finished_lines: List[rich.text.Text] = []
        # The group line being worked on, kept rather than pushed: the frame is
        # assembled by `block_renderable` whenever someone draws, which is mostly
        # the refresh thread rather than this reporter. See `_SolutionBlock`.
        self._current_line: Optional[rich.text.Text] = None
        self._elapsed: Optional[utils.Elapsed] = None

    # -- the block ------------------------------------------------------------

    def _fits_as_block(self) -> bool:
        """Whether the whole solution can be drawn as one live region.

        A live region taller than the terminal is not merely ugly: rich redraws
        it by moving the cursor back up over its own output, so a block that does
        not fit either flickers or leaves torn copies of itself behind. A package
        with more groups than the terminal has rows therefore falls back to the
        per-group Live, which is exactly the behaviour that shipped before this
        block existed -- a degradation, but a familiar one.

        Not a question worth asking on a non-terminal console: nothing is
        animated there, `Live` emits one frame at `stop()`, and the height rich
        reports for a file is a default rather than a measurement.
        """
        if not self.console.is_terminal:
            return True
        return len(self.result.skeleton.groups) + _BLOCK_CHROME_LINES <= (
            self.console.height
        )

    def _header_chips(self, solution: Solution) -> List[rich.text.Text]:
        """The live annotations on the solution header, left to right.

        The wall clock first, then whatever the backend running this solution has
        put on the board -- a testrun id, a queue state, a cache hit. The
        reporter renders those verbatim and knows nothing about what they mean;
        see `runners.base.RunProgress`.

        The clock renders on a terminal only. A shared report, an e2e golden and
        an asciinema cast are all non-terminal consoles, and an elapsed time in
        any of them turns every re-run into a diff. Backend chips are not
        wall-clock and do render there: a setter reading a shared report wants to
        know which testrun produced its numbers.
        """
        chips: List[rich.text.Text] = []
        if self._elapsed is not None and self.console.is_terminal:
            chips.append(rich.text.Text(str(self._elapsed), style='bright_black'))
        for chip in self.result.progress_board.get(str(solution.path)):
            chips.append(rich.text.Text(chip.text, style=chip.style))
        return chips

    def _header_line(self, solution: Solution) -> rich.text.Text:
        solution_skeleton = self.result.skeleton.find_solution_skeleton(solution)
        assert solution_skeleton is not None
        line = rich.text.Text.from_markup(
            f'{solution_skeleton.href()} ({solution_skeleton.runs_dir_href()})'
        )
        for chip in self._header_chips(solution):
            line.append(rich.text.Text(' · ', style='bright_black'))
            line.append(chip)
        return line

    def _group_line(self, finished: bool = False) -> rich.text.Text:
        """One group's line: its name, the verdicts worth showing, its extremes."""
        assert self.current_group is not None
        renderable = rich.text.Text.from_markup(
            f'[bstatus]{self.current_group.name} ({len(self.current_group.testcases)})[/bstatus] '
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

        bracketed = f'{get_capped_evals_formatted_time(self.get_current_limits(), self.current_group_evals, self.verification)}, {get_evals_formatted_memory(self.current_group_evals)}'
        renderable.append(
            rich.text.Text.from_markup(
                f'({bracketed})',
                style='bright_black',
                end='',
            )
        )
        # Only at group end: mid-run, the group's score is not settled yet.
        partial_report = (
            self.get_partial_report(self.current_group) if finished else None
        )
        if partial_report is not None:
            got_score = partial_report.gotScorePerGroup.get(self.current_group.name, 0)
            renderable.append(
                rich.text.Text.from_markup(
                    f' {get_solution_score_markup(got_score, self.current_group.score, pts=True)}',
                    end='',
                )
            )
        return renderable

    def block_renderable(self) -> rich.console.RenderableType:
        """The whole block as it stands right now.

        Called by `_SolutionBlock` on every drawn frame, which means it is called
        from `rich`'s refresh thread as well as from this reporter. It only reads
        -- the header off `self.current_solution`, the clock off `self._elapsed`,
        the chips off the board -- and the board hands back a tuple, so a write
        landing mid-frame cannot be seen half-applied.
        """
        if self.current_solution is None:
            return rich.text.Text('')
        rows: List[rich.console.RenderableType] = [
            self._header_line(self.current_solution)
        ]
        # Copied, because the list is appended to from the reporter while this
        # may be running on the refresh thread.
        for line in list(self._finished_lines):
            rows.append(rich.padding.Padding(line, (0, 0, 0, 2)))
        current = self._current_line
        if current is not None:
            rows.append(rich.padding.Padding(current, (0, 0, 0, 2)))
        return rich.console.Group(*rows)

    def _render(self, current: Optional[rich.text.Text]) -> None:
        """Record the current group line and ask for a repaint.

        Deliberately not "build a frame and hand it to `Live`": in block mode the
        frame is built by `block_renderable`, so that the frames nobody here
        triggers -- the ones the refresh thread produces while a judge is
        thinking -- are as current as the ones that come from an evaluation.
        """
        self._current_line = current
        if self.live is None:
            return
        if not self._block:
            if current is not None:
                self.live.update(current, refresh=True)
            return
        self.live.refresh()

    def _update_live(self, finished: bool = False):
        if self.live is None or self.current_group is None:
            return
        self._render(self._group_line(finished))

    # -- lifecycle ------------------------------------------------------------

    def render_solution(self, solution: Solution):
        self._elapsed = utils.Elapsed()
        self._finished_lines = []
        self._current_line = None
        self._block = self._fits_as_block()
        if not self._block:
            solution_skeleton = self.result.skeleton.find_solution_skeleton(solution)
            assert solution_skeleton is not None
            _print_solution_header(
                solution_skeleton,
                self.console,
            )
            return
        self.live = rich.live.Live(
            _SolutionBlock(self),
            console=self.console,
            # The elapsed chip has to repaint with nothing else happening, which
            # is the whole point of it during a remote run. Off on a non-terminal
            # console, which emits one frame at `stop()` regardless: a refresh
            # thread there would spin for frames nobody ever sees.
            auto_refresh=self.console.is_terminal,
            refresh_per_second=4,
            vertical_overflow='visible',
        )
        self.live.start()
        self._render(None)

    def render_solution_end(
        self, solution: Solution
    ) -> Optional[SolutionOutcomeReport]:
        self._stop_live()
        self._elapsed = None
        report = _print_solution_outcome(
            solution,
            self.result.skeleton,
            self.current_solution_evals,
            self.console,
            verification=self.verification,
            print_message=True,
        )
        self.console.print()
        return report

    def _stop_live(self) -> None:
        """Freeze whatever is live right now. Idempotent, and safe to call late.

        Called from `render_solution_end` on the happy path and from `close()`
        when a run never reaches one -- a deferred that raises (a judge that
        never answered, a Ctrl-C) unwinds straight through the reporter, and a
        `Live` left started leaves the cursor hidden and eats the first lines of
        the traceback that follows.
        """
        if self.live is None:
            return
        self.live.stop()
        self.live = None
        # On a real terminal, Live.stop() advances to a new line. On a
        # non-terminal console (e.g. when capturing the report to share it) it
        # finalizes without a trailing newline, so what follows would otherwise
        # run into the last line of the block; emit one explicitly.
        if not self.console.is_terminal:
            self.console.print()

    def close(self) -> None:
        self._stop_live()

    def render_group(self, group: GroupSkeleton):
        self.pre_evaluated = 0
        self.post_evaluated = 0
        if not self._block:
            self.live = rich.live.Live(console=self.console, auto_refresh=False)
            self.live.start()
        self._update_live()

    def render_group_end(self, group: GroupSkeleton):
        assert self.live is not None
        line = self._group_line(finished=True)
        if self._block:
            # Kept as a rendered line rather than recomputed on every later
            # frame: `finish_group` clears the evals behind it the moment this
            # returns, so this is the last point at which it can be drawn.
            self._finished_lines.append(line)
            self._render(None)
            return
        self.live.update(line, refresh=True)
        self._stop_live()

    def render_pre_evaluation(self, entry: GenerationTestcaseEntry):
        self.pre_evaluated = entry.group_entry.index + 1
        self._update_live()

    def render_post_evaluation(
        self, entry: GenerationTestcaseEntry, evaluation: Optional[Evaluation]
    ):
        self.post_evaluated = entry.group_entry.index + 1
        self._update_live()


class SingleSolutionRunReporter(TraditionalRunReporter):
    """The reporter used when exactly one solution runs.

    Deliberately **not** a live block. It prints a line per testcase, so the
    region that would have to stay live is as tall as the testset -- the case
    `LiveRunReporter._fits_as_block` refuses. The wall clock is reported once, at
    the end, instead of ticking.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._elapsed: Optional[utils.Elapsed] = None

    def render_solution(self, solution: Solution):
        self._elapsed = utils.Elapsed()
        solution_skeleton = self.result.skeleton.find_solution_skeleton(solution)
        assert solution_skeleton is not None
        _print_solution_header(solution_skeleton, self.console)
        self.console.print()

    def render_solution_end(
        self, solution: Solution
    ) -> Optional[SolutionOutcomeReport]:
        report = _print_solution_outcome(
            solution,
            self.result.skeleton,
            self.current_solution_evals,
            self.console,
            verification=self.verification,
            print_message=False,
        )
        # Terminal only, for the same reason the live chip is: a shared report,
        # an e2e golden and a cast are all non-terminal, and a wall clock in any
        # of them is a diff on every run.
        if self._elapsed is not None and self.console.is_terminal:
            self.console.print(f'[status]Ran in[/status] {self._elapsed}.')
        self._elapsed = None
        self.console.print()
        return report

    def render_group_end(self, group: GroupSkeleton):
        self.console.print(f'  [status]{group.name}[/status]', end=' ')
        bracketed = f'{get_capped_evals_formatted_time(self.get_current_limits(), self.current_group_evals, self.verification)}, {get_evals_formatted_memory(self.current_group_evals)}'
        self.console.print(f'({bracketed})', end='')
        partial_report = self.get_partial_report(group)
        if partial_report is not None:
            got_score = partial_report.gotScorePerGroup.get(group.name, 0)
            self.console.print(
                f' {get_solution_score_markup(got_score, group.score, pts=True)}',
                end='',
            )
        self.console.print()
        self.console.print()

    def render_post_evaluation(
        self, entry: GenerationTestcaseEntry, evaluation: Optional[Evaluation]
    ):
        if evaluation is None:
            return
        assert self.current_group is not None
        self.console.print(get_testcase_markup_verdict(evaluation), end=' ')
        self.console.print(f'{entry}', end='')
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


def _gates_report(solution: Solution, gating_solutions: Optional[Set[str]]) -> bool:
    """Whether this solution's outcome decides the report's pass/fail verdict."""
    return gating_solutions is None or str(solution.path) in gating_solutions


async def print_run_report(
    result: RunSolutionResult,
    console: rich.console.Console,
    verification: VerificationLevel,
    detailed: bool = False,
    timing: bool = True,
    skip_printing_limits: bool = False,
    gating_solutions: Optional[Set[str]] = None,
) -> bool:
    """Run every tracked solution and report it.

    ``gating_solutions`` restricts which solutions decide the returned verdict: every
    solution is still run and reported, but only these ones can make it fail.
    Time limit inference uses it to run solutions that are *expected* to hit the
    cap without their timeouts aborting the estimate. ``None`` gates on all of
    them.

    ``timing`` drops the timing summary, in both the detailed and the plain
    report. Pass ``False`` when the run may stop early: every line of that
    summary is an extreme over the solutions, and a solution that did not run to
    the end only measures a lower bound.
    """
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
            gating_solutions=gating_solutions,
        )

    ok = True

    try:
        for solution in result.skeleton.solutions:
            reporter.start_solution(solution)
            for group in result.skeleton.groups:
                reporter.start_group(group)
                entries = result.skeleton.get_entries_for_group(group.name)
                for entry in entries:
                    reporter.start_testcase(entry)
                    eval = reporter.get_current_evaluation()
                    evaled = None
                    if eval is not None:
                        evaled = await eval()
                    reporter.finish_testcase(evaled)
                reporter.finish_group()
            cur_ok = reporter.finish_solution()
            if _gates_report(solution, gating_solutions):
                ok = ok and cur_ok
    finally:
        # Awaiting a deferred can raise -- a remote judge that never answered, a
        # Ctrl-C mid-run -- and the reporter holds a live display that has to be
        # torn down before anything else reaches the terminal.
        reporter.close()

    if not single_solution and timing:
        await _print_timing(
            console,
            result.skeleton,
            reporter.structured_evaluations,
        )

    return ok
