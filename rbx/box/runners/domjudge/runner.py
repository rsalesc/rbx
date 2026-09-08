"""The backend that measures solution timings on a DOMjudge instance.

`rbx time` estimates a time limit from timings measured *where rbx runs*. This
runner measures them where the problem will actually be judged: it uploads a
throwaway probe package to a private `rbxt-` problem in its own `rbx-timing`
contest, then submits each solution there over the REST API and reads the
judgement back.

Everything expensive is once per run, which is what `prepare` is: one upload
serves however many solutions get measured, because a submission carries its own
source in the request rather than being read out of the package.

Design: `docs/plans/2026-09-08-domjudge-remote-runner-design.md`, and
`docs/plans/2026-09-08-domjudge-runner-caching-design.md` for what makes a
re-run cheap.
"""

import asyncio
import hashlib
import json
import pathlib
import tempfile
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import typer

from rbx import console, utils
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
from rbx.box.runners.problem_id import ensure_slug
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

# Where the fingerprint of the last probe package this machine successfully staged
# is kept, one entry per server-and-problem. Under the disposable problem cache
# rather than beside anything the setter owns: it is a per-machine observation
# ("*I* put this package there"), and losing it must cost one redundant upload
# rather than correctness. See `_recorded_fingerprint`.
UPLOAD_STATE_NAME = 'domjudge-runner.json'

# Where finished judgings are remembered, one JSON file per cache key.
#
# Beside the upload record, under the problem cache, and for the same reason: a
# judging is an observation this machine made about a package it staged, not
# anything that belongs to the package itself. Nothing here may be committed --
# it says what *a* judgehost answered at *a* moment -- and losing it must cost a
# redundant submission, never a wrong measurement. See `_cache_key`.
JUDGEMENT_CACHE_DIR_NAME = 'domjudge-judgements'

# Bumped when a change would make an older entry read wrong. It is part of the
# key rather than a field to validate, so entries of another version simply never
# match -- there is nothing to migrate and nothing to delete, and the cost of a
# bump is one redundant submission per solution.
JUDGEMENT_CACHE_VERSION = 1

