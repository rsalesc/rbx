"""The typed wrapper over the `moj` CLI.

Two kinds of test live here, and the split is deliberate.

The **prose** tests -- `whoami`, and `testrun --no-wait` -- run a real subprocess:
a stub shell script standing in for `moj`, installed by pointing `MOJ_BINARY` at
it. Their whole value is "this is what the CLI really prints and this is the argv
it really receives", and a fake that hands back a `str` can honour neither the
argv nor a non-zero exit. The stub records its own argv, so those assertions come
from a process that was actually spawned.

The **JSON** tests drive canned output through a fake `_run_moj`, because there is
nothing about a subprocess left to get wrong once the bytes are in hand.

Nothing here touches the network.
"""

import json
import os
import pathlib
import re
import textwrap
from typing import Any, Callable, List, Sequence, Union

import pytest

from rbx.box.runners.moj import cli
from rbx.box.runners.moj.cli import MojCliError, MojNotInstalledError

Canned = Union[str, Callable[[Sequence[str]], str]]

# A run id as the live judge really issues one: a 32-character hex digest, not a
# number. Observed four times out of four by the probe of 2026-08-21
# (`docs/plans/2026-08-21-moj-probe-notes.md`); the second id below is another of
# them, used to keep a single hard-coded digest from passing by coincidence.
_RUN_ID = 'd89e6b7735c675fd7b50b3354ba64097'
_OTHER_RUN_ID = '6ac4364288283cda5c5f8732eae6f144'

# What `moj testrun --no-wait` really prints. Confirmed from the CLI source, and
# the wording confirmed verbatim against the live CLI.
_QUEUED = (
    f'enfileirado no juiz: run {_RUN_ID}  (sol.cpp contra alice#rbxt-deadbeef)\n'
    f'acompanhe com: moj --json testrun-status {_RUN_ID}\n'
)

# What `moj whoami` really prints. Confirmed from the CLI source.
_WHOAMI = 'login: alice  nome: Alice A\npode criar problemas: sim\n'


# -- The stub binary, for everything whose value is the real CLI contract. ------


def _stub_moj(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, body: str
) -> pathlib.Path:
    """Install a shell script as `moj`, and have it record the argv it is given."""
    log = tmp_path / 'argv'
    path = tmp_path / 'moj'
    path.write_text(
        '#!/bin/sh\n'
        f'for a in "$@"; do printf \'%s\\n\' "$a" >> \'{log}\'; done\n'
        f"printf -- '--\\n' >> '{log}'\n" + textwrap.dedent(body)
    )
    path.chmod(0o755)
    monkeypatch.setattr(cli, 'MOJ_BINARY', str(path))
    return path


def _stub_calls(tmp_path: pathlib.Path) -> List[List[str]]:
    """The argv of every invocation of the stub, in order.

    `--` separates invocations; no argument rbx passes is ever literally `--`.
    """
    log = tmp_path / 'argv'
    if not log.is_file():
        return []
    calls: List[List[str]] = []
    current: List[str] = []
    for line in log.read_text().splitlines():
        if line == '--':
            calls.append(current)
            current = []
        else:
            current.append(line)
    return calls


# -- The fake, for the JSON subcommands. ---------------------------------------


def _fake_moj(monkeypatch: pytest.MonkeyPatch, canned: Canned) -> List[List[str]]:
    """Replace the subprocess call, and record the argv every wrapper builds."""
    calls: List[List[str]] = []

    async def fake_run_moj(args: Sequence[str]) -> str:
        calls.append(list(args))
        if callable(canned):
            return canned(args)
        return canned

    monkeypatch.setattr(cli, '_run_moj', fake_run_moj)
    return calls


# -- whoami: prose, not JSON. --------------------------------------------------


async def test_whoami_parses_the_login_out_of_the_human_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`moj whoami` returns before the `--json` branch and always prints prose.

    So it is not asked for JSON either: the flag would suggest the output is
    machine-readable when the only thing we can do with it is parse a sentence.
    """
    _stub_moj(monkeypatch, tmp_path, f"cat <<'EOF'\n{_WHOAMI}EOF\n")

    assert await cli.whoami() == 'alice'
    assert _stub_calls(tmp_path) == [['whoami']]


async def test_whoami_ignores_a_banner_line_that_also_says_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """A version banner carrying `ultimo login: <date>` must not become the login.

    This is why the pattern is anchored to the start of a line rather than to a
    word boundary: the unanchored form returns the date, which is a wrong login
    that looks entirely plausible.
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        f"cat <<'EOF'\nmoj 2.1 -- ultimo login: 2026-08-01\n{_WHOAMI}EOF\n",
    )

    assert await cli.whoami() == 'alice'


