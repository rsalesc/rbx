from unittest import mock

import pytest

from rbx.box.packaging.moj.upload import build_problem_id, resolve_problem_id
from rbx.box.runners.moj.cli import MojCliError


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
