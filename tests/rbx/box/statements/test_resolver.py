import pathlib

import pytest

from rbx.box.contest.schema import ContestStatement
from rbx.box.statements import resolver
from rbx.box.statements.resolver import StatementResolverError
from rbx.box.statements.schema import Statement, StatementType


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