# The DOMjudge verdict for a submission that did not build. Never cached: see
# `_is_cacheable`.
COMPILATION_ERROR_VERDICT = 'CE'

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
        # DOMjudge runs an interactive problem through `validation: custom
        # interactive`, which the packager already emits: the shipped validator
        # becomes the problem's *run* script, wrapped in `runpipe` and driven
        # bidirectionally against the submission. That is the same interactor rbx
        # drives locally, so the verdict comes from the same program.
        supports_interactive=True,
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
        # A digest over the probe package this run built, settled by `prepare`.
        # It is what "the judge is configured identically" means here, and it is
        # shared by the upload fast path and the judgement cache so the two can
        # never disagree about it. See `_directory_fingerprint`.
        self._fingerprint: Optional[str] = None
        # Created on first use rather than here: an `asyncio.Semaphore` belongs
        # to the loop that first awaits it, and nothing guarantees this object
        # was constructed inside the loop that will run it.
        self._slots: Optional[asyncio.Semaphore] = None
        # Every submission this run dispatched, held so a task in flight cannot
        # be garbage-collected out from under the judge.
        self._jobs: List['asyncio.Task[None]'] = []

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
        # The package's one identity on any remote judge, shared with every other
        # runner rather than derived here. See `rbx.box.runners.problem_id`.
        slug = ensure_slug(package.find_problem())
        problem_id = staging.probe_problem_id(slug, ctx.purpose)
        self._problem_id = problem_id

        packager, zip_path, fingerprint = self._build_probe(
            ctx, problem_id, timelimit_ms
        )
        self._packager = packager
        self._fingerprint = fingerprint

        if await self._is_already_staged(problem_id, fingerprint):
            # Said out loud, because otherwise it is unobservable: everything
            # above is spinner text that vanishes, so a setter watching two
            # phases go past would have no way to tell the cheap one from the
            # expensive one.
            console.console.print(
                f'[status]domjudge[/status] · {api.server} · reused `{problem_id}`, '
                f'package unchanged since the last upload.'
            )
            return

        # Cleared *before* the upload, not after: from the moment the server
        # starts receiving a new package, the recorded fingerprint no longer
        # describes what is up there. A crash mid-upload must leave the next run
        # re-uploading, never trusting a stale record.
        _forget_upload(api.server, problem_id)

        if ctx.progress:
            ctx.progress.update(f'Uploading the probe package to `{problem_id}`...')

        await staging.stage_problem(api, self._contest, problem_id, zip_path)
        _record_upload(api.server, problem_id, fingerprint)

        # One durable line, because everything above is spinner text that
        # vanishes. This is the only evidence afterwards that a phase re-uploaded
        # -- which the validation phase must, since the limits it measures under
        # live in the package.
        console.console.print(
            f'[status]domjudge[/status] · {api.server} · staged `{problem_id}` '
            f'at a {timelimit_ms} ms limit.'
        )

    async def _is_already_staged(self, problem_id: str, fingerprint: str) -> bool:
        """Whether the server already holds exactly this package, under this id.

        Two conditions, and the second is what this has over the equivalent MOJ
        fast path. **This machine last uploaded this fingerprint there** -- which
        is a record of what rbx did, not of what the server holds. And **the
        problem is still linked into the probe contest** -- which is the server's
        own answer, and is what catches a probe problem deleted by hand, a
        contest recreated, or a record carried onto an instance that was wiped.
        `stage_problem` asks for that list anyway on the path this skips, so the
        check costs a request only when it is about to save an upload.

        What neither condition can see is somebody else uploading *over* this
        problem id between two runs. That is why the record lives in the
        disposable problem cache: the escape hatch is to delete it, and the cost
        of the blind spot is bounded by the fact that the ids rbx stages to are
        its own (`rbxt-`).
        """
        assert self._api is not None
        assert self._contest is not None

        if _recorded_fingerprint(self._api.server, problem_id) != fingerprint:
            return False
        problems = await self._api.problems(self._contest)
        return any(problem.get('id') == problem_id for problem in problems)

    def _build_probe(
        self, ctx: RunContext, problem_id: str, timelimit_ms: int
    ) -> Tuple[DomjudgePackager, pathlib.Path, str]:
        """Build the throwaway package this run measures against.

        Built directly rather than through `run_packager`, whose full local
        verification run is the exact work a remote runner exists to avoid.

        Hands back the package's fingerprint along with the zip. It is taken over
        the built *tree* rather than over the zip's bytes, because
        `shutil.make_archive` stamps every entry with its mtime -- so two builds
        of an identical package produce different archives, and a fingerprint
        over them would never match anything.
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
        return packager, zip_path, _directory_fingerprint(into_dir)

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

        judging = _Judging(total=len(entries))
        job = asyncio.create_task(
            self._poll_into(solution, judging, ctx.progress_board)
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
                    judging, solution, entry, ordinal
                )
            )
            for entry, ordinal in zip(entries, ordinals)
        ]

    async def _poll_into(
        self,
        solution: 'SolutionSkeleton',
        judging: '_Judging',
        board: RunProgress,
    ) -> None:
        """Run the submission, and make sure the waiters are released either way.

        The deferreds block on `judging`, not on this task, so nothing here may
        return without the judging being settled -- a poll that raised or was
        cancelled would otherwise leave every deferred waiting on a condition
        nobody will notify again, turning an error into a hang.

        `CancelledError` is re-raised after settling, because `close` awaits
        these tasks and a task that swallowed its cancellation never finishes.
        """
        try:
            await self._submit_and_poll(solution, judging, board)
        except asyncio.CancelledError as cancelled:
            await judging.fail(cancelled)
            raise
        except BaseException as failure:
            await judging.fail(failure)
            raise

    async def _submit_and_poll(
        self,
        solution: 'SolutionSkeleton',
        judging: '_Judging',
        board: RunProgress,
    ) -> None:
        """Submit, then publish each testcase's run into `judging` as it lands.

        The whole point of polling `/runs` on every tick rather than once at the
        end is that DOMjudge exposes only runs whose `endtime` is set, so the
        list *grows* as judging proceeds. Reading it live turns a submission from
        one long silence into a testcase-by-testcase report, which is what a
        local run looks like.

        **The cache is consulted before the semaphore, not inside it.** A hit
        costs one file read and no judge time at all, so making it queue behind a
        real submission would serialize free work behind expensive work -- and
        with `MAX_INFLIGHT_SUBMISSIONS = 1` that means every hit waiting out every
        miss ahead of it, for nothing.
        """
        assert self._api is not None
        assert self._contest is not None
        assert self._problem_id is not None
        assert self._team_id is not None
        assert self._slots is not None

        content = self._solution_content(solution)
        language_id = self._language_id_for(solution)

        key = self._cache_key(solution, language_id, content)
        cached = _load_cached_judgement(key)
        if cached is not None:
            submission_id, judgement, runs = cached
            self._say(
                board,
                solution,
                RunnerChip(f'#{submission_id}'),
                RunnerChip('cached', style='green'),
            )
            # Put through the *same* `_Judging` a fresh submission publishes
            # into, rather than storing derived evaluations. That is what makes a
            # hit and a miss provably the same measurement: there is one path
            # from a DOMjudge run to an rbx `Evaluation`, and both take it --
            # pairing, the mismatch guard and the unknown-verdict refusal
            # included, which still apply to a file that has been on disk since
            # the last run and may have been anything by the time it is read.
            await judging.publish(runs)
            await judging.finish(judgement)
            return

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

            judgement, runs = await self._poll_until_judged(
                solution, submission_id, judging, board
            )

        if _is_cacheable(judgement, runs, judging.mismatched):
            _store_cached_judgement(key, submission_id, judgement, runs)

    async def _poll_until_judged(
        self,
        solution: 'SolutionSkeleton',
        submission_id: str,
        judging: '_Judging',
        board: RunProgress,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Poll until the judging is *finished*, publishing runs as they arrive.

        **Finished is `end_time`, not a verdict.** DOMjudge sets
        `judgement_type_id` as soon as the verdict is decided -- on the first
        failing testcase -- and goes on judging the rest. Stopping there would
        leave the later testcases unreported and `max_run_time` null.

        Per-testcase results are still handed out the moment they appear, so
        waiting for `end_time` costs the *report* nothing: it only decides when a
        testcase that never arrived is finally called SKIPPED.

        Hands back the finished judgement and the last run list it read, which is
        what the cache stores: the judge's own answer, rather than anything
        derived from it. See `_store_cached_judgement`.
        """
        assert self._api is not None
        assert self._contest is not None

        judgement_id: Optional[str] = None
        runs: List[Dict[str, Any]] = []
        # Real elapsed, not `attempt * interval`. Each attempt also spends a
        # request or two, so the nominal figure understates the wait -- by more
        # the busier the judge is, which is exactly when a setter reads it to
        # decide whether to give up.
        elapsed = utils.Elapsed()

        for _ in range(JUDGEMENT_POLL_ATTEMPTS):
            judgements = await self._api.judgements(self._contest, submission_id)
            judgement = judgements[0] if judgements else None
            if judgement is not None:
                judgement_id = str(judgement['id'])

            # A judging with no id yet has not been picked up, and asking for its
            # runs would be a request that can only answer nothing.
            if judgement_id is not None:
                runs = await self._api.runs(self._contest, judgement_id)
                await judging.publish(runs)

            verdict = judgement.get('judgement_type_id') if judgement else None
            self._say(
                board,
                solution,
                RunnerChip(f'#{submission_id}'),
                *judging.chips(),
                RunnerChip(str(verdict) if verdict else 'queued'),
                RunnerChip(str(elapsed)),
            )

            if judgement is not None and judgement.get('end_time'):
                await judging.finish(judgement)
                self._say(
                    board,
                    solution,
                    RunnerChip(f'#{submission_id}'),
                    RunnerChip(str(verdict or 'done')),
                )
                return judgement, runs

            await asyncio.sleep(JUDGEMENT_POLL_INTERVAL_SECONDS)

        raise DomjudgeRunnerError(
            f'DOMjudge did not finish judging `{solution.path}` (submission '
            f'{submission_id}) after {elapsed}. The submission may still be '
            f'queued behind other work, or its judging may have failed; check '
            f'{self._api.server} and try again.'
        )

    # -- deriving evaluations -------------------------------------------------

    async def _evaluation_from_job(
        self,
        judging: '_Judging',
        solution: 'SolutionSkeleton',
        entry: GenerationTestcaseEntry,
        ordinal: int,
    ) -> Evaluation:
        """Wait for *this testcase*, not for the whole submission.

        This is what makes the report tick: the deferred for testcase 1 resolves
        as soon as DOMjudge has judged testcase 1, while the rest are still
        running. Only a testcase the judging ended without ever reporting waits
        the full length of the submission -- and it has to, because "not judged
        yet" and "never going to be" are the same thing until `end_time`.
        """
        run = await judging.run_for(ordinal)
        return _evaluation_for(solution, entry, run)

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

    def _cache_key(
        self, solution: 'SolutionSkeleton', language_id: str, content: bytes
    ) -> str:
        """What makes a cached judging *the same measurement* as a fresh one.

        Everything the judge's answer depended on, and nothing else:

        - **the package the judge holds**, as `prepare`'s `_directory_fingerprint`
          of the built probe. Everything the submission is measured *against* is
          in there -- the testcases, the output validator, `problem.yaml`, and the
          pinned limit -- so a package that fingerprints equal is a problem
          configured identically. Reusing that fingerprint rather than inventing
          a second key is what stops the cache and the upload fast path
          disagreeing about what "the same package" means.
        - **the exact bytes submitted**, not the solution's path and not its
          mtime. `solution_content` amalgamates, so a change in an included
          header changes the program without touching the file rbx names -- and,
          the other way round, a whitespace-only edit that amalgamates to the
          same bytes really is the same submission.
        - **the language it was submitted under**, because that is what DOMjudge
          compiles it with. Very nearly implied by the file name, but it is the
          instance's own answer (`cpp` here, `cxx` elsewhere) and it is what the
          judgehost acted on.
        - **the server and the problem id**, because a timing is a measurement of
          a park, and two instances holding the same package are two different
          measurements. The problem id is very nearly implied by the fingerprint,
          but it is where the numbers were actually observed.

        **The limit needs no term of its own.** It is written into
        `domjudge-problem.ini`, which the fingerprint covers -- so the validation
        phase, which re-stages at `ceil(TL_lang x timeLimitToTle)`, misses on
        every solution by construction, which is right: a timing taken under a
        2.5s kill is not a timing under a 4s one. A picker round trip that lands
        back on a limit already probed hits the cache instead.

        **What this cannot see** is the park itself: its hardware, its load, a
        judgehost joining or leaving, or somebody uploading over the probe
        problem between two runs. A cached timing is a measurement from whenever
        it was taken. That is why the cache lives in the disposable problem
        cache, where throwing the observations away is one `rm -rf`.
        """
        assert self._api is not None
        assert self._contest is not None
        assert self._problem_id is not None
        assert self._fingerprint is not None

        digest = hashlib.sha256()
        # Framed with lengths, like `_directory_fingerprint`, so no field can be
        # made to look like part of the next one.
        for part in (
            f'v{JUDGEMENT_CACHE_VERSION}'.encode(),
            self._api.server.encode(),
            self._contest.encode(),
            self._problem_id.encode(),
            self._fingerprint.encode(),
            solution.path.name.encode(),
            language_id.encode(),
            content,
        ):
            digest.update(f'{len(part)}:'.encode())
            digest.update(part)
        return digest.hexdigest()

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


