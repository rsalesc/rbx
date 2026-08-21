"""A typed wrapper over the `moj` CLI.

rbx never speaks to the MOJ API directly: it shells out to the judge's own CLI and
reuses the session `moj login` established. Credentials therefore never pass
through rbx, and a CLI upgrade that changes an endpoint costs us nothing.

What the wrapper is for is the CLI's *two* output styles. Most subcommands honour
a global `--json` flag and print real JSON. Two of the ones we need do not, and
have to be read as prose:

- `moj whoami` returns before the `--json` branch and always prints human text.
- `moj testrun --no-wait` does the same: with `--no-wait` the CLI prints the
  queued message and returns *before* it would have serialized a result.

Prose parsing is a wart, and it is deliberate. The alternative to `--no-wait` is a
blocking `testrun`, which waits up to ten minutes per solution and serializes what
the whole remote-runner design exists to run concurrently. Both formats are driven
through a stub binary in the tests, so a CLI which later grows `--json` support for
them announces itself with a failing test rather than with a wrong login or a run
id that is silently never found.

**Confirmed vs. still open.** The prose formats, the `--json` placement and the
way a missing session fails were read off the CLI's source and are recorded in
`docs/plans/2026-08-20-moj-remote-runner-design.md`. The JSON *shapes* were read
off the CLI's own `jq` expressions rather than off recorded live responses -- the
live probe (task 0 of the design) has not run yet. Every model therefore ignores
unknown fields and defaults absent ones, and each site that is still open carries
an `OPEN:` comment naming what the probe has to settle.
"""

import asyncio
import collections
import json
import pathlib
import re
import shlex
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict

from rbx.box.exception import RbxException

# The executable to shell out to. A name rather than a path: which `moj` is on the
# setter's `PATH` is their business, and tests point this at a stub.
MOJ_BINARY = 'moj'

# The one `status` a testrun is known to report that means the judge is finished.
#
# OPEN (probe): whether the server can also report a *terminal failure* status.
# The CLI itself does not answer this -- its own wait loop polls 200 times at 3s
# (~10 minutes) testing only `status == "done"`, handles no failure status, and
# then gives up and tells the user to check back later. So the CLI bounds the wait
# rather than trusting a terminal state to arrive, and any polling loop rbx writes
# on top of `done` must bound it too: treating "not done" as "still in flight" is
# an assumption, not an observation, and without a bound a failed run hangs rbx
# forever.
DONE_STATUS = 'done'


