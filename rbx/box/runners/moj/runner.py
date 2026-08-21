"""The backend that measures solution timings on the MOJ judge park.

`rbx time` estimates a time limit from timings measured *where rbx runs*. This
runner measures them where the problem will actually be judged instead: it
uploads a throwaway probe package to a private `rbxt-` problem on MOJ, has the
judge calibrate it, and (from task 6 on) runs each solution there with
`moj testrun`.

Everything expensive is once per run, which is what `prepare` is: one upload and
one calibration serve however many solutions get measured, because `moj testrun`
sends the source of the solution being timed in the request body rather than
reading it out of the package.

Design: `docs/plans/2026-08-20-moj-remote-runner-design.md`.
"""

import asyncio
import hashlib
import json
import pathlib
import tempfile
from typing import TYPE_CHECKING, List, Optional, Tuple

import typer

from rbx.box import environment, package, timing_config
from rbx.box.code import find_language
from rbx.box.deferred import Deferred
from rbx.box.exception import RbxException
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging.moj.moj_language_utils import get_moj_language_from_rbx_language
from rbx.box.packaging.moj.packager import MojPackager, ProbePackage, UniformPinned
from rbx.box.runners.base import RunContext, RunnerCapabilities, SolutionRunner
from rbx.box.runners.moj import cli
from rbx.box.runners.moj.problem_id import ensure_moj_id, is_rbxt_id, moj_id_path
from rbx.grading.steps import Evaluation

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

# Where the fingerprint of the last package this machine successfully uploaded and
# calibrated is kept. Under the problem cache rather than beside `.moj-id`: it is a
# per-machine observation ("*I* put this package there"), not part of the binding,
# and losing it costs one redundant upload rather than correctness. See
# `_recorded_fingerprint`.
UPLOAD_STATE_NAME = 'moj-runner.json'