class _Judging:
    """One submission's results, handed out per testcase as they arrive.

    The seam between the single polling task and the N deferreds waiting on it.
    A deferred asks for *its* ordinal and blocks only until that testcase is
    judged, rather than until the whole submission is -- which is the difference
    between a report that ticks and a report that sits still for minutes.

    **An `asyncio.Condition`, not an Event per ordinal.** Runs arrive in batches
    (a poll returns every testcase finished since the last one), the set of
    ordinals is not known to be contiguous, and every waiter has to re-check the
    same two conditions -- its run arrived, or the judging ended without it. One
    condition with a predicate loop is exactly that shape; a map of Events would
    be the same logic plus bookkeeping to keep it consistent.

    Both ends run on the one event loop, so the lock is uncontended and only
    exists to make `wait` correct.
    """

    def __init__(self, total: int):
        self._total = total
        self._runs: Dict[int, Dict[str, Any]] = {}
        self._finished = False
        self._failure: Optional[BaseException] = None
        # Set when the run list grew past the testset. See `publish`.
        self._mismatched = False
        self._condition = asyncio.Condition()
        self.judgement: Optional[Dict[str, Any]] = None

    async def publish(self, runs: List[Dict[str, Any]]) -> None:
        """Record the runs reported so far and wake whoever they unblock."""
        async with self._condition:
            if len(runs) > self._total:
                # More runs than the testset rbx thinks it uploaded: the remote
                # problem holds testcases this run does not know about, so no
                # ordinal means what it appears to. Refusing to pair leaves every
                # testcase SKIPPED rather than mispaired.
                self._mismatched = True
                self._runs.clear()
            elif not self._mismatched:
                for run in runs:
                    ordinal = run.get('ordinal')
                    if ordinal is not None:
                        self._runs[int(ordinal)] = run
            self._condition.notify_all()

    async def finish(self, judgement: Dict[str, Any]) -> None:
        """The judging ended. Every ordinal still missing is never coming."""
        async with self._condition:
            self.judgement = judgement
            self._finished = True
            self._condition.notify_all()

    async def fail(self, failure: BaseException) -> None:
        """The poll gave up or blew up; hand the reason to every waiter.

        Without this a failed poll would leave the deferreds blocked forever on a
        condition nothing will ever notify -- a hang in place of the error the
        setter needs to see.
        """
        async with self._condition:
            self._failure = failure
            self._finished = True
            self._condition.notify_all()

    async def run_for(self, ordinal: int) -> Optional[Dict[str, Any]]:
        """This testcase's run, or None once the judging ended without it."""
        async with self._condition:
            while ordinal not in self._runs and not self._finished:
                await self._condition.wait()
            if self._failure is not None:
                raise self._failure
            return self._runs.get(ordinal)

    @property
    def mismatched(self) -> bool:
        """Whether the run list grew past the testset, so nothing may be paired.

        Read by the cache before it writes anything: an entry that cannot be
        paired is not a measurement of this testset, and remembering it would
        turn one confusing run into every run after it.
        """
        return self._mismatched

    def chips(self) -> Tuple[RunnerChip, ...]:
        """What the progress board says about how far along the judging is.

        Read without the lock: a plain dict `len` on the one event loop cannot
        observe a half-applied write, and the board is a status line -- a count
        one poll stale is not worth making the reporter await a lock for.
        """
        if self._mismatched or not self._runs:
            return ()
        return (RunnerChip(f'judged {len(self._runs)}/{self._total}'),)


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


