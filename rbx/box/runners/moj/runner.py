"""The backend that measures solution timings on the MOJ judge park.

`rbx time` estimates a time limit from timings measured *where rbx runs*. This
runner measures them where the problem will actually be judged instead: it
uploads a throwaway probe package to a private `rbxt-` problem on MOJ, has the
judge calibrate it, and then runs each solution there with `moj testrun`.

Everything expensive is once per run, which is what `prepare` is: one upload and
one calibration serve however many solutions get measured, because `moj testrun`
sends the source of the solution being timed in the request body rather than
reading it out of the package.

Design: `docs/plans/2026-08-20-moj-remote-runner-design.md`.
"""

import asyncio
import dataclasses
import hashlib
import json
import pathlib
import tempfile
from typing import (
    TYPE_CHECKING,
    Any,
    Coroutine,
    Dict,
    FrozenSet,
    List,
    Optional,
    Tuple,
    TypeVar,
)

import typer
from pydantic import ValidationError

from rbx import console, utils
from rbx.box import environment, package, tasks, timing_config
from rbx.box.code import find_language
from rbx.box.deferred import Deferred
from rbx.box.exception import RbxException
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging.moj.moj_language_utils import get_moj_language_from_rbx_language
from rbx.box.packaging.moj.packager import (
    HALT_VERDICTS,
    MojPackager,
    ProbePackage,
    ProbePinned,
)
from rbx.box.runners.base import (
    RunContext,
    RunnerCapabilities,
    RunnerChip,
    RunProgress,
    RunPurpose,
    SolutionRunner,
)
from rbx.box.runners.moj import cli, problem_id
from rbx.box.runners.moj.problem_id import ensure_moj_id, is_rbxt_id, moj_id_path
from rbx.box.schema import CodeItem
from rbx.grading.steps import (
    CheckerResult,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)

if TYPE_CHECKING:
    # Only for the annotation: `solutions` imports the runner machinery back, and
    # `base.py` takes the same precaution for the same reason.
    from rbx.box.solutions import SolutionSkeleton

# How often to ask whether the calibration has finished, and how many times.
#
# The cadence matches the CLI's own wait loop (200 polls at 3s). The *count* is
# larger because what is being waited on is bigger: the CLI bounds one testrun of
# one solution, while calibration runs every `sols/good` solution -- and then
# `pass`, `slow` and `wrong` -- over the whole testset, on a judge shared with
# everyone else's submissions.
#
# There is a bound at all because "not ready" is an assumption, not an
# observation: `moj check` reports no terminal failure state, and the CLI itself
# handles none (see `cli.DONE_STATUS`). Without a bound, a calibration that dies
# on the judge leaves `rbx time` waiting forever with no output -- the worst of
# the failure modes, because it looks like slowness rather than like a failure.
CALIBRATION_POLL_INTERVAL_SECONDS = 3.0
CALIBRATION_POLL_ATTEMPTS = 400

# How often to ask whether a *testrun* has finished, and how many times.
#
# Exactly the CLI's own wait loop (200 polls at 3s, ~10 minutes), because this
# waits on exactly what the CLI waits on: one solution against one testset. The
# bound exists for the same reason `CALIBRATION_POLL_ATTEMPTS` does, and the live
# probe strengthened the case rather than weakened it: a queued run carries no
# `tests` key at all and **no terminal failure status was ever observed**
# (`docs/plans/2026-08-21-moj-probe-notes.md`, "Shape while still running"). So
# "not done" cannot be distinguished from "will never be done", and an unbounded
# poll would hang `rbx time` with no output.
TESTRUN_POLL_INTERVAL_SECONDS = 3.0
TESTRUN_POLL_ATTEMPTS = 200

# How many testruns rbx keeps in flight at once. **One**, for three reasons that
# all point the same way.
#
# 1. **The account quota.** MOJ allows one login only a few queued testruns -- three,
#    observed -- and answers 429 beyond that. The quota counts testruns rbx has
#    *dispatched*, not ones it is still waiting on, and an interrupted `rbx time`
#    leaves its runs going on the judge (rbx stops waiting; MOJ does not stop
#    running). Dispatching one at a time leaves room for the previous session's
#    stragglers instead of racing them for the last slot.
# 2. **Measurement.** `moj testrun` has no host selection -- it posts only
#    `{id, filename, code_b64}` and the server picks -- and every testrun of the
#    2026-08-21 probe came back `host: judge-sp1`. Two in flight are therefore not
#    reliably one per judge; they may share a machine and inflate each other's
#    times, which is the contention `ALLOWPARALLELTEST=n` removes *inside* a run.
#    Serialising a run's tests and then racing two runs would be half a fix.
# 3. **A shared park.** Every other setter's submissions queue behind whatever rbx
#    dispatches, and this bounds how much of a run is lost when a session stops.
#
# The cost is real: a session now takes as long as the sum of its solutions. That is
# the trade -- `rbx time` is not on anyone's critical path, a re-run is free from the
# testrun cache, and a number that is quietly wrong is worth less than one that took
# twice as long to be right.
#
# `run_solution` still dispatches in the *background* rather than lazily, which is
# what this cap does not change: the first testrun is on the judge while the report
# is still starting, and each next one begins the moment its predecessor finishes
# rather than after the report has finished rendering the one before.
#
# A constant rather than a setting, deliberately. The design sketches
# `runners.moj.concurrency` in `env.rbx.yml`, but raising it trades measurement
# accuracy and a shared queue for wall clock, which is not a trade a timing run
# should offer.
MAX_INFLIGHT_TESTRUNS = 1

# How long to wait out a full testrun queue before giving up, and how often to
# retry. ~10 minutes, matching the CLI's own patience for a single testrun
# (200 x 3s): the queue drains when the runs holding it finish, so the unit that
# matters is how long one testrun takes, not how long a session does.
#
# Longer than that and the honest answer is that something is stuck and the setter
# should look, since nothing rbx can do will clear it -- MOJ exposes no way to
# cancel a testrun.
QUEUE_FULL_INTERVAL_SECONDS = 15.0
QUEUE_FULL_ATTEMPTS = 40

# MOJ's per-test `code`, as it lands in `TestrunTest.code`, mapped onto rbx's
# `Outcome`. Adding a code is one line here and nothing else.
#
# **Observed** -- provoked against the live judge and read off the response
# (`docs/plans/2026-08-21-moj-probe-notes.md`, section 3): all four below. There
# are no *inferred* entries in this table on purpose. `MLE`, `OLE`, `PE`, `CE` and
# `JE` are codes MOJ plausibly emits -- it enforces `MEMLIMITMB`, and its checker
# bridge has a judge-error path -- but plausibly is not observed, and their exact
# spellings are guesses. An unrecognised code is therefore refused by name (see
# `MojRunner._submit_and_poll`) rather than mapped: this table feeds a *time
# limit*, and a wrong verdict there is silent. A solution mis-mapped to ACCEPTED contributes its
# time to the estimate as if it had passed; one mis-mapped to TIME_LIMIT_EXCEEDED
# drops out of it. Neither leaves a trace in the report the setter reads.
_OUTCOME_BY_MOJ_CODE: Dict[str, Outcome] = {
    'AC': Outcome.ACCEPTED,
    'WA': Outcome.WRONG_ANSWER,
    'RE': Outcome.RUNTIME_ERROR,
    'TLE': Outcome.TIME_LIMIT_EXCEEDED,
}

# What goes in `TestcaseLog.exitstatus` for a testcase MOJ ran.
#
# Not one of `SandboxBase`'s constants, because none of them is true: those name
# how a *local* sandbox observed the process exit, and MOJ reports a verdict, not
# a wait status. `EXIT_SANDBOX_ERROR` -- what `RunLog` defaults to -- would be
# actively wrong, since `checkers.py` reads it as "the sandbox broke". A plain
# honest string follows the precedent `_record_skipped_evaluation` set with
# `'skipped'`.
REMOTE_EXIT_STATUS = 'judged remotely'

# ... and for one MOJ did not report on. See `_evaluation_for`.
UNREPORTED_EXIT_STATUS = 'not reported'


@dataclasses.dataclass
class _TestrunResult:
    """What one finished testrun tells rbx, shared by that solution's deferreds.

    A dataclass rather than the bare `{name: test}` dict because four of these
    fields exist to be *said* rather than read: what the judge left out, whether
    the numbers came off the judge or off the cache, and whether anyone has
    mentioned either yet. All of them are decided on the background task and
    reported from `_evaluation_from_job`, which is the only code here running on
    the consumer's thread of control.
    """

    run: str
    tests: Dict[str, cli.TestrunTest]
    # How many testcases rbx asked about, for a "3 of 72" that means something.
    expected: int
    # The names rbx asked about and MOJ said nothing about.
    missing: List[str]
    # Set the first time the missing ones are reported, so N deferreds over one
    # testrun produce one warning rather than N.
    warned: bool = False
    # Whether this came out of the local testrun cache rather than off the judge.
    # `run` is then the id of the testrun that was really measured, back when it
    # was measured -- which is the id the setter needs to look the run up.
    cached: bool = False
    # Same idea as `warned`, for the cache-hit line.
    announced: bool = False


def _retrieve_exception(task: 'asyncio.Task') -> None:
    """Consume a background testrun's exception so nothing else has to.

    `run_solution` dispatches every solution up front, but the report consumes
    them one at a time and stops at the first failure. So solutions 2..N can end
    up with a task nobody ever awaits -- and a task that failed unretrieved prints
    its traceback later, from the garbage collector, attached to nothing the
    setter did. Touching `.exception()` here marks it retrieved; the deferred that
    does await it still gets the exception raised normally, because retrieving
    does not consume it.

    **This is only about a task that finished.** A task still *pending* when the
    run ends is `close`'s business: it cancels everything left in `self._jobs`,
    from a `finally` around the *consumption* of the deferreds rather than from
    inside `run_solutions` -- which is the timing the removed `finalize` hook got
    wrong.
    """
    if not task.cancelled():
        task.exception()


