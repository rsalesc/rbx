"""Tests for contest_package validation helpers."""

import pathlib

from rbx.box.contest.contest_package import validate_problem_folders_exist
from rbx.box.contest.schema import Contest, ContestProblem


def _make_contest(*problems: ContestProblem) -> Contest:
    return Contest(name='ctt', problems=list(problems))


class TestValidateProblemFoldersExist:
    def test_all_folders_exist_does_not_raise(self, tmp_path: pathlib.Path):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'B').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
        )

        validate_problem_folders_exist(contest, tmp_path)
