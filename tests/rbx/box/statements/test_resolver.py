import pathlib
from unittest import mock

import pytest

from rbx.box.contest.schema import ContestStatement
from rbx.box.statements import resolver
from rbx.box.statements.resolver import StatementResolverError
from rbx.box.statements.schema import Statement, StatementKind, StatementType


def _problem_statement(
    language: str = 'en',
    variant: str = 'default',
    type: StatementType = StatementType.rbxTeX,
) -> Statement:
    return Statement(
        language=language,
        variant=variant,
        file=pathlib.Path('statement/statement.rbx.tex'),
        type=type,
    )


def _contest_statement(
    name: str,
    language: str = 'en',
    variant: str = 'default',
    type: StatementType = StatementType.rbxTeX,
    standalone: bool = True,
) -> ContestStatement:
    kwargs = {}
    if standalone:
        kwargs['standaloneProblemTemplate'] = pathlib.Path(
            'statements/problem-standalone.rbx.tex'
        )
    return ContestStatement(
        name=name,
        language=language,
        variant=variant,
        file=pathlib.Path('statements/contest.rbx.tex'),
        type=type,
        contestProblemTemplate=pathlib.Path('statements/problem-in-contest.rbx.tex'),
        **kwargs,
    )


class TestSelectStandaloneContestStatement:
    def test_returns_single_matching_candidate(self):
        st = _problem_statement(language='en', variant='default')
        contest_statements = [
            _contest_statement('main-en', language='en', variant='default'),
            _contest_statement('main-pt', language='pt', variant='default'),
        ]
        selected = resolver.select_standalone_contest_statement(st, contest_statements)
        assert selected.name == 'main-en'

    def test_matches_on_variant_too(self):
        st = _problem_statement(language='en', variant='short')
        contest_statements = [
            _contest_statement('main-en', language='en', variant='default'),
            _contest_statement('short-en', language='en', variant='short'),
        ]
        selected = resolver.select_standalone_contest_statement(st, contest_statements)
        assert selected.name == 'short-en'

    def test_errors_when_zero_candidates(self):
        st = _problem_statement(language='fr', variant='default')
        contest_statements = [
            _contest_statement('main-en', language='en', variant='default'),
        ]
        with pytest.raises(StatementResolverError):
            resolver.select_standalone_contest_statement(st, contest_statements)

    def test_zero_candidates_when_no_standalone_template(self):
        # A contest statement matching (language, variant) but WITHOUT a
        # standaloneProblemTemplate is not a candidate.
        st = _problem_statement(language='en', variant='default')
        contest_statements = [
            _contest_statement(
                'main-en', language='en', variant='default', standalone=False
            ),
        ]
        with pytest.raises(StatementResolverError):
            resolver.select_standalone_contest_statement(st, contest_statements)

    def test_errors_when_multiple_candidates(self):
        st = _problem_statement(language='en', variant='default')
        contest_statements = [
            _contest_statement('main-en', language='en', variant='default'),
            _contest_statement('alt-en', language='en', variant='default'),
        ]
        with pytest.raises(StatementResolverError):
            resolver.select_standalone_contest_statement(st, contest_statements)


class TestSelectProblemStatement:
    def test_returns_matching_problem_statement(self):
        cs = _contest_statement('main-en', language='en', variant='default')
        problem_statements = [
            _problem_statement(language='en', variant='default'),
            _problem_statement(language='pt', variant='default'),
        ]
        selected = resolver.select_problem_statement(cs, problem_statements, 'A')
        assert selected.key == ('en', 'default')

    def test_errors_when_no_matching_language_variant(self):
        cs = _contest_statement('main-en', language='en', variant='short')
        problem_statements = [
            _problem_statement(language='en', variant='default'),
        ]
        with pytest.raises(StatementResolverError):
            resolver.select_problem_statement(cs, problem_statements, 'A')

    def test_errors_when_type_mismatch(self):
        # Contest statement is rbxTeX; the problem statement at the same
        # (language, variant) is rbxMarkdown -> cannot join.
        cs = _contest_statement(
            'main-en', language='en', variant='default', type=StatementType.rbxTeX
        )
        problem_statements = [
            _problem_statement(
                language='en', variant='default', type=StatementType.rbxMarkdown
            ),
        ]
        with pytest.raises(StatementResolverError):
            resolver.select_problem_statement(cs, problem_statements, 'A')