async def test_whoami_does_not_read_the_following_line_as_a_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """An empty `login:` must fail, not swallow the next line's first word."""
    _stub_moj(monkeypatch, tmp_path, "cat <<'EOF'\nlogin:\n  nome: Alice A\nEOF\n")

    with pytest.raises(MojCliError) as exc_info:
        await cli.whoami()

    assert '`moj login`' in str(exc_info.value)


async def test_whoami_without_a_session_tells_the_setter_to_log_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`need_login` calls `die`: a message on stderr and a non-zero exit."""
    _stub_moj(
        monkeypatch,
        tmp_path,
        'echo "moj: faca \'moj login\' primeiro." >&2\nexit 1\n',
    )

    with pytest.raises(MojCliError) as exc_info:
        await cli.whoami()

    message = str(exc_info.value)
    assert '`moj login`' in message
    assert 'primeiro' in message


async def test_whoami_that_prints_something_unrecognizable_does_not_invent_a_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """Guessing here would upload the package under the wrong org."""
    _stub_moj(monkeypatch, tmp_path, "echo 'nao autenticado'\n")

    with pytest.raises(MojCliError) as exc_info:
        await cli.whoami()

    assert '`moj login`' in str(exc_info.value)


# -- testrun: a run id parsed out of prose. ------------------------------------


async def test_testrun_extracts_the_run_id_from_the_queued_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    _stub_moj(monkeypatch, tmp_path, f"cat <<'EOF'\n{_QUEUED}EOF\n")

    assert await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp')) == _RUN_ID


async def test_a_run_id_is_a_hex_digest_rather_than_a_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """What the live judge really issues, and what a `(\\d+)` pattern misses.

    The pattern was originally written for a numeric id, on the design doc's
    inference; the probe of 2026-08-21 got a hex digest four times out of four,
    which means that pattern matched nothing and every real testrun failed with
    "could not find a run id".
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        f"cat <<'EOF'\nenfileirado no juiz: run {_OTHER_RUN_ID}  "
        f'(re.cpp contra rsalesc#delete)\nEOF\n',
    )

    assert (
        await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp'))
        == _OTHER_RUN_ID
    )


async def test_the_follow_up_command_line_also_carries_a_hex_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The second pattern is the fallback if the queued line is ever reworded.

    It has to read the same ids as the first one, or the fallback is decorative.
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        f"cat <<'EOF'\nacompanhe com: moj --json testrun-status {_OTHER_RUN_ID}\nEOF\n",
    )

    assert (
        await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp'))
        == _OTHER_RUN_ID
    )


async def test_testrun_does_not_wait_for_the_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """Blocking is minutes per solution, and it serializes the whole run."""
    _stub_moj(monkeypatch, tmp_path, f"cat <<'EOF'\n{_QUEUED}EOF\n")

    await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp'))

    assert _stub_calls(tmp_path) == [
        ['testrun', 'alice#rbxt-deadbeef', 'sol.cpp', '--no-wait']
    ]


