"""The backend that measures solution timings on a DOMjudge instance.

`rbx time` estimates a time limit from timings measured *where rbx runs*. This
runner measures them where the problem will actually be judged: it uploads a
throwaway probe package to a private `rbxt-` problem in its own `rbx-timing`
contest, then submits each solution there over the REST API and reads the
judgement back.

Everything expensive is once per run, which is what `prepare` is: one upload
serves however many solutions get measured, because a submission carries its own
source in the request rather than being read out of the package.

Design: `docs/plans/2026-09-08-domjudge-remote-runner-design.md`.
"""

import asyncio
import hashlib
import pathlib
import tempfile
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import typer

from rbx import console
from rbx.box import package, tasks
from rbx.box.deferred import Deferred
from rbx.box.exception import RbxException
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging.domjudge.packager import DomjudgePackager, ProbePackage
from rbx.box.runners.base import (
    RunContext,
    RunnerCapabilities,
    RunnerCapabilityError,
    RunnerChip,
    RunProgress,
    SolutionRunner,
)
from rbx.box.runners.domjudge import staging
from rbx.box.runners.domjudge.api import (
    DomjudgeApi,
    DomjudgeApiError,
    credentials_from_env,
)
from rbx.grading.steps import (
    CheckerResult,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)

if TYPE_CHECKING:
    from rbx.box.solutions import SolutionSkeleton

# How often to ask whether a judging has finished, and how many times.
#
# There is a bound at all because "not finished" is an assumption, not an
# observation: a judging that dies on the judgehost never reports a terminal
# failure state, so an unbounded poll would leave `rbx time` waiting forever with
# no output -- the worst failure mode, because it looks like slowness rather than
# like a failure.
#
# Twenty minutes at three seconds. Longer than MOJ's equivalent because a
# DOMjudge park may be judging other people's submissions ahead of ours, and
# nothing here can see that queue.
JUDGEMENT_POLL_INTERVAL_SECONDS = 3.0
JUDGEMENT_POLL_ATTEMPTS = 400

# How many submissions rbx keeps in flight at once. **One.**
#
# A judgehost takes one submission at a time, so two in flight are not two
# machines -- on a single-judgehost instance the second merely queues, and on a
# multi-judgehost one they land on *different* machines whose timings are not
# comparable. Since comparability is the entire point of measuring remotely,
# serialising costs wall-clock and buys correctness.
MAX_INFLIGHT_SUBMISSIONS = 1

# What `TestcaseLog.exitstatus` says for a testcase somebody else ran. rbx never
# saw a process, so there is no exit status to report; these name the absence
# rather than inventing a zero.
REMOTE_EXIT_STATUS = 'judged remotely'
UNREPORTED_EXIT_STATUS = 'not reported'

# DOMjudge judgement types -> rbx outcomes.
#
# `MLE` is absent on purpose: DOMjudge has no memory-limit verdict and reports an
# over-memory run as `RTE`, which is the one lossy direction of this mapping and
# is documented as such on the packager's `_EXPECTED_RESULTS`.
_OUTCOMES: Dict[str, Outcome] = {
    'AC': Outcome.ACCEPTED,
    'WA': Outcome.WRONG_ANSWER,
    'TLE': Outcome.TIME_LIMIT_EXCEEDED,
    'RTE': Outcome.RUNTIME_ERROR,
    'OLE': Outcome.OUTPUT_LIMIT_EXCEEDED,
    'CE': Outcome.COMPILATION_ERROR,
    # DOMjudge's "no output" is a submission that printed nothing. rbx has no
    # separate outcome for it, and the checker would have called it wrong.
    'NO': Outcome.WRONG_ANSWER,
}


