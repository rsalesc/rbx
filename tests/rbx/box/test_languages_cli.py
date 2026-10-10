"""Tests for `rbx lang` (design 2026-09-20 §3): listing, adding and removing
statement languages across a contest and its problems."""

import os
import pathlib
from unittest import mock

import pytest
import ruyaml
import typer
from typer.testing import CliRunner

from rbx.box import creation, languages_cli, presets, yaml_include
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


@pytest.fixture
def shared_contest(contest: pathlib.Path) -> pathlib.Path:
    """The contest fixture in the #887 layout: everything but `problems` in
    `shared.rbx.yml`, merged by the canonical contest and a warmup variant."""
    head, problems = (contest / 'contest.rbx.yml').read_text().split('\nproblems:\n')
    (contest / 'shared.rbx.yml').write_text(head + '\n')
    (contest / 'contest.rbx.yml').write_text(
        '<<: !include_deep shared.rbx.yml\nproblems:\n' + problems
    )
    (contest / 'contest.warmup.rbx.yml').write_text(
        '<<: !include_deep shared.rbx.yml\nvars:\n  warmup: true\nproblems: []\n'
    )
    contest_utils.clear_all_caches()
    return contest


class TestSharedFragment:
    """#887: languages that reach contest.rbx.yml only via `<<: !include_deep`
    are edited in the fragment, after confirming the blast radius."""

    def _shared(self, contest: pathlib.Path):
        return yaml_include.make_yaml().load((contest / 'shared.rbx.yml').read_text())

    def test_yes_edits_the_fragment_for_every_contest(self, runner, shared_contest):
        canonical = (shared_contest / 'contest.rbx.yml').read_text()

        result = runner.invoke(languages_cli.app, ['add', 'pt', '--yes'])

        assert result.exit_code == 0, result.output
        assert 'contest.warmup.rbx.yml' in result.output
        assert list(self._shared(shared_contest)['languages']) == ['en', 'pt']
        assert self._shared(shared_contest)['titles']['pt'] == 'Novo contest'
        assert (shared_contest / 'contest.rbx.yml').read_text() == canonical
        assert (shared_contest / 'alpha/statement/statement-pt.rbx.tex').exists()

        result = runner.invoke(languages_cli.app, ['rm', 'pt', '-y'])

        assert result.exit_code == 0, result.output
        assert list(self._shared(shared_contest)['languages']) == ['en']
        assert 'pt' not in self._shared(shared_contest)['titles']

    def test_without_a_terminal_refuses_unless_yes(self, runner, shared_contest):
        before = (shared_contest / 'shared.rbx.yml').read_text()

        with mock.patch('sys.stdin.isatty', return_value=False):
            result = runner.invoke(languages_cli.app, ['add', 'pt'])

        assert result.exit_code == 1
        assert '--yes' in result.output
        assert (shared_contest / 'shared.rbx.yml').read_text() == before
        # Refused before any problem was touched either.
        assert not (shared_contest / 'alpha/statement/statement-pt.rbx.tex').exists()

    # The prompt tests call the commands directly: CliRunner swaps stdin for
    # one that is never a terminal.
    def test_declining_the_prompt_changes_nothing(self, shared_contest):
        before = (shared_contest / 'shared.rbx.yml').read_text()

        with (
            mock.patch('sys.stdin.isatty', return_value=True),
            mock.patch('typer.confirm', return_value=False) as confirm,
            pytest.raises(typer.Exit),
        ):
            languages_cli.rm('en')

        confirm.assert_called_once()
        assert (shared_contest / 'shared.rbx.yml').read_text() == before

    def test_accepting_the_prompt_edits_the_fragment(self, shared_contest):
        with (
            mock.patch('sys.stdin.isatty', return_value=True),
            mock.patch('typer.confirm', return_value=True),
        ):
            languages_cli.add('pt')

        assert list(self._shared(shared_contest)['languages']) == ['en', 'pt']

    def test_unshared_fragment_needs_no_confirmation(self, runner, shared_contest):
        (shared_contest / 'contest.warmup.rbx.yml').unlink()

        with mock.patch('sys.stdin.isatty', return_value=False):
            result = runner.invoke(languages_cli.app, ['add', 'pt'])

        assert result.exit_code == 0, result.output
        assert list(self._shared(shared_contest)['languages']) == ['en', 'pt']


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
