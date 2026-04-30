"""Tests for contest_package validation helpers."""

import pathlib

import pytest
import typer

from rbx.box.contest import contest_package as cp_module
from rbx.box.contest.contest_package import (
    validate_problem_folders_are_packages,
    validate_problem_folders_exist,
)
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
        assert '- A:' in out
        assert '- C:' in out
        assert '- B:' not in out

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

        assert '- A:' in capsys.readouterr().out


class TestValidateProblemFoldersArePackages:
    def test_folder_with_yaml_does_not_raise(self, tmp_path: pathlib.Path):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        contest = _make_contest(ContestProblem(short_name='A'))

        validate_problem_folders_are_packages(contest, tmp_path)

    def test_folder_without_yaml_exits(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        contest = _make_contest(ContestProblem(short_name='A'))

        with pytest.raises(typer.Exit):
            validate_problem_folders_are_packages(contest, tmp_path)

        assert '- A:' in capsys.readouterr().out

    def test_multiple_folders_without_yaml_listed_together(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        (tmp_path / 'B').mkdir()
        (tmp_path / 'C').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
            ContestProblem(short_name='C'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_are_packages(contest, tmp_path)

        out = capsys.readouterr().out
        assert '- B:' in out
        assert '- C:' in out
        assert '- A:' not in out


class TestFindContestPackageValidation:
    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()
        yield
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()

    def _write_contest(self, root: pathlib.Path, problems: list[str]) -> None:
        problems_yaml = '\n'.join(f'  - short_name: {p}' for p in problems)
        (root / 'contest.rbx.yml').write_text(
            f'name: ctt\nproblems:\n{problems_yaml}\n'
        )

    def test_returns_contest_when_all_problem_folders_valid(
        self, tmp_path: pathlib.Path
    ):
        self._write_contest(tmp_path, ['A', 'B'])
        for short_name in ['A', 'B']:
            (tmp_path / short_name).mkdir()
            (tmp_path / short_name / 'problem.rbx.yml').write_text('name: p\n')

        result = cp_module.find_contest_package(tmp_path)

        assert result is not None
        assert [p.short_name for p in result.problems] == ['A', 'B']

    def test_exits_when_a_problem_folder_is_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        self._write_contest(tmp_path, ['A', 'B'])
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        # No B folder.

        with pytest.raises(typer.Exit):
            cp_module.find_contest_package(tmp_path)

        assert '- B:' in capsys.readouterr().out

    def test_exits_when_problem_folder_lacks_yaml(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        self._write_contest(tmp_path, ['A'])
        (tmp_path / 'A').mkdir()
        # No problem.rbx.yml in A.

        with pytest.raises(typer.Exit):
            cp_module.find_contest_package(tmp_path)

        out = capsys.readouterr().out
        assert '- A:' in out
        assert 'problem.rbx.yml' in out