async def test_testrun_accepts_a_directory_holding_a_moj_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The CLI resolves a directory through its own `.moj-id`."""
    package = tmp_path / 'package'
    package.mkdir()
    _stub_moj(monkeypatch, tmp_path, f"cat <<'EOF'\n{_QUEUED}EOF\n")

    await cli.testrun(package, package / 'sol.cpp')

    assert _stub_calls(tmp_path)[0][1] == str(package)


async def test_the_run_id_never_swallows_the_punctuation_around_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The id goes straight back out as `moj testrun-status <run>`.

    A trailing `.` or `(` picked up from the prose would turn an immediate,
    readable failure into a remote 404 much later.
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        "cat <<'EOF'\nenfileirado no juiz: run 4711.\nEOF\n",
    )

    assert await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp')) == '4711'


async def test_the_run_id_never_swallows_an_adjacent_parenthesis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    _stub_moj(
        monkeypatch,
        tmp_path,
        "cat <<'EOF'\nenfileirado no juiz: run 4711(sol.cpp)\nEOF\n",
    )

    assert await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp')) == '4711'


async def test_a_problem_id_in_the_run_slot_is_refused_rather_than_truncated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`#` is what still bounds the id now that letters and digits are allowed.

    A reworded line that put the problem id where the run id goes would otherwise
    be truncated at the `#` and polled as a run that was never queued. Refusing
    is the safe half of being wrong: it fails immediately and readably instead of
    as a remote 404 later.
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        "cat <<'EOF'\nenfileirado no juiz: run rsalesc#delete\nEOF\n",
    )

    with pytest.raises(MojCliError):
        await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp'))


async def test_testrun_that_prints_no_run_id_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """A silent None here would poll forever on a run that was never queued."""
    _stub_moj(monkeypatch, tmp_path, "echo 'algo deu errado no envio'\n")

    with pytest.raises(MojCliError) as exc_info:
        await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp'))

    assert 'algo deu errado no envio' in str(exc_info.value)


# -- testrun-status: real JSON. ------------------------------------------------


async def test_a_pending_testrun_is_not_done_and_reports_no_tests(
    monkeypatch: pytest.MonkeyPatch,
):
    """While running there is no `tests` key at all, not an empty one."""
    calls = _fake_moj(
        monkeypatch,
        json.dumps({'status': 'running', 'filename': 'sol.cpp'}),
    )

    status = await cli.testrun_status('4711')

    assert not status.done
    assert status.tests == []
    assert status.by_name == {}
    assert calls == [['--json', 'testrun-status', '4711']]


async def test_a_done_testrun_exposes_its_tests_by_name(
    monkeypatch: pytest.MonkeyPatch,
):
    """Tests are paired by name, never by position."""
    _fake_moj(
        monkeypatch,
        json.dumps(
            {
                'status': 'done',
                'verdict': 'TLE',
                'correct': 1,
                'total_tests': 2,
                'duration_s': 3.4,
                'tl_used': 2.0,
                'tests': [
                    {'name': 'sample001', 'code': 'AC', 'time': 0.11, 'tl': 2.0},
                    {'name': 't1_g0_001', 'code': 'TLE', 'time': 2.0, 'tl': 2.0},
                ],
            }
        ),
    )

    status = await cli.testrun_status('4711')

    assert status.done
    assert status.verdict == 'TLE'
    assert status.tl_used == 2.0
    assert status.by_name['t1_g0_001'].code == 'TLE'
    assert status.by_name['t1_g0_001'].time == 2.0
    assert status.by_name['sample001'].time == 0.11


async def test_a_rerun_testcase_is_read_from_its_last_entry(
    monkeypatch: pytest.MonkeyPatch,
):
    """mojtools reruns a TLE measured under parallel load, and reports both.

    `run-testinput` appends a `VERDICT[<name>]=` line per run, so the reran
    testcase arrives twice: first the contended measurement the judge threw away,
    then the one it kept. Reading the first would hand rbx a TLE the judge does
    not believe in -- and refusing the pair, which is what this used to do, failed
    the whole run over a testrun MOJ considers ordinary.
    """
    _fake_moj(
        monkeypatch,
        json.dumps(
            {
                'status': 'done',
                'tests': [
                    {'name': 'sample001', 'code': 'TLE', 'time': 2.0},
                    {'name': 'sample001', 'code': 'AC', 'time': 0.11},
                ],
            }
        ),
    )

    status = await cli.testrun_status('4711')

    assert status.by_name['sample001'].code == 'AC'
    assert status.by_name['sample001'].time == 0.11
    # One testcase, however many times the judge measured it.
    assert len(status.by_name) == 1


async def test_a_test_without_a_measurement_reads_as_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
):
    """A test the judge never got to has no time; zero would be a lie."""
    _fake_moj(
        monkeypatch,
        json.dumps({'status': 'done', 'tests': [{'name': 'sample001', 'code': 'CE'}]}),
    )

    status = await cli.testrun_status('4711')

    assert status.by_name['sample001'].time is None
    assert status.by_name['sample001'].tl is None


async def test_unknown_fields_do_not_break_the_parse(
    monkeypatch: pytest.MonkeyPatch,
):
    """The server is older or newer than we are; extras are not our business."""
    _fake_moj(
        monkeypatch,
        json.dumps(
            {
                'status': 'done',
                'host': 'juiz03',
                'tests': [{'name': 'sample001', 'code': 'AC', 'host': 'juiz03'}],
            }
        ),
    )

    status = await cli.testrun_status('4711')

    assert status.done
    assert status.by_name['sample001'].code == 'AC'


# -- telling "never ran" from "ran, reported fewer". ---------------------------


async def test_a_compile_error_reads_as_a_run_that_never_started(
    monkeypatch: pytest.MonkeyPatch,
):
    """The exact payload the first end-to-end `rbx time --runner moj` received.

    Every solution in that run failed to build on the judge, and this is what the
    server said about each of them. rbx had no way to tell it from a testrun that
    ran and reported nothing back, so it said the testcases went unmeasured.
    """
    _fake_moj(
        monkeypatch,
        json.dumps(
            {
                'status': 'done',
                'verdict': 'Compilation Error',
                'verdict_canon': 'Compilation Error',
                'correct': 0,
                'total_tests': 0,
                'tests': [],
            }
        ),
    )

    status = await cli.testrun_status('c4bbc86b0707b9870b4c25d4e92336e7')

    assert status.ran_nothing
    assert status.canonical_verdict == 'Compilation Error'


async def test_a_truncated_run_is_not_a_run_that_never_started(
    monkeypatch: pytest.MonkeyPatch,
):
    """`total_tests` is the discriminator, and it is why: it stays at the size of
    the testset when `STOPWHEN_*` cuts the run short.

    The probe watched a failing solution come back with 4 entries out of 72. Zero
    entries out of 72 is the same event with the first test failing, and it is
    still a run that entered the testset -- so the per-testcase degradation has to
    keep applying to it.
    """
    _fake_moj(
        monkeypatch,
        json.dumps(
            {
                'status': 'done',
                'verdict': 'Wrong Answer,0p',
                'verdict_canon': 'Wrong Answer',
                'correct': 0,
                'total_tests': 72,
                'tests': [],
            }
        ),
    )

    status = await cli.testrun_status('4711')

    assert not status.ran_nothing


async def test_a_queued_run_has_not_failed_at_the_run_level(
    monkeypatch: pytest.MonkeyPatch,
):
    """A run still in flight has no tests and no `total_tests` either.

    Only `status == "done"` carries results, so reading a queued run as one that
    never started would refuse every solution the instant it was submitted.
    """
    _fake_moj(monkeypatch, json.dumps({'status': 'queued', 'filename': 'sol.cpp'}))

    status = await cli.testrun_status('4711')

    assert not status.ran_nothing


async def test_the_canonical_verdict_drops_the_score_suffix(
    monkeypatch: pytest.MonkeyPatch,
):
    """`verdict` carries `,100p`; `verdict_canon` does not, and is preferred."""
    _fake_moj(
        monkeypatch,
        json.dumps(
            {
                'status': 'done',
                'verdict': 'Accepted,100p',
                'verdict_canon': 'Accepted',
                'tests': [],
            }
        ),
    )

    status = await cli.testrun_status('4711')

    assert status.canonical_verdict == 'Accepted'


async def test_an_older_server_without_verdict_canon_falls_back_to_verdict(
    monkeypatch: pytest.MonkeyPatch,
):
    """Suffix and all: a name with noise in it beats no name at all."""
    _fake_moj(
        monkeypatch,
        json.dumps({'status': 'done', 'verdict': 'Runtime Error,0p', 'tests': []}),
    )

    status = await cli.testrun_status('4711')

    assert status.canonical_verdict == 'Runtime Error,0p'


async def test_a_run_with_no_verdict_at_all_is_nameless_rather_than_invented(
    monkeypatch: pytest.MonkeyPatch,
):
    """Nothing here guesses. The caller reports the failure without a name."""
    _fake_moj(monkeypatch, json.dumps({'status': 'done', 'tests': []}))

    status = await cli.testrun_status('4711')

    assert status.ran_nothing
    assert status.canonical_verdict is None


# -- check: real JSON, nested under `tl`. --------------------------------------


def _check_payload(**tl: Any) -> str:
    return json.dumps({'validation': {}, 'calib': {}, 'tl': tl})


async def _checked(monkeypatch: pytest.MonkeyPatch, **tl: Any) -> cli.MojCheck:
    _fake_moj(monkeypatch, _check_payload(**tl))
    return await cli.check('alice#rbxt-deadbeef')


async def test_calibrate_is_global_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """No targeting flag: the server queues it once and any free judge takes it.

    Which is what the probe upload in `runners.moj.runner` wants -- the fastest
    number, from anywhere. `packaging.moj.upload` is the caller that does not.
    """
    _stub_moj(monkeypatch, tmp_path, 'exit 0')

    await cli.calibrate('alice#rbxt-deadbeef')

    assert _stub_calls(tmp_path) == [['calibrate', 'alice#rbxt-deadbeef']]


async def test_calibrate_can_target_every_online_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`--all-judges` and not a `--hosts` list rbx builds itself.

    Confirmed from the CLI's `cmd_calibrate`: the flag is expanded client-side
    against the park it queries at that moment, while `--hosts` takes an explicit
    comma-separated list and refuses a host the park does not know. Assembling
    that list here would make rbx responsible for an inventory that changes
    without it.
    """
    _stub_moj(monkeypatch, tmp_path, 'exit 0')

    await cli.calibrate('unicamp#a-aplusb', all_judges=True)

    assert _stub_calls(tmp_path) == [
        ['calibrate', 'unicamp#a-aplusb', '--all-judges'],
    ]


