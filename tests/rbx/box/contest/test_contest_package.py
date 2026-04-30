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

    def test_multiple_missing_folders_listed_together(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'B').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
            ContestProblem(short_name='C'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        out = capsys.readouterr().out
        assert 'A' in out
        assert 'C' in out

    def test_custom_relative_path_resolved_against_contest_root(
        self, tmp_path: pathlib.Path
    ):
        (tmp_path / 'probs' / 'alpha').mkdir(parents=True)
        contest = _make_contest(
            ContestProblem(short_name='A', path=pathlib.Path('probs') / 'alpha'),
        )

        validate_problem_folders_exist(contest, tmp_path)

    def test_absolute_path_used_as_is(self, tmp_path: pathlib.Path):
        problem_dir = tmp_path / 'somewhere' / 'else'
        problem_dir.mkdir(parents=True)
        contest = _make_contest(
            ContestProblem(short_name='A', path=problem_dir),
        )

        # Passing a different `contest_root` must not affect validation
        # because the path is absolute.
        other_root = tmp_path / 'unrelated'
        other_root.mkdir()
        validate_problem_folders_exist(contest, other_root)

    def test_path_pointing_to_file_is_reported_as_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        # A is a file, not a directory.
        (tmp_path / 'A').write_text('not a folder')
        contest = _make_contest(ContestProblem(short_name='A'))

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        assert 'A' in capsys.readouterr().out