class MojCliError(RbxException):
    """The `moj` CLI refused, failed, or said something we cannot read.

    Messages are **plain text with backticks**, never rich markup: the top-level
    handler bare-prints `str(e)`, so `[item]...[/item]` would reach the setter
    literally.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


class MojNotInstalledError(MojCliError):
    """There is no `moj` executable to shell out to.

    Its own class because the fix is different from every other failure -- install
    the CLI -- and because `whoami`, which reads any failure as a missing session,
    must not report a missing binary as a missing login.
    """


class TestrunTest(BaseModel):
    """One test of one testrun.

    `code` stays a plain string. OPEN (probe): its vocabulary. Inventing a
    code -> `Outcome` mapping here would bake a guess into the layer everything
    else reads; the mapping belongs to the runner, where an unknown code can be
    surfaced instead of silently becoming a verdict.
    """

    model_config = ConfigDict(extra='ignore')

    name: str
    code: str
    # Optional because a test the judge never reached (compile error, an aborted
    # run) has no measurement, and a missing time must read as unmeasured rather
    # than as an instantaneous one.
    time: Optional[float] = None
    tl: Optional[float] = None


class TestrunStatus(BaseModel):
    """The state of one testrun, as `moj testrun-status` reports it."""

    model_config = ConfigDict(extra='ignore')

    status: str
    verdict: Optional[str] = None
    # The same verdict without the score suffix: the probe saw `Accepted,100p` in
    # `verdict` against a bare `Accepted` here, so this is the stable one to read
    # (`docs/plans/2026-08-21-moj-probe-notes.md`, section 3). It is what the
    # runner names when a run failed *as a whole* -- the first end-to-end run of
    # `rbx time --runner moj` hit `verdict_canon: 'Compilation Error'` with an
    # empty `tests` array, and without this field rbx could only say that its
    # testcases went unmeasured, never why.
    verdict_canon: Optional[str] = None
    correct: Optional[int] = None
    # How many tests the judge *intended* to run, which is not how many it
    # reported: the probe watched a `STOPWHEN_*` problem come back with 4 entries
    # and `total_tests: 72`, while the compile-error run came back with 0 entries
    # and `total_tests: 0`. That difference is the only structural signal telling
    # a truncated run from one that never started; see `ran_nothing`.
    total_tests: Optional[int] = None
    duration_s: Optional[float] = None
    tl_used: Optional[float] = None
    # Absent while the run is still queued or running: the CLI's own formatter
    # falls back to `.filename` / `.problem_id` in that case, so a status without
    # tests is normal, not an error.
    tests: List[TestrunTest] = []

    @property
    def done(self) -> bool:
        """Whether the judge is finished with this run.

        Anything other than `done` is read as still in flight -- see `DONE_STATUS`
        for why that reading obliges every caller to bound its own wait.
        """
        return self.status == DONE_STATUS

    @property
    def ran_nothing(self) -> bool:
        """Whether this finished run never got as far as running a testcase.

        **Observed.** The first end-to-end `rbx time --runner moj` submitted
        solutions that did not build on the judge, and every one of them came back
        as `{"status": "done", "verdict_canon": "Compilation Error", "correct": 0,
        "total_tests": 0, "tests": []}`. rbx read that as "MOJ reported no result
        for 6 of 6 testcases", which is true and useless: it describes the
        symptom, and the cause -- the submission never compiled -- was one
        `moj testrun-status <run> --report <file>` away and never mentioned.

        The discriminator is `total_tests`, not `len(tests)`, and the difference
        matters. `total_tests` is the judge's own count of the tests it set out to
        run, so it stays at 72 on a `STOPWHEN_*` run that reported only 4 of them
        (probe section 4) and drops to 0 only when the run died before the testset
        was ever entered. Keying on `len(tests) == 0` alone would fold those two
        together: a `STOPWHEN_*` problem whose very first test fails could
        legitimately report zero entries out of 72, and calling that a build
        failure would be a new lie replacing the old one.

        `tests` being empty is required too, so that a server which someday
        reports tests alongside a zero (or absent) `total_tests` is read by what
        it actually returned rather than by its bookkeeping.

        Deliberately structural rather than a `verdict_canon` denylist: the
        verdict vocabulary is only half observed -- five values so far -- and
        `_OUTCOME_BY_MOJ_CODE` already refuses to guess at the other half.
        `verdict_canon` is what *names* the cause once this has detected it.
        """
        return self.done and not self.tests and not self.total_tests

    @property
    def canonical_verdict(self) -> Optional[str]:
        """What the judge called this run, or `None` if it did not say.

        `verdict_canon` first because it is the stable spelling -- `verdict`
        carries a score suffix (`Accepted,100p`) that has no business in a message
        about a run that scored nothing -- and `verdict` as the fallback for a
        server that predates it. Absent is a real possibility and reads as absent:
        a run-level failure with no verdict at all is still a run-level failure,
        and the caller says so without a name rather than inventing one.
        """
        for candidate in (self.verdict_canon, self.verdict):
            if candidate and candidate.strip():
                return candidate.strip()
        return None

    @property
    def by_name(self) -> Dict[str, TestrunTest]:
        """The tests keyed by MOJ's name for them.

        Pairing rbx's testcases to these by *name* rather than by position is what
        keeps a change in the packager's naming from silently misattributing a
        timing to the wrong testcase. Duplicate names would defeat exactly that --
        a dict comprehension drops one of them just as silently -- so they are an
        error rather than a last-one-wins.
        """
        by_name = {test.name: test for test in self.tests}
        if len(by_name) != len(self.tests):
            repeated = sorted(
                name
                for name, count in collections.Counter(
                    test.name for test in self.tests
                ).items()
                if count > 1
            )
            raise MojCliError(
                f'The judge reported more than one test named '
                f'{", ".join(f"`{name}`" for name in repeated)} in the same '
                f"testrun. rbx pairs its testcases to MOJ's by name, and cannot "
                f'tell repeated names apart.'
            )
        return by_name


class MojCheck(BaseModel):
    """The `tl` block of `moj check` -- whether the time limits can be trusted."""

    model_config = ConfigDict(extra='ignore')

    # All three default to False rather than being required: the shapes here were
    # read off the CLI's `jq`, which gives `being_calibrated` an explicit `// false`
    # fallback for servers that predate it, and an older server that omits any of
    # them must read as "not ready" rather than fail to parse. See `is_ready` for
    # why False is the safe default in every one of the three.
    calibrated: bool = False
    being_calibrated: bool = False
    needs_recalibration: bool = False

    @property
    def is_ready(self) -> bool:
        """Whether the problem's limits describe the package as it is now.

        All three have to hold: a calibration in flight means the limits still
        describe the *previous* package, and a stale one means the package moved
        underneath them.
        """
        return (
            self.calibrated
            and not self.being_calibrated
            and not self.needs_recalibration
        )


# Confirmed from the CLI source: `cmd_whoami` prints exactly
# `login: <login>  nome: <name>` and never honours `--json`.
#
# Anchored to the start of a line, and `[ \t]` rather than `\s`, because neither
# looseness is free here. An unanchored `\blogin:` reads the `login:` inside a
# banner line such as `moj 2.1 -- ultimo login: 2026-08-01` and returns the date;
# a `\s` after the colon spans the newline and reads the *next* line's first word.
# Either one yields a wrong-but-plausible login, which uploads the package under an
# org the setter does not own and fails much later and much more confusingly than a
# refusal here would. Staying line-anchored keeps the tolerance that matters --
# a banner printed *before* the login line.
_LOGIN_RE = re.compile(r'^login:[ \t]*(\S+)', re.MULTILINE)

# Confirmed from the CLI source: with `--no-wait`, `cmd_testrun` prints
# `enfileirado no juiz: run $run  (<file> contra <id>)` and returns before the
# branch that would have honoured `--json`, followed by a line suggesting
# `moj --json testrun-status $run`. Either line carries the id, and both are tried:
# the first is the likelier of the two to be reworded, while the second is a
# copy-pasteable command and so is load-bearing for humans too.
#
# The character class is **observed**, not guessed: the live probe
# (`docs/plans/2026-08-21-moj-probe-notes.md`) got a 32-character hex digest back
# four times out of four -- `d89e6b7735c675fd7b50b3354ba64097` and friends. This
# pattern originally read `(\d+)`, on the design doc's inference that `$run` was
# numeric, and therefore matched **nothing at all**: every real testrun failed
# with "could not find a run id". That it failed loudly rather than truncating is
# what made the mistake catchable in one command instead of as a mystery 404 --
# which is the whole reason the class is narrow rather than `\S+`.
#
# So it is still a class rather than `\S+`, with a boundary after it, because the
# id goes straight back out as a shell token in `moj testrun-status <run>`.
# Swallowing a trailing `.` or `(` from the surrounding prose is worse than not
# matching at all, and the `#` in the boundary keeps the pattern from reading a
# problem id (`alice#rbxt-...`) as a run id: it refuses instead.
_RUN_ID = r'[A-Za-z0-9_-]+'
_RUN_ID_BOUNDARY = r'(?![A-Za-z0-9_#-])'
_RUN_ID_RES = (
    re.compile(
        r'enfileirado no juiz:[ \t]*run[ \t]+(' + _RUN_ID + r')' + _RUN_ID_BOUNDARY
    ),
    re.compile(r'testrun-status[ \t]+(' + _RUN_ID + r')' + _RUN_ID_BOUNDARY),
)


async def _run_moj(args: Sequence[str]) -> str:
    """Run `moj` with these arguments and return its stdout.

    Callers pass the argv exactly as it should be typed, `--json` included, so
    that the flag's position is visible at the call site: `--json` is a *global*
    flag and the CLI does not see it after the subcommand.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            MOJ_BINARY,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
        # Caught at the spawn call specifically, so that a `FileNotFoundError`
        # raised by something deeper cannot be mislabelled as a missing CLI.
        raise MojNotInstalledError(
            f'Could not run `{MOJ_BINARY}`: the MOJ CLI is not installed, or is '
            f'not on your `PATH`. Install it and run `moj login` before using '
            f'the MOJ runner.'
        ) from e

    stdout, stderr = await process.communicate()
    out = stdout.decode(errors='replace')
    err = stderr.decode(errors='replace')

    if process.returncode != 0:
        # Both streams: the CLI's `die()` writes to stderr, but not every failure
        # path goes through it, and a failure whose reason we dropped is a failure
        # the setter cannot act on.
        detail = '\n'.join(part.strip() for part in (err, out) if part.strip())
        message = (
            f'Command `{MOJ_BINARY} {shlex.join(args)}` failed with exit code '
            f'{process.returncode}.'
        )
        raise MojCliError(f'{message}\n{detail}' if detail else message)

    return out


