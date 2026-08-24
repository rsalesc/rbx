import pytest

from rbx.box.packaging.moj.upload import build_problem_id
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
