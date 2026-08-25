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
import os
import pathlib
import re
import shlex
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, ConfigDict, ValidationError

from rbx.box.exception import RbxException

# The executable to shell out to. A name rather than a path: which `moj` is on the
# setter's `PATH` is their business, and tests point this at a stub.
MOJ_BINARY = 'moj'

# An escape hatch for a setter whose `moj` cannot simply be run by name.
#
# It exists for one concrete situation. The CLI is a bash script that needs
# bash >= 4 behind a `#!/usr/bin/env bash` shebang, so the shell that runs it is
# whichever `bash` comes first on `PATH` -- and macOS still ships 3.2 at
# `/bin/bash`. The fix is to put Homebrew's bash ahead of it on `PATH`, and this
# variable is for when that cannot be arranged: it is split like a shell command
# rather than read as a path, so an interpreter and a script both fit --
#
#     RBX_MOJ_BINARY='/opt/homebrew/bin/bash /Users/alice/.local/bin/moj'
#
# It is deliberately *not* a package or `env.rbx.yml` setting: which `moj` runs is
# a property of the machine, not of the problem, and committing one setter's
# absolute paths would break the package for everyone else.
MOJ_BINARY_ENV_VAR = 'RBX_MOJ_BINARY'


def moj_command() -> List[str]:
    """The argv prefix that runs the MOJ CLI on this machine.

    Read on every call rather than resolved at import, so that a test -- and a
    setter exporting the variable mid-session -- gets what is set *now*.
    """
    override = os.environ.get(MOJ_BINARY_ENV_VAR, '')
    if override.strip():
        return shlex.split(override)
    # `MOJ_BINARY` and not a literal, because the tests point that at a stub.
    return [MOJ_BINARY]


def _display(args: Sequence[str] = ()) -> str:
    """What to print so the setter can re-run by hand exactly what rbx ran."""
    return shlex.join([*moj_command(), *args])


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


class MojUnsupportedShellError(MojCliError):
    """The CLI was handed to a shell too old to run it.

    Its own class for the same reason `MojNotInstalledError` is: the CLI *is*
    installed and the setter *is* logged in, so every other message here would
    send them somewhere that cannot help. In particular `whoami`, which reads a
    failure as a missing session, must not answer this one with `moj login` --
    that command dies in exactly the same way, which is a loop rather than a fix.
    """


class MojQueueFullError(MojCliError):
    """MOJ refused because this account already has too many testruns queued.

    The server caps how many a single login may have waiting at once -- three, as
    observed on 2026-08-21 -- and answers HTTP 429:

        moj: Você já tem 3 teste(s) na fila — aguarde terminarem (429)

    Its own class because it is the one failure here that is **transient and
    expected** rather than a mistake, and because there is no other way out of it.
    `moj` exposes exactly three testrun operations -- submit, status, report -- and
    nothing that cancels one, so a caller cannot clear the queue; it can only wait.

    Note the quota is per **account**, not per run. rbx caps its own in-flight
    testruns, but an interrupted `rbx time` leaves its dispatched runs going on the
    judge (rbx stops waiting; MOJ does not stop running), and a second session or a
    hand-run `moj testrun` holds slots too. So hitting this does not mean rbx
    dispatched too many.
    """


# `_api_fail` in the CLI ends a failed call's message with the HTTP status in
# parentheses -- `die "$msg${code:+ ($code)}"` -- so the code is a structural part
# of the output rather than something to be read out of the prose. Matching the
# Portuguese message instead would break on a translation or a reworded server.
_HTTP_STATUS_RE = re.compile(r'\((\d{3})\)\s*$', re.MULTILINE)

# HTTP 429: too many testruns already queued for this login.
_QUEUE_FULL_STATUS = '429'