async def _run_moj_json(args: Sequence[str]) -> Any:
    """Run `moj --json ...` and parse what it printed."""
    out = await _run_moj(['--json', *args])
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise MojCliError(
            f'Could not read the output of '
            f'`{MOJ_BINARY} {shlex.join(["--json", *args])}` as JSON.\n'
            f'{out.strip()}'
        ) from e


async def whoami() -> str:
    """The login of the session `moj login` established.

    Parsed out of prose, because this subcommand does not honour `--json`.
    """
    try:
        out = await _run_moj(['whoami'])
    except MojNotInstalledError:
        # A missing binary is not a missing session; let it say what it is.
        raise
    except MojCliError as e:
        # Confirmed from the CLI source: without a session, `need_login` calls
        # `die`, which prints to stderr and exits non-zero. So this is the path a
        # logged-out setter actually takes, and the message they need is the one
        # naming `moj login`.
        raise MojCliError(
            f'Could not read your MOJ login. Run `moj login` first.\n{e}'
        ) from e

    match = _LOGIN_RE.search(out)
    if match is None:
        # Never guess. A wrong login here uploads the package under an org the
        # setter does not own, which fails much later and much more confusingly.
        raise MojCliError(
            f'Could not find a login in the output of `{MOJ_BINARY} whoami`. '
            f'Run `moj login` first.\n{out.strip()}'
        )
    return match.group(1)


