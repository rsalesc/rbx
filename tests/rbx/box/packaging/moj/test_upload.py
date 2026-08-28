from unittest import mock

import pytest

from rbx.box.packaging.moj.upload import (
    build_problem_id,
    resolve_org,
    resolve_problem_id,
    upload_package,
)
from rbx.box.runners.moj.cli import MojCliError
from tests.rbx.box.runners.moj.test_cli import _stub_calls, _stub_moj


def test_builds_the_id_from_the_org_and_the_basename():
    assert build_problem_id('unicamp', 'a-aplusb') == 'unicamp#a-aplusb'


def test_lowercases_the_slug():
    # rbx allows uppercase in a problem name and contest short names ARE
    # uppercase letters, but MOJ slugs are lowercase-only.
    assert build_problem_id('alice', 'A-APlusB') == 'alice#a-aplusb'


def test_rejects_a_slug_that_is_not_a_legal_moj_slug():
    with pytest.raises(MojCliError, match='problem name'):
        build_problem_id('alice', 'a+b')


def test_rejects_an_illegal_org():
    with pytest.raises(MojCliError, match='org'):
        build_problem_id('not an org', 'aplusb')


def test_refuses_a_slug_that_looks_like_an_rbx_timing_problem():
    # `rbxt-` marks a throwaway problem `rbx time --runner moj` created and may
    # overwrite. A real package must never land on an id that looks like one.
    with pytest.raises(MojCliError, match='rbxt-'):
        build_problem_id('alice', 'rbxt-aplusb')


# -- Resolving against the live CLI. -------------------------------------------
#
# `whoami` and the configured org are patched, so nothing here spawns a process
# or reads an `env.rbx.yml`. Assertions are on the single word `personal` rather
# than a phrase: rich wraps the warning at the console width, and a phrase can
# straddle the break.


async def test_resolve_org_uses_the_configured_org_without_a_session():
    # No `whoami` patch on purpose: a configured org must resolve without ever
    # reaching the CLI, which is what lets `rbx tooling moj summary` list a
    # contest's ids while logged out.
    with mock.patch(
        'rbx.box.packaging.moj.upload.configured_org', return_value='unicamp'
    ):
        assert await resolve_org() == ('unicamp', False)


async def test_resolve_org_falls_back_to_the_login():
    with (
        mock.patch(
            'rbx.box.packaging.moj.upload.cli.whoami',
            new=mock.AsyncMock(return_value='alice'),
        ),
        mock.patch('rbx.box.packaging.moj.upload.configured_org', return_value=None),
    ):
        assert await resolve_org() == ('alice', True)


async def test_resolve_warns_when_uploading_to_the_personal_org(capsys):
    with (
        mock.patch(
            'rbx.box.packaging.moj.upload.cli.whoami',
            new=mock.AsyncMock(return_value='alice'),
        ),
        mock.patch('rbx.box.packaging.moj.upload.configured_org', return_value=None),
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
            'rbx.box.packaging.moj.upload.configured_org', return_value='unicamp'
        ),
    ):
        problem_id = await resolve_problem_id('a-aplusb')

    assert problem_id == 'unicamp#a-aplusb'
    assert 'personal' not in capsys.readouterr().out


# -- The upload itself. --------------------------------------------------------
#
# Driven through the stub binary rather than a fake, so the argv asserted on is
# the argv a process really received. Nothing here touches the network.


async def test_upload_shells_out_to_moj_upload_and_queues_a_calibration(
    monkeypatch, tmp_path
):
    _stub_moj(monkeypatch, tmp_path, 'exit 0')
    directory = tmp_path / 'package'
    directory.mkdir()

    await upload_package('unicamp#a-aplusb', directory)

    # Both, whatever settled the limits: mojtools refuses to judge a package with no
    # `tl` file, so a package nobody calibrates is a package nobody can submit to --
    # pinned limits included. What `--calibrate` decides is whether the numbers
    # calibration measures survive `TLOVERRIDE`, not whether it runs.
    calls = _stub_calls(tmp_path)
    assert calls == [
        ['upload', 'unicamp#a-aplusb', str(directory)],
        ['calibrate', 'unicamp#a-aplusb', '--all-judges'],
    ]
    # Queued, never waited on: no `check` poll follows it. A setter who has just
    # uploaded has nothing to block on, and calibration is a long judge-side job.
    assert not any('check' in call for call in calls)


# -- Calibrating the whole park. -----------------------------------------------
#
# `--all-judges` and not a `--hosts` list rbx assembles itself: the CLI expands the
# flag against the park it queries at that moment, so an inventory that changes --
# a judge added, a judge retired -- is never something rbx has to have known about.


async def test_the_package_upload_calibrates_on_every_judge(monkeypatch, tmp_path):
    """Unlike the probe upload, which asks for the cheap global calibration.

    `moj check` publishes the time limit as the max across the judges that
    calibrated, so a package measured on one machine is judged, everywhere else,
    against a limit nothing measured there.
    """
    _stub_moj(monkeypatch, tmp_path, 'exit 0')
    directory = tmp_path / 'package'
    directory.mkdir()

    await upload_package('unicamp#a-aplusb', directory)

    assert ['calibrate', 'unicamp#a-aplusb', '--all-judges'] in _stub_calls(tmp_path)


async def test_an_unreachable_park_falls_back_to_a_global_calibration(
    monkeypatch, tmp_path, capsys
):
    """The package is already uploaded by this point, and mojtools will not judge
    a package with no `tl` file. Failing here would leave a problem nobody can
    submit to; one global request instead queues, and the first free judge takes
    it."""
    _stub_moj(
        monkeypatch,
        tmp_path,
        """
        for a in "$@"; do
          if [ "$a" = --all-judges ]; then
            echo 'nenhum juiz online -- veja "moj calibrate --judges"' >&2
            exit 1
          fi
        done
        exit 0
        """,
    )
    directory = tmp_path / 'package'
    directory.mkdir()

    await upload_package('unicamp#a-aplusb', directory)

    assert _stub_calls(tmp_path) == [
        ['upload', 'unicamp#a-aplusb', str(directory)],
        ['calibrate', 'unicamp#a-aplusb', '--all-judges'],
        ['calibrate', 'unicamp#a-aplusb'],
    ]
    # Said out loud: the limits the fallback measures describe one judge, and the
    # setter is the only one who can decide to re-run it later.
    assert 'Falling back' in capsys.readouterr().out


async def test_a_failure_that_is_not_the_park_still_reaches_the_setter(
    monkeypatch, tmp_path
):
    """The retry is unconditional rather than matched against the CLI's error
    text, so a failure with another cause simply fails again -- and it is that
    second error, not a swallowed first one, that is raised."""
    _stub_moj(
        monkeypatch,
        tmp_path,
        """
        case "$1" in
          calibrate) echo 'sem permissao para editar o problema' >&2; exit 1;;
        esac
        exit 0
        """,
    )
    directory = tmp_path / 'package'
    directory.mkdir()

    with pytest.raises(MojCliError, match='permissao'):
        await upload_package('unicamp#a-aplusb', directory)
