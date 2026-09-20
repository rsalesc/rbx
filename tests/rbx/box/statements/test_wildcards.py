"""Tests for wildcard (`language: "*"`) statement expansion (design
2026-09-20 §1)."""

import pathlib

import pytest

from rbx.box.contest.schema import ContestStatement, Document
from rbx.box.statements.schema import Statement
from rbx.box.statements.wildcards import (
    WildcardExpansionError,
    concrete_languages,
    expand_contest_wildcards,
    expand_problem_wildcards,
    substitute_lang,
)


class TestSubstituteLang:
    def test_string(self):
        assert substitute_lang('a-{lang}.tex', 'pt') == 'a-pt.tex'

    def test_path(self):
        assert substitute_lang(pathlib.Path('x/{lang}/s.tex'), 'pt') == pathlib.Path(
            'x/pt/s.tex'
        )

    def test_nested_containers_and_non_strings_untouched(self):
        assert substitute_lang({'a': ['{lang}', 1], 'b': {'c': '{lang}'}}, 'en') == {
            'a': ['en', 1],
            'b': {'c': 'en'},
        }


class TestProblemExpansion:
    def test_expands_per_language_in_list_order(self):
        sts = [
            Statement(
                language='*',
                file=pathlib.Path('st-{lang}.rbx.tex'),
                params={'k': '{lang}'},
            )
        ]
        out = expand_problem_wildcards(sts, ['en', 'pt'])
        assert [(s.language, str(s.file), s.params['k']) for s in out] == [
            ('en', 'st-en.rbx.tex', 'en'),
            ('pt', 'st-pt.rbx.tex', 'pt'),
        ]
        assert not any(s.is_wildcard for s in out)

    def test_concrete_entry_beats_wildcard_for_same_key(self):
        sts = [
            Statement(language='*', file=pathlib.Path('st-{lang}.rbx.tex')),
            Statement(language='pt', file=pathlib.Path('special.rbx.tex')),
        ]
        out = expand_problem_wildcards(sts, ['en', 'pt'])
        assert [(s.language, str(s.file)) for s in out] == [
            ('en', 'st-en.rbx.tex'),
            ('pt', 'special.rbx.tex'),
        ]

    def test_variant_is_preserved_so_keys_stay_unique(self):
        sts = [
            Statement(language='*', file=pathlib.Path('a-{lang}.tex')),
            Statement(language='*', variant='short', file=pathlib.Path('b-{lang}.tex')),
        ]
        out = expand_problem_wildcards(sts, ['en'])
        assert [(s.language, s.variant) for s in out] == [
            ('en', 'default'),
            ('en', 'short'),
        ]

    def test_no_wildcards_is_identity(self):
        sts = [Statement(language='en', file=pathlib.Path('a.tex'))]
        assert expand_problem_wildcards(sts, None) == sts
        assert expand_problem_wildcards(sts, []) == sts

    def test_wildcard_without_languages_errors(self):
        sts = [Statement(language='*', file=pathlib.Path('a-{lang}.tex'))]
        with pytest.raises(WildcardExpansionError):
            expand_problem_wildcards(sts, None)
        with pytest.raises(WildcardExpansionError):
            expand_problem_wildcards(sts, [])


class TestContestExpansion:
    def test_substitutes_name_templates_and_assets(self):
        sts = [
            ContestStatement(
                name='statement-{lang}',
                language='*',
                file=pathlib.Path('sheet.rbx.tex'),
                standaloneProblemTemplate=pathlib.Path('p-{lang}.rbx.tex'),
                contestProblemTemplate=pathlib.Path('f.rbx.tex'),
                assets=['img/{lang}/*'],
            )
        ]
        out = expand_contest_wildcards(sts, ['en', 'pt'])
        assert [s.name for s in out] == ['statement-en', 'statement-pt']
        assert [s.language for s in out] == ['en', 'pt']
        assert str(out[1].standaloneProblemTemplate) == 'p-pt.rbx.tex'
        assert str(out[1].contestProblemTemplate) == 'f.rbx.tex'
        assert out[1].assets == ['img/pt/*']

    def test_concrete_beats_wildcard_by_name(self):
        sts = [
            ContestStatement(
                name='statement-{lang}', language='*', file=pathlib.Path('a.rbx.tex')
            ),
            ContestStatement(
                name='statement-pt', language='pt', file=pathlib.Path('b.rbx.tex')
            ),
        ]
        out = expand_contest_wildcards(sts, ['en', 'pt'])
        assert [(s.name, str(s.file)) for s in out] == [
            ('statement-en', 'a.rbx.tex'),
            ('statement-pt', 'b.rbx.tex'),
        ]

    def test_documents_expand_too(self):
        out = expand_contest_wildcards(
            [
                Document(
                    name='info-{lang}',
                    language='*',
                    file=pathlib.Path('i.tex'),
                    type='tex',
                )
            ],
            ['en'],
        )
        assert (out[0].name, out[0].language) == ('info-en', 'en')


def test_concrete_languages_dedupes_in_order_and_skips_wildcards():
    sts = [
        Statement(language='pt', file=pathlib.Path('a.tex')),
        Statement(language='*', file=pathlib.Path('b-{lang}.tex')),
        Statement(language='en', file=pathlib.Path('c.tex')),
        Statement(language='pt', variant='short', file=pathlib.Path('d.tex')),
    ]
    assert concrete_languages(sts) == ['pt', 'en']