async def test_check_asks_for_json_before_the_subcommand(
    monkeypatch: pytest.MonkeyPatch,
):
    """The flag is global; after the subcommand the CLI does not see it."""
    calls = _fake_moj(monkeypatch, _check_payload(calibrated=True))

    await cli.check('alice#rbxt-deadbeef')

    assert calls == [['--json', 'check', 'alice#rbxt-deadbeef']]


async def test_a_calibrated_problem_is_ready(monkeypatch: pytest.MonkeyPatch):
    check = await _checked(
        monkeypatch, calibrated=True, being_calibrated=False, needs_recalibration=False
    )

    assert check.is_ready


async def test_a_calibration_still_in_flight_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
):
    """Reading the limits mid-calibration would read the previous ones."""
    check = await _checked(
        monkeypatch, calibrated=True, being_calibrated=True, needs_recalibration=False
    )

    assert check.being_calibrated
    assert not check.is_ready


async def test_a_stale_calibration_is_not_ready(monkeypatch: pytest.MonkeyPatch):
    """The package moved under the limits; they no longer describe it."""
    check = await _checked(
        monkeypatch, calibrated=True, being_calibrated=False, needs_recalibration=True
    )

    assert not check.is_ready


async def test_a_problem_that_was_never_calibrated_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
):
    check = await _checked(monkeypatch, calibrated=False)

    assert not check.is_ready


