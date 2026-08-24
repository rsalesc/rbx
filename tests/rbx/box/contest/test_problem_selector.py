"""Tests for the `rbx on` problem selector."""

from typing import Dict, List, Optional

import pytest

from rbx.box.contest.problem_selector import (
    ProblemSelectorError,
    resolve_selector,
)
from rbx.box.contest.schema import ContestProblem


def _p(
    short_name: str,
    aliases: Optional[List[str]] = None,
    path: Optional[str] = None,
) -> ContestProblem:
    return ContestProblem(short_name=short_name, aliases=aliases or [], path=path)


CONTEST = [
    _p('A', ['apple'], 'day1/knapsack'),
    _p('B', [], 'day1/two-sum'),
    _p('C', ['choco', 'cake'], 'day2/tree-dp'),
]

NAMES: Dict[str, str] = {
    'A': 'knapsack-lite',
    'B': 'two-sum',
    'C': 'tree-dp',
}


def _resolve(selector: str, problems: Optional[List[ContestProblem]] = None):
    problems = CONTEST if problems is None else problems
    return [
        p.short_name
        for p in resolve_selector(selector, problems, lambda p: NAMES.get(p.short_name))
    ]


def _resolve_without_names(selector: str, problems: List[ContestProblem]):
    return [p.short_name for p in resolve_selector(selector, problems, lambda p: None)]


class TestWildcard:
    def test_star_matches_everything(self):
        assert _resolve('*') == ['A', 'B', 'C']


class TestTiers:
    def test_short_name(self):
        assert _resolve('B') == ['B']

    def test_short_name_is_case_insensitive(self):
        assert _resolve('b') == ['B']

    def test_problem_name(self):
        assert _resolve('knapsack-lite') == ['A']

    def test_alias(self):
        assert _resolve('choco') == ['C']
        assert _resolve('CAKE') == ['C']

    def test_folder_basename(self):
        assert _resolve('knapsack') == ['A']

    def test_short_name_wins_over_an_alias_on_another_problem(self):
        problems = [_p('A'), _p('B'), _p('C', aliases=['bee'])]
        assert _resolve_without_names('B', problems) == ['B']

    def test_name_wins_over_an_alias_on_another_problem(self):
        problems = [_p('A'), _p('B', aliases=['two-sum'])]
        names = {'A': 'two-sum'}
        assert [
            p.short_name
            for p in resolve_selector(
                'two-sum', problems, lambda p: names.get(p.short_name)
            )
        ] == ['A']

    def test_alias_wins_over_a_basename_on_another_problem(self):
        problems = [_p('A', aliases=['tree-dp']), _p('C', path='day2/tree-dp')]
        assert _resolve_without_names('tree-dp', problems) == ['A']

    def test_a_missing_problem_name_does_not_break_resolution(self):
        assert _resolve_without_names('choco', CONTEST) == ['C']

    def test_default_path_is_the_short_name(self):
        problems = [_p('A'), _p('B')]
        assert _resolve_without_names('a', problems) == ['A']


class TestLists:
    def test_comma_list(self):
        assert _resolve('A,C') == ['A', 'C']

    def test_comma_list_tolerates_spaces(self):
        assert _resolve('A , C') == ['A', 'C']

    def test_result_keeps_contest_order(self):
        assert _resolve('C,A') == ['A', 'C']

    def test_result_is_deduplicated(self):
        assert _resolve('A,apple') == ['A']

    def test_mixed_kinds(self):
        assert _resolve('A,choco') == ['A', 'C']

    def test_empty_token_is_an_error(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('A,')
        with pytest.raises(ProblemSelectorError):
            _resolve('A,,B')

    def test_empty_selector_is_an_error(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('')


class TestRanges:
    def test_inclusive_range(self):
        assert _resolve('A..C') == ['A', 'B', 'C']

    def test_partial_range(self):
        assert _resolve('B..C') == ['B', 'C']

    def test_range_is_case_insensitive(self):
        assert _resolve('a..c') == ['A', 'B', 'C']

    def test_range_follows_file_order_not_alphabetical_order(self):
        problems = [_p('C'), _p('A'), _p('B')]
        assert _resolve_without_names('C..A', problems) == ['C', 'A']

    def test_range_over_numbered_short_names(self):
        problems = [_p('A1'), _p('A2'), _p('A3'), _p('B')]
        assert _resolve_without_names('A1..A3', problems) == ['A1', 'A2', 'A3']

    def test_range_endpoints_are_short_names_only(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('apple..C')

    def test_unknown_range_endpoint_is_an_error(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('A..Z')

    def test_inverted_range_is_an_error(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('C..A')

    def test_malformed_range_is_an_error(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('A..')
        with pytest.raises(ProblemSelectorError):
            _resolve('A..B..C')

    def test_range_composes_with_a_list(self):
        problems = [_p('A'), _p('B'), _p('C'), _p('D')]
        assert _resolve_without_names('A..B,D', problems) == ['A', 'B', 'D']


class TestHyphenIsNotARange:
    def test_hyphenated_token_matches_literally(self):
        assert _resolve('two-sum') == ['B']

    def test_hyphenated_range_attempt_is_an_error_with_a_hint(self):
        with pytest.raises(ProblemSelectorError) as exc:
            _resolve('A-C')
        assert 'A..C' in str(exc.value)

    def test_hint_is_absent_when_the_halves_are_not_problems(self):
        with pytest.raises(ProblemSelectorError) as exc:
            _resolve('foo-bar')
        assert '..' not in str(exc.value)


class TestGlobs:
    def test_glob_over_basenames(self):
        problems = [
            _p('A', path='day1/knapsack'),
            _p('B', path='day1/two-sum'),
            _p('C', path='day2/tree-dp'),
        ]
        assert _resolve_without_names('*-*', problems) == ['B', 'C']

    def test_glob_matches_the_basename_not_the_whole_path(self):
        problems = [_p('A', path='day1/knapsack'), _p('B', path='day2/two-sum')]
        with pytest.raises(ProblemSelectorError):
            _resolve_without_names('day1/*', problems)

    def test_glob_over_short_names_wins_over_lower_tiers(self):
        problems = [_p('A1'), _p('A2'), _p('B', aliases=['abc'])]
        assert _resolve_without_names('a*', problems) == ['A1', 'A2']

    def test_glob_over_names(self):
        assert _resolve('knapsack*') == ['A']

    def test_glob_matching_nothing_is_an_error(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('zzz*')


class TestExclusions:
    def test_exclusion_from_the_wildcard(self):
        assert _resolve('*,!B') == ['A', 'C']

    def test_bare_exclusion_implies_everything(self):
        assert _resolve('!B') == ['A', 'C']

    def test_exclusion_from_a_range(self):
        assert _resolve('A..C,!B') == ['A', 'C']

    def test_exclusion_by_any_identifier_kind(self):
        assert _resolve('*,!choco') == ['A', 'B']
        assert _resolve('*,!two-sum') == ['A', 'C']

    def test_unmatched_exclusion_is_an_error(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('*,!Z')

    def test_everything_excluded_yields_nothing(self):
        assert _resolve('*,!A,!B,!C') == []

    def test_bare_exclusion_marker_is_an_error(self):
        with pytest.raises(ProblemSelectorError):
            _resolve('!')


class TestErrorMessages:
    def test_unmatched_token_names_the_token_and_lists_the_problems(self):
        with pytest.raises(ProblemSelectorError) as exc:
            _resolve('Z')
        message = str(exc.value)
        assert 'Z' in message
        assert 'A' in message and 'B' in message and 'C' in message