# -- the upload record -----------------------------------------------------------
#
# What this machine last staged, per server and problem id, so a re-run does not
# push the same package onto a server that already holds it. `stage_problem` is
# four requests and a zip upload, and the two `rbx time` phases alternate over and
# over as the picker narrows -- so this is the difference between a re-run that
# costs nothing and one that re-uploads the whole testset every time.
#
# Keyed by server as well as by problem id, unlike MOJ's equivalent: `rbxt-` ids
# are derived from the package, so the same id on a staging instance and on a
# production one is two entirely different problems.


def _upload_state_path() -> pathlib.Path:
    return package.get_problem_cache_dir() / UPLOAD_STATE_NAME


def _upload_state_key(server: str, problem_id: str) -> str:
    return f'{server}|{problem_id}'


def _read_upload_state() -> Dict[str, str]:
    """Every problem this machine has staged to, and what it last sent.

    A **map**, not a single record: `rbx time` stages one problem per phase, and
    a single record would have each phase evict the other's -- which would make
    the fast path unreachable in exactly the run that needs it most. Anything
    unreadable or of an unrecognised shape reads as empty; the only cost is a
    redundant upload, and that is the direction to fail in.
    """
    path = _upload_state_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: value
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _write_upload_state(state: Dict[str, str]) -> None:
    try:
        _upload_state_path().write_text(json.dumps(state, indent=2) + '\n')
    except OSError:
        # A record that cannot be written is a record that is not there: the next
        # run re-uploads. Nothing about the package just staged is affected, and
        # there is nothing the setter would do about it.
        return


