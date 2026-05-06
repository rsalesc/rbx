"""Tests for `rbx contest` Typer commands."""

import pathlib

import pytest
from typer.testing import CliRunner

from rbx.box.contest import main as contest_main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_single_contest(root: pathlib.Path) -> None:
    (root / 'contest.rbx.yml').write_text('name: ctt\nproblems: []\n')


def _write_dispatcher(root: pathlib.Path, *variant_ids: str) -> None:
    (root / 'contest.rbx.yml').write_text('use_variants: true\n')
    for vid in variant_ids:
        (root / f'contest.{vid}.rbx.yml').write_text(f'name: ctt-{vid}\nproblems: []\n')


class TestContestList:
    def test_list_in_single_contest_dir(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_single_contest(tmp_path)

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        assert 'contest.rbx.yml' in result.output
        assert 'single' in result.output

    def test_list_in_dispatcher_dir(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1', 'div2')

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        assert 'div1' in result.output
        assert 'div2' in result.output

    def test_list_marks_active_selection_via_flag(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1', 'div2')

        result = runner.invoke(contest_main.app, ['-C', 'div1', 'list'])

        assert result.exit_code == 0, result.output
        assert 'div1' in result.output
        assert 'div2' in result.output
        # 'div1' line should have a marker; 'div2' line should not.
        div1_line = next(line for line in result.output.splitlines() if 'div1' in line)
        div2_line = next(line for line in result.output.splitlines() if 'div2' in line)
        assert '*' in div1_line
        assert '*' not in div2_line

    def test_list_marks_active_selection_via_env(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1', 'div2')
        monkeypatch.setenv('RBX_CONTEST', 'div2')

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        div1_line = next(line for line in result.output.splitlines() if 'div1' in line)
        div2_line = next(line for line in result.output.splitlines() if 'div2' in line)
        assert '*' in div2_line
        assert '*' not in div1_line

    def test_list_no_contest_dir_warns(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        assert 'No contests found' in result.output