# The CLI's `need_login`: `die "faça '$MOJ_TOOL login' primeiro."`. Matched on the
# two words that survive a rewording rather than on the sentence, and case-folded,
# since the only cost of a false positive is a *better* message than the CLI's.
#
# Read by both `whoami` and `contest_whoami`, and for opposite purposes: the
# contest one uses it to *replace* a hint that cannot be followed, while `whoami`
# uses it to decide whether a failure is a missing session at all -- so a failure
# that is something else keeps its own cause instead of being told to log in.
_NO_SESSION_RE = re.compile(r'\blogin\b.*\bprimeiro\b', re.IGNORECASE)


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
    # Which machine of the park ran this. The 2026-08-21 probe came back
    # `host: judge-sp1`; it is surfaced on the run reporter's solution header, so
    # a timing can be read against the machine that produced it. Optional because
    # nothing guarantees every response carries it -- and a park with one judge
    # may well never send it.
    host: Optional[str] = None
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
            *moj_command(),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
        # Caught at the spawn call specifically, so that a `FileNotFoundError`
        # raised by something deeper cannot be mislabelled as a missing CLI.
        raise _not_installed_error(e) from e

    stdout, stderr = await process.communicate()
    return _stdout_or_raise(
        args,
        process.returncode,
        stdout.decode(errors='replace'),
        stderr.decode(errors='replace'),
    )


def _not_installed_error(e: BaseException) -> MojNotInstalledError:
    """The failure to *spawn* the CLI, which is never a failure of the command."""
    if os.environ.get(MOJ_BINARY_ENV_VAR, '').strip():
        # An override that does not resolve is a typo in one place the setter
        # controls, so name that place rather than telling them to install a CLI
        # they may well already have.
        return MojNotInstalledError(
            f'Could not run `{_display()}`, which is what `{MOJ_BINARY_ENV_VAR}` '
            f'is set to. Check that path, or unset `{MOJ_BINARY_ENV_VAR}` to go '
            f'back to the `{MOJ_BINARY}` on your `PATH`.'
        )
    return MojNotInstalledError(
        f'Could not run `{MOJ_BINARY}`: the MOJ CLI is not installed, or is '
        f'not on your `PATH`. Install it and run `moj login` before using '
        f'the MOJ runner.'
    )


# The major version the MOJ CLI's own guard requires:
#
#     [ "${BASH_VERSINFO[0]:-0}" -ge 4 ] || die "preciso de bash >= 4 ..."
#
# It needs one because it really does use bash-4 features (`declare -A`,
# `mapfile`, `${x^^}`), and macOS really does still ship 3.2.
_MIN_BASH_MAJOR = 4


def _shebang_interpreter(script: str) -> Optional[str]:
    """Which program a script's `#!` line hands it to, resolved as the kernel would.

    `None` if this is not a script at all -- a compiled binary, or something
    unreadable -- which is the answer for every `moj` that is not the bash one.
    """
    try:
        with open(script, 'rb') as f:
            first = f.readline(256).decode(errors='replace')
    except OSError:
        return None
    if not first.startswith('#!'):
        return None
    parts = first[2:].strip().split()
    if not parts:
        return None
    if pathlib.PurePath(parts[0]).name != 'env':
        return parts[0]
    # `#!/usr/bin/env bash`, which is what the MOJ CLI carries: `env` resolves the
    # interpreter off `PATH`, and that indirection is the entire reason a setter
    # can install a modern bash and still be handed the stock one.
    for arg in parts[1:]:
        if not arg.startswith('-') and '=' not in arg:
            return shutil.which(arg) or arg
    return None