def _recorded_fingerprint(server: str, problem_id: str) -> Optional[str]:
    return _read_upload_state().get(_upload_state_key(server, problem_id))


def _record_upload(server: str, problem_id: str, fingerprint: str) -> None:
    state = _read_upload_state()
    state[_upload_state_key(server, problem_id)] = fingerprint
    _write_upload_state(state)


def _forget_upload(server: str, problem_id: str) -> None:
    """Drop what is recorded for one problem, leaving every other one intact."""
    state = _read_upload_state()
    if state.pop(_upload_state_key(server, problem_id), None) is None:
        return
    _write_upload_state(state)


def _directory_fingerprint(path: pathlib.Path) -> str:
    """A digest over every file in the built package, path and contents.

    Deterministic across machines (sorted relative POSIX paths, lengths framed so
    a rename cannot be absorbed into a neighbouring file's bytes) and covers
    exactly what the upload sends: change a testcase, the limit, `problem.yaml`
    or the output validator, and this moves.
    """
    digest = hashlib.sha256()
    for file_path in sorted(p for p in path.rglob('*') if p.is_file()):
        rel = file_path.relative_to(path).as_posix().encode()
        content = file_path.read_bytes()
        digest.update(f'{len(rel)}:'.encode())
        digest.update(rel)
        digest.update(f'{len(content)}:'.encode())
        digest.update(content)
    return digest.hexdigest()


