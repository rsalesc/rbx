"""Tests for contest_utils (match_problem, get_problems_of_interest) with short_name and aliases."""

from typing import Optional
from unittest.mock import patch

import pytest

from rbx.box.contest.contest_utils import (
    EmptyCommandError,
    build_command_argvs,
    get_problems_of_interest,
    match_problem,
    split_commands,
)
from rbx.box.contest.schema import Contest, ContestProblem


def _p(short_name: str, aliases: Optional[list[str]] = None) -> ContestProblem:
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


class TestSplitCommands:
    def test_no_separator_yields_single_group(self):
        assert split_commands(['build', '-v']) == [['build', '-v']]

    def test_empty_args_yield_no_groups(self):
        assert split_commands([]) == []

    def test_splits_on_separator_keeping_per_command_flags(self):
        assert split_commands(
            ['build', '::', 'run', '-s', '::', 'package', 'build']
        ) == [
            ['build'],
            ['run', '-s'],
            ['package', 'build'],
        ]

    def test_separator_only_matches_a_bare_token(self):
        # A `::` glued to something else is a normal argument.
        assert split_commands(['run', '--filter', 'a::b']) == [
            ['run', '--filter', 'a::b']
        ]

    @pytest.mark.parametrize(
        'args',
        [
            ['::'],
            ['::', 'build'],
            ['build', '::'],
            ['build', '::', '::', 'run'],
        ],
    )
    def test_empty_group_is_an_error(self, args):
        with pytest.raises(EmptyCommandError):
            split_commands(args)


class TestBuildCommandArgvs:
    def test_prefixes_each_command_with_rbx(self):
        argvs, prefix = build_command_argvs(['build', '::', 'run', '-s'])
        assert argvs == [['rbx', 'build'], ['rbx', 'run', '-s']]
        assert prefix == 'rbx'

    def test_shell_group_keeps_its_own_argv(self):
        argvs, _ = build_command_argvs(['build', '::', 'bash', '-c', 'ls'])
        assert argvs == [['rbx', 'build'], ['bash', '-c', 'ls']]

    def test_placeholder_prefix_follows_the_first_command(self):
        _, prefix = build_command_argvs(['bash', '-c', 'ls', '::', 'build'])
        assert prefix is None

    def test_no_args_still_gives_the_rbx_placeholder(self):
        argvs, prefix = build_command_argvs([])
        assert argvs == []
        assert prefix == 'rbx'
