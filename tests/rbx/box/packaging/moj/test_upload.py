from unittest import mock

import pytest

from rbx.box.packaging.moj.upload import (
    build_problem_id,
    resolve_problem_id,
    upload_package,
)
from rbx.box.runners.moj.cli import MojCliError
from tests.rbx.box.runners.moj.test_cli import _stub_calls, _stub_moj


def test_uses_the_configured_org():
    assert build_problem_id('alice', 'unicamp', 'a-aplusb') == 'unicamp#a-aplusb'


def test_falls_back_to_the_login_when_no_org_is_configured():
    assert build_problem_id('alice', None, 'a-aplusb') == 'alice#a-aplusb'


def test_lowercases_the_slug():
    # rbx allows uppercase in a problem name and contest short names ARE
    # uppercase letters, but MOJ slugs are lowercase-only.
    assert build_problem_id('alice', None, 'A-APlusB') == 'alice#a-aplusb'


def test_rejects_a_slug_that_is_not_a_legal_moj_slug():
    with pytest.raises(MojCliError, match='problem name'):
        build_problem_id('alice', None, 'a+b')


def test_rejects_an_illegal_org():
    with pytest.raises(MojCliError, match='org'):
        build_problem_id('alice', 'not an org', 'aplusb')


def test_refuses_a_slug_that_looks_like_an_rbx_timing_problem():
    # `rbxt-` marks a throwaway problem `rbx time --runner moj` created and may
    # overwrite. A real package must never land on an id that looks like one.
    with pytest.raises(MojCliError, match='rbxt-'):
        build_problem_id('alice', None, 'rbxt-aplusb')


# -- Resolving against the live CLI. -------------------------------------------
#
# `whoami` and the configured org are patched, so nothing here spawns a process
# or reads an `env.rbx.yml`. Assertions are on the single word `personal` rather
# than a phrase: rich wraps the warning at the console width, and a phrase can
# straddle the break.


async def test_resolve_warns_when_uploading_to_the_personal_org(capsys):
    with (
        mock.patch(
            'rbx.box.packaging.moj.upload.cli.whoami',
            new=mock.AsyncMock(return_value='alice'),
        ),
        mock.patch('rbx.box.packaging.moj.upload._configured_org', return_value=None),
    ):
        problem_id = await resolve_problem_id('a-aplusb')

    assert problem_id == 'alice#a-aplusb'
    assert 'personal' in capsys.readouterr().out


async def test_resolve_does_not_warn_when_an_org_is_configured(capsys):
    with (
        mock.patch(
            'rbx.box.packaging.moj.upload.cli.whoami',
            new=mock.AsyncMock(return_value='alice'),
        ),
        mock.patch(
            'rbx.box.packaging.moj.upload._configured_org', return_value='unicamp'
        ),
    ):
        problem_id = await resolve_problem_id('a-aplusb')

    assert problem_id == 'unicamp#a-aplusb'
    assert 'personal' not in capsys.readouterr().out


# -- The upload itself. --------------------------------------------------------
#
# Driven through the stub binary rather than a fake, so the argv asserted on is
# the argv a process really received. Nothing here touches the network.


async def test_upload_shells_out_to_moj_upload(monkeypatch, tmp_path):
    _stub_moj(monkeypatch, tmp_path, 'exit 0')
    directory = tmp_path / 'package'
    directory.mkdir()

    await upload_package('unicamp#a-aplusb', directory, calibrate=False)

    assert _stub_calls(tmp_path) == [['upload', 'unicamp#a-aplusb', str(directory)]]


async def test_upload_queues_a_calibration_when_asked(monkeypatch, tmp_path):
    _stub_moj(monkeypatch, tmp_path, 'exit 0')
    directory = tmp_path / 'package'
    directory.mkdir()

    await upload_package('unicamp#a-aplusb', directory, calibrate=True)

    calls = _stub_calls(tmp_path)
    assert calls == [
        ['upload', 'unicamp#a-aplusb', str(directory)],
        ['calibrate', 'unicamp#a-aplusb'],
    ]
    # Queued, never waited on: no `check` poll follows it. A setter who has just
    # uploaded has nothing to block on, and calibration is a long judge-side job.
    assert not any('check' in call for call in calls)