# Where the fingerprint of the last package this machine successfully uploaded and
# calibrated is kept. Under the problem cache rather than beside `.moj-id`: it is a
# per-machine observation ("*I* put this package there"), not part of the binding,
# and losing it costs one redundant upload rather than correctness. See
# `_recorded_fingerprint`.
UPLOAD_STATE_NAME = 'moj-runner.json'

# Where finished testruns are remembered, one JSON file per cache key.
#
# Beside the upload record, under the problem cache, and for the same reason: a
# testrun is an observation this machine made about a package it uploaded, not
# anything that belongs to the package itself. Nothing here may be committed --
# it says what *a* judge park answered at *a* moment -- and losing it must cost a
# redundant testrun, never a wrong measurement. See `_cache_key`.
TESTRUN_CACHE_DIR_NAME = 'moj-testruns'

# Bumped when a change would make an older entry read wrong. It is part of the
# key rather than a field to validate, so entries of another version simply never
# match -- there is nothing to migrate and nothing to delete, and the cost of a
# bump is one redundant testrun per solution.
TESTRUN_CACHE_VERSION = 1


class MojRunnerError(RbxException):
    """The MOJ runner cannot do what the run asked of it.

    Messages are **plain text with backticks**, never rich markup: `main.py`
    bare-prints `str(e)`, so `[item]...[/item]` would reach the setter literally.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


def _run_never_started(
    solution: 'SolutionSkeleton', run: str, status: cli.TestrunStatus
) -> MojRunnerError:
    """The error for a finished testrun that never ran a single testcase.

    **This exists because of the first end-to-end run of `rbx time --runner moj`.**
    Every solution came back as `{"status": "done", "verdict_canon":
    "Compilation Error", "correct": 0, "total_tests": 0, "tests": []}` -- they did
    not build on the judge -- and rbx said, once per solution:

        MOJ reported no result for 6 of 6 testcases of tle-and-incorrect.sol.cpp
        (testrun c4bbc86b...). Those testcases are left unmeasured; the time limit
        is estimated from the rest.

    Every word of that is true and none of it is usable. It describes six
    testcases that were never the problem, and it never mentions the compiler
    output, which was one command away the whole time. So the run-level verdict is
    named here, and the command that shows the judge's own report is quoted with
    the real run id in it.

    **Raised rather than degraded per testcase, on purpose.** A `SKIPPED`
    testcase means "rbx has no measurement for this one", and the estimator is
    entitled to carry on with the rest -- which is right for a truncated run,
    where the rest genuinely exist. Here there is no rest: nothing about this
    solution was measured, and letting N deferreds each resolve to `SKIPPED`
    produces a report shaped like a partial success. The end-to-end run did
    eventually stop, on `Failed to run ACCEPTED solutions`, which was luck of the
    expectations rather than a decision -- a solution declared slow, or a `TLE`
    the estimator is content to drop, would have gone through and left the limit
    silently estimated from fewer solutions than the setter asked for. Failing the
    solution outright is the same call the unknown-code check makes, for the same
    reason: this feeds a *time limit*, and a wrong one leaves no trace.
    """
    verdict = status.canonical_verdict
    named = f'`{verdict}`' if verdict else 'no verdict at all'

    lines = [
        f'MOJ finished the testrun of `{solution.path}` without running a single '
        f'testcase: it reported {named} for the run as a whole (testrun `{run}`).',
        'So this is not a case of some testcases going unmeasured -- the '
        'submission never ran, and rbx has no timings for it.',
    ]

    # Named specifically because it is by far the likeliest of the run-level
    # verdicts and because its fix is local: the judge compiles with the
    # package's own `scripts/<lang>/compile.sh`, which is neither the compiler nor
    # the flags rbx used to compile the same solution successfully a moment ago.
    # `compil` rather than the exact string so the Portuguese spelling the CLI
    # sometimes prints (`Erro de Compilacao`) lands here too.
    if verdict and 'compil' in verdict.lower():
        lines.append(
            f'That usually means `{solution.path}` did not build on the judge. '
            f"MOJ compiles a submission from a single file, with the package's "
            f'own compile script -- not with the compiler or the flags rbx uses '
            f'locally, so a solution that builds here can still fail there.'
        )

    lines.append(
        f'See what the judge said, compiler output included, with '
        f'`moj testrun-status {run} --report moj-{run}.html`.'
    )
    return MojRunnerError('\n'.join(lines))


class MojRunner:
    name = 'moj'
    caps = RunnerCapabilities(
        # `moj testrun-status` reports `{name, code, time, tl}` per test, and
        # nothing about memory. MOJ does enforce a memory limit (`MEMLIMITMB`),
        # so an MLE still arrives as a verdict -- there is simply no number.
        measures_memory=False,
        # The judge keeps the run's stdout/stderr; the API hands back a verdict,
        # not the bytes. Writing an empty `.out` would claim the solution printed
        # nothing, which is a plausible-looking lie.
        captures_artifacts=False,
        # MOJ judges with the packaged checker and returns a `code`, never the
        # checker's own words.
        reports_checker_messages=False,
        # One testrun is one execution per test. Repeating would mean N
        # submissions to a shared judge park, so a run asking for repeats is
        # refused by name rather than silently measured once.
        supports_nruns=False,
        # A testrun has already run every test it was going to by the time rbx
        # sees the result, so aborting saves nothing -- and gating would
        # overwrite real judge verdicts with SKIPPED.
        #
        # The saving the local gate exists for is not lost, it is delegated: a
        # probe package sets `STOPWHEN_TLE=y`, so the judge itself stops a
        # solution at its first timeout, which is the same rule `abort_on` asks
        # for in both `rbx time` phases. The tests it therefore never reports
        # become SKIPPED here, exactly as the gate would have written them.
        #
        # One visible consequence, in `rbx time`'s validation phase. That phase
        # aborts a slow solution at its first timeout, so locally the testcases
        # after it are SKIPPED and contribute nothing. Here they all really ran,
        # so a solution that both times out *and* answers some later test wrongly
        # comes back with a WA beside the TLE, and `_record_validation_run` reads
        # a non-slow bad verdict as "broke for another reason" rather than as
        # confirmation. That is more information, not less -- the WA is real, and
        # the local abort merely hid it -- but it does mean a slow solution that
        # is also wrong is reported here and passes locally. The fix is the same
        # one the message names: fix the solution, or `inference: false` it.
        supports_abort=False,
        # `MojPackager.task_types()` is `[BATCH]`: MOJ's interactive support uses
        # its own arbiter protocol, not a testlib interactor.
        supports_interactive=False,
        # Sanitizers are a local-compilation concept; the judge compiles the
        # submission itself, with the package's own `scripts/<lang>/compile.sh`.
        supports_sanitizers=False,
        # MOJ judges every submission with the packaged checker; there is no
        # "just run it" mode. And a probe package cannot be built at all without
        # the answers `--no-check` skips building, so this would fail on the way
        # up regardless -- pointing at packaging rather than at the flag.
        supports_unchecked=False,
    )

    def __init__(self) -> None:
        # Everything below is settled by `prepare` and read by `run_solution`.
        # One `MojRunner` instance serves a whole `run_solutions` call --
        # `_produce_solution_items` holds the same object across every solution --
        # so instance state is the run's state, and a second run gets a second
        # object rather than a stale field.
        #
        # `run_solution` refuses rather than re-derives when these are unset: the
        # remote problem is not something to guess at, and the testcase names have
        # to be the ones the *uploaded* package used, not the ones a fresh
        # packager would produce from whatever the tree holds now.
        self._moj_id: Optional[str] = None
        self._packager: Optional[MojPackager] = None
        self._names_by_entry: Optional[Dict[Tuple[str, int], str]] = None
        # The fingerprint of the probe package this run measures against, set
        # whether or not it had to be uploaded -- the fast path skips the upload
        # precisely *because* the judge already holds this package, so the
        # fingerprint describes what is up there either way. It is the first term
        # of the testrun cache key; see `_cache_key`.
        self._fingerprint: Optional[str] = None
        # Created on first use rather than here: an `asyncio.Semaphore` belongs to
        # the loop that first awaits it, and nothing guarantees this object was
        # constructed inside the loop that will run it.
        self._testrun_slots: Optional[asyncio.Semaphore] = None
        # Every testrun this run dispatched. Held so a task in flight cannot be
        # garbage-collected out from under the judge; see `_retrieve_exception`
        # for the other half of why, and for what is still missing.
        self._jobs: List['asyncio.Task[_TestrunResult]'] = []

    async def prepare(self, ctx: RunContext) -> None:
        """Get a calibrated probe problem onto the judge, once per run.

        Everything here is idempotent across runs by design: the `rbxt-` problem
        is persistent (`.moj-id` is committed and reused), so a session that dies
        halfway leaves the next one closer to ready rather than leaving garbage.
        """
        overall = _Elapsed()

        if ctx.progress:
            ctx.progress.update('Reading your MOJ login...')
        # Surfaced as-is: `cli.whoami` already distinguishes "the CLI is not
        # installed" from "you are not logged in", and both have a different fix
        # from anything this module could say.
        login = await cli.whoami()

        purpose = ctx.purpose
        # One remote problem per purpose. They run under different limits and
        # different stop rules, and both live *in the package*, so a single
        # problem would be re-uploaded and re-calibrated every time two purposes
        # took turns -- and its recorded fingerprint would never match at the
        # start of a run, so the fast path could not fire at all. A problem each
        # keeps every package stable across runs. See `problem_id.derived_id`.
        moj_id = problem_id.derived_id(self._problem_id(login), _id_suffix(purpose))
        self._moj_id = moj_id

        pin = _probe_pin(ctx)

        # The package is built on every run, even when the upload is about to be
        # skipped: it is cheap (copying built tests, amalgamating the checker) and
        # it is what the fast path compares against. The expensive half is the
        # upload and the calibration, which is what gets skipped.
        with tempfile.TemporaryDirectory(prefix='rbx-moj-probe-') as tmp:
            # Both live inside the temp dir on purpose. `package()` also writes a
            # `.zip` of the tree into `build_path` and returns its path, while
            # `moj upload` wants the *directory*; putting the archive somewhere
            # that is deleted on the way out is how the stray file stops
            # mattering.
            root = pathlib.Path(tmp)
            build_path = root / 'build'
            package_path = root / 'package'
            build_path.mkdir(parents=True, exist_ok=True)

            if ctx.progress:
                ctx.progress.update('Building the MOJ probe package...')
            self._build_probe(ctx, package_path, build_path, pin)

            fingerprint = _directory_fingerprint(package_path)
            self._fingerprint = fingerprint
            if await self._is_already_prepared(moj_id, fingerprint, ctx):
                # Said out loud, because otherwise it is unobservable. The status
                # line `_is_already_prepared` sets is transient -- the next
                # `update` overwrites it and the spinner clears at the end of the
                # run -- so a setter watching two phases go past has no way to
                # tell the cheap one from the expensive one, and no way to tell
                # that the second phase re-uploaded at all.
                console.console.print(
                    f'[status]moj · [item]{moj_id}[/item] · reused, package '
                    f'unchanged since the last upload ({overall}).[/status]'
                )
                return

            # Cleared *before* the upload, not after: from the moment the server
            # starts receiving a new package, the recorded fingerprint no longer
            # describes what is up there. A crash mid-upload must leave the next
            # run re-uploading, never trusting a stale record.
            _forget_upload(moj_id)

            # Measured before the upload rather than after: the temp directory is
            # gone by the time the summary is printed.
            size = _directory_size(package_path)
            upload_elapsed = _Elapsed()
            await _with_ticker(
                ctx,
                cli.upload(moj_id, package_path),
                f'Uploading the probe package to [item]{moj_id}[/item] '
                f'([item]{utils.format_size(size)}[/item])... {{elapsed}}',
            )

        calibration_elapsed = _Elapsed()
        await cli.calibrate(moj_id)
        await self._wait_for_calibration(moj_id, ctx)
        _record_upload(moj_id, fingerprint)

        console.console.print(
            f'[status]moj · [item]{moj_id}[/item] · uploaded '
            f'[item]{utils.format_size(size)}[/item] of package files in '
            f'[item]{upload_elapsed}[/item], calibrated in '
            f'[item]{calibration_elapsed}[/item].[/status]'
        )

    def _say(
        self,
        board: RunProgress,
        solution: 'SolutionSkeleton',
        *chips: RunnerChip,
    ) -> None:
        """Put this solution's current state on the board, as one whole line.

        Always led by the remote problem, because on a park shared between the
        two `rbx time` phases -- which upload to *different* problems -- knowing
        which one a testrun belongs to is what makes the rest of the line mean
        anything.

        Writing here is safe from a polling task in a way that writing to the
        console is not: the board is a per-solution slot, and the reporter draws
        only the slot it is currently blocked on. See `RunProgress`.
        """
        board.set(
            str(solution.path),
            RunnerChip(f'moj {self._moj_id}' if self._moj_id else 'moj'),
            *chips,
        )

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
        already sitting in the judge's queue while the report is still printing
        the first one. That is the entire reason the seam is per solution.

        The N deferreds share one job. `Deferred` will not do that for you: its
        `__call__` memoizes each deferred's *own* result with a bare
        `if self.cache is None` and no lock, so N deferreds over one submission
        would be N submissions unless the task is held here.
        """
        if not entries:
            # No entries, no submission -- and, more to the point, no task. An
            # `asyncio.Task` nobody awaits whose body raises prints an
            # "exception was never retrieved" traceback out of the garbage
            # collector, at a moment unrelated to anything the setter did.
            return []

        names = self._names_for(entries)

        if self._testrun_slots is None:
            self._testrun_slots = asyncio.Semaphore(MAX_INFLIGHT_TESTRUNS)

        # `create_task`, not a coroutine held for later: the point is that the
        # judge starts working before anything awaits. The task is captured by
        # every deferred below and by `self._jobs`, so it is never
        # garbage-collected mid-flight.
        # Said before the task is even created, so a solution the report has not
        # reached yet is already accounted for on the board rather than blank.
        self._say(ctx.progress_board, solution, RunnerChip('waiting for a slot'))

        job = asyncio.create_task(
            self._submit_and_poll(solution, names, ctx.progress_board)
        )
        job.add_done_callback(_retrieve_exception)
        self._jobs.append(job)

        return [
            Deferred(
                # Bound as defaults, because the lambda outlives the loop
                # iteration: a late-bound `entry` would give every deferred the
                # last testcase's evaluation.
                lambda entry=entry, name=name: self._evaluation_from_job(
                    job, solution, entry, name, ctx
                )
            )
            for entry, name in zip(entries, names)
        ]

    async def close(self) -> None:
        """Stop waiting on every testrun nobody is going to read. Idempotent.

        `run_solution` queues **every** solution up front -- that is the point of
        the seam -- while the report consumes them one at a time and stops at the
        first failure. So a run that ends early (a solution whose job raised, a
        report that blew up, Ctrl-C) leaves the later solutions' tasks polling MOJ
        for results nothing will ever ask for, and asyncio reports them at
        interpreter exit as `Task was destroyed but it is pending!` -- a message
        about rbx internals, arriving after the error the setter actually cares
        about. This is the hook `_retrieve_exception` said was missing.

        **The drain is not optional.** `cancel()` schedules a `CancelledError`;
        a task suspended in `cli.testrun_status` is suspended inside
        `process.communicate()`, which takes several turns of the loop to unwind
        -- and `syncer` stops the loop as soon as the consumer returns or raises,
        which is the very path this is called on. Awaiting the tasks here is what
        makes "cancelled" true by the time `close` returns instead of hoping
        something later pumps the loop.

        **Ends this batch, not this runner.** `_moj_id`, `_packager` and
        `_names_by_entry` are deliberately left alone: the remote problem is
        persistent by design, and a second batch on the same object (the
        validation phase, re-preparing at `ceil(TL_lang x timeLimitToTle)`) is
        meant to reuse the binding rather than resolve it again. It does still
        re-upload: the limits moved, and the limits live in the package.

        **Only the runner-side wait is cancelled. The judge keeps running.** A
        cancelled poll does not un-submit anything: MOJ has the submission and
        will finish it on its own schedule. That costs the setter nothing and
        needs no cleanup -- a `testrun` runs **outside history and placar**, so it
        leaves no submission on the problem, no entry in anyone's standings, and
        nothing to delete. It occupies a judge slot until it finishes, which is
        the honest cost of interrupting, and `MAX_INFLIGHT_TESTRUNS` is what
        bounds it.

        Called after the deferreds are consumed, never inside `run_solutions` --
        see `SolutionRunner.close` for why that timing is the whole difference
        between this and the `finalize` hook the seam deliberately does not have.
        """
        # Read and cleared first, so a second `close` (or one racing the report's
        # own teardown) has nothing left to cancel and says nothing twice.
        jobs, self._jobs = self._jobs, []
        pending = [job for job in jobs if not job.done()]
        for job in pending:
            # `cancel` on an already-finished task is a no-op returning False, so
            # filtering above is about what to *say*, not about safety.
            job.cancel()

        if not pending:
            return

        # `return_exceptions=True` because this is running in a `finally`, very
        # possibly while another exception is on its way to the setter: a job
        # that failed instead of cancelling, or a cleanup that raised on the way
        # out, must not replace the error they are actually looking at. Awaiting
        # every job (not only the pending ones) would be the same set anyway --
        # the finished ones were already retrieved by `_retrieve_exception`.
        await asyncio.gather(*pending, return_exceptions=True)

        # Said out loud, because the alternative is a setter who interrupted a
        # timing run wondering whether they left something broken on a shared
        # judge, with no way to find out. One line, after the fact, on the
        # consumer's own thread of control -- `close` is only ever called from
        # there.
        console.console.print(
            f'[warning]Stopped waiting for {len(pending)} MOJ testrun(s) that '
            f'were still in flight.[/warning]\n'
            f'[warning]They keep running on the judge until they finish, but a '
            f'testrun is outside history and placar, so there is nothing to clean '
            f'up.[/warning]'
        )

    # -- run_solution, in pieces ----------------------------------------------

    def _names_for(self, entries: List[GenerationTestcaseEntry]) -> List[str]:
        """The MOJ file name of each entry, in entry order.

        Looked up in the mapping `prepare` captured off the packager that built
        the uploaded package -- never re-derived. See `_names_by_entry`.
        """
        # The one place this is checked. `prepare` settles `_moj_id`,
        # `_packager` and `_names_by_entry` together and nothing clears them, so
        # every later user of the three asserts instead of repeating this prose --
        # three copies of the same sentence is three things to keep true.
        if self._names_by_entry is None:
            raise MojRunnerError(
                'The MOJ runner was asked to run a solution before it prepared '
                'the problem on the judge. This is an rbx bug: `prepare()` has to '
                'run first, and it is what settles which remote problem to submit '
                'to and what the judge calls each testcase.'
            )

        names: List[str] = []
        for entry in entries:
            name = self._names_by_entry.get(_entry_key(entry))
            if name is None:
                # The run is asking for a testcase the probe package does not
                # contain, so the judge never ran it and never will. There is no
                # honest evaluation to synthesize, and inventing a name would pair
                # this entry with some *other* testcase's timing.
                #
                # Not blamed on rbx: the likeliest cause is the built input file
                # having gone missing between the build and now, which is what
                # `find_built_testcases` filters on -- rebuilding is the fix, and
                # saying "rbx bug" would send the setter looking somewhere else.
                raise MojRunnerError(
                    f'The testcase `{entry.subgroup_entry}` is not in the package '
                    f'rbx uploaded to MOJ, so the judge has no result for it. The '
                    f'probe package is built from the testcases rbx found built on '
                    f'disk, so this one was most likely not among them.\n'
                    f'Run `rbx build` and try again.'
                )
            names.append(name)
        return names

    async def _submit_and_poll(
        self,
        solution: 'SolutionSkeleton',
        expected_names: List[str],
        board: RunProgress,
    ) -> '_TestrunResult':
        """Submit one solution and wait for its verdicts, keyed by MOJ test name.

        Holds a slot for the whole submit-and-wait, not just for the submit: what
        `MAX_INFLIGHT_TESTRUNS` bounds is how much of the shared judge park rbx
        occupies, and a run that has been dispatched is occupying it whether or
        not rbx is still talking to the server.

        **Writes to the board, never to the console.** This runs on a background
        task -- up to `MAX_INFLIGHT_TESTRUNS` of them at once, on their own
        schedule, long after the call that created them returned. The
        `StatusProgress` and the console belong to the reporter that is printing
        results right now, so a poll *printing* from here would make the display
        flip between solutions every few seconds. A board write does not: it
        lands in this solution's own slot, and the reporter draws only the slot
        it is currently blocked on (see `RunProgress`). So the solution the
        report is waiting on reports itself, live, while the nine queued behind
        it keep their slots current for free.

        Anything that has to be said *durably* -- a cache hit, a short testset --
        is still handed back and printed by `_evaluation_from_job`, on the
        consumer's own thread of control. The board is a status line: it is
        overwritten and then gone.

        **The cache is consulted before the semaphore, not inside it.** A hit
        costs one file read and no judge time at all, so making it queue behind
        two real testruns would serialize free work behind expensive work for no
        reason: a run where every solution hits would take as long as the slowest
        thing already in flight.
        """
        content = self._solution_content(solution)
        key = self._cache_key(solution, content)

        cached = _load_cached_testrun(key)
        if cached is not None:
            run, status = cached
            self._say(
                board,
                solution,
                RunnerChip(f'testrun {run}'),
                RunnerChip('cached', style='green'),
            )
            # Deliberately put through the *same* derivation a fresh status goes
            # through, rather than storing the derived `_TestrunResult`. That is
            # what makes a hit and a miss provably identical: there is one place
            # where a `TestrunStatus` becomes an rbx result, and both paths go
            # through it. It also means the checks below still apply to a cached
            # entry -- nothing that fails them was ever written, but a cache file
            # is a file on disk and may have been anything by the time it is read.
            result = self._result_from_status(solution, run, status, expected_names)
            result.cached = True
            return result

        # Started before the slot is taken, so what it counts is the whole wait
        # a setter is actually enduring -- queueing behind other solutions
        # included, which on `MAX_INFLIGHT_TESTRUNS = 1` is most of it.
        since = _Elapsed()

        assert self._testrun_slots is not None
        async with self._testrun_slots:
            run = await self._submit(solution, content)
            self._say(
                board,
                solution,
                RunnerChip(f'testrun {run}'),
                RunnerChip('submitted'),
                RunnerChip(str(since)),
            )
            status = await self._wait_for_testrun(run, solution, board, since)

        self._say(
            board,
            solution,
            RunnerChip(f'testrun {run}'),
            RunnerChip('done', style='green'),
            RunnerChip(str(since)),
        )

        result = self._result_from_status(solution, run, status, expected_names)
        # Written only once the status has survived every check above, which is
        # how "never cache a failure" is enforced: a compile error and an
        # unrecognised verdict code both raise out of `_result_from_status` and
        # never reach this line. See `_store_cached_testrun`.
        _store_cached_testrun(key, run, status)
        return result

    def _result_from_status(
        self,
        solution: 'SolutionSkeleton',
        run: str,
        status: cli.TestrunStatus,
        expected_names: List[str],
    ) -> '_TestrunResult':
        """One finished `TestrunStatus`, checked and paired onto rbx's testcases.

        The single path from a judge response to a run's results, taken by a
        fresh testrun and by a cache hit alike -- see `_submit_and_poll`. It
        raises rather than returns on everything the runner refuses to interpret,
        which is also what keeps those responses out of the cache.
        """
        # Before anything is paired: a run that never entered the testset has no
        # per-testcase story to tell, and telling one anyway is what the first
        # end-to-end run did wrong. Raised, not degraded, for the same reason the
        # unknown-code check below is raised -- see `_run_never_started`.
        if status.ran_nothing:
            raise _run_never_started(solution, run, status)

        # `by_name` refuses duplicate names rather than letting a dict
        # comprehension drop one of them.
        tests = status.by_name

        # Every code is checked here, once, before any evaluation is built -- and
        # the failure lands on *every* deferred of this solution, because they all
        # await this task. Doing it per-slice instead would let the entries before
        # the unknown code resolve into a report that looks complete.
        unknown = sorted(
            {
                test.code
                for test in tests.values()
                if test.code not in _OUTCOME_BY_MOJ_CODE
            }
        )
        if unknown:
            listed = ', '.join(f'`{code}`' for code in unknown)
            raise MojRunnerError(
                f'MOJ reported the verdict code(s) {listed} for `{solution.path}` '
                f'in testrun `{run}`, and rbx does not know what they mean.\n'
                f'Refusing to guess: only `AC`, `WA`, `RE` and `TLE` have ever '
                f'been seen from a real testrun (see '
                f'`docs/plans/2026-08-21-moj-probe-notes.md`), and a code mapped '
                f'to the wrong outcome would silently corrupt the time limit this '
                f'run is estimating, with nothing in the report to say so.\n'
                f'If the code is legitimate, add it to `_OUTCOME_BY_MOJ_CODE` in '
                f'`rbx/box/runners/moj/runner.py`.'
            )

        # Counted here, said later. Every test MOJ *did* report carries a real
        # verdict and a real timing, and throwing those away over the ones it did
        # not is the worse trade -- but a timing vector quietly short a few
        # entries is exactly how an estimate goes wrong without anyone noticing,
        # so it is said out loud, by `_evaluation_from_job`. The evaluations
        # themselves stay honest: unmeasured, never zero (see `_evaluation_for`).
        #
        # A probe package suppresses `STOPWHEN_*` precisely so this does not
        # happen; the live probe watched a failing run come back with 4 tests out
        # of 72 against a problem that had them enabled.
        missing = [name for name in expected_names if name not in tests]
        return _TestrunResult(
            run=run, tests=tests, expected=len(expected_names), missing=missing
        )

    def _solution_content(self, solution: 'SolutionSkeleton') -> bytes:
        """The exact bytes that get submitted for this solution.

        Amalgamated, because MOJ compiles a submission from one file. That is why
        this -- and not the source path, nor its mtime -- is what the cache keys
        on: amalgamation inlines the headers a solution includes, so two packages
        can hand the judge the same path and different programs.
        """
        # Asserted, not raised: `run_solution` cannot reach here without
        # `_names_for` having refused first, and `prepare` sets all three of these
        # together. See `_names_for` for the message a setter actually gets.
        assert self._packager is not None

        try:
            return self._packager.solution_content(solution)
        except typer.Exit as e:
            # Same reasoning as `_build_probe`: `MojPackager` reports a setter
            # mistake -- here, a solution that does not reduce to one translation
            # unit -- by printing and raising a CLI control-flow exception, and
            # letting that unwind a library call would end the command with an
            # exit code nothing here chose.
            raise MojRunnerError(
                f'Could not prepare `{solution.path}` for MOJ; see the error '
                f'above. MOJ compiles a submission from a single file, so every '
                f'solution rbx times has to reduce to one.'
            ) from e

    async def _submit(self, solution: 'SolutionSkeleton', content: bytes) -> str:
        """Queue one solution with `moj testrun` and return the run id."""
        assert self._moj_id is not None

        with tempfile.TemporaryDirectory(prefix='rbx-moj-testrun-') as tmp:
            # The **basename is load-bearing**: `moj testrun` sends
            # `filename: basename(sol)` and the server picks the language off the
            # extension. Writing the amalgamated bytes to `solution.cpp` would
            # compile a Python solution as C++.
            source = pathlib.Path(tmp) / solution.path.name
            source.write_bytes(content)
            # The problem *id*, not the package directory the CLI would also
            # accept: rbx builds its package into a temp dir that is long gone by
            # now, and the id is what `prepare` decided to write to.
            return await self._submit_when_the_queue_has_room(solution, source)

    async def _submit_when_the_queue_has_room(
        self, solution: 'SolutionSkeleton', source: pathlib.Path
    ) -> str:
        """`cli.testrun`, waiting out a full queue rather than failing the run.

        MOJ caps how many testruns one **account** may have waiting and answers
        429. That is not something rbx can avoid by dispatching less: an
        interrupted `rbx time` leaves its runs going on the judge (rbx stops
        waiting, MOJ does not stop running), and a second session or a hand-run
        `moj testrun` holds slots too. Nor can it be cleared -- the CLI has submit,
        status and report for a testrun and nothing that cancels one -- so waiting
        is the only recovery there is.

        Bounded, like every other wait here: a queue held by something that never
        finishes must fail with a message rather than hang `rbx time` forever. The
        slot is deliberately still held while waiting, so a full queue does not
        turn into every solution retrying at once.
        """
        assert self._moj_id is not None
        for attempt in range(QUEUE_FULL_ATTEMPTS):
            try:
                return await cli.testrun(self._moj_id, source)
            except cli.MojQueueFullError:
                if attempt == 0:
                    # Once, on the consumer's own thread of control: a run that
                    # goes quiet for minutes looks hung, and the reason is not
                    # something the setter could guess.
                    console.console.print(
                        f"[status]MOJ already has this account's testrun queue "
                        f'full, so [item]{solution.path}[/item] is waiting for a '
                        f'slot. Testruns from an interrupted run keep going on the '
                        f'judge until they finish.[/status]'
                    )
                if attempt + 1 < QUEUE_FULL_ATTEMPTS:
                    await asyncio.sleep(QUEUE_FULL_INTERVAL_SECONDS)
        waited = QUEUE_FULL_ATTEMPTS * QUEUE_FULL_INTERVAL_SECONDS / 60
        raise MojRunnerError(
            f'MOJ kept refusing to queue `{solution.path}`: this account already '
            f'has as many testruns waiting as it is allowed, and none of them '
            f'finished in {waited:.0f} minutes.\n'
            f'Testruns cannot be cancelled -- `moj` can submit, poll and fetch a '
            f'report, and nothing else -- so they have to run their course. Check '
            f'what is queued with `moj status`, and note that an interrupted '
            f'`rbx time --runner moj` leaves its testruns running on the judge.'
        )

    def _cache_key(self, solution: 'SolutionSkeleton', content: bytes) -> str:
        """What makes a cached testrun *the same measurement* as a fresh one.

        Three things, and the argument for each is what the cache is worth:

        - **the package the judge holds**, as `prepare`'s `_directory_fingerprint`
          of it. Everything the judge measures *against* is in there -- the
          testcases, the checker, the compile scripts, and the cap (see below) --
          so a package that fingerprints equal is a judge configured identically.
          Reusing that fingerprint rather than inventing a second key means the
          cache and the upload fast path can never disagree about what "the same
          package" means.
        - **the exact bytes submitted**, not the solution's path and not its
          mtime. `solution_content` amalgamates, so a change in an included
          header changes the program without touching the file rbx names -- and,
          the other way round, a whitespace-only edit that amalgamates to the
          same bytes really is the same submission.
        - **the file name**, because MOJ picks the *language* off the extension
          (`moj testrun` sends `filename: basename(sol)`), so it is part of the
          submission rather than a label on it.

        The remote problem id is in there too. It is very nearly implied by the
        package fingerprint -- the same bytes measured on two `rbxt-` problems of
        the same park measure the same -- but the id is what the timings were
        actually observed against, and keying on it costs one hash update.

        **The cap needs no term of its own.** It is emitted as `TLOVERRIDE` into
        the package's `conf`, which `_directory_fingerprint` hashes along with
        every other file; `test_a_changed_package_is_uploaded_again_even_though_
        the_problem_is_ready` is what pins that. So the validation phase, which
        re-uploads at `ceil(TL_lang x timeLimitToTle)`, gets a different
        fingerprint and therefore a different key for every solution -- exactly
        right, since those are different measurements. A picker round trip that
        lands back on limits already probed hits the cache instead.

        **What this cannot see** is the judge park itself. rbx has no way to ask
        MOJ which package a problem currently holds (the CLI exposes no package
        checksum), so a `moj upload` from another machine -- or by hand -- leaves
        both this key and `prepare`'s record describing a package the server no
        longer has. Nor does it see the park's hardware, its load, or a judge
        joining or leaving: a cached timing is a measurement from whenever it was
        taken. That is why the cache lives in the disposable problem cache and
        why the hit says where to delete it.
        """
        assert self._moj_id is not None
        assert self._fingerprint is not None

        digest = hashlib.sha256()
        # Framed with lengths, like `_directory_fingerprint`, so no field can be
        # made to look like part of the next one.
        for part in (
            f'v{TESTRUN_CACHE_VERSION}'.encode(),
            self._moj_id.encode(),
            self._fingerprint.encode(),
            solution.path.name.encode(),
            content,
        ):
            digest.update(f'{len(part)}:'.encode())
            digest.update(part)
        return digest.hexdigest()

    async def _wait_for_testrun(
        self,
        run: str,
        solution: 'SolutionSkeleton',
        board: RunProgress,
        since: '_Elapsed',
    ) -> cli.TestrunStatus:
        """Poll until the judge is finished with `run`. Bounded, and on the board.

        This is the slow half of a remote run and the half a setter most wants to
        see moving, so every poll repaints this solution's slot. It writes to the
        board rather than the console for the reason `_submit_and_poll` gives:
        printing from a background task would make the display flip between
        solutions, a board write cannot.

        What it can say depends on what the judge chose to answer with. The state
        word is always there; the counts and the host are reported by some
        responses and not others, so they are added when present rather than
        defaulted -- a `0/0` on a run that simply has not started would read as a
        judge losing the testset.
        """
        for attempt in range(TESTRUN_POLL_ATTEMPTS):
            status = await cli.testrun_status(run)
            if status.done:
                return status
            self._say(board, solution, *self._poll_chips(run, status, since))
            if attempt + 1 < TESTRUN_POLL_ATTEMPTS:
                await asyncio.sleep(TESTRUN_POLL_INTERVAL_SECONDS)

        minutes = int(TESTRUN_POLL_ATTEMPTS * TESTRUN_POLL_INTERVAL_SECONDS / 60)
        raise MojRunnerError(
            f'MOJ has not finished the testrun of `{solution.path}` after '
            f'{minutes} minutes, so rbx has no timings for it and stopped '
            f'waiting.\n'
            f'Check it with `moj --json testrun-status {run}`. A testrun runs '
            f'outside history and placar, so nothing on the server needs cleaning '
            f'up.'
        )

    def _poll_chips(
        self,
        run: str,
        status: cli.TestrunStatus,
        since: '_Elapsed',
    ) -> List[RunnerChip]:
        """What one in-flight poll has to say. Only what the judge reported."""
        chips = [RunnerChip(f'testrun {run}')]
        if status.status:
            chips.append(RunnerChip(status.status))
        if status.host:
            chips.append(RunnerChip(status.host))
        # `correct`, not "tests run": MOJ reports how many *passed*, and calling
        # that progress would show a solution expected to fail -- which is half
        # of what the validation phase submits -- stuck at 0 while it works fine.
        if status.total_tests:
            chips.append(RunnerChip(f'{status.correct or 0}/{status.total_tests} ok'))
        chips.append(RunnerChip(str(since)))
        return chips

    async def _evaluation_from_job(
        self,
        job: 'asyncio.Task[_TestrunResult]',
        solution: 'SolutionSkeleton',
        entry: GenerationTestcaseEntry,
        name: str,
        ctx: RunContext,
    ) -> Evaluation:
        """One entry's evaluation, out of the shared testrun.

        Awaiting a `Task` more than once is fine -- it hands every waiter the same
        result (or the same exception), and does not re-run the body.

        This is where the runner *prints* to the setter, and the only place it
        does during a run: it is reached from the deferred the reporter itself is
        awaiting, so a warning written here lands on the consumer's own thread of
        control rather than racing the live display from a polling task.

        Live status is not printed at all -- it goes on `ctx.progress_board`, from
        whichever task owns the solution, and this method only *clears* the slot
        once there is a real verdict to show instead.
        """
        # Nothing is said here on the way in, deliberately. This used to be
        # `ctx.progress.update('Waiting for MOJ to judge ...')`, which nobody ever
        # saw: every caller exits its `StatusProgress` context manager *before*
        # `print_run_report` runs, so the `Status` being updated was always
        # already stopped.
        #
        # It is not replaced by a board write either, and that is the more
        # interesting half. This solution's slot is already being repainted by
        # its own polling task, with the testrun id, the judge's state and how
        # long the wait has been -- strictly more than "waiting" -- so writing
        # here would overwrite a better line with a worse one, and leave it worse
        # until the next poll came round to fix it.
        result = await job

        # Said out loud, and said here, for the same reason the missing-testcase
        # warning is: a setter who expected a judge round-trip and got an answer
        # instantly has to be told *why* it was instant, or the run reads as
        # either magic or a bug. It also names the one way to force a real
        # measurement -- see `_testrun_cache_dir` for why that is a directory to
        # delete rather than a `--no-cache` flag.
        if result.cached and not result.announced:
            result.announced = True
            console.console.print(
                f'[status]Reused MOJ timings for [item]{solution.path}[/item] from '
                f'testrun [item]{result.run}[/item]: the probe package and the '
                f'submitted source are byte-for-byte the ones that run measured, '
                f'so nothing was submitted to the judge.[/status]\n'
                f'[status]Delete [item]{_testrun_cache_dir()}[/item] to measure it '
                f'again.[/status]'
            )

        # Once per testrun, not once per testcase, and only when the report has
        # actually got here. `warned` is set before anything awaits, so two
        # deferreds cannot both pass the check.
        if result.missing and not result.warned:
            result.warned = True
            console.console.print(
                f'[warning]MOJ reported no result for {len(result.missing)} of '
                f'{result.expected} testcases of [item]{solution.path}[/item] '
                f'(testrun [item]{result.run}[/item]).[/warning]\n'
                f'[warning]Those testcases are left unmeasured; the time limit is '
                f'estimated from the rest.[/warning]'
            )

        # The slot is deliberately **not** cleared here. Clearing it was meant to
        # keep a stale `running` chip from sitting beside a finished verdict, but
        # nothing here is stale: `_submit_and_poll` has already overwritten the
        # slot with `done` and the total wait, or with `cached`, before any
        # deferred can resolve. Both are exactly what the finished line should
        # say.
        #
        # And clearing actively lost them. The reporter's block is rebuilt on
        # every drawn frame, so the last frame -- the one `Live.stop()` freezes
        # into scrollback, and the only one a non-terminal console emits at all --
        # renders whatever the board holds *then*. Clearing first meant the
        # testrun id vanished from the permanent record and from every `--share`
        # report, which is where it is most worth having.

        # `.get`, not `[]`: a name MOJ did not report is a case with an answer,
        # and it is not this one blowing up. See `_evaluation_for`.
        return _evaluation_for(solution, entry, result.tests.get(name))

    # -- prepare, in pieces ---------------------------------------------------

    def _problem_id(self, login: str) -> str:
        """The `rbxt-` problem to upload to, refusing anything rbx did not create.

        `ensure_moj_id` returns a foreign binding **verbatim** -- `.moj-id` is
        written by `moj upload` too, so a package may legitimately be bound to a
        real, published problem. `cli.upload` overwrites whatever id it is given,
        so uploading a probe over that binding would destroy the setter's real
        problem: the tests would become rbx's, the statement would become the
        dummy, the solutions would become the model one alone. There is no undo
        and no `rbxt-` marker left afterwards to explain what happened.
        """
        moj_id = ensure_moj_id(login, package.find_problem())
        if is_rbxt_id(moj_id):
            return moj_id
        raise MojRunnerError(
            f'This package is bound to the MOJ problem `{moj_id}`, which rbx did '
            f'not create. Refusing to touch it: the MOJ runner uploads a '
            f'throwaway timing package, and doing that here would overwrite that '
            f"problem's tests, statement and solutions with rbx's probe.\n"
            f'If `{moj_id}` really is a scratch problem, delete the `id` field '
            f'from `{moj_id_path(package.find_problem())}` and rbx will bind a '
            f'fresh `rbxt-` problem of its own.'
        )

    def _build_probe(
        self,
        ctx: RunContext,
        package_path: pathlib.Path,
        build_path: pathlib.Path,
        pin: ProbePinned,
    ) -> None:
        """Build the probe package into `package_path`."""
        packager = MojPackager(
            testcase_entries=ctx.skeleton.entries,
            timing_mode=pin,
            probe=ProbePackage(
                submission_languages=_testrun_languages(ctx),
                halt_on=_halt_on(ctx),
            ),
        )
        # Kept for `run_solution`, which needs two things from this exact object:
        # the names the testcases take **in the package that gets uploaded**, and
        # `solution_content` to amalgamate each timed solution the same way the
        # shipped one was. Building a second packager there would be a second
        # chance to disagree with this one; and the names in particular cannot be
        # re-derived from the entries alone, which is why `testcase_names` is
        # public at all (see its docstring: the index is a 1-based running counter
        # over *built* entries, not `group_entry.index`).
        #
        # Assigned before `package()` runs, so the mapping is the one the fast
        # path's fingerprint was computed over too, whether or not the upload
        # happens.
        self._packager = packager
        self._names_by_entry = _names_by_entry(packager)
        try:
            packager.package(build_path, package_path, [])
        except typer.Exit as e:
            # `MojPackager` reports setter mistakes by printing to the console and
            # raising `typer.Exit` -- a CLI control-flow exception. It has already
            # said what is wrong (a non-C++ checker, a package with no `samples`
            # group, no accepted solution, an unamalgamatable source), and letting
            # `typer.Exit` escape through `run_solutions` would unwind a library
            # call as if a command had ended, with no exit code anyone here chose.
            raise MojRunnerError(
                'Could not build the MOJ probe package for this problem; see the '
                'error above. `rbx time --runner moj` uploads a MOJ package, so '
                'anything that stops `rbx package moj` stops it too.'
            ) from e

    async def _is_already_prepared(
        self, moj_id: str, fingerprint: str, ctx: RunContext
    ) -> bool:
        """Whether the judge already holds *this* package, calibrated.

        Two things have to hold, and neither implies the other:

        - `moj check` says the problem is ready -- calibrated, not being
          calibrated, and not stale (`MojCheck.is_ready`).
        - the package rbx just built is byte-for-byte the one this machine last
          uploaded and saw calibrated.

        **What this cannot detect**, stated plainly because the cost of being
        wrong is silently measuring against the wrong package: rbx has no way to
        ask the server what package a problem actually holds -- the CLI exposes no
        package checksum -- so the second clause is a *local* record of what this
        machine did. The same login uploading a different probe from a second
        machine, or a `moj upload` by hand, leaves that record intact and
        `is_ready` true, and the fast path would then skip an upload it should
        have done. (A *co-setter* is not one of those cases: `ensure_moj_id`
        rewrites the org to whoever is logged in, so they reach `bob#rbxt-<slug>`
        -- a different problem, under a different record key.) The
        record is deliberately kept in the disposable problem cache so the failure
        leans the other way whenever it can: losing it re-uploads needlessly,
        which costs judge time and nothing else.
        """
        # The local record is consulted FIRST, and that ordering matters beyond
        # saving a subprocess: on a package's very first run the problem does not
        # exist on the server yet, and `moj check` on a nonexistent id fails. A
        # fingerprint can only match after an upload of ours completed, so this
        # order means `check` is never asked about a problem rbx has not created.
        if fingerprint != _recorded_fingerprint(moj_id):
            return False
        if ctx.progress:
            ctx.progress.update(
                f'Checking whether [item]{moj_id}[/item] is already calibrated...'
            )
        if not (await cli.check(moj_id)).is_ready:
            return False
        if ctx.progress:
            ctx.progress.update(
                f'[item]{moj_id}[/item] is already calibrated for this package.'
            )
        return True

    async def _wait_for_calibration(self, moj_id: str, ctx: RunContext) -> None:
        """Poll until the judge's limits describe this package. Bounded.

        The first poll happens immediately, which is only safe because
        `MojCheck.is_ready` also requires `not needs_recalibration`: the upload
        just moved the package's checksum, so a *previous* calibration still
        reporting `calibrated: true` must not read as ready. OPEN (probe):
        whether the server sets `needs_recalibration` synchronously with the
        upload. If it lags, this loop can return on a stale calibration -- and
        the fix is to require one observed not-ready poll before believing a
        ready one, not to drop the immediate first poll (which is what makes the
        already-queued case cheap).
        """
        # Real time, not `attempt * CALIBRATION_POLL_INTERVAL_SECONDS`. Every
        # attempt also spends a `moj check` subprocess, so the nominal figure
        # *understates* the wait -- by more the busier the park is, which is
        # exactly when a setter is looking at it and deciding whether to give up.
        elapsed = _Elapsed()
        for attempt in range(CALIBRATION_POLL_ATTEMPTS):
            if (await cli.check(moj_id)).is_ready:
                return
            if ctx.progress:
                ctx.progress.update(
                    f'Waiting for MOJ to calibrate [item]{moj_id}[/item] ({elapsed})...'
                )
            # Not after the last check: there is nothing left to wait for, and
            # sleeping there would delay the give-up message by a whole interval
            # for no reason.
            if attempt + 1 < CALIBRATION_POLL_ATTEMPTS:
                await asyncio.sleep(CALIBRATION_POLL_INTERVAL_SECONDS)

        # The real wait, for the same reason: quoting the nominal bound tells a
        # setter it gave up sooner than it did.
        minutes = int(elapsed.seconds / 60)
        raise MojRunnerError(
            f'MOJ has not finished calibrating `{moj_id}` after {minutes} '
            f'minutes, so rbx has no time limits to measure against and stopped '
            f'waiting.\n'
            f'Check the problem with `moj check {moj_id}`, and queue it again '
            f'with `moj calibrate {moj_id}` if it is not in flight. Nothing was '
            f'lost: the problem stays on the server, and running rbx again picks '
            f'up where this left off.'
        )


