"""Tests for `rbx lang` (design 2026-09-20 §3): listing, adding and removing
statement languages across a contest and its problems."""

import os
import pathlib

import pytest
import ruyaml
from typer.testing import CliRunner

from rbx.box import creation, languages_cli, presets
from rbx.box.contest import contest_utils
from rbx.box.presets.fetch import PresetFetchInfo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _load(path: pathlib.Path):
    return ruyaml.YAML().load(path.read_text())


@pytest.fixture
def contest(cleandir: pathlib.Path, testdata_path: pathlib.Path) -> pathlib.Path:
    """A contest created from the multilang preset with only `en`, holding two
    problems that inherit its language list."""
    preset = testdata_path / 'presets' / 'multilang'
    fetch_info = PresetFetchInfo(name='multilang', inner_dir=str(preset))
    root = cleandir / 'ctt'
    template = presets.install_contest(root, fetch_info, languages=['en'])
    presets.generate_lock(root, template=template)

    cwd = os.getcwd()
    os.chdir(root)
    try:
        contest_utils.clear_all_caches()
        for name in ('alpha', 'beta'):
            creation.create(name, path=pathlib.Path(name))
        (root / 'contest.rbx.yml').write_text(
            (root / 'contest.rbx.yml').read_text() + 'problems:\n'
            '  - short_name: "A"\n    path: "alpha"\n'
            '  - short_name: "B"\n    path: "beta"\n'
        )
        contest_utils.clear_all_caches()
        yield root
    finally:
        os.chdir(cwd)
        contest_utils.clear_all_caches()


class TestAdd:
    def test_adds_to_contest_and_every_problem(self, runner, contest):
        result = runner.invoke(languages_cli.app, ['add', 'pt'])

        assert result.exit_code == 0, result.output
        assert list(_load(contest / 'contest.rbx.yml')['languages']) == ['en', 'pt']
        assert _load(contest / 'contest.rbx.yml')['titles']['pt'] == 'Novo contest'
        for name in ('alpha', 'beta'):
            problem = _load(contest / name / 'problem.rbx.yml')
            assert 'languages' not in problem
            assert problem['titles']['pt'] == 'Novo problema'
            assert (contest / name / 'statement/statement-pt.rbx.tex').exists()
            assert (contest / name / 'statement/editorial-pt.rbx.tex').exists()
        assert 'alpha' in result.output and 'statement-pt.rbx.tex' in result.output

    def test_is_idempotent(self, runner, contest):
        runner.invoke(languages_cli.app, ['add', 'pt'])
        (contest / 'alpha/statement/statement-pt.rbx.tex').write_text('edited')

        result = runner.invoke(languages_cli.app, ['add', 'pt'])

        assert result.exit_code == 0, result.output
        assert list(_load(contest / 'contest.rbx.yml')['languages']) == ['en', 'pt']
        assert (contest / 'alpha/statement/statement-pt.rbx.tex').read_text() == (
            'edited'
        )

    def test_unshipped_language_errors_listing_shipped(self, runner, contest):
        result = runner.invoke(languages_cli.app, ['add', 'fr'])

        assert result.exit_code == 1
        assert 'en, pt, es' in result.output
        assert '--from' in result.output
        assert list(_load(contest / 'contest.rbx.yml')['languages']) == ['en']

    def test_from_clones_an_existing_language(self, runner, contest):
        (contest / 'alpha/statement/statement-en.rbx.tex').write_text('alpha en')

        result = runner.invoke(languages_cli.app, ['add', 'fr', '--from', 'en'])

        assert result.exit_code == 0, result.output
        assert (contest / 'alpha/statement/statement-fr.rbx.tex').read_text() == (
            'alpha en'
        )
        assert _load(contest / 'alpha/problem.rbx.yml')['titles']['fr'] == (
            'New problem'
        )
        assert list(_load(contest / 'contest.rbx.yml')['languages']) == ['en', 'fr']

    def test_refuses_inside_a_problem_of_a_contest(self, runner, contest):
        os.chdir(contest / 'alpha')

        result = runner.invoke(languages_cli.app, ['add', 'pt'])

        assert result.exit_code == 1
        assert 'contest root' in result.output
        assert not (contest / 'alpha/statement/statement-pt.rbx.tex').exists()

    def test_standalone_problem(self, runner, cleandir, testdata_path):
        preset = testdata_path / 'presets' / 'multilang'
        fetch_info = PresetFetchInfo(name='multilang', inner_dir=str(preset))
        root = cleandir / 'prob'
        template = presets.install_problem(root, fetch_info, languages=['en'])
        presets.generate_lock(root, template=template)
        os.chdir(root)

        result = runner.invoke(languages_cli.app, ['add', 'es'])

        assert result.exit_code == 0, result.output
        assert list(_load(root / 'problem.rbx.yml')['languages']) == ['en', 'es']
        assert (root / 'statement/statement-es.rbx.tex').exists()

    def test_outside_any_package_errors(self, runner, cleandir):
        result = runner.invoke(languages_cli.app, ['add', 'pt'])

        assert result.exit_code == 1


class TestRemove:
    def test_unlists_and_keeps_files(self, runner, contest):
        runner.invoke(languages_cli.app, ['add', 'pt'])

        result = runner.invoke(languages_cli.app, ['rm', 'pt'])

        assert result.exit_code == 0, result.output
        assert list(_load(contest / 'contest.rbx.yml')['languages']) == ['en']
        assert 'pt' not in _load(contest / 'alpha/problem.rbx.yml')['titles']
        assert (contest / 'alpha/statement/statement-pt.rbx.tex').exists()
        assert 'statement-pt.rbx.tex' in result.output

    def test_delete_files(self, runner, contest):
        runner.invoke(languages_cli.app, ['add', 'pt'])

        result = runner.invoke(languages_cli.app, ['rm', 'pt', '--delete-files'])

        assert result.exit_code == 0, result.output
        assert not (contest / 'alpha/statement/statement-pt.rbx.tex').exists()
        assert not (contest / 'beta/editorial-pt.rbx.tex').exists()


class TestList:
    def test_lists_every_package_language_and_file(self, runner, contest):
        runner.invoke(languages_cli.app, ['add', 'pt'])
        (contest / 'beta/statement/editorial-pt.rbx.tex').unlink()

        result = runner.invoke(languages_cli.app, ['ls'])

        assert result.exit_code == 0, result.output
        assert 'en' in result.output and 'pt' in result.output
        assert 'alpha' in result.output and 'beta' in result.output
        assert 'editorial-pt.rbx.tex' in result.output
        assert 'missing' in result.output
