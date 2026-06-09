"""Tests for the statements v2 slim `extends` expander (design §5).

The v2 expander inherits ONLY the build recipe — `type`, `file`, `params`
(and, for contest statements, the two templates). Identity/targeting fields
(`name`, `language`, `variant`) are never inherited, and `params` deep-merges
key-by-key.
"""

import pathlib

import pytest

from rbx.box.contest.schema import ContestStatement, Document
from rbx.box.statements.expander import (
    StatementExpanderError,
    expand_contest_statements,
    expand_problem_statements,
)
from rbx.box.statements.schema import Statement, StatementType, StatementVariantRef


def _by_key(result, language, variant='default'):
    return next(
        st for st in result if st.language == language and st.variant == variant
    )


class TestProblemExpansion:
    def test_no_extends_unchanged(self):
        statements = [
            Statement(language='en', file=pathlib.Path('en.rbx.tex')),
            Statement(language='pt', file=pathlib.Path('pt.rbx.tex')),
        ]
        result = expand_problem_statements(statements)
        assert [st.language for st in result] == ['en', 'pt']
        assert _by_key(result, 'pt').file == pathlib.Path('pt.rbx.tex')

    def test_extends_by_language_string_inherits_recipe(self):
        statements = [
            Statement(
                language='en',
                file=pathlib.Path('statement.rbx.tex'),
                type=StatementType.rbxTeX,
                params={'show_limits': True},
            ),
            Statement(language='pt', extends='en'),
        ]
        result = expand_problem_statements(statements)

        pt = _by_key(result, 'pt')
        # Recipe inherited.
        assert pt.file == pathlib.Path('statement.rbx.tex')
        assert pt.type is StatementType.rbxTeX
        assert pt.params == {'show_limits': True}
        # Identity NEVER inherited.
        assert pt.language == 'pt'
        assert pt.variant == 'default'

    def test_extends_by_variant_dict(self):
        statements = [
            Statement(
                language='en',
                variant='short',
                file=pathlib.Path('short.rbx.tex'),
            ),
            Statement(
                language='pt',
                variant='short',
                extends=StatementVariantRef(language='en', variant='short'),
            ),
        ]
        result = expand_problem_statements(statements)
        pt = _by_key(result, 'pt', 'short')
        assert pt.file == pathlib.Path('short.rbx.tex')
        assert pt.variant == 'short'

    def test_params_deep_merge_key_by_key(self):
        statements = [
            Statement(
                language='en',
                file=pathlib.Path('s.rbx.tex'),
                params={'show_limits': True, 'nested': {'a': 1, 'b': 2}},
            ),
            Statement(
                language='pt',
                extends='en',
                params={'show_limits': False, 'nested': {'b': 3}},
            ),
        ]
        result = expand_problem_statements(statements)
        pt = _by_key(result, 'pt')
        # child overrides show_limits and nested.b; inherits nested.a.
        assert pt.params == {
            'show_limits': False,
            'nested': {'a': 1, 'b': 3},
        }

    def test_child_overrides_file_and_type(self):
        statements = [
            Statement(
                language='en',
                file=pathlib.Path('en.rbx.tex'),
                type=StatementType.rbxTeX,
            ),
            Statement(
                language='pt',
                extends='en',
                file=pathlib.Path('pt.rbx.tex'),
            ),
        ]
        result = expand_problem_statements(statements)
        pt = _by_key(result, 'pt')
        assert pt.file == pathlib.Path('pt.rbx.tex')  # overridden
        assert pt.type is StatementType.rbxTeX  # inherited

    def test_title_not_inherited(self):
        statements = [
            Statement(language='en', file=pathlib.Path('s.rbx.tex'), title='Hello'),
            Statement(language='pt', extends='en'),
        ]
        result = expand_problem_statements(statements)
        assert _by_key(result, 'pt').title is None

    def test_chain_extension(self):
        statements = [
            Statement(
                language='en',
                file=pathlib.Path('en.rbx.tex'),
                params={'a': 1},
            ),
            Statement(language='pt', extends='en', params={'b': 2}),
            Statement(language='es', extends='pt', params={'c': 3}),
        ]
        result = expand_problem_statements(statements)
        es = _by_key(result, 'es')
        assert es.file == pathlib.Path('en.rbx.tex')
        assert es.params == {'a': 1, 'b': 2, 'c': 3}

    def test_dangling_reference_errors(self):
        statements = [Statement(language='pt', extends='en')]
        with pytest.raises(StatementExpanderError, match=r'(?s)extends.*not.*defined'):
            expand_problem_statements(statements)

    def test_cycle_errors(self):
        statements = [
            Statement(language='en', extends='pt'),
            Statement(language='pt', extends='en'),
        ]
        with pytest.raises(StatementExpanderError, match=r'(?s)cycle'):
            expand_problem_statements(statements)


class TestContestExpansion:
    def test_extends_by_name_inherits_recipe_and_templates(self):
        statements = [
            ContestStatement(
                name='main-en',
                language='en',
                file=pathlib.Path('contest-en.rbx.tex'),
                type=StatementType.rbxTeX,
                standaloneProblemTemplate=pathlib.Path('standalone.rbx.tex'),
                contestProblemTemplate=pathlib.Path('in-contest.rbx.tex'),
                params={'k': 1},
            ),
            ContestStatement(
                name='main-pt',
                language='pt',
                extends='main-en',
                file=pathlib.Path('contest-pt.rbx.tex'),
            ),
        ]
        result = expand_contest_statements(statements)
        pt = next(st for st in result if st.name == 'main-pt')
        # Recipe + templates inherited.
        assert pt.type is StatementType.rbxTeX
        assert pt.standaloneProblemTemplate == pathlib.Path('standalone.rbx.tex')
        assert pt.contestProblemTemplate == pathlib.Path('in-contest.rbx.tex')
        assert pt.params == {'k': 1}
        # `file` overridden; identity never inherited.
        assert pt.file == pathlib.Path('contest-pt.rbx.tex')
        assert pt.name == 'main-pt'
        assert pt.language == 'pt'

    def test_documents_extends_by_name(self):
        documents = [
            Document(
                name='base',
                file=pathlib.Path('base.tex'),
                type=StatementType.TeX,
            ),
            Document(name='derived', extends='base'),
        ]
        result = expand_contest_statements(documents)
        derived = next(st for st in result if st.name == 'derived')
        assert derived.file == pathlib.Path('base.tex')
        assert derived.type is StatementType.TeX

    def test_cycle_errors(self):
        statements = [
            ContestStatement(name='a-en', extends='b-en'),
            ContestStatement(name='b-en', extends='a-en'),
        ]
        with pytest.raises(StatementExpanderError, match=r'(?s)cycle'):
            expand_contest_statements(statements)

    def test_dangling_reference_errors(self):
        statements = [ContestStatement(name='a-en', extends='nope')]
        with pytest.raises(StatementExpanderError, match=r'(?s)extends.*not.*defined'):
            expand_contest_statements(statements)