# What distinguishes each purpose's remote problem from the base one.
#
# Empty for estimation, so the problem `rbx time` uses is exactly the one
# `.moj-id` has always named and every committed binding keeps working. See
# `problem_id.derived_id` for why the purposes need a problem each.
#
# A table rather than a method on `RunPurpose`: the enum lives in `runners.base`
# and is shared by every backend, and a MOJ problem-id suffix is this backend's
# business alone.
_ID_SUFFIXES = {
    RunPurpose.ESTIMATION: '',
    RunPurpose.VALIDATION: 'slow',
    RunPurpose.RUN: 'run',
}

# What to call the solutions a run submits, for the packager's report line. Only
# a noun phrase; nothing reads it back.
_MEASURING = {
    RunPurpose.ESTIMATION: 'accepted solutions',
    RunPurpose.VALIDATION: 'slow solutions',
    RunPurpose.RUN: 'solutions',
}


def _id_suffix(purpose: RunPurpose) -> str:
    return _ID_SUFFIXES[purpose]


def _measuring(purpose: RunPurpose) -> str:
    return _MEASURING[purpose]


def _halt_on(ctx: RunContext) -> FrozenSet[str]:
    """The `STOPWHEN_*` bits that enforce this run's abort predicate on the judge.

    The predicate itself cannot be inspected -- it is a closure over an
    `Evaluation` -- so the rule is read off the pair (purpose, did the caller ask
    to abort at all), which is the whole of what distinguishes the three cases:

    - **No `abort_on`** -- a plain `rbx run` -- halts on nothing. Every test comes
      back with a real verdict, which is exactly what the local run reports. This
      is the case the hard-coded `STOPWHEN_TLE` used to get wrong: it would have
      turned the tests after the first timeout into SKIPPED on a run that never
      asked to stop, and a setter comparing local against MOJ would have read that
      as the judge losing tests.
    - **`rbx time`, either phase**, aborts on `outcome.is_slow()` and nothing
      else, so a timeout alone halts. WA and RE deliberately do not: a
      `TLE_OR_RTE` solution may legitimately crash, and `_record_validation_run`
      reads a non-slow bad verdict as "broke for another reason", which needs the
      run to have continued.
    - **`rbx run --fail-fast`** aborts on any non-accepted verdict
      (`fail_fast_abort_predicate`), so all three bits go on.

    Reading the purpose rather than the predicate means a *new* caller passing
    some third predicate under `RUN` would get the fail-fast rule, which is the
    safe direction to be wrong in: it stops early where the caller asked to stop
    early, and `rbx run` already refuses to trust the timings of a truncated run.
    """
    if ctx.abort_on is None:
        return frozenset()
    if ctx.purpose is RunPurpose.RUN:
        return HALT_VERDICTS
    return frozenset({'TLE'})


