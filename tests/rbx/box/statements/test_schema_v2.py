"""Tests for the statements v2 schema models (design §3).

Covers the new problem/contest statement + document models, the renamed
`params`/`file`/`variant` surface, and the validation rules of §3.3.
"""

import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.contest.schema import Contest, ContestStatement, Document
from rbx.box.schema import Package
from rbx.box.statements.schema import (
    DEFAULT_VARIANT,
    Statement,
    StatementType,
)


class TestStatementType:
    def test_has_v2_markdown_and_jinja_aliases(self):
        # The full v2 type set: rbxtex | rbxmd | jinjatex | jinjamd | tex | md | pdf.
        assert StatementType('rbx-tex') is StatementType.rbxTeX
        assert StatementType('rbx-md') is StatementType.rbxMarkdown
        assert StatementType('jinja-tex') is StatementType.JinjaTeX
        assert StatementType('jinja-md') is StatementType.JinjaMarkdown
        assert StatementType('tex') is StatementType.TeX
        assert StatementType('md') is StatementType.Markdown
        assert StatementType('pdf') is StatementType.PDF


class TestProblemStatement:
    def test_minimal_defaults(self):
        st = Statement(file=pathlib.Path('statements/statement-en.rbx.tex'))
        assert st.language == 'en'
        assert st.variant == DEFAULT_VARIANT
        assert st.type is StatementType.rbxTeX
        assert st.params == {}
        assert st.file == pathlib.Path('statements/statement-en.rbx.tex')

    def test_params_is_own_namespace(self):
        st = Statement(
            language='en',
            file=pathlib.Path('s.rbx.tex'),
            params={'show_limits': True},
        )
        assert st.params == {'show_limits': True}

    def test_rejects_removed_fields(self):
        # name/assets/steps/configure/inheritFromContest/vars are gone (extra forbid).
        for bad in (
            'name',
            'assets',
            'steps',
            'configure',
            'inheritFromContest',
            'vars',
        ):
            with pytest.raises(ValidationError):
                Statement(file=pathlib.Path('s.rbx.tex'), **{bad: _sample_for(bad)})

    def test_variant_disambiguates(self):
        st = Statement(language='en', variant='short', file=pathlib.Path('s.rbx.tex'))
        assert st.variant == 'short'


def _sample_for(field: str):
    return {
        'name': 'main-en',
        'assets': ['imgs/*.png'],
        'steps': [],
        'configure': [],
        'inheritFromContest': True,
        'vars': {'x': 1},
    }[field]


class TestProblemStatementUniqueness:
    def _pkg(self, statements):
        return Package.model_validate(
            {
                'name': 'prob',
                'timeLimit': 1000,
                'memoryLimit': 256,
                'statements': statements,
            }
        )

    def test_language_variant_must_be_unique(self):
        with pytest.raises(
            ValidationError, match=r'(?i)language.*variant|variant.*unique'
        ):
            self._pkg(
                [
                    {'language': 'en', 'file': 'a.rbx.tex'},
                    {'language': 'en', 'file': 'b.rbx.tex'},
                ]
            )

    def test_same_language_different_variant_ok(self):
        pkg = self._pkg(
            [
                {'language': 'en', 'variant': 'default', 'file': 'a.rbx.tex'},
                {'language': 'en', 'variant': 'short', 'file': 'b.rbx.tex'},
            ]
        )
        assert len(pkg.statements) == 2


class TestContestStatement:
    def test_requires_name(self):
        with pytest.raises(ValidationError):
            ContestStatement(language='en', file=pathlib.Path('c.rbx.tex'))

    def test_minimal_with_name(self):
        st = ContestStatement(name='main-en', file=pathlib.Path('c.rbx.tex'))
        assert st.name == 'main-en'
        assert st.variant == DEFAULT_VARIANT
        assert st.type is StatementType.rbxTeX

    def test_templates_allowed_for_rbx(self):
        st = ContestStatement(
            name='main-en',
            file=pathlib.Path('c.rbx.tex'),
            type=StatementType.rbxTeX,
            standaloneProblemTemplate=pathlib.Path('standalone.rbx.tex'),
            contestProblemTemplate=pathlib.Path('in-contest.rbx.tex'),
            params={'k': 1},
        )
        assert st.standaloneProblemTemplate == pathlib.Path('standalone.rbx.tex')
        assert st.contestProblemTemplate == pathlib.Path('in-contest.rbx.tex')

    def test_templates_forbidden_for_static_type(self):
        with pytest.raises(ValidationError, match=r'(?i)rbx'):
            ContestStatement(
                name='main-en',
                file=pathlib.Path('c.tex'),
                type=StatementType.TeX,
                standaloneProblemTemplate=pathlib.Path('standalone.rbx.tex'),
            )

    def test_params_forbidden_for_static_type(self):
        with pytest.raises(ValidationError, match=r'(?i)rbx'):
            ContestStatement(
                name='main-en',
                file=pathlib.Path('c.tex'),
                type=StatementType.TeX,
                params={'k': 1},
            )


class TestContestStatementUniqueness:
    def _contest(self, statements):
        return Contest.model_validate({'name': 'my-contest', 'statements': statements})

    def test_name_must_be_unique(self):
        with pytest.raises(ValidationError, match=r'(?i)name.*unique'):
            self._contest(
                [
                    {'name': 'main-en', 'language': 'en', 'file': 'a.rbx.tex'},
                    {'name': 'main-en', 'language': 'pt', 'file': 'b.rbx.tex'},
                ]
            )

    def test_language_variant_may_repeat(self):
        contest = self._contest(
            [
                {'name': 'main-en', 'language': 'en', 'file': 'a.rbx.tex'},
                {'name': 'alt-en', 'language': 'en', 'file': 'b.rbx.tex'},
            ]
        )
        assert len(contest.statements) == 2


class TestDocument:
    def test_static_and_jinja_types_allowed(self):
        for t in (
            StatementType.JinjaTeX,
            StatementType.JinjaMarkdown,
            StatementType.TeX,
            StatementType.Markdown,
            StatementType.PDF,
        ):
            doc = Document(name='infosheet-en', file=pathlib.Path('i.tex'), type=t)
            assert doc.type is t

    def test_rbx_types_forbidden(self):
        for t in (StatementType.rbxTeX, StatementType.rbxMarkdown):
            with pytest.raises(ValidationError, match=r'(?i)document.*(rbx|join)|rbx'):
                Document(name='infosheet-en', file=pathlib.Path('i.rbx.tex'), type=t)

    def test_documents_unique_by_name_in_contest(self):
        with pytest.raises(ValidationError, match=r'(?i)name.*unique'):
            Contest.model_validate(
                {
                    'name': 'my-contest',
                    'documents': [
                        {'name': 'doc', 'file': 'a.tex', 'type': 'tex'},
                        {'name': 'doc', 'file': 'b.tex', 'type': 'tex'},
                    ],
                }
            )