async def upload(problem_id: str, directory: pathlib.Path) -> None:
    """Upload a package directory. The CLI tars it itself.

    This **overwrites** whatever `problem_id` names on the server. See
    `problem_id.is_rbxt_id`: a caller must not hand this an id it did not create.
    """
    await _run_moj(['upload', problem_id, str(directory)])


async def calibrate(problem_id: str) -> None:
    """Queue a calibration. Repeating it does not queue a second one."""
    await _run_moj(['calibrate', problem_id])


async def check(problem_id: str) -> MojCheck:
    """The problem's calibration state."""
    payload = await _run_moj_json(['check', problem_id])
    block = payload.get('tl') if isinstance(payload, dict) else None
    # An absent `tl` block is read as "nothing is calibrated". Absent is not the
    # same as calibrated, and of the two readings only this one errs towards
    # waiting rather than towards trusting limits that may not exist.
    return MojCheck.model_validate(block if isinstance(block, dict) else {})


async def testrun(ref: Union[str, pathlib.Path], solution: pathlib.Path) -> str:
    """Queue one solution against a problem, and return the run id.

    `ref` is either a problem id or a directory containing a `.moj-id`; the CLI
    resolves both.

    `--json` is deliberately *not* passed. With `--no-wait` the CLI returns before
    the branch that would honour it, so the output is prose either way; asking for
    JSON we would not get would only suggest this is parsed as JSON when it is not.
    """
    out = await _run_moj(['testrun', str(ref), str(solution), '--no-wait'])

    for pattern in _RUN_ID_RES:
        match = pattern.search(out)
        if match is not None:
            return match.group(1)

    # Returning nothing here would leave the caller polling a run that was never
    # queued, forever.
    raise MojCliError(
        f'Could not find a run id in the output of `{MOJ_BINARY} testrun`.\n'
        f'{out.strip()}'
    )


async def testrun_status(run: str) -> TestrunStatus:
    """The state of a queued testrun. Poll until `done`, and bound the wait."""
    return TestrunStatus.model_validate(await _run_moj_json(['testrun-status', run]))