def _probe_pin(ctx: RunContext) -> ProbePinned:
    """The limits this run is measured under: whatever the local run would enforce.

    Read off `ctx.skeleton.limits`, the one place that has already resolved
    everything deciding an enforced time limit -- the active limits profile, the
    verification level (`isDoubleTL`), and any `timelimit_override` the caller
    passed. Pinning from it is what makes `--runner moj` answer the same question
    the local run answers, and it collapses three cases into one:

    - **`rbx run`** passes no override, so the skeleton holds the profile's own
      per-language limits. Those are what a plain run enforces, and now what MOJ
      enforces.
    - **`rbx time`, estimating**, passes one `int`, so every language in the
      skeleton holds that same `inferenceTimeout` cap.
    - **`rbx time`, validating**, passes a mapping, so each language group holds
      its own `ceil(TL x timeLimitToTle)` -- and a language the mapping does not
      mention keeps the profile's own limit, which the old
      `timelimit_override`-shaped reading could only approximate with the loosest
      of the others.

    The expanded limit (`get_expanded_tl`), not the declared one: a double-TL
    language really is run at twice the number locally
    (`tasks._get_execution_config`), and pinning the undoubled figure would TLE a
    solution here that passes there. Neither `rbx time` phase is affected -- both
    run at `ALL_SOLUTIONS`, which keeps `isDoubleTL` off.

    Two things it refuses rather than guesses at:

    - A language whose enforced limit is `None`. MOJ **always** enforces a time
      limit, so "no limit" -- which the local sandbox expresses by nulling
      `Limits.time` -- has no package-level counterpart, and every number that
      could be substituted is one nobody chose.
    - Nothing at all to read. An empty `limits` means no tracked solution resolved
      to a language, which is a run with nothing to pin; it falls back to the
      configured estimation cap so a caller outside these three -- a test building
      a context by hand, say -- still gets a buildable package.
    """
    limits = ctx.skeleton.limits if ctx.skeleton is not None else {}
    unlimited = sorted(
        language
        for language, limit in limits.items()
        if limit.get_expanded_tl() is None
    )
    if unlimited:
        named = ', '.join(f'`{language}`' for language in unlimited)
        raise MojRunnerError(
            f'This run enforces no time limit for {named}, and MOJ always '
            f'enforces one -- there is no package that means "run this untimed".\n'
            f'Pick a limits profile that sets a time limit for that language, or '
            f'run this on the local sandbox.'
        )

    per_language = {
        language: limit_ms
        for language, limit in limits.items()
        if (limit_ms := limit.get_expanded_tl()) is not None
    }
    if per_language:
        return ProbePinned(
            # The loosest, not the tightest. Only a language the run did not name
            # falls back to it, and being generous there cannot truncate a
            # measurement -- being stingy could.
            default_ms=max(per_language.values()),
            per_rbx_language_ms=tuple(sorted(per_language.items())),
            # Said here rather than inferred in the packager, which sees limits
            # and not purposes.
            measuring=_measuring(ctx.purpose),
        )

    strategy = timing_config.resolve_strategy(
        environment.get_environment().timing,
        package.find_problem_package_or_die().timing,
    )
    return ProbePinned(
        default_ms=strategy.inferenceTimeout, measuring=_measuring(ctx.purpose)
    )


