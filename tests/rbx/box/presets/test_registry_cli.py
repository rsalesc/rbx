import pytest
from typer.testing import CliRunner

from rbx.box import presets
from rbx.box.presets import registry
from rbx.box.presets.registry_schema import RegistryPreset

runner = CliRunner()


@pytest.fixture
def isolated_app_dir(monkeypatch, tmp_path):
    from rbx import utils

    monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
    return tmp_path


class TestRegistryLs:
    def test_ls_lists_default(self, isolated_app_dir):
        result = runner.invoke(presets.app, ['registry', 'ls'])
        assert result.exit_code == 0
        assert 'default' in result.stdout

    def test_ls_marks_builtin_and_user_sources(self, isolated_app_dir):
        registry.add_to_user_registry(
            RegistryPreset(name='myp', uri='o/r', description='d')
        )
        result = runner.invoke(presets.app, ['registry', 'ls'])
        assert result.exit_code == 0
        assert 'built-in' in result.stdout
        assert 'user' in result.stdout


class TestRegistryAdd:
    def test_add_writes_user_entry(self, isolated_app_dir, monkeypatch):
        # Stub the metadata peek so no network/clone happens.
        monkeypatch.setattr(
            presets,
            '_peek_preset_metadata',
            lambda uri, local=False: RegistryPreset(
                name='myp', uri=uri, description='desc'
            ),
        )
        result = runner.invoke(presets.app, ['registry', 'add', 'owner/repo'])
        assert result.exit_code == 0, result.stdout
        names = {p.name for p in registry.get_user_registry().presets}
        assert 'myp' in names

    def test_add_default_reads_bundled_without_network(self, isolated_app_dir):
        # `default` is bundled with rbx, so the metadata peek reads it directly
        # (no network, no install-time prompts). Exercises the real peek path.
        result = runner.invoke(presets.app, ['registry', 'add', 'default'])
        assert result.exit_code == 0, result.stdout
        entries = {p.name: p for p in registry.get_user_registry().presets}
        assert 'default' in entries
        assert entries['default'].uri == 'default'
        assert entries['default'].description.strip() != ''


class TestRegistryRm:
    def test_rm_removes_user_entry(self, isolated_app_dir):
        registry.add_to_user_registry(
            RegistryPreset(name='myp', uri='o/r', description='d')
        )
        result = runner.invoke(presets.app, ['registry', 'rm', 'myp'])
        assert result.exit_code == 0
        names = {p.name for p in registry.get_user_registry().presets}
        assert 'myp' not in names

    def test_rm_unknown_errors(self, isolated_app_dir):
        result = runner.invoke(presets.app, ['registry', 'rm', 'nope'])
        assert result.exit_code != 0
        assert 'not in the user registry' in result.stdout

    def test_rm_builtin_errors_with_builtin_message(self, isolated_app_dir):
        result = runner.invoke(presets.app, ['registry', 'rm', 'default'])
        assert result.exit_code != 0
        assert 'built-in' in result.stdout


class TestOfferToRegister:
    def test_offers_and_registers_when_confirmed(
        self, isolated_app_dir, tmp_path, monkeypatch
    ):
        from types import SimpleNamespace

        monkeypatch.setattr(presets.preset_registry, 'is_interactive', lambda: True)
        # Confirm "yes".
        monkeypatch.setattr(
            presets.questionary,
            'confirm',
            lambda *a, **k: SimpleNamespace(ask=lambda: True),
        )
        # The just-installed preset is read locally (no re-fetch).
        monkeypatch.setattr(presets, 'find_local_preset', lambda d: d)
        monkeypatch.setattr(
            presets,
            'get_preset_yaml',
            lambda d: SimpleNamespace(name='newp', description='d'),
        )

        fetch_info = SimpleNamespace(uri='o/r')
        presets.maybe_offer_to_register(fetch_info, tmp_path)
        entries = {
            p.name: p for p in presets.preset_registry.get_user_registry().presets
        }
        assert 'newp' in entries
        assert entries['newp'].uri == 'o/r'
        assert entries['newp'].description == 'd'

    def test_skips_when_already_registered(
        self, isolated_app_dir, tmp_path, monkeypatch
    ):
        from types import SimpleNamespace

        presets.preset_registry.add_to_user_registry(
            RegistryPreset(name='newp', uri='o/r', description='d')
        )
        monkeypatch.setattr(presets.preset_registry, 'is_interactive', lambda: True)

        called = {'confirm': False}

        def _confirm(*a, **k):
            called['confirm'] = True
            return SimpleNamespace(ask=lambda: True)

        monkeypatch.setattr(presets.questionary, 'confirm', _confirm)
        presets.maybe_offer_to_register(SimpleNamespace(uri='o/r'), tmp_path)
        assert called['confirm'] is False  # already known -> no prompt

    def test_skips_when_non_interactive(self, isolated_app_dir, tmp_path, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(presets.preset_registry, 'is_interactive', lambda: False)
        presets.maybe_offer_to_register(SimpleNamespace(uri='o/r'), tmp_path)
        assert presets.preset_registry.get_user_registry().presets == []
