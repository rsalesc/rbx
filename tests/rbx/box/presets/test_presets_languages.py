"""Choosing which of a preset's languages a new package keeps (design
2026-09-20 §3): `pick_languages` and the pruning `install_problem` /
`install_contest` do with its answer."""

import pathlib
from unittest import mock

import pytest
import ruyaml
import typer

from rbx.box import presets, yaml_include


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

    def test_unknown_language_fails_before_copying_anything(self, installed):
        with pytest.raises(typer.Exit):
            presets.install_contest(installed, languages=['fr'])

        assert not (installed / 'contest.rbx.yml').exists()
        assert not (installed / 'statements').exists()


def _share_contest_template(package_dir: pathlib.Path) -> pathlib.Path:
    """Turn the installed preset's contest template into the #887 layout: the
    whole config in `shared.rbx.yml`, merged by the canonical contest and by a
    warmup variant."""
    template = package_dir / '.local.rbx' / 'contest'
    (template / 'shared.rbx.yml').write_text((template / 'contest.rbx.yml').read_text())
    (template / 'contest.rbx.yml').write_text(
        '<<: !include_deep shared.rbx.yml\nproblems: []\n'
    )
    (template / 'contest.warmup.rbx.yml').write_text(
        '<<: !include_deep shared.rbx.yml\nvars:\n  warmup: true\nproblems: []\n'
    )
    return template


class TestInstallSharedFragment:
    """#887: a contest whose languages reach it only via `<<: !include_deep`."""

    def _shared(self, package_dir: pathlib.Path):
        return yaml_include.make_yaml().load(
            (package_dir / 'shared.rbx.yml').read_text()
        )

    def test_explicit_languages_prune_the_fragment(self, installed):
        _share_contest_template(installed)

        presets.install_contest(installed, languages=['pt', 'en'])

        shared = self._shared(installed)
        assert list(shared['languages']) == ['pt', 'en']
        assert dict(shared['titles']) == {'en': 'New contest', 'pt': 'Novo contest'}
        canonical = (installed / 'contest.rbx.yml').read_text()
        assert '<<: !include_deep shared.rbx.yml' in canonical
        assert 'languages' not in canonical

    def test_without_a_terminal_keeps_every_language(self, installed):
        _share_contest_template(installed)

        with mock.patch('sys.stdin.isatty', return_value=False):
            presets.install_contest(installed)

        assert list(self._shared(installed)['languages']) == ['en', 'pt', 'es']

    def test_interactive_pick_prunes_the_fragment_without_asking_more(self, installed):
        _share_contest_template(installed)

        with (
            mock.patch('sys.stdin.isatty', return_value=True),
            mock.patch('questionary.checkbox') as checkbox,
            mock.patch('typer.confirm') as confirm,
        ):
            checkbox.return_value.ask.return_value = ['es']
            presets.install_contest(installed)

        confirm.assert_not_called()
        assert list(self._shared(installed)['languages']) == ['es']
