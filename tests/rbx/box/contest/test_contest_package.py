"""Tests for contest_package validation helpers."""

import pathlib

import pytest
import typer

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

    def test_missing_folder_exits_and_names_short_name(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        # B has no folder.
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        captured = capsys.readouterr()
        assert 'B' in captured.out
        assert 'A' not in captured.out.replace('[error]', '').replace('[/error]', '')