async def test_an_older_server_that_omits_being_calibrated_still_reads(
    monkeypatch: pytest.MonkeyPatch,
):
    """The CLI's own `jq` defaults this one to false, so we do too."""
    check = await _checked(monkeypatch, calibrated=True, needs_recalibration=False)

    assert not check.being_calibrated
    assert check.is_ready


async def test_a_check_without_a_tl_block_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
):
    """Absent is not the same as calibrated, and the safe reading is "no"."""
    _fake_moj(monkeypatch, json.dumps({'validation': {}, 'calib': {}}))

    assert not (await cli.check('alice#rbxt-deadbeef')).is_ready


# -- upload and calibrate: fire and forget. ------------------------------------


async def test_upload_hands_the_directory_to_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The CLI tars the directory itself; rbx must not pre-tar it."""
    calls = _fake_moj(monkeypatch, '')

    await cli.upload('alice#rbxt-deadbeef', tmp_path)

    assert calls == [['upload', 'alice#rbxt-deadbeef', str(tmp_path)]]


async def test_calibrate_queues_the_problem(monkeypatch: pytest.MonkeyPatch):
    calls = _fake_moj(monkeypatch, '')

    await cli.calibrate('alice#rbxt-deadbeef')

    assert calls == [['calibrate', 'alice#rbxt-deadbeef']]


# -- The subprocess layer itself. ----------------------------------------------


async def test_a_missing_moj_binary_says_so_instead_of_tracing_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """A setter without the CLI is the common case, not an internal error.

    And "not installed" must not be reported as "not logged in", which is why it
    has its own class.
    """
    monkeypatch.setattr(cli, 'MOJ_BINARY', str(tmp_path / 'nowhere' / 'moj'))

    with pytest.raises(MojNotInstalledError) as exc_info:
        await cli.whoami()

    message = str(exc_info.value)
    assert 'MOJ CLI is not installed' in message
    assert 'PATH' in message
    assert 'moj login' in message


async def test_a_failing_command_names_the_command_and_shows_its_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    _stub_moj(
        monkeypatch,
        tmp_path,
        """
        echo 'problema nao encontrado' >&2
        exit 3
        """,
    )

    with pytest.raises(MojCliError) as exc_info:
        await cli.check('alice#rbxt-deadbeef')

    message = str(exc_info.value)
    assert "--json check 'alice#rbxt-deadbeef'" in message
    assert 'problema nao encontrado' in message
    assert '3' in message


async def test_no_error_message_carries_rich_markup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`main.py` bare-prints `str(e)`, so markup would reach the setter literally.

    Every path below interpolates CLI output into a message, which is where a
    stray `[...]` would come from.
    """
    markup = re.compile(r'\[/?[a-z]')
    cases = [
        ('whoami with no login', "echo 'nao autenticado'\n", cli.whoami),
        (
            'testrun with no run id',
            "echo 'algo deu errado'\n",
            lambda: cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp')),
        ),
        (
            'testrun-status that is not json',
            "echo 'nao e json'\n",
            lambda: cli.testrun_status('4711'),
        ),
        (
            'a non-zero exit',
            "echo 'problema nao encontrado' >&2\nexit 3\n",
            lambda: cli.check('alice#rbxt-deadbeef'),
        ),
    ]

    for index, (label, body, call) in enumerate(cases):
        directory = tmp_path / str(index)
        directory.mkdir()
        with monkeypatch.context() as context:
            _stub_moj(context, directory, body)
            with pytest.raises(MojCliError) as exc_info:
                await call()
        assert markup.search(str(exc_info.value)) is None, label


