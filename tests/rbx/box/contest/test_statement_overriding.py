from unittest.mock import MagicMock, patch

import pytest

from rbx.box.contest.schema import (
    Contest,
    ContestStatement,
    ProblemStatementOverride,
)
from rbx.box.contest.statement_overriding import (
    StatementInheritanceError,
    StatementOverrideData,
    get_inheritance_overrides,
    get_overrides,
)
from rbx.box.statements.schema import (
    ConversionType,
    Statement,
    rbxToTeX,
)


class TestStatementOverrideData:
    def test_to_kwargs(self):
        data = StatementOverrideData(
            root=MagicMock(),
            assets=[],
            params={},
            vars={'a': 1, 'b': 2},
        )
        kwargs = data.to_kwargs({'b': 3, 'c': 4})
        assert kwargs['custom_vars'] == {'a': 1, 'b': 3, 'c': 4}
        assert kwargs['overridden_params_root'] == data.root
        assert kwargs['overridden_assets'] == data.assets
        assert kwargs['overridden_params'] == data.params


class TestGetOverrides:
    @patch('rbx.box.contest.statement_overriding.utils.abspath')
    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest')
    @patch('rbx.box.contest.statement_overriding.statement_utils.get_relative_assets')
    def test_get_overrides_no_inherit(
        self, mock_get_relative_assets, mock_find_contest, mock_abspath
    ):
        mock_abspath.return_value = MagicMock()
        mock_find_contest.return_value = MagicMock()
        mock_get_relative_assets.return_value = ['asset1']

        override_config = ProblemStatementOverride(
            configure=[rbxToTeX(type=ConversionType.rbxToTex)],
            vars={'foo': 'bar'},
        )
        statement = ContestStatement(
            name='ProblemA',
            override=override_config,
        )

        overrides = get_overrides(statement, inherit=False)

        assert overrides.root == mock_abspath.return_value
        assert overrides.assets == ['asset1']
        assert overrides.vars == {'foo': 'bar'}
        assert ConversionType.rbxToTex in overrides.params
        assert isinstance(overrides.params[ConversionType.rbxToTex], rbxToTeX)

    @patch('rbx.box.contest.statement_overriding.utils.abspath')
    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest')
    @patch('rbx.box.contest.statement_overriding.statement_utils.get_relative_assets')
    def test_get_overrides_inherit(
        self, mock_get_relative_assets, mock_find_contest, mock_abspath
    ):
        mock_abspath.return_value = MagicMock()
        mock_find_contest.return_value = MagicMock()
        mock_get_relative_assets.return_value = ['asset2']

        override_config = ProblemStatementOverride(
            vars={'inherit': 'true'},
        )
        statement = ContestStatement(
            name='ProblemA',
            inheritOverride=override_config,
        )

        overrides = get_overrides(statement, inherit=True)

        assert overrides.assets == ['asset2']
        assert overrides.vars == {'inherit': 'true'}
        assert overrides.params == {}

    @patch('rbx.box.contest.statement_overriding.utils.abspath')
    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest')
    @patch('rbx.box.contest.statement_overriding.statement_utils.get_relative_assets')
    def test_get_overrides_none(
        self, mock_get_relative_assets, mock_find_contest, mock_abspath
    ):
        mock_abspath.return_value = MagicMock()
        mock_find_contest.return_value = MagicMock()
        mock_get_relative_assets.return_value = []

        statement = ContestStatement(name='ProblemA')

        overrides = get_overrides(statement, inherit=False)

        assert overrides.assets == []
        assert overrides.vars == {}
        assert overrides.params == {}


