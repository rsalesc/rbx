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