def _bash_major(bash: str) -> Optional[int]:
    """The major version of `bash`, asked in the one way bash 3.2 also answers.

    `None` when the question does not apply -- the program is not a bash, or
    could not be run -- rather than a guess, since the only thing this number is
    used for is refusing.
    """
    try:
        probe = subprocess.run(
            [bash, '-c', 'echo "${BASH_VERSINFO[0]}"'],
            capture_output=True,
            text=True,
            errors='replace',
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return int(probe.stdout.strip())
    except ValueError:
        return None


def _outdated_bash() -> Optional[Tuple[str, int]]:
    """The bash that runs `moj` and its version, if it is too old to run it.

    Structural rather than a match on the CLI's own message, deliberately: that
    message is Portuguese prose, and this module already argues (see
    `_HTTP_STATUS_RE`) that reading prose to classify a failure breaks on the
    first rewording. Reading the shebang and asking the shell its version breaks
    on neither.

    Run only on the *failure* path, so a healthy setter never pays for the two
    extra `stat`s and the subprocess it costs.
    """
    command = moj_command()
    if len(command) > 1:
        # `RBX_MOJ_BINARY='<bash> <script>'`: the setter named the interpreter,
        # so that is the one that runs, and reading the script's shebang instead
        # would resolve the very bash they overrode to get away from.
        interpreter: Optional[str] = command[0]
    else:
        executable = shutil.which(command[0])
        interpreter = _shebang_interpreter(executable) if executable else None
    if interpreter is None or pathlib.PurePath(interpreter).name != 'bash':
        return None
    major = _bash_major(interpreter)
    if major is None or major >= _MIN_BASH_MAJOR:
        return None
    return interpreter, major


def _unsupported_shell_error(bash: str, major: int, detail: str) -> MojCliError:
    """Name the shell, and the one change that fixes it for good."""
    return MojUnsupportedShellError(
        f'The MOJ CLI needs bash {_MIN_BASH_MAJOR} or newer, but the bash that '
        f'runs it here is bash {major} (`{bash}`).\n'
        f'macOS still ships bash 3.2 as `/bin/bash`, and `moj` starts with '
        f'`#!/usr/bin/env bash` -- so it runs under whichever bash comes first '
        f'on your `PATH`.\n'
        f'Install a current one and put it ahead of the system one:\n'
        f'  brew install bash\n'
        f'  eval "$(brew shellenv)"   # in your shell profile, before /bin is reached\n'
        f'If you cannot change your `PATH`, point '
        f'`{MOJ_BINARY_ENV_VAR}` at an interpreter and the script instead:\n'
        f'  export {MOJ_BINARY_ENV_VAR}="$(brew --prefix)/bin/bash $(command -v moj)"\n'
        f'\n{detail}'
    )


def _stdout_or_raise(
    args: Sequence[str], returncode: Optional[int], out: str, err: str
) -> str:
    """What the CLI printed, or the reason it failed.

    Shared by the async and the sync spawners so that the two cannot disagree
    about what a failure means -- the 429 in particular, which decides whether a
    caller waits or gives up.
    """
    if returncode == 0:
        return out

    # Both streams: the CLI's `die()` writes to stderr, but not every failure
    # path goes through it, and a failure whose reason we dropped is a failure
    # the setter cannot act on.
    detail = '\n'.join(part.strip() for part in (err, out) if part.strip())
    message = f'Command `{_display(args)}` failed with exit code {returncode}.'
    full = f'{message}\n{detail}' if detail else message
    status = _HTTP_STATUS_RE.search(detail)
    if status is not None and status.group(1) == _QUEUE_FULL_STATUS:
        # Raised as its own type so a caller can wait it out. Everything else
        # here is a mistake to report; this one is a queue to sit behind.
        raise MojQueueFullError(full)
    # Checked after the 429 and before anything else is concluded: a queue that
    # is full answered over the network, so the shell that asked was fine. Every
    # remaining failure is a candidate for the one cause the CLI cannot survive.
    outdated = _outdated_bash()
    if outdated is not None:
        raise _unsupported_shell_error(*outdated, full)
    raise MojCliError(full)


def _run_moj_sync(args: Sequence[str]) -> str:
    """`_run_moj`, for the callers that cannot await.

    Solution-path expansion (`rbx.box.remote`) is synchronous, and is itself
    called from inside async code -- `compile.any` does -- so it can neither
    `await` nor start a loop of its own. A second spawner is the small price;
    the error handling above is shared, which is the part worth not duplicating.
    """
    try:
        process = subprocess.run(
            [*moj_command(), *args],
            capture_output=True,
            text=True,
            errors='replace',
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
        raise _not_installed_error(e) from e

    return _stdout_or_raise(args, process.returncode, process.stdout, process.stderr)


async def _run_moj_json(args: Sequence[str]) -> Any:
    """Run `moj --json ...` and parse what it printed."""
    out = await _run_moj(['--json', *args])
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise MojCliError(
            f'Could not read the output of '
            f'`{_display(["--json", *args])}` as JSON.\n'
            f'{out.strip()}'
        ) from e


async def whoami() -> str:
    """The login of the session `moj login` established.

    Parsed out of prose, because this subcommand does not honour `--json`.
    """
    try:
        out = await _run_moj(['whoami'])
    except (MojNotInstalledError, MojUnsupportedShellError):
        # Neither a missing binary nor a shell too old to run it is a missing
        # session; each already says what it is, and `moj login` would fail in
        # exactly the same way.
        raise
    except MojCliError as e:
        # Confirmed from the CLI source: without a session, `need_login` calls
        # `die`, which prints to stderr and exits non-zero. So this is the path a
        # logged-out setter actually takes, and the message they need is the one
        # naming `moj login`.
        #
        # Only *that* path, though. `whoami` is the first call every MOJ command
        # makes, so it is where an unrelated failure -- a 500, a proxy, a CLI too
        # old for the server -- surfaces first, and relabelling all of them as a
        # missing session buries the cause under an instruction that cannot help.
        if not _NO_SESSION_RE.search(str(e)):
            raise
        raise MojCliError(
            f'Could not read your MOJ login. Run `moj login` first.\n{e}'
        ) from e

    match = _LOGIN_RE.search(out)
    if match is None:
        # Never guess. A wrong login here uploads the package under an org the
        # setter does not own, which fails much later and much more confusingly.
        raise MojCliError(
            f'Could not find a login in the output of `{_display(["whoami"])}`. '
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
        f'Could not find a run id in the output of `{_display(["testrun"])}`.\n'
        f'{out.strip()}'
    )


async def testrun_status(run: str) -> TestrunStatus:
    """The state of a queued testrun. Poll until `done`, and bound the wait."""
    return TestrunStatus.model_validate(await _run_moj_json(['testrun-status', run]))


class ContestWhoami(BaseModel):
    """`/auth/status` for one contest, as `moj contest --json whoami` relays it.

    Every role flag defaults to `False` rather than being required: a server that
    predates one of them has to read as *no* access. The opposite default would
    turn a missing field into a permission.
    """

    model_config = ConfigDict(extra='ignore')

    login: str
    contest: Optional[str] = None
    is_admin: bool = False
    is_judge: bool = False
    is_chief: bool = False

    @property
    def can_read_any_submission(self) -> bool:
        """Whether this session may list submissions other than its own.

        A plain `.judge` is enough. The contest's own judge screen lists every
        submission through `/contest/allsubmissions` and links each one's source;
        what a plain judge loses is the *identity* behind a row -- the server
        blanks `username`/`fullname`/`univ` for judge and monitor -- and never the
        code. Chief and admin get the identities too, which rbx does not need.
        """
        return self.is_judge or self.is_chief or self.is_admin


def contest_whoami(contest: str) -> ContestWhoami:
    """Who this machine is inside `contest`, and what it is allowed to read.

    Contest sessions are **not** the session `moj login` creates. That one covers
    `treino` and only `treino`; a contest gets its own account, its own token file
    (`$CFG/token-<contest>`) and its own login command. Which is why a missing
    session here cannot be reported the way the rest of this module reports one.

    Synchronous, alone among the wrappers here, because its caller is: solution
    paths expand synchronously, from inside async code, so there is neither a
    loop to await on nor room to start one.

    `--json` goes **after** `contest`, and that is load-bearing: `moj` parses the
    global flag into a shell variable and then `exec`s `moj-contest` without it,
    so `moj --json contest whoami` prints prose and parses as nothing.
    """
    try:
        out = _run_moj_sync(['contest', '--json', '-c', contest, 'whoami'])
    except MojNotInstalledError:
        # No `moj` at all. Its own message installs the right thing; so does the
        # one for a missing `contest` *layer*, which arrives as a plain
        # `MojCliError` below and is likewise passed through.
        raise
    except MojCliError as e:
        if _NO_SESSION_RE.search(str(e)):
            raise MojCliError(
                f'There is no MOJ session for the contest `{contest}`.\n'
                f'Log in with `moj-contest login {contest}`, then try again.\n'
                f'Note this is a different session from the one `moj login` '
                f'creates: that one only ever covers `treino`.'
            ) from e
        raise

    try:
        parsed = json.loads(out)
    except json.JSONDecodeError as e:
        raise MojCliError(
            f'Could not read the output of '
            f'`{_display(["contest", "--json", "-c", contest, "whoami"])}` as '
            f'JSON.\n{out.strip()}'
        ) from e
    try:
        return ContestWhoami.model_validate(parsed)
    except ValidationError as e:
        raise MojCliError(
            f'`{_display(["contest", "--json", "-c", contest, "whoami"])}` returned '
            f'JSON without a login in it.\n{out.strip()}'
        ) from e
