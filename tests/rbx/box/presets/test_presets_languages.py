"""Choosing which of a preset's languages a new package keeps (design
2026-09-20 §3): `pick_languages` and the pruning `install_problem` /
`install_contest` do with its answer."""

import pathlib
from unittest import mock

import pytest
import ruyaml
import typer

from rbx.box import presets


@pytest.fixture
def multilang_preset(testdata_path: pathlib.Path) -> pathlib.Path:
    return testdata_path / 'presets' / 'multilang'


@pytest.fixture
def installed(tmp_path: pathlib.Path, multilang_preset: pathlib.Path) -> pathlib.Path:
    package_dir = tmp_path / 'package'
    package_dir.mkdir()
    presets.install_preset_from_dir(multilang_preset, package_dir / '.local.rbx')
    return package_dir


def _template(package_dir: pathlib.Path, is_contest: bool):
    return presets.get_active_template(package_dir, is_contest=is_contest)


def _load(path: pathlib.Path):
    return ruyaml.YAML().load(path.read_text())


class TestPickLanguages:
    def test_explicit_flag_wins_without_prompting(self, installed):
        with mock.patch('questionary.checkbox') as checkbox:
            assert presets.pick_languages(
                _template(installed, False), is_contest=False, languages=['pt']
            ) == ['pt']
        checkbox.assert_not_called()

    def test_explicit_unknown_language_errors(self, installed):
        with pytest.raises(typer.Exit):
            presets.pick_languages(
                _template(installed, False), is_contest=False, languages=['fr']
            )

    def test_single_language_template_never_prompts(self, tmp_path, testdata_path):
        package_dir = tmp_path / 'single'
        package_dir.mkdir()
        presets.install_preset_from_dir(
            testdata_path / 'presets' / 'simple-preset', package_dir / '.local.rbx'
        )
        with mock.patch('sys.stdin.isatty', return_value=True):
            with mock.patch('questionary.checkbox') as checkbox:
                assert (
                    presets.pick_languages(
                        _template(package_dir, False), is_contest=False, languages=None
                    )
                    is None
                )
        checkbox.assert_not_called()

    def test_non_tty_keeps_every_language(self, installed):
        with mock.patch('sys.stdin.isatty', return_value=False):
            assert (
                presets.pick_languages(
                    _template(installed, False), is_contest=False, languages=None
                )
                is None
            )

    def test_tty_prompts_with_every_language_checked(self, installed):
        prompt = mock.MagicMock()
        prompt.ask.return_value = ['en', 'es']
        with mock.patch('sys.stdin.isatty', return_value=True):
            with mock.patch('questionary.checkbox', return_value=prompt) as checkbox:
                answer = presets.pick_languages(
                    _template(installed, True), is_contest=True, languages=None
                )
        assert answer == ['en', 'es']
        choices = checkbox.call_args.kwargs['choices']
        assert [c.value for c in choices] == ['en', 'pt', 'es']
        assert all(c.checked for c in choices)

    def test_empty_or_cancelled_answer_exits(self, installed):
        prompt = mock.MagicMock()
        prompt.ask.return_value = []
        with mock.patch('sys.stdin.isatty', return_value=True):
            with mock.patch('questionary.checkbox', return_value=prompt):
                with pytest.raises(typer.Exit):
                    presets.pick_languages(
                        _template(installed, False), is_contest=False, languages=None
                    )


class TestInstallPrunes:
    def test_install_problem_keeps_only_selected(self, installed):
        presets.install_problem(installed, languages=['pt'])

        data = _load(installed / 'problem.rbx.yml')
        assert list(data['languages']) == ['pt']
        assert dict(data['titles']) == {'pt': 'Novo problema'}
        assert (installed / 'statement/statement-pt.rbx.tex').exists()
        assert not (installed / 'statement/statement-en.rbx.tex').exists()
        assert not (installed / 'statement/editorial-es.rbx.tex').exists()

    def test_install_problem_inheriting_writes_no_list(self, installed):
        presets.install_problem(installed, languages=['en'], inherit_languages=True)

        data = _load(installed / 'problem.rbx.yml')
        assert 'languages' not in data
        assert not (installed / 'statement/statement-pt.rbx.tex').exists()

    def test_install_contest_keeps_only_selected(self, installed):
        presets.install_contest(installed, languages=['en', 'es'])

        data = _load(installed / 'contest.rbx.yml')
        assert list(data['languages']) == ['en', 'es']
        assert dict(data['titles']) == {'en': 'New contest', 'es': 'Nuevo contest'}

    def test_install_without_selection_keeps_everything(self, installed):
        with mock.patch('sys.stdin.isatty', return_value=False):
            presets.install_problem(installed)

        data = _load(installed / 'problem.rbx.yml')
        assert list(data['languages']) == ['en', 'pt', 'es']
        assert (installed / 'statement/statement-es.rbx.tex').exists()
