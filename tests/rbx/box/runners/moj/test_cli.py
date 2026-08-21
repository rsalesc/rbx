"""The typed wrapper over the `moj` CLI.

Every test here drives canned CLI output through a fake `_run_moj`: the point of
the wrapper is to turn the CLI's two very different output styles -- real JSON for
some subcommands, human prose for others -- into models, and none of that needs a
judge. The two tests that do exercise the subprocess layer use a throwaway shell
script, never the network.

Several of these tests exist to *pin* a CLI behaviour rather than to cover our
own logic: that `whoami` prints prose, that `testrun --no-wait` prints prose. If
the CLI ever gains `--json` for those, the pinning test is what tells us, instead
of a wrong login or a wrong run id doing so silently much later.
"""

import json
import pathlib
import textwrap
from typing import Any, Callable, List, Sequence, Union

import pytest

from rbx.box.runners.moj import cli
from rbx.box.runners.moj.cli import MojCliError, MojNotInstalledError

Canned = Union[str, Callable[[Sequence[str]], str]]


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


def _fake_moj_raising(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    async def fake_run_moj(args: Sequence[str]) -> str:
        raise exc

    monkeypatch.setattr(cli, '_run_moj', fake_run_moj)


def _stub_binary(tmp_path: pathlib.Path, script: str) -> pathlib.Path:
    path = tmp_path / 'moj'
    path.write_text('#!/bin/sh\n' + textwrap.dedent(script))
    path.chmod(0o755)
    return path


# -- whoami: prose, not JSON. --------------------------------------------------


async def test_whoami_parses_the_login_out_of_the_human_output(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = _fake_moj(
        monkeypatch,
        'login: alice  nome: Alice A\npode criar problemas: sim\n',
    )

    assert await cli.whoami() == 'alice'
    assert calls == [['whoami']]


async def test_whoami_is_not_asked_for_json(monkeypatch: pytest.MonkeyPatch):
    """`moj whoami` does not honour `--json`; it returns before that branch.

    Asking for it anyway would suggest the output is machine-readable when the
    only thing we can do with it is parse prose.
    """
    calls = _fake_moj(monkeypatch, 'login: alice  nome: Alice A\n')

    await cli.whoami()

    assert '--json' not in calls[0]


async def test_whoami_without_a_session_tells_the_setter_to_log_in(
    monkeypatch: pytest.MonkeyPatch,
):
    _fake_moj_raising(monkeypatch, MojCliError('`moj whoami` failed: sem sessao'))

    with pytest.raises(MojCliError) as exc_info:
        await cli.whoami()

    assert '`moj login`' in str(exc_info.value)


async def test_whoami_that_prints_something_unrecognizable_does_not_invent_a_login(
    monkeypatch: pytest.MonkeyPatch,
):
    """Guessing here would upload the package under the wrong org."""
    _fake_moj(monkeypatch, 'nao autenticado\n')

    with pytest.raises(MojCliError) as exc_info:
        await cli.whoami()

    assert '`moj login`' in str(exc_info.value)


async def test_a_missing_binary_survives_whoami_as_a_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
):
    """ "Not installed" must not be reported as "not logged in"."""
    _fake_moj_raising(monkeypatch, MojNotInstalledError('no `moj` on the `PATH`'))

    with pytest.raises(MojNotInstalledError):
        await cli.whoami()


# -- testrun: a run id parsed out of prose. ------------------------------------

_QUEUED = (
    'enfileirado no juiz: run 4711  (sol.cpp contra alice#rbxt-deadbeef)\n'
    'acompanhe com: moj --json testrun-status 4711\n'
)


async def test_testrun_extracts_the_run_id_from_the_queued_message(
    monkeypatch: pytest.MonkeyPatch,
):
    _fake_moj(monkeypatch, _QUEUED)

    assert await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp')) == '4711'


async def test_testrun_does_not_wait_for_the_judge(monkeypatch: pytest.MonkeyPatch):
    """Blocking is minutes per solution, and it serializes the whole run."""
    calls = _fake_moj(monkeypatch, _QUEUED)

    await cli.testrun('alice#rbxt-deadbeef', pathlib.Path('sol.cpp'))

    assert calls == [['testrun', 'alice#rbxt-deadbeef', 'sol.cpp', '--no-wait']]


async def test_testrun_accepts_a_directory_holding_a_moj_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """The CLI resolves a directory through its own `.moj-id`."""
    calls = _fake_moj(monkeypatch, _QUEUED)

    await cli.testrun(tmp_path, tmp_path / 'sol.cpp')

    assert calls[0][1] == str(tmp_path)


async def test_testrun_that_prints_no_run_id_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
):
    """A silent None here would poll forever on a run that was never queued."""
    _fake_moj(monkeypatch, 'algo deu errado no envio\n')

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


# -- check: real JSON, nested under `tl`. --------------------------------------


def _check_payload(**tl: Any) -> str:
    return json.dumps({'validation': {}, 'calib': {}, 'tl': tl})


async def test_check_asks_for_json_before_the_subcommand(
    monkeypatch: pytest.MonkeyPatch,
):
    """The flag is global; after the subcommand the CLI does not see it."""
    calls = _fake_moj(monkeypatch, _check_payload(calibrated=True))

    await cli.check('alice#rbxt-deadbeef')

    assert calls == [['--json', 'check', 'alice#rbxt-deadbeef']]


async def test_a_calibrated_problem_is_ready(monkeypatch: pytest.MonkeyPatch):
    _fake_moj(
        monkeypatch,
        _check_payload(
            calibrated=True, being_calibrated=False, needs_recalibration=False
        ),
    )

    assert (await cli.check('alice#rbxt-deadbeef')).is_ready


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


async def _checked(monkeypatch: pytest.MonkeyPatch, **tl: Any):
    _fake_moj(monkeypatch, _check_payload(**tl))
    return await cli.check('alice#rbxt-deadbeef')


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
    """A setter without the CLI is the common case, not an internal error."""
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
    monkeypatch.setattr(
        cli,
        'MOJ_BINARY',
        str(
            _stub_binary(
                tmp_path,
                """
                echo 'problema nao encontrado' >&2
                exit 3
                """,
            )
        ),
    )

    with pytest.raises(MojCliError) as exc_info:
        await cli.check('alice#rbxt-deadbeef')

    message = str(exc_info.value)
    assert '--json check alice#rbxt-deadbeef' in message
    assert 'problema nao encontrado' in message
    assert '3' in message


async def test_errors_are_plain_text_not_rich_markup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`main.py` bare-prints `str(e)`, so markup would reach the setter literally."""
    monkeypatch.setattr(cli, 'MOJ_BINARY', str(tmp_path / 'nowhere' / 'moj'))

    with pytest.raises(MojCliError) as exc_info:
        await cli.whoami()

    assert '[item]' not in str(exc_info.value)
    assert '[/' not in str(exc_info.value)


async def test_output_of_a_successful_command_is_returned_verbatim(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        cli,
        'MOJ_BINARY',
        str(_stub_binary(tmp_path, "echo 'login: alice  nome: Alice A'\n")),
    )

    assert await cli.whoami() == 'alice'


async def test_malformed_json_is_reported_as_such(
    monkeypatch: pytest.MonkeyPatch,
):
    """A `jq`-less CLI, or a warning printed before the JSON, lands here."""
    _fake_moj(monkeypatch, 'nao e json')

    with pytest.raises(MojCliError) as exc_info:
        await cli.testrun_status('4711')

    assert 'nao e json' in str(exc_info.value)
