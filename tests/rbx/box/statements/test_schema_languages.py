"""Schema tests for wildcard statement languages and `languages:` lists
(design 2026-09-20 §1)."""

import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.contest.schema import Contest, ContestStatement, Document
from rbx.box.schema import Package
from rbx.box.statements.schema import WILDCARD_LANGUAGE, Statement


def _pkg(**kwargs):
    return Package(name='prob', timeLimit=1000, memoryLimit=256, **kwargs)


def test_wildcard_language_is_accepted_on_problem_statement():
    st = Statement(
        language='*', file=pathlib.Path('statement/statement-{lang}.rbx.tex')
    )
    assert st.language == WILDCARD_LANGUAGE
    assert st.is_wildcard


def test_concrete_language_is_not_wildcard():
    assert not Statement(language='en', file=pathlib.Path('a.tex')).is_wildcard


def test_invalid_language_still_rejected():
    with pytest.raises(ValidationError):
        Statement(language='english', file=pathlib.Path('a.tex'))


def test_contest_statement_name_may_carry_lang_placeholder():
    st = ContestStatement(
        name='statement-{lang}', language='*', file=pathlib.Path('a.rbx.tex')
    )
    assert st.name == 'statement-{lang}'
    doc = Document(
        name='info-{lang}', language='*', file=pathlib.Path('i.tex'), type='tex'
    )
    assert doc.name == 'info-{lang}'


@pytest.mark.parametrize('bad', ['statement-{foo}', 'st{', 'st}x', '{lang'])
def test_contest_statement_name_rejects_other_placeholders(bad):
    with pytest.raises(ValidationError):
        ContestStatement(name=bad, file=pathlib.Path('a.rbx.tex'))


def test_package_languages_list():
    assert _pkg(languages=['en', 'pt']).languages == ['en', 'pt']


def test_package_languages_defaults_to_none():
    assert _pkg().languages is None


def test_languages_list_rejects_wildcard():
    with pytest.raises(ValidationError):
        _pkg(languages=['*'])


def test_languages_list_rejects_duplicates():
    with pytest.raises(ValidationError):
        Contest(name='contest', languages=['en', 'en'])


def test_contest_languages_list():
    assert Contest(name='contest', languages=['en']).languages == ['en']


def test_dispatcher_rejects_languages():
    with pytest.raises(ValidationError):
        Contest(use_variants=True, languages=['en'])