# -- the judgement cache ---------------------------------------------------------
#
# `rbx time` is a command a setter runs *again*: tweak a solution, re-estimate,
# change the profile, look at the table once more. Every re-run used to re-submit
# every solution, including ones whose source had not changed by a byte -- and a
# submission occupies the whole judgehost for as long as the solution takes on
# every test, with `MAX_INFLIGHT_SUBMISSIONS = 1` making that strictly serial. So
# a finished judging is remembered, keyed (see `_cache_key`) so that a hit is
# provably the same measurement rather than merely a similar one.
#
# **There is no `--no-cache` flag**, deliberately. The two questions a flag would
# answer both have better answers already: "I changed something" is what the key
# is for, and it covers everything rbx can observe; "I want to see the variance"
# is not a workflow this backend supports at all, since `nruns > 1` is refused
# outright (`RunnerCapabilities.supports_nruns`). What is left is the blind spot
# no flag can fix either -- a park whose hardware or load changed underneath the
# numbers -- and for that the honest escape hatch is to throw the observations
# away, which is one `rm -rf` of a directory under the problem cache.
#
# No expiry, no size cap, no eviction, for want of a problem they would solve: an
# entry is a few hundred bytes of JSON, entries are only written for packages that
# were really staged, and a stale entry is unreachable rather than wrong -- its
# key names a package fingerprint no later run will ever produce again.


