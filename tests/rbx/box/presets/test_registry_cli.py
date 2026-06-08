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