async def test_malformed_json_is_reported_as_such(
    monkeypatch: pytest.MonkeyPatch,
):
    """A `jq`-less CLI, or a warning printed before the JSON, lands here."""
    _fake_moj(monkeypatch, 'nao e json')

    with pytest.raises(MojCliError) as exc_info:
        await cli.testrun_status('4711')

    assert 'nao e json' in str(exc_info.value)


async def test_a_full_testrun_queue_is_its_own_retryable_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """MOJ caps queued testruns per account and answers 429.

    Its own type because it is the one failure here a caller can do something
    about -- wait -- and because nothing can clear it: `moj` has no command that
    cancels a testrun.
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        """
        echo 'moj: Você já tem 3 teste(s) na fila — aguarde terminarem (429)' >&2
        exit 1
        """,
    )

    with pytest.raises(cli.MojQueueFullError):
        await cli.testrun('alice#rbxt-deadbeef', tmp_path / 'sol.cpp')


async def test_the_queue_is_recognised_by_the_status_not_the_wording(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`_api_fail` appends `(<code>)`; the Portuguese prose is not the signal.

    A translated or reworded server message must still be recognised, and an
    unrelated failure that merely mentions a queue must not be.
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        """
        echo 'moj: too many pending submissions (429)' >&2
        exit 1
        """,
    )
    with pytest.raises(cli.MojQueueFullError):
        await cli.testrun('alice#rbxt-deadbeef', tmp_path / 'sol.cpp')


async def test_another_failure_that_mentions_a_queue_is_not_a_full_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    _stub_moj(
        monkeypatch,
        tmp_path,
        """
        echo 'moj: problema nao encontrado na fila (404)' >&2
        exit 1
        """,
    )
    with pytest.raises(cli.MojCliError) as exc_info:
        await cli.testrun('alice#rbxt-deadbeef', tmp_path / 'sol.cpp')
    assert not isinstance(exc_info.value, cli.MojQueueFullError)


# -- contest whoami: the contest-scoped session, through the `contest` layer. ---

# What `moj contest --json -c <cid> whoami` really prints: with `--json` the CLI's
# `out` relays `/auth/status` untouched. Confirmed live on 2026-08-24 against
# `treino`; the role flags below are the ones a judge account carries.
_CONTEST_WHOAMI = (
    '{"success":true,"logged_in":true,"login":"ana.judge","name":"Ana A",'
    '"contest":"sbc2026","is_admin":false,"is_judge":true,"is_staff":false,'
    '"is_cstaff":false,"is_chief":false,"is_animeitor":false}\n'
)


def test_contest_whoami_reads_the_role_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The argv is the assertion here as much as the parse is.

    `moj --json contest whoami` **silently loses the flag** -- `moj` consumes it
    into a shell variable and then `exec`s `moj-contest` without it -- and the
    prose that comes back instead parses as nothing at all. So the flag has to sit
    after `contest`, and a refactor that "tidies" it back to the front has to fail
    here rather than in front of a setter.
    """
    _stub_moj(monkeypatch, tmp_path, f"cat <<'EOF'\n{_CONTEST_WHOAMI}EOF\n")

    who = cli.contest_whoami('sbc2026')

    assert who.login == 'ana.judge'
    assert who.can_read_any_submission
    assert _stub_calls(tmp_path) == [['contest', '--json', '-c', 'sbc2026', 'whoami']]


def test_contest_whoami_denies_any_submission_to_a_plain_competitor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    _stub_moj(
        monkeypatch,
        tmp_path,
        'cat <<\'EOF\'\n{"login":"ana","is_admin":false,"is_judge":false,'
        '"is_chief":false}\nEOF\n',
    )

    assert not cli.contest_whoami('sbc2026').can_read_any_submission


def test_contest_whoami_treats_absent_role_flags_as_no_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """A server that predates a flag must read as "no access", never as access."""
    _stub_moj(monkeypatch, tmp_path, 'cat <<\'EOF\'\n{"login":"ana"}\nEOF\n')

    who = cli.contest_whoami('sbc2026')

    assert who.login == 'ana'
    assert not who.can_read_any_submission