def _judgement_cache_dir() -> pathlib.Path:
    path = package.get_problem_cache_dir() / JUDGEMENT_CACHE_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _is_cacheable(
    judgement: Dict[str, Any], runs: List[Dict[str, Any]], mismatched: bool
) -> bool:
    """Whether this judging is a measurement worth remembering.

    Three refusals, and every one of them is a thing the setter is about to
    *fix*, where answering the next run from the cache would make the fix appear
    to change nothing:

    - **no runs at all.** The submission never entered the testset: a compile
      error, a judgehost that fell over, a judging that died. This is the
      analogue of MOJ's `ran_nothing` check, and it is what keeps a `CE` out of
      the cache -- the one a setter is guaranteed to hit, and the one that would
      be maddening to have remembered.
    - **a run list rbx refused to pair** (more runs than the testset). Nothing
      was attributed to anything, so there is nothing to remember.
    - **a verdict rbx cannot read.** `_evaluation_for` raises on it by name so
      the fix is a one-line table entry; caching the response would mean the fix
      did nothing until the cache was cleared.

    A non-accepted judging **is** cached, on purpose. A WA, an RE or a TLE is a
    legitimate, reproducible measurement of a solution that is *supposed* to fail
    -- the validation phase exists to measure exactly those -- and its timings are
    as real as an accepted solution's. Only "rbx could not read this" is refused,
    never "the judge did not like the solution".
    """
    if mismatched or not runs:
        return False
    if str(judgement.get('judgement_type_id') or '') == COMPILATION_ERROR_VERDICT:
        # Belt and braces: DOMjudge reports a compile error with no runs, so the
        # check above already covers it. It stays because the rule being applied
        # here is "never remember a build failure", and leaving that to be
        # inferred from an empty list is how such a rule gets lost.
        return False
    return all(
        str(run.get('judgement_type_id') or '') in _OUTCOMES
        for run in runs
        if run.get('ordinal') is not None
    )


def _load_cached_judgement(
    key: str,
) -> Optional[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]]:
    """The submission id, judgement and runs remembered under `key`, if any.

    Anything unreadable -- absent, truncated, not JSON, not the shape it was
    written in, written by a version of this code that meant something else by it
    -- reads as a miss. That is the direction to fail in: a miss costs one
    redundant submission, while trusting a half-written file costs a wrong timing
    in the number `rbx time` is about to write into a limits profile.
    """
    path = _judgement_cache_dir() / f'{key}.json'
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None

    submission = payload.get('submission')
    judgement = payload.get('judgement')
    runs = payload.get('runs')
    if not isinstance(submission, str) or not submission:
        return None
    if not isinstance(judgement, dict) or not isinstance(runs, list):
        return None
    if not all(isinstance(run, dict) for run in runs):
        return None
    return submission, judgement, runs


def _store_cached_judgement(
    key: str,
    submission_id: str,
    judgement: Dict[str, Any],
    runs: List[Dict[str, Any]],
) -> None:
    """Remember a judging rbx was able to read in full.

    **Only ever called for a judging that passed `_is_cacheable`**, which is what
    keeps a failure out of the cache.

    What is stored is the API's own answer -- the judgement object and the run
    list -- rather than the evaluations derived from them. The derivation depends
    on which testcases *this* run asked about, so storing its output would bake
    one run's testset into an entry the next run reuses. Storing the input instead
    means a hit re-derives, through the same `_Judging`, against whatever the
    current run asked for.

    Written whole and then moved into place, because a poll interrupted mid-write
    would otherwise leave a truncated JSON file under a key that says it describes
    a real measurement. `_load_cached_judgement` tolerates that anyway; this makes
    it not happen.
    """
    directory = _judgement_cache_dir()
    path = directory / f'{key}.json'
    payload = {
        'submission': submission_id,
        'judgement': judgement,
        'runs': runs,
    }
    try:
        # Same directory, so the replace is atomic on every filesystem rbx runs
        # on.
        with tempfile.NamedTemporaryFile(
            'w', dir=directory, prefix=f'.{key}-', suffix='.tmp', delete=False
        ) as tmp:
            tmp.write(json.dumps(payload, indent=2) + '\n')
            temporary = pathlib.Path(tmp.name)
        temporary.replace(path)
    except OSError:
        # A cache that cannot be written is a cache that is not there. The
        # measurement in hand is unaffected, and saying anything here would be
        # said from a background task, about something the setter did not ask for
        # and cannot act on.
        return


# Re-exported so `registry` can name the class without knowing the module layout.
__all__ = [
    'DomjudgeRunner',
    'DomjudgeRunnerError',
    'DomjudgeApiError',
    'SolutionRunner',
]