class TestResolveStandalone:
    def test_single_match_returns_real_resolution(self):
        st = _problem_statement(language='en', variant='default')
        contest = mock.Mock()
        contest.expanded_statements = [
            _contest_statement('main-en', language='en', variant='default'),
            _contest_statement('main-pt', language='pt', variant='default'),
        ]
        with (
            mock.patch.object(
                resolver, 'find_contest_for_problem', return_value=contest
            ),
            mock.patch.object(
                resolver.contest_package,
                'find_contest',
                return_value=pathlib.Path('/contest'),
            ),
        ):
            res = resolver.resolve_standalone(st, StatementKind.STATEMENTS)
        assert res.is_fallback is False
        assert res.contest is contest
        assert res.contest_statement.name == 'main-en'
        assert res.contest_root == pathlib.Path('/contest')

    def test_multiple_candidates_still_errors(self):
        st = _problem_statement(language='en', variant='default')
        contest = mock.Mock()
        contest.expanded_statements = [
            _contest_statement('main-a', language='en', variant='default'),
            _contest_statement('main-b', language='en', variant='default'),
        ]
        with mock.patch.object(
            resolver, 'find_contest_for_problem', return_value=contest
        ):
            with pytest.raises(StatementResolverError):
                resolver.resolve_standalone(st, StatementKind.STATEMENTS)

    def test_no_contest_falls_back_to_bundled_default(self):
        st = _problem_statement(language='en', variant='default')
        with (
            mock.patch.object(resolver, 'find_contest_for_problem', return_value=None),
            mock.patch.object(
                resolver.contest_package, 'find_contest_root', return_value=None
            ),
        ):
            res = resolver.resolve_standalone(st, StatementKind.STATEMENTS)
        assert res.is_fallback is True
        assert res.contest is None
        assert res.contest_statement.language == 'en'
        assert res.contest_statement.variant == 'default'
        assert res.contest_statement.standaloneProblemTemplate is not None
        assert (res.contest_root / 'contest.rbx.yml').is_file()

    def test_fallback_rebinds_non_english_language(self):
        st = _problem_statement(language='pt', variant='short')
        with (
            mock.patch.object(resolver, 'find_contest_for_problem', return_value=None),
            mock.patch.object(
                resolver.contest_package, 'find_contest_root', return_value=None
            ),
        ):
            res = resolver.resolve_standalone(st, StatementKind.STATEMENTS)
        assert res.contest_statement.language == 'pt'
        assert res.contest_statement.variant == 'short'

    def test_tutorials_kind_uses_preset_tutorial_template(self):
        st = _problem_statement(language='en', variant='default')
        with (
            mock.patch.object(resolver, 'find_contest_for_problem', return_value=None),
            mock.patch.object(
                resolver.contest_package, 'find_contest_root', return_value=None
            ),
        ):
            res = resolver.resolve_standalone(st, StatementKind.TUTORIALS)
        assert res.is_fallback is True
        # The preset's editorial standalone template is named distinctively (not
        # `editorial.rbx.tex`) so it never collides with a problem's own editorial
        # source in the merged overlay (see #592).
        assert res.contest_statement.standaloneProblemTemplate == pathlib.Path(
            'statements/editorial-standalone.rbx.tex'
        )

    def test_contest_present_no_match_falls_back(self):
        st = _problem_statement(language='pt', variant='default')
        contest = mock.Mock()
        contest.expanded_statements = [
            _contest_statement('main-en', language='en', variant='default'),
        ]
        with mock.patch.object(
            resolver, 'find_contest_for_problem', return_value=contest
        ):
            res = resolver.resolve_standalone(st, StatementKind.STATEMENTS)
        assert res.is_fallback is True
        assert res.contest is contest

    def test_unselected_dispatcher_errors_with_hint(self):
        st = _problem_statement(language='en', variant='default')
        with (
            mock.patch.object(resolver, 'find_contest_for_problem', return_value=None),
            mock.patch.object(
                resolver.contest_package,
                'find_contest_root',
                return_value=pathlib.Path('/contest'),
            ),
            mock.patch.object(
                resolver.contest_state,
                'resolve_explicit_selection',
                return_value=None,
            ),
            mock.patch.object(
                resolver.contest_package,
                'discover_contest_variants',
                return_value=['div1', 'div2'],
            ),
        ):
            with pytest.raises(StatementResolverError):
                resolver.resolve_standalone(st, StatementKind.STATEMENTS)