def test_contest_whoami_says_how_to_log_in_when_there_is_no_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The CLI's own hint names a command that cannot be followed.

    `moj-contest login` without a contest exits asking for one, so relaying that
    message unchanged sends the setter around a loop. rbx names the contest.
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        """
        echo "moj-contest: faca 'moj-contest login' primeiro." >&2
        exit 1
        """,
    )

    with pytest.raises(MojCliError) as exc_info:
        cli.contest_whoami('sbc2026')
    assert 'moj-contest login sbc2026' in str(exc_info.value)


def test_contest_whoami_passes_the_missing_layer_message_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`moj-contest` is a separate artifact, and moj's own error installs it.

    Rewriting this one would replace a working `curl` command with a `login` hint
    for a CLI that is not there yet -- the wrong fix, in the wrong order.
    """
    _stub_moj(
        monkeypatch,
        tmp_path,
        """
        echo "moj: camada 'contest' nao instalada: curl -fLO https://moj.naquadah.com.br/moj-contest" >&2
        exit 1
        """,
    )

    with pytest.raises(MojCliError) as exc_info:
        cli.contest_whoami('sbc2026')
    assert 'curl -fLO' in str(exc_info.value)
    assert 'moj-contest login sbc2026' not in str(exc_info.value)


def test_contest_whoami_refuses_output_that_is_not_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The prose form is what a dropped `--json` produces, and it is not a login."""
    _stub_moj(
        monkeypatch,
        tmp_path,
        "echo 'contest: sbc2026  login: ana  nome: Ana  admin: nao'\n",
    )

    with pytest.raises(MojCliError):
        cli.contest_whoami('sbc2026')


# -- Which `moj`, and which shell runs it. -------------------------------------
#
# The MOJ CLI is a bash script that needs bash >= 4, behind a `#!/usr/bin/env
# bash` shebang -- so *which* bash runs it is decided by `PATH` at exec time, and
# macOS still ships 3.2 at `/bin/bash`. Both of the things below exist because of
# that: a way to say which command to run, and a diagnosis when the default one is
# run by a shell too old for it.


def _stub_bash(tmp_path: pathlib.Path, major: int) -> pathlib.Path:
    """A `bash` reporting `major`, which refuses to run anything if that is < 4.

    It answers the version probe and, for every other argv, does what the real
    CLI's own guard does: prints its message and exits non-zero. So a `moj` whose
    shebang resolves to this one fails exactly the way it fails on a stock macOS.
    """
    directory = tmp_path / f'bash{major}'
    directory.mkdir()
    path = directory / 'bash'
    refusal = (
        "echo 'moj: preciso de bash >= 4 (macOS: brew install bash e rode com ele)' >&2; exit 1"
        if major < 4
        else "echo 'login: alice  nome: Alice A'"
    )
    path.write_text(
        textwrap.dedent(f"""\
        #!/bin/sh
        case "$*" in
          *BASH_VERSINFO*) echo '{major}' ;;
          *) {refusal} ;;
        esac
        """)
    )
    path.chmod(0o755)
    return path


def _stub_bash_script(tmp_path: pathlib.Path, shebang: str) -> pathlib.Path:
    """A `moj` carrying `shebang`, so what executes it is the shebang's business."""
    path = tmp_path / 'moj'
    path.write_text(f'{shebang}\necho "unreachable: the shebang decides"\n')
    path.chmod(0o755)
    return path


async def test_the_command_to_run_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`RBX_MOJ_BINARY` is split like a shell command, not taken as a path.

    Which is the whole point of it: the fix a setter on macOS reaches for is an
    interpreter *plus* a script -- `/opt/homebrew/bin/bash ~/.local/bin/moj` --
    and a plain path could not express that.

    The script is deliberately left non-executable, so that a spawn which ignored
    the interpreter and exec'd it directly would fail rather than pass by luck.
    """
    script = tmp_path / 'somewhere' / 'moj.sh'
    script.parent.mkdir()
    script.write_text(f"cat <<'EOF'\n{_WHOAMI}EOF\n")
    script.chmod(0o644)
    monkeypatch.setenv('RBX_MOJ_BINARY', f'/bin/sh {script}')

    assert await cli.whoami() == 'alice'


async def test_an_override_that_is_not_there_reads_as_a_missing_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """A typo in the override is still "no CLI to run", not an internal error."""
    monkeypatch.setenv('RBX_MOJ_BINARY', str(tmp_path / 'nowhere' / 'moj'))

    with pytest.raises(MojNotInstalledError) as exc_info:
        await cli.whoami()
    assert 'RBX_MOJ_BINARY' in str(exc_info.value)


async def test_an_empty_override_falls_back_to_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """An unset-by-blanking variable must not spawn the empty string."""
    _stub_moj(monkeypatch, tmp_path, f"cat <<'EOF'\n{_WHOAMI}EOF\n")
    monkeypatch.setenv('RBX_MOJ_BINARY', '   ')

    assert await cli.whoami() == 'alice'


async def test_a_failure_names_the_overridden_command_rather_than_moj(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The setter has to be able to re-run by hand what rbx actually ran."""
    script = tmp_path / 'moj.sh'
    script.write_text("echo 'problema nao encontrado' >&2\nexit 3\n")
    monkeypatch.setenv('RBX_MOJ_BINARY', f'/bin/sh {script}')

    with pytest.raises(MojCliError) as exc_info:
        await cli.check('alice#rbxt-deadbeef')
    assert f'/bin/sh {script} --json check' in str(exc_info.value)