def _testrun_languages(ctx: RunContext) -> Tuple[str, ...]:
    """The MOJ ids to whitelist for submission, in `.moj-meta.json`.

    Every language rbx **may testrun**, and emphatically *not* just the accepted
    ones. The API rejects a submission outside the whitelist, a testrun included,
    so a whitelist derived from the accepted solutions (which is the right rule
    for a real problem, and what `MojPackager` does off the probe path) would
    refuse every testrun of a slow or wrong solution: those are never ACCEPTED by
    construction. Nothing is protected by narrowing it here -- a private `rbxt-`
    problem has no submission surface to protect.

    So it is the whole package's solutions, not this batch's. That matters since
    `rbx time` split into two phases: the estimation phase tracks only the
    accepted solutions and the validation phase only the ones expected to be too
    slow, so a whitelist built from `ctx.skeleton.solutions` would be a different
    -- and, in phase 2, a *disjoint* -- list each time. Two costs, both real: the
    package would fingerprint differently in each phase even when the limits did
    not move, spending an upload and a calibration on nothing; and a package that
    fingerprinted *equal* would leave phase 2 submitting slow solutions against
    phase 1's accepted-only whitelist, which the API refuses.

    A language rbx cannot map is refused only when this batch actually runs a
    solution in it. The rest of the package is a superset offered for free, and
    failing a run over a solution it never touches would be refusing work that
    was never asked for.
    """
    languages: List[str] = []
    unmapped: List[Tuple[pathlib.Path, str]] = []

    def add(solution: CodeItem, *, tracked: bool) -> None:
        # `find_language` reports an unknown language by printing and raising
        # `typer.Exit`, which is not wrapped here on purpose: by the time
        # `prepare` runs, `_get_report_skeleton` has already resolved and
        # *compiled* every tracked solution, so a language that does not resolve
        # cannot reach this loop for one.
        rbx_language = find_language(solution).name
        moj_language = get_moj_language_from_rbx_language(rbx_language)
        if moj_language is None:
            if tracked:
                unmapped.append((solution.path, rbx_language))
            return
        if moj_language not in languages:
            languages.append(moj_language)

    tracked_paths = {solution.path for solution in ctx.skeleton.solutions}
    for solution in ctx.skeleton.solutions:
        add(solution, tracked=True)
    for solution in package.get_solutions():
        if solution.path in tracked_paths:
            continue
        add(solution, tracked=False)

    if unmapped:
        # Refused, not skipped, and the difference matters. Dropping the solution
        # from the whitelist does not drop it from the run: rbx would still
        # testrun it, and the API -- which enforces the whitelist -- would reject
        # the submission, so the failure surfaces as a server-side message about
        # a language rather than here where the setter can act on it. Even if the
        # run did skip it, that is not a mere downgrade: a skipped lower-bound
        # solution means the time limit is estimated from incomplete data with
        # nothing saying so. Refusing names the solution to exclude.
        listed = '\n'.join(f'  `{path}` (`{language}`)' for path, language in unmapped)
        raise MojRunnerError(
            f'These solutions are written in languages MOJ has no counterpart '
            f'for, so the judge could not run them:\n{listed}\n'
            f"MOJ rejects a submission in a language outside the problem's "
            f'whitelist, a testrun included, so rbx will not measure this run '
            f'rather than silently leave those solutions out of the estimate.\n'
            f'Give the language a `moj` id in the `extensions.moj` block of '
            f'`env.rbx.yml`, or exclude those solutions from this run.'
        )

    if not languages:
        # `ProbePackage` would refuse this too, but with a message about the
        # whitelist rather than about the solutions that produced it.
        raise MojRunnerError(
            'This run measures no solutions at all, so there is no language to '
            'let the judge accept a submission in.'
        )
    return tuple(languages)


