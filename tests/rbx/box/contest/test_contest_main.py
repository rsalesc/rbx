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

    def test_list_in_real_contest_with_siblings_lists_default_and_variants(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text('name: main-c\nproblems: []\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\nproblems: []\n')

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        # The default contest is listed, plus the sibling variant.
        assert 'contest.rbx.yml' in result.output
        assert 'default' in result.output
        assert 'div1' in result.output

    def test_list_real_contest_with_siblings_marks_default_when_no_selection(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text('name: main-c\nproblems: []\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\nproblems: []\n')

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        default_line = next(
            line for line in result.output.splitlines() if 'default' in line
        )
        div1_line = next(line for line in result.output.splitlines() if 'div1' in line)
        assert '*' in default_line
        assert '*' not in div1_line

    def test_list_real_contest_with_siblings_marks_active_variant(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text('name: main-c\nproblems: []\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\nproblems: []\n')

        result = runner.invoke(contest_main.app, ['-C', 'div1', 'list'])

        assert result.exit_code == 0, result.output
        default_line = next(
            line for line in result.output.splitlines() if 'default' in line
        )
        div1_line = next(line for line in result.output.splitlines() if 'div1' in line)
        assert '*' not in default_line
        assert '*' in div1_line


class TestContestAddVariant:
    def test_invalid_id_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', 'bad id'])

        assert result.exit_code != 0, result.output
        assert not (tmp_path / 'contest.bad id.rbx.yml').exists()

    def test_invalid_id_leading_digit_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', '1abc'])

        assert result.exit_code != 0, result.output

    def test_not_in_contest_dir_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', 'div3'])

        assert result.exit_code != 0, result.output

    def test_existing_variant_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1')
        original = (tmp_path / 'contest.div1.rbx.yml').read_text()

        result = runner.invoke(contest_main.app, ['add_variant', 'div1'])

        assert result.exit_code != 0, result.output
        assert (tmp_path / 'contest.div1.rbx.yml').read_text() == original