async def test_a_moj_run_by_a_bash_too_old_for_it_says_which_bash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The macOS failure, diagnosed structurally rather than by its wording.

    `/bin/bash` is 3.2 and the CLI needs 4; the message it dies with is
    Portuguese prose that rbx must not have to match to recognise this.
    """
    bash = _stub_bash(tmp_path, 3)
    monkeypatch.setenv('PATH', f'{bash.parent}:{os.environ["PATH"]}')
    monkeypatch.setattr(
        cli, 'MOJ_BINARY', str(_stub_bash_script(tmp_path, '#!/usr/bin/env bash'))
    )

    with pytest.raises(cli.MojUnsupportedShellError) as exc_info:
        await cli.check('alice#rbxt-deadbeef')

    message = str(exc_info.value)
    assert str(bash) in message
    assert 'bash 3' in message
    assert 'PATH' in message


async def test_a_current_bash_leaves_a_failure_as_the_failure_it_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The diagnosis must not fire on every failure that happens under bash."""
    bash = _stub_bash(tmp_path, 5)
    monkeypatch.setenv('PATH', f'{bash.parent}:{os.environ["PATH"]}')
    monkeypatch.setattr(
        cli, 'MOJ_BINARY', str(_stub_bash_script(tmp_path, '#!/usr/bin/env bash'))
    )

    with pytest.raises(MojCliError) as exc_info:
        await cli.testrun_status('4711')
    assert not isinstance(exc_info.value, cli.MojUnsupportedShellError)


async def test_an_explicit_interpreter_is_believed_over_the_shebang(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """An override naming a modern bash is the fix, and must not be diagnosed.

    The script it names still carries `#!/usr/bin/env bash`, so reading the
    shebang here would resolve the *stale* bash off `PATH` and report the setter's
    working setup as broken.
    """
    old = _stub_bash(tmp_path, 3)
    new = _stub_bash(tmp_path, 5)
    monkeypatch.setenv('PATH', f'{old.parent}:{os.environ["PATH"]}')
    script = _stub_bash_script(tmp_path, '#!/usr/bin/env bash')
    monkeypatch.setenv('RBX_MOJ_BINARY', f'{new} {script}')

    with pytest.raises(MojCliError) as exc_info:
        await cli.check('alice#rbxt-deadbeef')
    assert not isinstance(exc_info.value, cli.MojUnsupportedShellError)


async def test_an_outdated_bash_is_not_reported_as_a_missing_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`whoami` is the first call every MOJ command makes, and it lied here.

    Reading this as "run `moj login` first" sends the setter to a command that
    dies the same way, which is a loop rather than a fix.
    """
    bash = _stub_bash(tmp_path, 3)
    monkeypatch.setenv('PATH', f'{bash.parent}:{os.environ["PATH"]}')
    monkeypatch.setattr(
        cli, 'MOJ_BINARY', str(_stub_bash_script(tmp_path, '#!/usr/bin/env bash'))
    )

    with pytest.raises(cli.MojUnsupportedShellError) as exc_info:
        await cli.whoami()
    assert 'Could not read your MOJ login' not in str(exc_info.value)


async def test_whoami_does_not_read_every_failure_as_a_missing_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """A server error is not a logged-out setter, and saying so hides the cause."""
    _stub_moj(
        monkeypatch,
        tmp_path,
        "echo 'moj: erro interno do servidor (500)' >&2\nexit 1\n",
    )

    with pytest.raises(MojCliError) as exc_info:
        await cli.whoami()

    message = str(exc_info.value)
    assert '(500)' in message
    assert 'Could not read your MOJ login' not in message