# -- pairing rbx testcases to MOJ's ---------------------------------------------


def _entry_key(entry: GenerationTestcaseEntry) -> Tuple[str, int]:
    """What identifies a testcase entry across two lists of them.

    Object identity would be wrong even though it would work today: a
    `SolutionReportSkeleton` round-trips through `skeleton.yml`, so the entries
    `run_solution` is handed are not guaranteed to be the same *objects* the
    packager was constructed with.

    **`subgroup_entry`, not `group_entry`.** This started out as the latter, and
    that was a bug that killed every subgrouped problem in `prepare()`:
    `group_entry.group` is the **top-level** group while `group_entry.index` is a
    per-*subgroup* counter that restarts at 0 (`testcase_extractors.py`:
    `_explore_subgroup` resets `i = 0` per call, and `_entry` pairs that index
    with `prefix[0]`). So `beta/one`'s first testcase and `beta/two`'s first
    testcase are both `beta/0` -- two built testcases, one key. `subgroup_entry`
    carries the full subgroup path (`beta/one` vs `beta/two`), which makes it
    unique over the flattened testset while keeping every property `group_entry`
    was chosen for: it is a value, not an object, so it survives the
    `skeleton.yml` round-trip, and it is what rbx itself names a subgrouped
    testcase by.
    """
    return (entry.subgroup_entry.group, entry.subgroup_entry.index)


