"""Tests for contest_utils (match_problem, get_problems_of_interest) with short_name and aliases."""

from unittest.mock import patch

import pytest

from rbx.box.contest.contest_utils import get_problems_of_interest, match_problem
from rbx.box.contest.schema import Contest, ContestProblem


def _p(short_name: str, aliases: list[str] | None = None) -> ContestProblem:
    return ContestProblem(short_name=short_name, aliases=aliases or [])


class TestMatchProblem:
    def test_wildcard_matches_all(self):
        assert match_problem('*', _p('A')) is True
        assert match_problem('*', _p('B', ['choco'])) is True

    def test_range_matches_by_short_name_only(self):
        assert match_problem('A-C', _p('B')) is True
        assert match_problem('A-C', _p('A')) is True
        assert match_problem('A-C', _p('C')) is True
        assert match_problem('A-C', _p('D')) is False
        # Range does not match by alias
        assert match_problem('A-C', _p('D', ['choco'])) is False

    def test_comma_list_matches_short_name(self):
        assert match_problem('A,B,C', _p('B')) is True
        assert match_problem('A, B , C', _p('B')) is True
        assert match_problem('A,B', _p('C')) is False

    def test_comma_list_matches_alias(self):
        assert match_problem('choco,other', _p('A', ['choco'])) is True
        assert match_problem('choco', _p('A', ['choco'])) is True
        assert match_problem('A,choco', _p('A', ['choco'])) is True
        assert match_problem('other', _p('A', ['choco'])) is False

    def test_comma_list_case_insensitive(self):
        assert match_problem('CHOCO', _p('A', ['choco'])) is True
        assert match_problem('Choco', _p('A', ['choco'])) is True
        assert match_problem('a', _p('A')) is True


class TestGetProblemsOfInterest:
    @patch('rbx.box.contest.contest_utils.contest_package.find_contest_package_or_die')
    def test_returns_problems_matching_short_name_or_alias(self, mock_find):
        contest = Contest(
            name='Test',
            problems=[
                ContestProblem(short_name='A', aliases=['apple']),
                ContestProblem(short_name='B', aliases=[]),
                ContestProblem(short_name='C', aliases=['choco', 'cake']),
            ],
        )
        mock_find.return_value = contest

        assert len(get_problems_of_interest('A')) == 1
        assert get_problems_of_interest('A')[0].short_name == 'A'

        assert len(get_problems_of_interest('apple')) == 1
        assert get_problems_of_interest('apple')[0].short_name == 'A'

        assert len(get_problems_of_interest('choco')) == 1
        assert get_problems_of_interest('choco')[0].short_name == 'C'

        two = get_problems_of_interest('A,B')
        assert len(two) == 2
        assert {p.short_name for p in two} == {'A', 'B'}

        two_by_alias = get_problems_of_interest('apple,C')
        assert len(two_by_alias) == 2
        assert {p.short_name for p in two_by_alias} == {'A', 'C'}

        all_three = get_problems_of_interest('*')
        assert len(all_three) == 3