class MojRunnerError(RbxException):
    """The MOJ runner cannot do what the run asked of it.

    Messages are **plain text with backticks**, never rich markup: `main.py`
    bare-prints `str(e)`, so `[item]...[/item]` would reach the setter literally.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


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
        # A testrun has already run every test by the time rbx sees the result
        # (which is exactly why a probe package suppresses `STOPWHEN_*`), so
        # aborting saves nothing -- and gating would overwrite real judge
        # verdicts with SKIPPED.
        supports_abort=False,
        # `MojPackager.task_types()` is `[BATCH]`: MOJ's interactive support uses
        # its own arbiter protocol, not a testlib interactor.
        supports_interactive=False,
        # Sanitizers are a local-compilation concept; the judge compiles the
        # submission itself, with the package's own `scripts/<lang>/compile.sh`.
        supports_sanitizers=False,
    )

    async def prepare(self, ctx: RunContext) -> None:
        """Get a calibrated probe problem onto the judge, once per run.

        Everything here is idempotent across runs by design: the `rbxt-` problem
        is persistent (`.moj-id` is committed and reused), so a session that dies
        halfway leaves the next one closer to ready rather than leaving garbage.
        """
        if ctx.progress:
            ctx.progress.update('Reading your MOJ login...')
        # Surfaced as-is: `cli.whoami` already distinguishes "the CLI is not
        # installed" from "you are not logged in", and both have a different fix
        # from anything this module could say.
        login = await cli.whoami()

        moj_id = self._problem_id(login)

        cap_ms = _uniform_cap_ms(ctx)

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
            self._build_probe(ctx, package_path, build_path, cap_ms)

            fingerprint = _directory_fingerprint(package_path)
            if await self._is_already_prepared(moj_id, fingerprint, ctx):
                return

            # Cleared *before* the upload, not after: from the moment the server
            # starts receiving a new package, the recorded fingerprint no longer
            # describes what is up there. A crash mid-upload must leave the next
            # run re-uploading, never trusting a stale record.
            _forget_upload()

            if ctx.progress:
                ctx.progress.update(
                    f'Uploading the probe package to [item]{moj_id}[/item]...'
                )
            await cli.upload(moj_id, package_path)

        await cli.calibrate(moj_id)
        await self._wait_for_calibration(moj_id, ctx)
        _record_upload(moj_id, fingerprint)

    def run_solution(
        self,
        solution: 'SolutionSkeleton',
        entries: List[GenerationTestcaseEntry],
        ctx: RunContext,
    ) -> List[Deferred[Evaluation]]:
        # Task 6. Deliberately not stubbed out with a guessed verdict mapping.
        # The live probe (`docs/plans/2026-08-21-moj-probe-notes.md`) observed
        # `AC` / `WA` / `RE` / `TLE` and nothing else: `MLE`, `OLE`, `PE`, `CE`
        # and `JE` were never provoked, so a code -> `Outcome` table written here
        # would turn an unobserved code into a confident wrong verdict. Whatever
        # task 6 writes has to keep an unknown code *unknown*.
        raise NotImplementedError(
            'The MOJ runner cannot run solutions yet: `moj testrun` fan-out and '
            'verdict mapping are task 6 of the remote-runner design. See '
            '`docs/plans/2026-08-20-moj-remote-runner-design.md`.'
        )

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
        cap_ms: int,
    ) -> None:
        """Build the probe package into `package_path`."""
        packager = MojPackager(
            testcase_entries=ctx.skeleton.entries,
            timing_mode=UniformPinned(limit_ms=cap_ms),
            probe=ProbePackage(submission_languages=_testrun_languages(ctx)),
        )
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
        machine did. A co-setter uploading a different probe from another machine,
        or a `moj upload` by hand, leaves that record intact and `is_ready` true,
        and the fast path would then skip an upload it should have done. The
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
        for attempt in range(CALIBRATION_POLL_ATTEMPTS):
            if (await cli.check(moj_id)).is_ready:
                return
            if ctx.progress:
                waited = int(attempt * CALIBRATION_POLL_INTERVAL_SECONDS)
                ctx.progress.update(
                    f'Waiting for MOJ to calibrate [item]{moj_id}[/item] ({waited}s)...'
                )
            await asyncio.sleep(CALIBRATION_POLL_INTERVAL_SECONDS)

        minutes = int(
            CALIBRATION_POLL_ATTEMPTS * CALIBRATION_POLL_INTERVAL_SECONDS / 60
        )
        raise MojRunnerError(
            f'MOJ has not finished calibrating `{moj_id}` after {minutes} '
            f'minutes, so rbx has no time limits to measure against and stopped '
            f'waiting.\n'
            f'Check the problem with `moj check {moj_id}`, and queue it again '
            f'with `moj calibrate {moj_id}` if it is not in flight. Nothing was '
            f'lost: the problem stays on the server, and running rbx again picks '
            f'up where this left off.'
        )


def _uniform_cap_ms(ctx: RunContext) -> int:
    """The single cap every timing this run produces is measured under.

    MOJ **always** enforces a time limit, so "no cap" is not expressible in a
    package the way it is in the local sandbox, and `UniformPinned` refuses a
    non-positive number rather than emitting a `TLOVERRIDE` that TLEs every run.
    So the three cases are settled here (see the design doc, "What to pin when
    there is no cap"):

    1. The run carries a cap -- `timing._run_for_inference`'s `_InferenceCap`, or
       `timeLimitToTle x TL` in phase 2. Pin it.
    2. No cap, but the problem estimates with multipliers. Pin
       `inferenceTimeout`: its own description is "the time limit enforced on
       solutions while estimating", which is exactly the question. (Its "only
       used when `timeLimitToTle` is set" clause is about the upper *bound*, not
       about how long rbx is willing to wait for a solution.)
    3. No multipliers at all -- the problem estimates with a formula. Refuse,
       rather than invent a number every measurement would then be silently
       truncated by. The same call `rbx package moj --calibrate` already makes
       when it needs an `acToTimeLimit` a formula does not define.
    """
    # `> 0` rather than `is not None`: `timing.py` passes **-1**, the "no
    # override" sentinel, whenever there is no cap -- which is every problem with
    # no `timeLimitToTle` and every problem with no upper-bound solution. A
    # `None` check would take a -1 for a cap and pin `TLOVERRIDE[default]=-0.001`.
    if ctx.timelimit_override is not None and ctx.timelimit_override > 0:
        return ctx.timelimit_override

    strategy = timing_config.resolve_strategy(
        environment.get_environment().timing,
        package.find_problem_package_or_die().timing,
    )
    if strategy.uses_multipliers:
        return strategy.multipliers_or_die().inferenceTimeout

    raise MojRunnerError(
        'The MOJ runner needs one time limit to measure every solution under, '
        'but this problem estimates its time limit with a formula, which defines '
        'no such cap -- and MOJ always enforces a limit, so there is nothing to '
        'fall back on.\n'
        'Set `timing.multipliers.inferenceTimeout` in `env.rbx.yml` (the cap rbx '
        'enforces on solutions while estimating), or measure this problem on a '
        'local runner instead.'
    )


def _testrun_languages(ctx: RunContext) -> Tuple[str, ...]:
    """The MOJ ids to whitelist for submission, in `.moj-meta.json`.

    Every language rbx **may testrun** -- one per solution this run measures --
    and emphatically *not* just the accepted ones. The API rejects a submission
    outside the whitelist, a testrun included, so a whitelist derived from the
    accepted solutions (which is the right rule for a real problem, and what
    `MojPackager` does off the probe path) would refuse every testrun of a slow
    or wrong solution: those are never ACCEPTED by construction. Nothing is
    protected by narrowing it here -- a private `rbxt-` problem has no submission
    surface to protect.
    """
    languages: List[str] = []
    unmapped: List[Tuple[pathlib.Path, str]] = []
    for solution in ctx.skeleton.solutions:
        rbx_language = find_language(solution).name
        moj_language = get_moj_language_from_rbx_language(rbx_language)
        if moj_language is None:
            unmapped.append((solution.path, rbx_language))
            continue
        if moj_language not in languages:
            languages.append(moj_language)

    if not languages:
        # `ProbePackage` would refuse this too, but with a message about the
        # whitelist rather than about the solutions that produced it.
        listed = ', '.join(f'`{path}` (`{language}`)' for path, language in unmapped)
        raise MojRunnerError(
            'None of the solutions this run would measure is written in a '
            'language MOJ accepts, so there is nothing the judge could run.'
            + (f'\nSolutions: {listed}.' if listed else '')
        )
    return tuple(languages)


# -- the fast path's local record -----------------------------------------------


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


def _recorded_fingerprint(moj_id: str) -> Optional[str]:
    """The fingerprint this machine last uploaded to `moj_id` and saw calibrated.

    Keyed by the id, so a package that got rebound to a different remote problem
    never matches a record made for the previous one. Any unreadable state reads
    as "nothing recorded": the only cost is a redundant upload, and that is the
    direction to fail in.
    """
    path = _upload_state_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get('id') != moj_id:
        return None
    fingerprint = payload.get('fingerprint')
    return fingerprint if isinstance(fingerprint, str) else None


def _record_upload(moj_id: str, fingerprint: str) -> None:
    """Record an upload that reached a calibrated problem.

    Written **after** the calibration finishes, never before: a package that is
    on the server but whose calibration never completed is not something the next
    run may skip work over.
    """
    _upload_state_path().write_text(
        json.dumps({'id': moj_id, 'fingerprint': fingerprint}, indent=2) + '\n'
    )


def _forget_upload() -> None:
    path = _upload_state_path()
    path.unlink(missing_ok=True)


# See `runners/local.py`: the Protocol is only load-bearing if something checks
# it at run time, and `runtime_checkable` checks that the members are present.
assert isinstance(MojRunner(), SolutionRunner)