def _names_by_entry(packager: MojPackager) -> Dict[Tuple[str, int], str]:
    """The MOJ file name of each built testcase, keyed by `_entry_key`.

    **This is the load-bearing one.** The live probe found the `tests` array of a
    testrun is *not ordered* -- an AC run began `['t01_handmade_002', 'sample2',
    't01_handmade_001']`, because the park runs tests in parallel and they come
    back as they finish. Pairing by position would therefore misattribute
    essentially every timing, and would do it silently: every number would still
    look like a plausible time for *some* test.

    Duplicate keys are an error rather than last-one-wins, for the same reason
    `TestrunStatus.by_name` refuses duplicate names: a dict that silently drops one
    of two entries pairs one of them with the other's timing. This raise has
    already earned its keep once -- it is what turned the `group_entry` key bug
    (see `_entry_key`) into a refusal in `prepare()` instead of a whole run of
    timings attributed to the wrong subgroup.
    """
    named: Dict[Tuple[str, int], str] = {}
    for entry, name in packager.testcase_names():
        key = _entry_key(entry)
        if key in named:
            raise MojRunnerError(
                f'Two built testcases of this problem are both '
                f"`{entry.subgroup_entry}`, and rbx cannot tell which of MOJ's "
                f'results belongs to which. This is an rbx bug.'
            )
        named[key] = name
    return named


