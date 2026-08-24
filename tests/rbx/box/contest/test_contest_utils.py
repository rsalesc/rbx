"""Tests for contest_utils: command chaining, and selector wiring for `rbx on`."""

import pathlib
from unittest.mock import patch

import pytest

from rbx.box.contest.contest_utils import (
    EmptyCommandError,
    build_command_argvs,
    get_problems_of_interest,
    split_commands,
)
from rbx.box.contest.problem_selector import ProblemSelectorError
from rbx.box.contest.schema import Contest, ContestProblem

CONTEST = Contest(
    name='Test',
    problems=[
        ContestProblem(short_name='A', aliases=['apple'], path=pathlib.Path('probs/a')),
        ContestProblem(short_name='B'),
        ContestProblem(short_name='C', aliases=['choco', 'cake']),
    ],
)


@pytest.fixture
def contest(tmp_path):
    """A contest on disk, so problem names are read from real package files."""
    (tmp_path / 'probs' / 'a').mkdir(parents=True)
    (tmp_path / 'probs' / 'a' / 'problem.rbx.yml').write_text('name: knapsack\n')
    with (
        patch(
            'rbx.box.contest.contest_utils.contest_package.find_contest_package_or_die',
            return_value=CONTEST,
        ),
        patch(
            'rbx.box.contest.contest_utils.contest_package.find_contest',
            return_value=tmp_path,
        ),
    ):
        yield


def _short_names(selector: str):
    return [p.short_name for p in get_problems_of_interest(selector)]


class TestGetProblemsOfInterest:
    def test_short_name(self, contest):
        assert _short_names('A') == ['A']

    def test_alias(self, contest):
        assert _short_names('choco') == ['C']

    def test_problem_name_read_from_the_problem_package(self, contest):
        assert _short_names('knapsack') == ['A']

    def test_folder_basename(self, contest):
        assert _short_names('a') == ['A']

    def test_comma_list(self, contest):
        assert _short_names('apple,C') == ['A', 'C']

    def test_range(self, contest):
        assert _short_names('A..B') == ['A', 'B']

    def test_wildcard(self, contest):
        assert _short_names('*') == ['A', 'B', 'C']

    def test_exclusion(self, contest):
        assert _short_names('*,!B') == ['A', 'C']

    def test_unmatched_selector_raises(self, contest):
        with pytest.raises(ProblemSelectorError):
            get_problems_of_interest('nope')

    def test_a_problem_without_a_package_file_is_still_selectable(self, contest):
        # B has no problem.rbx.yml on disk; the name tier just finds nothing.
        assert _short_names('B') == ['B']


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