class TestGetInheritanceOverrides:
    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    def test_no_contest_found(self, mock_find_pkg):
        mock_find_pkg.return_value = None
        statement = Statement(name='problem', inheritFromContest=True)

        with pytest.raises(StatementInheritanceError) as exc:
            get_inheritance_overrides(statement)
        assert 'no contest was found' in str(exc.value)

    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    def test_no_matching_statement(self, mock_find_pkg):
        contest = Contest(name='MyContest', statements=[])
        mock_find_pkg.return_value = contest
        statement = Statement(name='problem', inheritFromContest=True)

        with pytest.raises(StatementInheritanceError) as exc:
            get_inheritance_overrides(statement)
        assert 'no matching statement' in str(exc.value)

    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    @patch('rbx.box.contest.statement_overriding.get_overrides')
    def test_match_by_language(self, mock_get_overrides, mock_find_pkg):
        contest_stm = ContestStatement(name='portuguese', language='pt')
        contest = Contest(name='MyContest', statements=[contest_stm])
        mock_find_pkg.return_value = contest

        statement = Statement(name='problem', language='pt', inheritFromContest=True)

        from rbx.box.statements.schema import JoinerType, JoinTexToPDF

        contest_stm.joiner = JoinTexToPDF(type=JoinerType.TexToPDF)

        get_inheritance_overrides(statement)

        mock_get_overrides.assert_called_once_with(contest_stm, inherit=True)

    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    @patch('rbx.box.contest.statement_overriding.get_overrides')
    def test_match_by_name(self, mock_get_overrides, mock_find_pkg):
        from rbx.box.statements.schema import JoinerType, JoinTexToPDF

        contest_stm = ContestStatement(
            name='special',
            match='my_special_statement',
            joiner=JoinTexToPDF(type=JoinerType.TexToPDF),
        )
        contest = Contest(name='MyContest', statements=[contest_stm])
        mock_find_pkg.return_value = contest

        statement = Statement(
            name='my_special_statement', language='en', inheritFromContest=True
        )

        get_inheritance_overrides(statement)

        mock_get_overrides.assert_called_once_with(contest_stm, inherit=True)

    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    def test_no_match_due_to_missing_joiner(self, mock_find_pkg):
        contest_stm = ContestStatement(name='english', language='en')
        contest = Contest(name='MyContest', statements=[contest_stm])
        mock_find_pkg.return_value = contest

        statement = Statement(name='problem', language='en', inheritFromContest=True)

        with pytest.raises(StatementInheritanceError) as exc:
            get_inheritance_overrides(statement)
        assert 'no matching statement' in str(exc.value)


class TestGetStatementBuilderContestForProblem:
    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    def test_no_contest(self, mock_find_pkg):
        mock_find_pkg.return_value = None
        from rbx.box.contest.statement_overriding import (
            get_statement_builder_contest_for_problem,
        )

        assert get_statement_builder_contest_for_problem() is None

    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    def test_with_contest_no_inherit_no_custom(self, mock_find_pkg):
        contest = MagicMock()
        contest.expanded_vars = {'a': 1, 'b': 2}
        contest.name = ''
        mock_find_pkg.return_value = contest
        from rbx.box.contest.statement_overriding import (
            get_statement_builder_contest_for_problem,
        )

        builder_contest = get_statement_builder_contest_for_problem()
        assert builder_contest is not None
        assert builder_contest.title == ''
        assert builder_contest.vars == {'a': 1, 'b': 2}

    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    def test_with_inherit_and_custom_vars(self, mock_find_pkg):
        contest = MagicMock()
        contest.expanded_vars = {'a': 1, 'b': 2}
        mock_find_pkg.return_value = contest

        inherited = ContestStatement(
            name='problem',
            vars={'b': 3, 'c': 4},
            title='My Title',
        )
        custom_vars = {'c': 5, 'd': 6}

        from rbx.box.contest.statement_overriding import (
            get_statement_builder_contest_for_problem,
        )

        builder_contest = get_statement_builder_contest_for_problem(
            inherited_from=inherited,
            custom_vars=custom_vars,
        )

        assert builder_contest is not None
        assert builder_contest.title == 'My Title'
        # Check priority: custom > inherited > contest
        assert builder_contest.vars == {'a': 1, 'b': 3, 'c': 5, 'd': 6}

    @patch('rbx.box.contest.statement_overriding.contest_package.find_contest_package')
    def test_with_contest_titles_and_language(self, mock_find_pkg):
        contest = MagicMock()
        # Mocking the titles dictionary on the contest object
        contest.titles = {'pt': 'Título Português', 'en': 'English Title'}
        contest.expanded_vars = {}
        mock_find_pkg.return_value = contest

        from rbx.box.contest.statement_overriding import (
            get_statement_builder_contest_for_problem,
        )

        # Test asking for Portuguese title
        builder_contest_pt = get_statement_builder_contest_for_problem(language='pt')
        assert builder_contest_pt is not None
        assert builder_contest_pt.title == 'Título Português'

        # Test asking for English title
        builder_contest_en = get_statement_builder_contest_for_problem(language='en')
        assert builder_contest_en is not None
        assert builder_contest_en.title == 'English Title'
