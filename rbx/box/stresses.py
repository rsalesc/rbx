import datetime
import heapq
import pathlib
import random
import secrets
import shutil
import signal
import threading
import time
from shutil import rmtree
from typing import Dict, List, Optional, Tuple, Union

import async_lru
import typer
import yaml
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import (
    checkers,
    generators,
    package,
    stress_manifest,
    tasks,
    validators,
)
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
    Solution,
    Stress,
    TaskType,
    Testcase,
)
from rbx.box.solutions import (
    compile_solutions,
    expand_solutions,
    get_outcome_style_verdict,
)
from rbx.box.stressing import finder_parser
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.grading.steps import (
    CompilationError,
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


async def _compile_finder(finder: Checker) -> str:
    try:
        digest = await checkers.compile_checker(custom_checker=finder)
    except:
        console.console.print(
            f'[error]Failed compiling checker {finder.href()}.[/error]'
        )
        raise
    return digest


def _renumber_slowest_findings(
    findings_dir: pathlib.Path, old_indices: List[int]
) -> None:
    """Move the finding directories `old_indices` to `1..n`, in that order."""
    temp_dir = findings_dir.parent / '.temp_findings'
    rmtree(str(temp_dir), ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Move all candidates to temp directory
    for old_index in old_indices:
        old_path = findings_dir / str(old_index)
        if old_path.exists():
            shutil.move(str(old_path), str(temp_dir / str(old_index)))

    # Clean findings directory to avoid leftovers
    rmtree(str(findings_dir), ignore_errors=True)
    findings_dir.mkdir(parents=True, exist_ok=True)

    # Move back with new numbering
    for new_index, old_index in enumerate(old_indices, start=1):
        temp_path = temp_dir / str(old_index)
        if temp_path.exists():
            shutil.move(str(temp_path), str(findings_dir / str(new_index)))

    rmtree(str(temp_dir), ignore_errors=True)


def _keep_finding_artifacts(
    finding_index: int,
    input_path: pathlib.Path,
    answer_path: Optional[pathlib.Path],
    evaluations: Dict[int, Evaluation],
) -> None:
    """Copy a finding out of the scratch area, before the next iteration
    overwrites it.

    `evaluations` maps a solution index to its last evaluation this iteration,
    which is the one whose artifacts are on disk. Each lands as
    `<index>.out|.err|.eval`, the shapes a regular run writes, with the `.eval`
    pointing at the kept copies rather than at the scratch files.
    """
    directory = stress_manifest.finding_dir(finding_index)
    rmtree(str(directory), ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_path, stress_manifest.finding_input_path(finding_index))
    if answer_path is not None and answer_path.is_file():
        shutil.copyfile(answer_path, stress_manifest.finding_answer_path(finding_index))

    for index, evaluation in sorted(evaluations.items()):
        out_path = directory / f'{index}.out'
        for src, dst in (
            (evaluation.log.stdout_absolute_path, out_path),
            (evaluation.log.stderr_absolute_path, out_path.with_suffix('.err')),
        ):
            if src is not None and src.is_file():
                shutil.copyfile(src, dst)
        _write_kept_evaluation(out_path, evaluation)


def _write_kept_evaluation(out_path: pathlib.Path, evaluation: Evaluation) -> None:
    """Write a finding's `.eval`, pointing at the files beside it."""
    kept = evaluation.model_copy(deep=True)
    directory = out_path.parent
    answer = directory / stress_manifest.FINDING_ANSWER_FILENAME
    err_path = out_path.with_suffix('.err')
    kept.testcase.input = (
        directory / stress_manifest.FINDING_INPUT_FILENAME
    ).absolute()
    kept.testcase.output = answer.absolute() if answer.is_file() else None
    kept.log.stdout_absolute_path = out_path.absolute() if out_path.is_file() else None
    kept.log.stderr_absolute_path = err_path.absolute() if err_path.is_file() else None
    kept.log.log_absolute_path = None
    kept.log.checker_stderr_absolute_path = None
    tasks.write_evaluation(kept, out_path)


def _repoint_kept_evaluations(directory: pathlib.Path) -> None:
    """Rewrite the `.eval`s of a finding directory that was moved."""
    for eval_path in directory.glob('*.eval'):
        evaluation = Evaluation.model_validate(yaml.safe_load(eval_path.read_text()))
        _write_kept_evaluation(eval_path.with_suffix('.out'), evaluation)


def _finding_results(
    results: List[finder_parser.FinderResult], solution_index: Dict[str, int]
) -> List[stress_manifest.StressSolutionResult]:
    """One result per solution, in finder order, with its worst outcome."""
    by_solution: Dict[int, List[finder_parser.FinderResult]] = {}
    for result in results:
        index = solution_index[str(result.solution.path)]
        by_solution.setdefault(index, []).append(result)

    entries = []
    for index, solution_results in by_solution.items():
        log = solution_results[-1].solution_log
        entries.append(
            stress_manifest.StressSolutionResult(
                solution=index,
                outcome=Outcome.worst_outcome(r.outcome for r in solution_results),
                time=log.time if log is not None else None,
                memory=log.memory if log is not None else None,
            )
        )
    return entries


def _generator_expression(call: GeneratorCall) -> str:
    return ' '.join(part for part in (call.name, call.args) if part)


class _StressSession:
    """The bookkeeping of one stress session, and its publication.

    The single source of truth for the findings: the manifest on disk and the
    `StressReport` handed back to the caller are both derived from it, so they
    cannot disagree.
    """

    # Counters are republished at most this often (seconds).
    TICK_INTERVAL = 1.0

    def __init__(
        self,
        spec: stress_manifest.StressSpec,
        solutions: List[Solution],
        find_slowest: bool,
        findings_limit: int,
    ):
        self.find_slowest = find_slowest
        self.findings_limit = findings_limit
        self.executed = 0
        self.skipped = 0
        self._solution_index = {
            str(solution.path): i for i, solution in enumerate(solutions)
        }
        # Findings are numbered from 1. In `--slowest` mode the number is only
        # a unique key while the stress runs; `renumber` makes it 1..n.
        self._counter = 0
        # `--slowest` only: a min-heap of (duration, index) for the candidates.
        self._heap: List[Tuple[int, int]] = []
        self._started = time.monotonic()
        self._last_publish = self._started
        self._finished = False
        self._path = stress_manifest.manifest_path().absolute()
        self.manifest = stress_manifest.StressManifest(
            state=stress_manifest.StressState.RUNNING,
            spec=spec,
            startedAt=datetime.datetime.now().astimezone(),
            solutions=[str(solution.path) for solution in solutions],
        )
        self.publish()
        stress_manifest.begin_session(self._path)

    @property
    def found(self) -> int:
        return len(self.manifest.findings)

    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def is_done(self) -> bool:
        return not self.find_slowest and self.found >= self.findings_limit

    def is_too_fast(self, duration: int) -> bool:
        """Whether a `--slowest` candidate would not make the cut."""
        return (
            self.find_slowest
            and len(self._heap) >= self.findings_limit
            and duration <= self._heap[0][0]
        )

    def add_finding(
        self,
        generator: GeneratorCall,
        duration: int,
        results: List[finder_parser.FinderResult],
        input_path: pathlib.Path,
        answer_path: Optional[pathlib.Path],
        evaluations: Dict[int, Evaluation],
    ) -> None:
        self._counter += 1
        index = self._counter
        _keep_finding_artifacts(index, input_path, answer_path, evaluations)
        self.manifest.findings.append(
            stress_manifest.StressFindingEntry(
                index=index,
                generator=generator,
                duration=duration,
                results=_finding_results(results, self._solution_index),
            )
        )
        if self.find_slowest:
            if len(self._heap) < self.findings_limit:
                heapq.heappush(self._heap, (duration, index))
            else:
                _, evicted = heapq.heappushpop(self._heap, (duration, index))
                self._evict(evicted)
        self.publish()

    def _evict(self, index: int) -> None:
        rmtree(str(stress_manifest.finding_dir(index)), ignore_errors=True)
        self.manifest.findings = [
            entry for entry in self.manifest.findings if entry.index != index
        ]

    def tick(self) -> None:
        """Republish the counters, if the last write is old enough."""
        if time.monotonic() - self._last_publish >= self.TICK_INTERVAL:
            self.publish()

    def publish(self) -> None:
        self.manifest.elapsed = self.elapsed()
        self.manifest.executed = self.executed
        self.manifest.skipped = self.skipped
        stress_manifest.write_manifest(self.manifest, self._path)
        self._last_publish = time.monotonic()

    def renumber(self) -> None:
        """`--slowest` only: number the kept candidates 1..n, slowest first."""
        if not self.find_slowest or not self.manifest.findings:
            return
        ordered = sorted(
            self.manifest.findings,
            key=lambda entry: (-(entry.duration or 0), entry.index),
        )
        _renumber_slowest_findings(
            stress_manifest.findings_dir(), [entry.index for entry in ordered]
        )
        self.manifest.findings = [
            entry.model_copy(update={'index': new_index})
            for new_index, entry in enumerate(ordered, start=1)
        ]
        for entry in self.manifest.findings:
            _repoint_kept_evaluations(stress_manifest.finding_dir(entry.index))

    def finish(self, state: stress_manifest.StressState) -> None:
        """Publish the final state. Never raises: this runs in a `finally`, and
        must not replace whatever ended the session.

        Only the first call counts: once a termination signal has stamped the
        session (`abandon`), the `finally` that runs on the way out must not
        overwrite it."""
        if self._finished:
            return
        self._finished = True
        self.manifest.state = state
        try:
            self.publish()
        except Exception as e:
            console.console.print(
                f'[warning]Could not write the stress manifest: {e}[/warning]'
            )
        stress_manifest.end_session()

    def abandon(self, state: stress_manifest.StressState) -> None:
        """`finish`, from a signal handler: silent, since the terminal may be
        gone, and never raises."""
        if self._finished:
            return
        self._finished = True
        self.manifest.state = state
        try:
            self.publish()
        except Exception:
            pass
        stress_manifest.end_session()

    def report(self) -> 'StressReport':
        return StressReport(
            findings=[
                StressFinding(generator=entry.generator, duration=entry.duration)
                for entry in self.manifest.findings
            ],
            executed=self.executed,
            skipped=self.skipped,
        )


class _SigintStop:
    """Turn the first Ctrl-C into a request to stop, the second into an abort.

    The stress loop awaits its sandbox runs directly, so a `KeyboardInterrupt`
    raised by the default handler surfaces wherever the main thread happens to
    be waiting -- under the CLI that is the outermost event loop, outside
    `run_stress`, which would then never get to finish its session. A flag the
    loop polls lets it stop between steps instead, and still report what it
    found. Only the main thread can install signal handlers; elsewhere this is a
    no-op and Ctrl-C behaves as before.
    """

    def __init__(self):
        self.requested = False
        self._announced = False
        self._previous = None
        self._installed = False

    def __enter__(self) -> '_SigintStop':
        if threading.current_thread() is threading.main_thread():
            previous = signal.getsignal(signal.SIGINT)
            # `None` means a handler not installed from Python; there is no way
            # to put that back, so fall back to Python's own.
            self._previous = (
                previous if previous is not None else signal.default_int_handler
            )
            signal.signal(signal.SIGINT, self._handle)
            self._installed = True
        return self

    def _handle(self, signum, frame):
        if self.requested:
            self._restore()
            raise KeyboardInterrupt()
        # Only a flag: printing here could interleave with a live status line.
        self.requested = True

    def check(self) -> bool:
        """Whether a stop was requested, announcing it the first time it is
        seen, from the loop rather than from the signal handler."""
        if self.requested and not self._announced:
            self._announced = True
            console.console.print(
                '[warning]Stopping after the current test. '
                'Press Ctrl-C again to abort immediately.[/warning]'
            )
        return self.requested

    def _restore(self) -> None:
        if self._installed:
            signal.signal(signal.SIGINT, self._previous)
            self._installed = False

    def __exit__(self, *args) -> None:
        self._restore()


class _StampOnTermination:
    """End the session as `interrupted` on SIGTERM or SIGHUP, then exit.

    This is how the VS Code extension stops a stress: it terminates the task,
    which kills the terminal (SIGHUP to the process group) or sends SIGTERM.
    Python's default for both is to die on the spot, leaving the manifest
    `running` forever. There is no waiting for the current iteration here --
    whoever asked is not going to read a report -- and nothing is printed, since
    the terminal may already be gone. Main thread only, like any handler.
    """

    SIGNALS = tuple(
        getattr(signal, name) for name in ('SIGTERM', 'SIGHUP') if hasattr(signal, name)
    )

    def __init__(self, session: _StressSession):
        self._session = session
        self._previous: Dict[int, object] = {}

    def __enter__(self) -> '_StampOnTermination':
        if threading.current_thread() is threading.main_thread():
            for signum in self.SIGNALS:
                self._previous[signum] = signal.getsignal(signum)
                signal.signal(signum, self._handle)
        return self

    def _handle(self, signum, frame):
        self._restore()
        self._session.abandon(stress_manifest.StressState.INTERRUPTED)
        raise SystemExit(128 + signum)

    def _restore(self) -> None:
        previous, self._previous = self._previous, {}
        for signum, handler in previous.items():
            # `None` means a handler not installed from Python: the default.
            signal.signal(signum, handler if handler is not None else signal.SIG_DFL)

    def __exit__(self, *args) -> None:
        self._restore()


def _get_reference_solution(reference_solution: Optional[str]) -> Optional[Solution]:
    if reference_solution is not None:
        return expand_solutions([reference_solution])[0]
    return package.get_main_solution()


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
    fuzz: Optional[Union[List[str], bool]] = None,
    validate: bool = True,
    reference_solution: Optional[str] = None,
) -> StressReport:
    pkg = package.find_problem_package_or_die()
    ref_sol = _get_reference_solution(reference_solution)
    # The declared stress being run, if any; published in the manifest.
    declared_name: Optional[str] = None
    if ref_sol is not None:
        console.console.print(f'Using {ref_sol.href()} as reference solution.')

    if fuzz is not None and generator_call is not None:
        console.console.print(
            '[error]You cannot specify both a generator call (with [item]-g[/item]) and fuzzing (with [item]--fuzz[/item]).[/error]'
        )
        raise typer.Exit(1)

    if finder:
        if generator_call is None and fuzz is None:
            console.console.print(
                '[error]Generator arguments are required for stress testing. Specify them through the [item]-g[/item] flag, or use [item]--fuzz[/item] to fuzz existing testgroups.[/error]'
            )
            raise typer.Exit(1)

        if generator_call:
            generator = generators.get_call_from_string(generator_call)
            stress = Stress(
                name=f'{pathlib.Path(generator.name).stem}',
                generator=generator,
                finder=finder,
            )
        else:
            # Placeholder stress object for fuzzing, will be populated in the loop
            stress = Stress(
                name='fuzz',
                generator=GeneratorCall(name='fuzz'),
                finder=finder,
            )
    else:
        if fuzz is not None:
            # Implicit finder mode for fuzzing
            # Default to checking against the main solution if available
            main_sol = package.get_main_solution()
            if not main_sol:
                console.console.print(
                    '[error]Fuzzing without a finder requires at least one solution to verify against.[/error]'
                )
                raise typer.Exit(1)

            stress = Stress(
                name='fuzz',
                generator=GeneratorCall(name='fuzz'),
                finder=str(main_sol.path),
            )
        elif name is None:
            console.console.print(
                '[error]Invalid stress test paramaters. Either provide a stress test name, or provide a finder expression (-f) and generator arguments (-g).[/error]'
            )
            raise typer.Exit(1)
        else:
            stress = package.get_stress(name)
            declared_name = stress.name

    generator_candidates = []
    if fuzz is not None:
        # Fuzz tests should force skipping invalid testcases.
        skip_invalid_testcases = True

        fuzz_groups_msg = 'all testgroups'
        fuzz_set = None
        if isinstance(fuzz, list):
            fuzz_groups_msg = ', '.join(fuzz)
            fuzz_set = set(fuzz)

        console.console.print(f'[info]Fuzzing testgroups: {fuzz_groups_msg}[/info]')
        # We need to extract potential generator calls from the specified groups
        # We can't use async calls here easily before the loop if we want to keep structure simple,
        # but extract_generation_testcases_from_groups is async.
        # However, run_stress is async, so we can await it!

        testcases = await extract_generation_testcases_from_groups(fuzz_set)
        for tc in testcases:
            if tc.metadata.generator_call:
                generator_candidates.append(tc.metadata.generator_call)

        if not generator_candidates:
            console.console.print(
                f'[error]No generator calls found in testgroups: {fuzz_groups_msg}[/error]'
            )
            raise typer.Exit(1)
        console.console.print(
            f'[info]Found {len(generator_candidates)} generator calls to fuzz.[/info]'
        )

    call = stress.generator
    if fuzz is None:
        generator = package.get_generator(call.name)
        if progress:
            progress.update('Compiling generator...')
        try:
            generator_digest = await compile_item(
                generator, sanitized=SanitizationLevel.PREFER
            )
        except:
            console.console.print(
                f'[error]Failed compiling generator [item]{generator.name}[/item].[/error]'
            )
            raise
    else:
        # For fuzzing, we might need multiple generators.
        # But usually all generators in a package are compiled together or we can compile them on demand?
        # compile_item creates a digest for a specific item.
        # If we have multiple generators, we might switch between them.
        # Ideally we should compile ALL generators used in candidates.
        # For simplicity, let's compile the generator for the CHOSEN call in the loop if it changes,
        # OR pre-compile all unique generators found.

        unique_generators = set(c.name for c in generator_candidates)
        generator_digests = {}
        if progress:
            progress.update('Compiling generators for fuzzing...')

        for gen_name in unique_generators:
            gen_item = package.get_generator(gen_name)
            try:
                if progress:
                    progress.update(f'Compiling generator [item]{gen_name}[/item]...')
                generator_digests[gen_name] = await compile_item(
                    gen_item, sanitized=SanitizationLevel.PREFER
                )
            except CompilationError:
                console.console.print(
                    f'[warning]Failed compiling generator [item]{gen_name}[/item], skipping it.[/warning]'
                )
                continue

        if not generator_digests:
            console.console.print(
                '[error]No generators could be compiled, halting fuzz tests.[/error]'
            )
            raise typer.Exit(1)

    # Finder expression parser
    parsed_finder = finder_parser.parse(stress.finder, ref_sol)

    solutions = finder_parser.get_all_solution_items(parsed_finder, ref_sol)
    finders = finder_parser.get_all_checker_items(parsed_finder)
    needs_expected_output = finder_parser.needs_expected_output(parsed_finder)
    eval_only_outcome = (
        ExpectedOutcome.ANY if find_slowest else ExpectedOutcome.INCORRECT
    )

    solution_indices = {solution: i for i, solution in enumerate(solutions)}
    solutions_digest = await compile_solutions(
        tracked_solutions=set(str(solution.path) for solution in solutions),
        sanitized=sanitized,
    )
    if progress:
        progress.update('Compiling finders...')
    finders_digest = {}
    for finder_item in finders:
        finders_digest[str(finder_item.path)] = await _compile_finder(finder_item)

    interactor_digest = None
    if pkg.type == TaskType.COMMUNICATION:
        interactor_digest = await checkers.compile_interactor(progress=progress)

    all_validators = package.get_all_validators()
    if validators:
        if progress:
            progress.update('Compiling validators...')
        validators_digests = await validators.compile_validators(
            all_validators, progress=progress
        )
    else:
        validators_digests = {}

    # Use limits if we are not in find_slowest mode or if we have double TL explicitly
    # specified.
    use_timelimit = not find_slowest or (limits is not None and limits.isDoubleTL)

    if limits is not None:
        if not use_timelimit:
            limits.time = None
        console.console.print(
            '[bstatus]Running stress tests with the following limits:[/bstatus]'
        )
        console.console.print(limits)

    # Erase old stress directory
    stress_dir = stress_manifest.stress_dir()
    rmtree(str(stress_dir), ignore_errors=True)
    stress_dir.mkdir(parents=True, exist_ok=True)
    empty_path = stress_dir / '.empty'
    empty_path.write_text('')

    spec_fuzz: Optional[List[str]] = None
    if fuzz is not None:
        spec_fuzz = list(fuzz) if isinstance(fuzz, list) else []
    session = _StressSession(
        stress_manifest.StressSpec(
            name=declared_name,
            generator=_generator_expression(stress.generator) if fuzz is None else None,
            finder=stress.finder,
            fuzz=spec_fuzz,
            slowest=find_slowest,
            timeout=timeout_in_seconds,
            findingsLimit=findings_limit,
            timelimit=limits.time if limits is not None else None,
            doubleTL=limits.isDoubleTL if limits is not None else False,
        ),
        solutions,
        find_slowest=find_slowest,
        findings_limit=findings_limit,
    )

    only_call: Optional[str] = None
    has_diff_call = False
    duplicate_call_error = False
    eval_calls = finder_parser.get_all_eval_calls(parsed_finder)

    # Whatever happens, the manifest ends in a final state: a reader must never
    # be left with a `running` session no process is running.
    final_state = stress_manifest.StressState.FAILED
    try:
        with _SigintStop() as stop, _StampOnTermination(session):
            interrupted = False
            try:
                while not stop.check():
                    # Check for timeout first
                    if session.elapsed() > timeout_in_seconds:
                        break

                    # If not in find_slowest mode, check if we reached the limit
                    if session.is_done():
                        break

                    if print_descriptors:
                        utils.print_open_fd_count()

                    session.tick()
                    session.executed += 1

                    if progress:
                        seconds = timeout_in_seconds - int(session.elapsed())
                        skipped_str = (
                            f'skipped [item]{session.skipped}[/item], '
                            if session.skipped
                            else ''
                        )
                        progress.update(
                            f'Stress testing: found [item]{session.found}[/item] tests, '
                            f'executed [item]{session.executed}[/item], '
                            f'{skipped_str}'
                            f'[item]{seconds}[/item] second(s) remaining...'
                        )

                    input_path = stress_dir / 'input'
                    input_path.parent.mkdir(parents=True, exist_ok=True)

                    if fuzz is not None:
                        base_call = random.choice(generator_candidates)
                        fuzz_suffix = secrets.token_hex(4)
                        # Append fuzz suffix to args
                        new_args = str(base_call.args or '') + ' ' + fuzz_suffix
                        expanded_generator_call = GeneratorCall(
                            name=base_call.name, args=new_args.strip()
                        )
                        generator_digest = generator_digests[base_call.name]
                    else:
                        expanded_generator_call = expand_generator_call(
                            stress.generator
                        )

                    if (
                        only_call is not None
                        and str(expanded_generator_call) != only_call
                    ):
                        has_diff_call = True
                    only_call = str(expanded_generator_call)

                    if not has_diff_call and session.executed % 10 == 0:
                        console.console.print(
                            f'[warning]Generator call [item]{only_call}[/item] was repeated [item]{session.executed}[/item] times.[/warning]'
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
                            validate=validate,
                        )
                    except (ValidationError, GenerationError) as err:
                        if skip_invalid_testcases:
                            session.skipped += 1
                            continue
                        with err:
                            err.print('[warning]Invalid testcase generated.[/warning]')
                            err.print(
                                '[warning]You can use the [item]--skip[/item] flag to skip invalid testcases without halting.[/warning]'
                            )
                    if stop.check():
                        break

                    # The last evaluation of each solution this iteration: the
                    # one whose artifacts are in the scratch area right now.
                    iteration_evals: Dict[int, Evaluation] = {}

                    @async_lru.alru_cache(maxsize=None)
                    async def run_solution_fn(
                        solution: Solution,
                        checker_digest: Optional[str] = None,
                        input_path=input_path,
                        output_path: Optional[pathlib.Path] = None,
                        iteration_evals=iteration_evals,
                    ) -> Evaluation:
                        index = solution_indices[solution]
                        evaluation = await tasks.run_solution_on_testcase(
                            solution,
                            compiled_digest=solutions_digest[solution.path],
                            checker_digest=checker_digest,
                            interactor_digest=interactor_digest,
                            testcase=Testcase(
                                inputPath=input_path, outputPath=output_path
                            ),
                            output_dir=input_path.parent,
                            filestem=f'{index}',
                            is_stress=True,
                            limits_override=limits,
                            use_timelimit=use_timelimit,
                        )
                        iteration_evals[index] = evaluation
                        return evaluation

                    # Get main solution output.
                    expected_output_path = empty_path
                    answer_path: Optional[pathlib.Path] = None
                    if needs_expected_output:
                        eval = await run_solution_fn(solutions[0])
                        if stop.check():
                            break
                        if eval.result.outcome != Outcome.ACCEPTED:
                            console.console.print(
                                f'[error]Error while generating main solution output for stress with args [item]{expanded_generator_call.name} {expanded_generator_call.args}[/item].[/error]'
                            )
                            console.console.print(
                                f'Input written at [item]{input_path}[/item]'
                            )
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
                            shutil.copyfile(
                                eval.log.stdout_absolute_path, expected_output_path
                            )
                            answer_path = expected_output_path
                        else:
                            expected_output_path = None

                    async def run_solution_and_checker_fn(
                        call: finder_parser.FinderCall,
                        expected_output_path=expected_output_path,
                    ) -> finder_parser.FinderResult:
                        checker = call.checker
                        checker_digest = (
                            finders_digest[checker.path]
                            if checker is not None
                            else None
                        )
                        eval = await run_solution_fn(
                            call.solution,
                            checker_digest=checker_digest,
                            output_path=expected_output_path,
                        )

                        return finder_parser.FinderResult(
                            solution=call.solution,
                            outcome=eval.result.outcome,
                            checker=call.checker,
                            solution_log=eval.log,
                            checker_result=eval.result,
                        )

                    # The finder runner is synchronous and evaluates every call
                    # in the expression anyway, so run them all up front and
                    # hand it the results.
                    call_results = {}
                    # Once the finder calls start, the iteration is let finish
                    # even if a stop is requested: sandboxed programs run in
                    # their own process group (`program.py` calls `setpgid`),
                    # so a terminal Ctrl-C never reaches them and their verdicts
                    # stand. The `while` condition stops the next iteration.
                    for call in eval_calls:
                        call_results[call] = await run_solution_and_checker_fn(call)
                    stop.check()
                    runner = finder_parser.FinderTreeRunner(
                        runner=call_results.__getitem__,
                        eval_only_outcome=eval_only_outcome,
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
                            f'[error]Checkers failed during stress test [item]{stress.name}[/item] with args [item]{expanded_generator_call.name} {expanded_generator_call.args}[/item].[/error]'
                        )
                        for internal_error_result in internal_error_results:
                            assert internal_error_result.checker is not None
                            assert internal_error_result.checker_result is not None
                            internal_error_checker_name = (
                                internal_error_result.checker.path
                            )
                            console.console.print(
                                f'[warning]Checker [item]{internal_error_checker_name}[/item] failed with message:'
                            )
                            console.console.print(
                                internal_error_result.checker_result.message
                            )
                        raise typer.Exit(1)

                    if not finder_outcome.truth_value:
                        continue

                    # Calculate max duration for this finding
                    max_duration = 0
                    for finder_result in finder_outcome.results:
                        if (
                            finder_result.solution_log
                            and finder_result.solution_log.time
                        ):
                            max_duration = max(
                                max_duration,
                                int(finder_result.solution_log.time * 1000),
                            )

                    if session.is_too_fast(max_duration):
                        # Faster than the fastest of our slow tests, skip it.
                        continue

                    # Before the next iteration overwrites the scratch area.
                    session.add_finding(
                        expanded_generator_call,
                        max_duration,
                        finder_outcome.results,
                        input_path,
                        answer_path,
                        iteration_evals,
                    )

                    if progress:
                        _print_finding(
                            expanded_generator_call,
                            max_duration,
                            finder_outcome,
                            find_slowest,
                        )

                    # Be cooperative.
                    time.sleep(0.001)
            except KeyboardInterrupt:
                interrupted = True

            interrupted = interrupted or stop.requested
            session.renumber()
            final_state = (
                stress_manifest.StressState.INTERRUPTED
                if interrupted
                else stress_manifest.StressState.DONE
            )
    except typer.Exit as e:
        if e.exit_code == 0:
            final_state = stress_manifest.StressState.DONE
        raise
    finally:
        session.finish(final_state)

    return session.report()


def _print_finding(
    generator_call: GeneratorCall,
    duration: int,
    finder_outcome: finder_parser.FinderOutcome,
    find_slowest: bool,
) -> None:
    status_header = '[error]FINDING[/error]'
    if find_slowest:
        status_header = f'[error]CANDIDATE ({get_formatted_time(duration)})[/error]'

    console.console.print(
        f'{status_header} Generator args are "[status]{generator_call.name} {generator_call.args}[/status]"'
    )
    seen_finder_results = set()
    for finder_result in finder_outcome.results:
        style = get_outcome_style_verdict(finder_result.outcome)
        finder_result_key = (
            str(finder_result.solution.path),
            finder_result.checker,
        )
        if finder_result_key in seen_finder_results:
            continue
        seen_finder_results.add(finder_result_key)
        finder_result_report_line = f'{finder_result.solution.href()} = [{style}]{finder_result.outcome.name}[/{style}]'
        if finder_result.checker is not None:
            finder_result_report_line += (
                f' [item]ON[/item] {finder_result.checker.path}'
            )
        console.console.print(finder_result_report_line)


def print_stress_report(report: StressReport):
    console.console.rule('Stress test report', style='status')
    console.console.print(f'Executed [item]{report.executed}[/item] tests.')
    if report.skipped:
        console.console.print(f'Skipped [item]{report.skipped}[/item] invalid tests.')
    if not report.findings:
        console.console.print('No stress test findings.')
        return
    console.console.print(f'Found [item]{len(report.findings)}[/item] testcases.')

    findings_dir = stress_manifest.findings_dir()
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