def _evaluation_for(
    solution: 'SolutionSkeleton',
    entry: GenerationTestcaseEntry,
    test: Optional[cli.TestrunTest],
) -> Evaluation:
    """Turn one MOJ per-test result into an rbx `Evaluation`, and persist it.

    Honest about what a remote judge does not report, which
    `RunnerCapabilities` has already declared and this must not quietly walk back:

    - **no memory.** `moj testrun-status` reports `{name, code, time, tl}`, and
      nothing about memory. `None`, never 0 -- a 0 reads as a measurement.
    - **no wall time.** Same.
    - **no artifacts.** No `.out`, no `.err`, no `.log`. Only the `.eval` is
      written, which is the precedent `_record_skipped_evaluation` set: the run
      explorer renders a missing artifact as "(does not exist)", while an empty
      `.out` would claim the solution printed nothing.
    - **no exit status.** See `REMOTE_EXIT_STATUS`.

    `test is None` is a testcase MOJ did not report on at all. It gets `SKIPPED`
    with no timing -- the outcome rbx already uses for "this testcase produced no
    result", and the one thing that cannot be mistaken for a verdict about the
    solution. It deliberately does **not** get `INTERNAL_ERROR` or
    `JUDGE_FAILED`: neither happened as far as anyone knows, and both rank worse
    than every real verdict, so one unreported test would take over the solution's
    outcome. `SKIPPED` ranks just after `ACCEPTED` and therefore never masks the
    verdict that a reported test really produced. `_submit_and_poll` has already
    said out loud how many there were.
    """
    testcase = entry.metadata.copied_to
    output_dir = solution.runs_dir / entry.group_entry.group

    if test is None:
        result = CheckerResult(
            outcome=Outcome.SKIPPED,
            message='MOJ reported no result for this testcase.',
        )
        log = TestcaseLog(
            exitcode=-1,
            exitstatus=UNREPORTED_EXIT_STATUS,
            time=None,
            wall_time=None,
            memory=None,
        )
    else:
        result = CheckerResult(
            outcome=_OUTCOME_BY_MOJ_CODE[test.code],
            # MOJ judges with the packaged checker and hands back a code, never
            # the checker's own words (`reports_checker_messages=False`). Saying
            # where the verdict came from is the useful thing left to say, and it
            # is what stops a reader taking an empty message for a checker that
            # had nothing to report.
            message=f'Judged remotely by MOJ ({test.code}).',
        )
        log = TestcaseLog(
            exitcode=-1,
            exitstatus=REMOTE_EXIT_STATUS,
            # Seconds, which is what `TestcaseLog.time` is in and what MOJ
            # reports. A TLE carries its *real* time rather than the limit
            # (2.81s against a 0.614s `tl`, in the probe), so it is stored as
            # reported and not clamped: how far over the cap a solution ran is
            # exactly what the validation phase wants.
            time=test.time,
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


# -- the fast path's local record -----------------------------------------------


# The result type `_with_ticker` passes through untouched.
_T = TypeVar('_T')

# How often the spinner repaints while a blocking step runs. One second is what
# reads as "alive" without the message flickering.
TICKER_INTERVAL_SECONDS = 1.0


# Wall-clock durations are shared with the run reporter, which ticks one on the
# solution header while this runner is waiting on the judge -- the same clock,
# formatted the same way, so a header and a summary line never disagree.
_Elapsed = utils.Elapsed


async def _with_ticker(
    ctx: RunContext,
    coro: 'Coroutine[Any, Any, _T]',
    label: str,
) -> '_T':
    """Await `coro`, repainting `label` with an elapsed count while it runs.

    For the steps that are a *single* blocking call and so cannot report on
    themselves: `moj upload` is one subprocess that tars the package, posts it,
    and answers when it is done. Without this the spinner holds one frozen
    message for however long that takes, which is the longest step of `prepare`
    and the one most likely to be mistaken for a hang. The polling steps need
    nothing here -- they already come back every few seconds and can repaint on
    their own.

    `label` is formatted with `{elapsed}`.

    The result and any exception pass through untouched. Cancellation is
    forwarded and **awaited**: `Task.cancel` only schedules the `CancelledError`,
    and a task suspended in `process.communicate()` needs more than one turn of
    the loop to unwind -- the same reason `MojRunner.close` drains rather than
    just cancelling.
    """
    task = asyncio.ensure_future(coro)
    elapsed = _Elapsed()
    try:
        while True:
            done, _ = await asyncio.wait(
                {task}, timeout=TICKER_INTERVAL_SECONDS if ctx.progress else None
            )
            if done:
                break
            if ctx.progress:
                ctx.progress.update(label.format(elapsed=elapsed))
    except asyncio.CancelledError:
        task.cancel()
        # `shield` is deliberately not used: the point is to let the inner task
        # observe the cancellation and finish unwinding before this returns.
        await asyncio.gather(task, return_exceptions=True)
        raise
    return await task


def _directory_size(path: pathlib.Path) -> int:
    """Total bytes of the files in the built package.

    Not what goes over the wire -- `moj upload` tars the directory itself, and
    rbx never sees the archive -- so whatever is said about this number must say
    "package files" rather than imply an upload size. Guessing at the CLI's
    archiving would be a number that can be *wrong*, which this one cannot be.
    """
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file())


def _directory_fingerprint(path: pathlib.Path) -> str:
    """A digest over every file in the built package, path and contents.

    Deterministic across machines (sorted relative POSIX paths, lengths framed so
    a rename cannot be absorbed into a neighbouring file's bytes) and covers
    exactly what the upload sends: change a testcase, the cap, the whitelist or
    the checker, and this moves.
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


def _upload_state_path() -> pathlib.Path:
    return package.get_problem_cache_dir() / UPLOAD_STATE_NAME


def _read_upload_state() -> Dict[str, str]:
    """Every problem this machine has uploaded to, and what it last sent.

    A **map**, not a single record: `rbx time` uploads to one problem per phase,
    and a single record would have each phase evict the other's -- which is the
    same way the fast path used to be unreachable, just moved. Any unreadable or
    unrecognised state reads as empty, including the flat `{id, fingerprint}` this
    replaced: the only cost is a redundant upload, and that is the direction to
    fail in.
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
    uploads = payload.get('uploads')
    if not isinstance(uploads, dict):
        return {}
    return {
        moj_id: fingerprint
        for moj_id, fingerprint in uploads.items()
        if isinstance(moj_id, str) and isinstance(fingerprint, str)
    }


def _write_upload_state(uploads: Dict[str, str]) -> None:
    _upload_state_path().write_text(
        json.dumps({'uploads': uploads}, indent=2, sort_keys=True) + '\n'
    )


def _recorded_fingerprint(moj_id: str) -> Optional[str]:
    """The fingerprint this machine last uploaded to `moj_id` and saw calibrated.

    Keyed by the id, so a package that got rebound to a different remote problem
    -- or that belongs to the other phase -- never matches a record made for
    another one.
    """
    return _read_upload_state().get(moj_id)


def _record_upload(moj_id: str, fingerprint: str) -> None:
    """Record an upload that reached a calibrated problem.

    Written **after** the calibration finishes, never before: a package that is
    on the server but whose calibration never completed is not something the next
    run may skip work over.

    Read-modify-write, so recording one phase's upload leaves the other phase's
    record alone. Losing the file entirely costs a redundant upload of both,
    which is why it may live in the disposable problem cache at all.
    """
    uploads = _read_upload_state()
    uploads[moj_id] = fingerprint
    _write_upload_state(uploads)


def _forget_upload(moj_id: str) -> None:
    """Drop what is recorded for one problem, leaving every other one intact."""
    uploads = _read_upload_state()
    if uploads.pop(moj_id, None) is None:
        return
    _write_upload_state(uploads)


# -- the testrun cache ----------------------------------------------------------
#
# `rbx time` is a command a setter runs *again*: tweak a solution, re-estimate,
# change the profile, look at the table once more. Every re-run used to re-submit
# every solution, including ones whose source had not changed by a byte -- and a
# testrun occupies a shared two-judge park for as long as the solution takes on
# every test. So a finished testrun is remembered, keyed (see `_cache_key`) so
# that a hit is provably the same measurement rather than merely a similar one.
#
# **There is no `--no-cache` flag**, deliberately. The two questions a flag would
# answer both have better answers already: "I changed something" is what the key
# is for, and it covers everything rbx can observe; "I want to see the variance"
# is not a workflow this backend supports at all, since `nruns > 1` is refused
# outright on a shared park (`RunnerCapabilities.supports_nruns`). What is left
# is the blind spot no flag can fix either -- somebody else's upload, or a park
# that changed underneath the numbers -- and for that the honest escape hatch is
# to throw the observations away, which is one `rm -rf` of a directory the
# cache-hit line prints by name. A flag would also have to be threaded through
# `rbx time`, `timing.py` and `RunContext` to reach the one backend that means
# anything by it.
#
# No expiry, no size cap, no eviction, for want of a problem they would solve: an
# entry is a few hundred bytes of JSON, entries are only written for packages
# that were really uploaded, and a stale entry is unreachable rather than wrong
# -- its key names a package fingerprint no later run will ever produce again.


def _testrun_cache_dir() -> pathlib.Path:
    path = package.get_problem_cache_dir() / TESTRUN_CACHE_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_cached_testrun(key: str) -> Optional[Tuple[str, cli.TestrunStatus]]:
    """The run id and finished status remembered under `key`, if any.

    Anything unreadable -- absent, truncated, not JSON, not the shape it was
    written in, written by a version of this code that meant something else by
    it -- reads as a miss. That is the direction to fail in: a miss costs one
    redundant testrun, while trusting a half-written file costs a wrong timing in
    the number `rbx time` is about to write into a limits profile.
    """
    path = _testrun_cache_dir() / f'{key}.json'
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None

    run = payload.get('run')
    # The shape check on `status` is belt-and-braces: every non-object JSON value
    # fails `model_validate` anyway, so removing it changes no behaviour today
    # (a mutation test confirmed it). It stays because it says what this file is
    # supposed to contain at the point where that is being decided, rather than
    # leaving it to be inferred from which exception pydantic happens to raise.
    status = payload.get('status')
    if not isinstance(run, str) or not run or not isinstance(status, dict):
        return None
    try:
        return run, cli.TestrunStatus.model_validate(status)
    except ValidationError:
        return None


def _store_cached_testrun(key: str, run: str, status: cli.TestrunStatus) -> None:
    """Remember a testrun rbx was able to read in full.

    **Only ever called for a status that already survived `_result_from_status`**,
    which is what keeps a failure out of the cache. A run-level failure -- the
    `Compilation Error` shape, a `done` run that never entered the testset -- is
    a thing the setter is about to *fix*, and answering the next run from a
    cached compile error would be maddening: the fix would appear to change
    nothing. An unrecognised verdict code is excluded by the same rule, since it
    is likewise a run rbx could not interpret.

    A non-`Accepted` run **is** cached, on purpose. A WA, an RE or a TLE is a
    legitimate, reproducible measurement of a solution that is *supposed* to fail
    -- the validation phase exists to measure exactly those -- and the timings it produced are
    as real as an accepted solution's. Only "rbx could not read this" is refused,
    never "the judge did not like the solution".

    Written whole and then moved into place, because a poll interrupted
    mid-write would otherwise leave a truncated JSON file under a key that says
    it describes a real measurement. `_load_cached_testrun` tolerates that
    anyway; this makes it not happen.
    """
    directory = _testrun_cache_dir()
    path = directory / f'{key}.json'
    payload = {
        'run': run,
        # The status as the judge reported it, rather than the `_TestrunResult`
        # derived from it: the derivation depends on which testcases *this* run
        # asked about (`expected`, `missing`), so storing its output would bake
        # one run's testset into an entry the next run reuses. Storing the input
        # instead means a hit re-derives, through the same code, against whatever
        # the current run asked for.
        #
        # `model_dump` keeps every field the model knows, including the run-level
        # `verdict` / `verdict_canon` / `total_tests` that `ran_nothing` reads --
        # so the cached entry can be checked on the way back in exactly as a
        # fresh response is.
        'status': status.model_dump(mode='json'),
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
        # said from a background task, about something the setter did not ask
        # for and cannot act on.
        return


# See `runners/local.py`: the Protocol is only load-bearing if something checks
# it at run time, and `runtime_checkable` checks that the members are present.
assert isinstance(MojRunner(), SolutionRunner)