class DomjudgeRunnerError(RbxException):
    """Something went wrong talking to DOMjudge that is the setter's to fix.

    Message is **plain text with backticks**, never rich markup: `main.py` prints
    an `RbxException` with a bare builtin `print`, so `[item]` tags would reach
    the setter literally.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


class DomjudgeRunner:
    name = 'domjudge'
    caps = RunnerCapabilities(
        # No run or judgement object carries memory. DOMjudge does enforce a
        # memory limit, so an over-memory run still produces a verdict (as RTE);
        # there is simply no number, and `None` says that where a 0 would read
        # as a measurement.
        measures_memory=False,
        # The judgehost keeps the submission's stdout/stderr; the API hands back
        # verdicts, not bytes. Writing an empty `.out` would claim the solution
        # printed nothing.
        captures_artifacts=False,
        # `JudgingRunOutput` is not serialized by any endpoint, so the checker's
        # own words never leave the jury interface.
        reports_checker_messages=False,
        # One submission is one judging. Repeating would mean N submissions to a
        # shared judge, so a run asking for repeats is refused by name rather
        # than silently measured once.
        supports_nruns=False,
        # A batch backend: DOMjudge has already judged everything it is going to
        # by the time rbx reads the judgement, so gating would overwrite real
        # verdicts with SKIPPED. See `RunnerCapabilities.supports_abort`.
        supports_abort=False,
        # Untested rather than impossible. The packager emits `custom
        # interactive`, but nothing has yet measured an interactive solution's
        # timing here, and declaring support rbx has not verified is how a run
        # comes back quietly wrong.
        supports_interactive=False,
        # Sanitizers are a local-compilation concept; DOMjudge compiles the
        # submission itself with an instance-global script rbx cannot influence.
        supports_sanitizers=False,
        # DOMjudge always judges with the problem's validator. There is no "just
        # run it" mode for `--no-check` to map onto.
        supports_unchecked=False,
    )

    def __init__(self) -> None:
        # Settled by `prepare`, read by `run_solution`. One instance serves one
        # `run_solutions` call, so instance state is the run's state and a second
        # run gets a second object rather than a stale field.
        self._api: Optional[DomjudgeApi] = None
        self._contest: Optional[str] = None
        self._problem_id: Optional[str] = None
        self._team_id: Optional[str] = None
        self._packager: Optional[DomjudgePackager] = None
        self._languages: List[Dict[str, Any]] = []
        # Created on first use rather than here: an `asyncio.Semaphore` belongs
        # to the loop that first awaits it, and nothing guarantees this object
        # was constructed inside the loop that will run it.
        self._slots: Optional[asyncio.Semaphore] = None
        # Every submission this run dispatched, held so a task in flight cannot
        # be garbage-collected out from under the judge.
        self._jobs: List['asyncio.Task[_JudgedSubmission]'] = []

    # -- prepare --------------------------------------------------------------

    async def prepare(self, ctx: RunContext) -> None:
        """Get a probe problem onto the server, once per run.

        Idempotent across runs by design: the contest and the problem are
        persistent, so a session that dies halfway leaves the next one closer to
        ready rather than leaving garbage behind.
        """
        api = DomjudgeApi(credentials_from_env())
        self._api = api

        if ctx.progress:
            ctx.progress.update('Checking the DOMjudge server...')

        warnings = await staging.preflight(api)
        for warning in warnings:
            console.console.print(f'[warning]{warning}[/warning]')

        self._contest = await staging.ensure_contest(api)
        self._team_id = await staging.ensure_team(api)
        self._languages = await api.languages(self._contest)

        if ctx.progress:
            ctx.progress.update('Building the DOMjudge probe package...')

        timelimit_ms = _probe_timelimit_ms(ctx)
        fingerprint = _package_fingerprint(ctx)
        problem_id = staging.probe_problem_id(fingerprint, ctx.purpose)
        self._problem_id = problem_id

        packager, zip_path = self._build_probe(ctx, problem_id, timelimit_ms)
        self._packager = packager

        if ctx.progress:
            ctx.progress.update(f'Uploading the probe package to `{problem_id}`...')

        await staging.stage_problem(api, self._contest, problem_id, zip_path)

        # One durable line, because everything above is spinner text that
        # vanishes. This is the only evidence afterwards that a phase re-uploaded
        # -- which the validation phase must, since the limits it measures under
        # live in the package.
        console.console.print(
            f'[status]domjudge[/status] · {api.server} · staged `{problem_id}` '
            f'at a {timelimit_ms} ms limit.'
        )

    def _build_probe(
        self, ctx: RunContext, problem_id: str, timelimit_ms: int
    ) -> Tuple[DomjudgePackager, pathlib.Path]:
        """Build the throwaway package this run measures against.

        Built directly rather than through `run_packager`, whose full local
        verification run is the exact work a remote runner exists to avoid.
        """
        packager = DomjudgePackager(
            testcase_entries=list(ctx.skeleton.entries),
            probe=ProbePackage(problem_id=problem_id, timelimit_ms=timelimit_ms),
        )

        build_dir = pathlib.Path(tempfile.mkdtemp(prefix='rbx-domjudge-probe-'))
        into_dir = build_dir / 'package'
        try:
            zip_path = packager.package(build_dir, into_dir, [])
        except typer.Exit as e:
            # `DomjudgePackager` reports a setter mistake -- a solution that does
            # not reduce to one translation unit, a non-C++ checker -- by
            # printing and raising a CLI control-flow exception. Letting that
            # unwind a library call would end the command with an exit code
            # nothing here chose.
            raise DomjudgeRunnerError(
                'Could not build the DOMjudge probe package; see the error above.'
            ) from e
        return packager, zip_path

    # -- run_solution ---------------------------------------------------------

    def run_solution(
        self,
        solution: 'SolutionSkeleton',
        entries: List[GenerationTestcaseEntry],
        ctx: RunContext,
    ) -> List[Deferred[Evaluation]]:
        """Queue this solution on the judge now; hand back one deferred per entry.

        **Nothing here awaits.** `_produce_solution_items` calls this
        synchronously, once per solution, before a single deferred is resolved --
        so the submission goes onto a background task and every solution is
        already queued while the report is still printing the first. That is the
        entire reason the seam is per solution.

        The N deferreds share one job. `Deferred` will not do that for you: it
        memoizes each deferred's *own* result, so N deferreds over one submission
        would be N submissions unless the task is held here.
        """
        if not entries:
            # No entries, no submission -- and, more to the point, no task. An
            # `asyncio.Task` nobody awaits whose body raises prints an "exception
            # was never retrieved" traceback out of the garbage collector, at a
            # moment unrelated to anything the setter did.
            return []

        if self._api is None or self._problem_id is None:
            raise DomjudgeRunnerError(
                'The DOMjudge runner was asked to run a solution before it was '
                'prepared. This is an rbx bug; please report it.'
            )

        if self._slots is None:
            self._slots = asyncio.Semaphore(MAX_INFLIGHT_SUBMISSIONS)

        self._say(ctx.progress_board, solution, RunnerChip('waiting for a slot'))

        job = asyncio.create_task(
            self._submit_and_poll(solution, len(entries), ctx.progress_board)
        )
        job.add_done_callback(_retrieve_exception)
        self._jobs.append(job)

        ordinals = _ordinals_for(entries)
        return [
            Deferred(
                # Bound as defaults, because the lambda outlives the loop
                # iteration: a late-bound `entry` would give every deferred the
                # last testcase's evaluation.
                lambda entry=entry, ordinal=ordinal: self._evaluation_from_job(
                    job, solution, entry, ordinal
                )
            )
            for entry, ordinal in zip(entries, ordinals)
        ]

    async def _submit_and_poll(
        self,
        solution: 'SolutionSkeleton',
        total: int,
        board: RunProgress,
    ) -> '_JudgedSubmission':
        assert self._api is not None
        assert self._contest is not None
        assert self._problem_id is not None
        assert self._team_id is not None
        assert self._slots is not None

        content = self._solution_content(solution)
        language_id = self._language_id_for(solution)

        async with self._slots:
            self._say(board, solution, RunnerChip('submitting'))
            submission = await self._api.submit(
                self._contest,
                self._problem_id,
                language_id,
                self._team_id,
                solution.path.name,
                content,
            )
            submission_id = str(submission['id'])

            judgement = await self._wait_for_judgement(solution, submission_id, board)

        judgement_id = str(judgement['id'])
        runs = await self._api.runs(self._contest, judgement_id)

        self._say(
            board,
            solution,
            RunnerChip(f'#{submission_id}'),
            RunnerChip(str(judgement.get('judgement_type_id') or 'done')),
        )
        return _JudgedSubmission(
            submission_id=submission_id,
            judgement=judgement,
            runs=_runs_by_ordinal(runs, total),
        )

    async def _wait_for_judgement(
        self,
        solution: 'SolutionSkeleton',
        submission_id: str,
        board: RunProgress,
    ) -> Dict[str, Any]:
        """Poll until the judging is *finished*, not merely until it has a verdict.

        **This is the subtlety of the whole runner.** DOMjudge sets
        `judgement_type_id` as soon as the verdict is decided -- on the first
        failing testcase -- and goes on judging the rest. A poll that stops there
        reads `max_run_time: null` and a run list holding only the testcases
        judged so far, and reports a solution with no timing and missing
        testcases as though that were the answer.

        `end_time` is the field that means finished, so that is what this waits
        for.
        """
        assert self._api is not None
        assert self._contest is not None

        for attempt in range(JUDGEMENT_POLL_ATTEMPTS):
            judgements = await self._api.judgements(self._contest, submission_id)
            if judgements and judgements[0].get('end_time'):
                return judgements[0]

            verdict = judgements[0].get('judgement_type_id') if judgements else None
            self._say(
                board,
                solution,
                RunnerChip(f'#{submission_id}'),
                RunnerChip(str(verdict) if verdict else 'queued'),
                RunnerChip(f'{attempt * JUDGEMENT_POLL_INTERVAL_SECONDS:.0f}s'),
            )
            await asyncio.sleep(JUDGEMENT_POLL_INTERVAL_SECONDS)

        waited = JUDGEMENT_POLL_ATTEMPTS * JUDGEMENT_POLL_INTERVAL_SECONDS
        raise DomjudgeRunnerError(
            f'DOMjudge did not finish judging `{solution.path}` (submission '
            f'{submission_id}) after {waited:.0f}s. The submission may still be '
            f'queued behind other work, or its judging may have failed; check '
            f'{self._api.server} and try again.'
        )

    # -- deriving evaluations -------------------------------------------------

    async def _evaluation_from_job(
        self,
        job: 'asyncio.Task[_JudgedSubmission]',
        solution: 'SolutionSkeleton',
        entry: GenerationTestcaseEntry,
        ordinal: int,
    ) -> Evaluation:
        judged = await job
        return _evaluation_for(solution, entry, judged.runs.get(ordinal))

    def _solution_content(self, solution: 'SolutionSkeleton') -> bytes:
        """The exact bytes submitted for this solution.

        Amalgamated by the packager, because DOMjudge compiles a submission from
        a single file -- and taken from the packager rather than re-derived, so
        what is timed is what a real package would have shipped.
        """
        assert self._packager is not None
        sol = _solution_for(solution)
        try:
            return self._packager.solution_content(sol)
        except typer.Exit as e:
            raise DomjudgeRunnerError(
                f'Could not prepare `{solution.path}` for DOMjudge; see the error '
                f'above. DOMjudge compiles a submission from a single file, so '
                f'every solution rbx times has to reduce to one.'
            ) from e

    def _language_id_for(self, solution: 'SolutionSkeleton') -> str:
        """The DOMjudge language for this solution's extension.

        Refused by name rather than guessed: submitting under the wrong language
        gets a compile error that reads as the solution's fault.
        """
        extension = solution.path.suffix
        language_id = staging.language_id_for(self._languages, extension)
        if language_id is None:
            known = ', '.join(
                sorted(
                    f'`{ext}`'
                    for language in self._languages
                    for ext in (language.get('extensions') or [])
                )
            )
            raise RunnerCapabilityError(
                f'This DOMjudge has no language that accepts `{extension}` files, so '
                f'`{solution.path}` cannot be submitted to it.\n'
                f'The extensions it does accept are: {known}.'
            )
        return language_id

    def _say(
        self, board: RunProgress, solution: 'SolutionSkeleton', *chips: RunnerChip
    ) -> None:
        board.set(str(solution.path), *chips)

    # -- close ----------------------------------------------------------------

    async def close(self) -> None:
        """Stop waiting on submissions nobody is going to read. Idempotent.

        `run_solution` queues **every** solution up front -- that is the point of
        the seam -- while the report consumes them one at a time and stops at the
        first failure. So a run that ends early leaves the later solutions' tasks
        polling DOMjudge for results nothing will ever ask for, and asyncio
        reports them at interpreter exit as `Task was destroyed but it is
        pending!` -- a message about rbx internals, arriving after the error the
        setter actually cares about.

        **The drain is not optional.** `cancel()` only schedules the
        `CancelledError`; a task suspended in a request needs more than one turn
        of the loop to unwind, and `syncer` stops the loop as soon as the
        consumer returns or raises -- which is precisely the path this is called
        on.

        **Ends this batch, not this runner.** The contest, the problem and the
        packager are deliberately left alone: they are persistent by design, and
        a second batch on the same object (the validation phase, re-preparing at
        the estimated limit) is meant to reuse them. It does still re-upload,
        because the limits moved and the limits live in the package.

        **Only the wait is cancelled. The judge keeps going.** A cancelled poll
        does not un-submit anything -- unlike a MOJ testrun, a DOMjudge
        submission *is* a submission, and it stays in the probe contest. That
        contest is private and has no scoreboard anyone reads, so it costs
        nothing but a row.
        """
        jobs, self._jobs = self._jobs, []
        pending = [job for job in jobs if not job.done()]
        for job in pending:
            job.cancel()

        if not pending:
            return

        # `return_exceptions=True` because this runs in a `finally`, very
        # possibly while another exception is on its way to the setter: a job
        # that failed instead of cancelling must not replace the error they are
        # actually looking at.
        await asyncio.gather(*pending, return_exceptions=True)

        console.console.print(
            f'[warning]Stopped waiting for {len(pending)} DOMjudge submission(s) '
            f'that were still being judged. They finish on the judge; they live in '
            f'the private `{staging.PROBE_CONTEST_ID}` contest, so nothing a '
            f'contestant sees is affected.[/warning]'
        )


# -- helpers ---------------------------------------------------------------------


class _JudgedSubmission:
    """What one finished submission told us, before it is split per testcase."""

    def __init__(
        self,
        submission_id: str,
        judgement: Dict[str, Any],
        runs: Dict[int, Dict[str, Any]],
    ):
        self.submission_id = submission_id
        self.judgement = judgement
        self.runs = runs


def _retrieve_exception(task: 'asyncio.Task') -> None:
    """Mark a finished task's exception as retrieved.

    A task whose body raised and which nobody awaits prints an "exception was
    never retrieved" traceback out of the garbage collector, at a moment
    unrelated to anything the setter did. Reading it here keeps the real error
    on the path that awaits the deferred.
    """
    if not task.cancelled():
        task.exception()


def _ordinals_for(entries: List[GenerationTestcaseEntry]) -> List[int]:
    """The DOMjudge ordinal each entry was written to the package as.

    **Not the position in `entries`.** `DomjudgePackager._write_testcases`
    numbers samples and secrets with *separate* counters, and DOMjudge orders
    `data/sample/*` before `data/secret/*`, so the ordinals run over every sample
    in entry order and then over every secret in entry order. Whenever a
    non-sample group precedes a sample one -- which nothing forbids -- that is a
    different permutation from entry order, and pairing positionally would
    attribute each timing to the wrong testcase.

    Rebuilt here from the same rule the packager applies, rather than assumed.
    """
    samples = [index for index, entry in enumerate(entries) if entry.is_sample()]
    secrets = [index for index, entry in enumerate(entries) if not entry.is_sample()]

    ordinals = [0] * len(entries)
    # DOMjudge numbers runs from 1.
    for ordinal, index in enumerate(samples + secrets, start=1):
        ordinals[index] = ordinal
    return ordinals


def _runs_by_ordinal(
    runs: List[Dict[str, Any]], total: int
) -> Dict[int, Dict[str, Any]]:
    """Index the runs by ordinal, or refuse to index them at all.

    A run list shorter than the testset means DOMjudge stopped early -- lazy
    evaluation that the probe problem's `lazy_eval_results` was supposed to turn
    off, or a judging that failed part-way. Pairing what did arrive would be
    *fine* here, since ordinals are explicit; what would not be fine is treating
    a missing ordinal as a measurement, so the caller renders those as SKIPPED.

    A list *longer* than the testset is a package/testset mismatch: the uploaded
    problem holds testcases this run does not know about, so no pairing is
    trustworthy and none is offered.
    """
    if len(runs) > total:
        return {}
    return {int(run['ordinal']): run for run in runs if run.get('ordinal') is not None}


def _evaluation_for(
    solution: 'SolutionSkeleton',
    entry: GenerationTestcaseEntry,
    run: Optional[Dict[str, Any]],
) -> Evaluation:
    """Turn one DOMjudge run into an rbx `Evaluation`, and persist it.

    Honest about what the API does not report, which `RunnerCapabilities` has
    already declared and this must not quietly walk back: no memory, no wall
    time, no artifacts, no checker message, no exit status.

    `run is None` is a testcase DOMjudge never reported on. It gets `SKIPPED`
    with no timing -- the outcome rbx already uses for "this testcase produced no
    result", and the one thing that cannot be mistaken for a verdict about the
    solution. Deliberately not `INTERNAL_ERROR` or `JUDGE_FAILED`: neither
    happened as far as anyone knows, and both rank worse than every real verdict,
    so one unreported test would take over the solution's outcome.
    """
    testcase = entry.metadata.copied_to
    output_dir = solution.runs_dir / entry.group_entry.group

    if run is None:
        result = CheckerResult(
            outcome=Outcome.SKIPPED,
            message='DOMjudge reported no result for this testcase.',
        )
        log = TestcaseLog(
            exitcode=-1,
            exitstatus=UNREPORTED_EXIT_STATUS,
            time=None,
            wall_time=None,
            memory=None,
        )
    else:
        verdict = str(run.get('judgement_type_id') or '')
        outcome = _OUTCOMES.get(verdict)
        if outcome is None:
            raise DomjudgeRunnerError(
                f'DOMjudge reported a verdict rbx does not know how to read '
                f'(`{verdict}`) for `{solution.path}`. Refusing rather than '
                f'guessing, because a wrong verdict silently corrupts the time '
                f'limit being estimated.'
            )
        result = CheckerResult(
            outcome=outcome,
            # DOMjudge judges with the packaged validator and hands back a
            # verdict, never the validator's own words
            # (`reports_checker_messages=False`). Saying where the verdict came
            # from is the useful thing left to say, and it stops a reader taking
            # an empty message for a checker that had nothing to report.
            message=f'Judged remotely by DOMjudge ({verdict}).',
        )
        log = TestcaseLog(
            exitcode=-1,
            exitstatus=REMOTE_EXIT_STATUS,
            # Seconds, which is what `TestcaseLog.time` is in and what DOMjudge
            # reports. **This is CPU time, not wall time**: a solution killed on
            # the wall clock reports the CPU it actually burned, which for a
            # sleeping or I/O-bound solution is near zero. Stored as reported
            # rather than clamped or substituted -- the verdict already says it
            # was too slow, and inventing a number here would be worse than a
            # small one.
            time=run.get('run_time'),
            wall_time=None,
            memory=None,
        )

    evaluation = Evaluation(
        result=result,
        testcase=TestcaseIO(
            # The index *within its group*, which is what names the on-disk
            # artifact and what the report renders -- not the position in the
            # flattened testset.
            index=entry.group_entry.index,
            input=testcase.inputPath,
            output=testcase.outputPath,
        ),
        log=log,
    )
    tasks.write_evaluation(
        evaluation, tasks.get_testcase_output_path(testcase, output_dir)
    )
    return evaluation


def _solution_for(solution: 'SolutionSkeleton'):
    """The package's `Solution` matching this skeleton.

    The packager works in terms of the declared solution (it needs the outcome
    and the language), while the runner is handed a skeleton. Matched on path,
    which is what identifies a solution everywhere else in rbx.
    """
    for candidate in package.get_solutions():
        if candidate.path == solution.path:
            return candidate
    raise DomjudgeRunnerError(
        f'`{solution.path}` is not a solution declared in this package, so rbx '
        f'cannot work out what to submit for it. This is an rbx bug; please '
        f'report it.'
    )


def _probe_timelimit_ms(ctx: RunContext) -> int:
    """The limit the probe package pins.

    Generous by construction. The probe exists to *measure*, and DOMjudge kills a
    run at the limit (plus `timelimit_overshoot`), so a limit set near the
    expected answer would truncate exactly the solutions whose timings matter
    most. `rbx time`'s own cap is the right generous number when the run supplies
    one; a run that supplies none is not estimating anything and can use the
    package's limit.
    """
    from rbx.box.solutions import resolve_timelimit_override

    override = ctx.timelimit_override
    if override is None:
        # `skeleton.limits` is per language, and one package pins one limit for
        # all of them, so the loosest is the only safe choice: anything tighter
        # would kill a slower language's solutions before they were measured.
        times = [
            limits.time
            for limits in ctx.skeleton.limits.values()
            if limits.time is not None
        ]
        return (
            max(int(time) for time in times) if times else _DEFAULT_PROBE_TIMELIMIT_MS
        )

    # A per-language mapping (the validation phase) pins the *loosest* of them:
    # one package serves every solution in the batch, and a limit tighter than
    # some language's would truncate that language's measurements. Which
    # solution gets judged against which limit is decided by rbx afterwards,
    # from the timings.
    if isinstance(override, dict):
        values = [value for value in override.values() if value is not None]
        return (
            max(int(value) for value in values)
            if values
            else (_DEFAULT_PROBE_TIMELIMIT_MS)
        )

    resolved = resolve_timelimit_override(override, None)
    if resolved is None or resolved < 0:
        return _DEFAULT_PROBE_TIMELIMIT_MS
    return int(resolved)


# What a probe pins when nothing else says. Ten seconds is DOMjudge's own default
# problem limit, and is generous enough that an accepted solution is measured
# rather than killed.
_DEFAULT_PROBE_TIMELIMIT_MS = 10_000


def _package_fingerprint(ctx: RunContext) -> str:
    """A short, stable name for "this package's testset".

    Part of the remote problem id, so two problems on one server do not collide.
    Derived from the package name and the testset shape rather than from the
    built bytes: it only has to separate problems, and a content hash would move
    on every regeneration and leave a trail of dead problems behind.
    """
    pkg = package.find_problem_package_or_die()
    material = f'{pkg.name}:{len(ctx.skeleton.entries)}'
    return hashlib.sha256(material.encode()).hexdigest()[:8]


# Re-exported so `registry` can name the class without knowing the module layout.
__all__ = [
    'DomjudgeRunner',
    'DomjudgeRunnerError',
    'DomjudgeApiError',
    'SolutionRunner',
]
