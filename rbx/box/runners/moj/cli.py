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
the whole remote-runner design exists to run concurrently. The two tests that pin
these formats are there so that a CLI which later grows `--json` support for them
announces itself with a failing test, rather than with a wrong login or a run id
that is silently never found.

**Caveat**: the JSON shapes below were read off the CLI's own `jq` expressions, not
off recorded live responses -- the live probe (task 0 of the design) has not run
yet. Every model therefore ignores unknown fields and defaults absent ones, and
every place we are guessing carries a comment saying so.
"""

import asyncio
import json
import pathlib
import re
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict

from rbx.box.exception import RbxException

# The executable to shell out to. A name rather than a path: which `moj` is on the
# setter's `PATH` is their business, and tests point this at a stub.
MOJ_BINARY = 'moj'

# The one `status` a testrun reports that means the judge is finished with it.
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

    `code` stays a plain string. Its vocabulary is a probe question, and inventing
    a code -> `Outcome` mapping here would bake a guess into the layer everything
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
    correct: Optional[int] = None
    total_tests: Optional[int] = None
    duration_s: Optional[float] = None
    tl_used: Optional[float] = None
    # Absent while the run is still queued or running: the CLI's own formatter
    # falls back to `.filename` / `.problem_id` in that case, so a status without
    # tests is normal, not an error.
    tests: List[TestrunTest] = []

    @property
    def done(self) -> bool:
        """Only `done` means finished. Anything else is still in flight."""
        return self.status == DONE_STATUS

    @property
    def by_name(self) -> Dict[str, TestrunTest]:
        """The tests keyed by MOJ's name for them.

        Pairing rbx's testcases to these by *name* rather than by position is what
        keeps a change in the packager's naming from silently misattributing a
        timing to the wrong testcase.
        """
        return {test.name: test for test in self.tests}


class MojCheck(BaseModel):
    """The `tl` block of `moj check` -- whether the time limits can be trusted."""

    model_config = ConfigDict(extra='ignore')

    calibrated: bool = False
    # The CLI's `jq` gives this a `// false` fallback for servers that predate it,
    # so it is optional here for the same reason.
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


DONE_STATUS = 'done'

# `login: alice  nome: Alice A` -- the first line of `moj whoami`.
_LOGIN_RE = re.compile(r'\blogin:\s*(\S+)')

# `enfileirado no juiz: run 4711  (sol.cpp contra alice#rbxt-x)`, followed by
# `acompanhe com: moj --json testrun-status 4711`. Either line carries the id, and
# both are tried: the wording of the first is the likelier of the two to be
# reworded, while the second is a copy-pasteable command and so is effectively
# load-bearing for humans too.
_RUN_ID_RES = (
    re.compile(r'enfileirado no juiz:\s*run\s+(\S+)'),
    re.compile(r'testrun-status\s+(\S+)'),
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
        raise MojNotInstalledError(
            f'Could not run `{MOJ_BINARY}`: the MOJ CLI is not installed, or is '
            f'not on your `PATH`. Install it and run `moj login` before using '
            f'the MOJ runner.'
        ) from e

    stdout, stderr = await process.communicate()
    out = stdout.decode(errors='replace')
    err = stderr.decode(errors='replace')

    if process.returncode != 0:
        # Both streams: the CLI is not consistent about which one it complains on,
        # and a failure whose reason we dropped is a failure the setter cannot act
        # on.
        detail = '\n'.join(part.strip() for part in (err, out) if part.strip())
        message = (
            f'Command `{MOJ_BINARY} {" ".join(args)}` failed with exit code '
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
            f'Could not read the output of `{MOJ_BINARY} --json '
            f'{" ".join(args)}` as JSON.\n{out.strip()}'
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
    """Upload a package directory. The CLI tars it itself."""
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
    """The state of a queued testrun. Poll until `done`."""
    return TestrunStatus.model_validate(await _run_moj_json(['testrun-status', run]))
