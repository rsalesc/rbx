import pytest
from pydantic import ValidationError

from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset


class TestRegistrySchema:
    def test_entry_requires_name_and_uri(self):
        e = RegistryPreset(name='default', uri='default')
        assert e.name == 'default'
        assert e.uri == 'default'
        assert e.description == ''

    def test_registry_defaults_to_empty(self):
        assert PresetRegistry().presets == []

    def test_name_pattern_enforced(self):
        with pytest.raises(ValidationError):
            RegistryPreset(name='a', uri='x')  # too short for NameField


class TestBuiltinRegistry:
    def test_builtin_registry_loads_and_has_default(self):
        from rbx.box.presets import registry

        reg = registry.get_builtin_registry()
        names = {p.name for p in reg.presets}
        assert 'default' in names

    def test_builtin_default_entry_has_description(self):
        from rbx.box.presets import registry

        reg = registry.get_builtin_registry()
        default = next(p for p in reg.presets if p.name == 'default')
        assert default.uri == 'default'
        assert default.description.strip() != ''


class TestRegistryMergeAndMutate:
    def test_user_registry_path_under_app_dir(self, monkeypatch, tmp_path):
        from rbx import utils
        from rbx.box.presets import registry

        monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
        assert registry.user_registry_path() == tmp_path / 'presets' / 'registry.yml'

    def test_user_registry_empty_when_missing(self, monkeypatch, tmp_path):
        from rbx import utils
        from rbx.box.presets import registry

        monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
        assert registry.get_user_registry().presets == []

    def test_merge_unions_builtin_and_user(self, monkeypatch, tmp_path):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset

        monkeypatch.setattr(
            registry,
            'get_user_registry',
            lambda: registry.PresetRegistry(
                presets=[RegistryPreset(name='mine', uri='me/repo', description='d')]
            ),
        )
        merged = registry.get_merged_registry()
        names = [p.name for p in merged.presets]
        assert 'default' in names and 'mine' in names
        # built-ins first
        assert names.index('default') < names.index('mine')

    def test_user_entry_wins_on_name_collision(self, monkeypatch):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset

        monkeypatch.setattr(
            registry,
            'get_user_registry',
            lambda: registry.PresetRegistry(
                presets=[
                    RegistryPreset(name='default', uri='custom/uri', description='x')
                ]
            ),
        )
        merged = registry.get_merged_registry()
        default = next(p for p in merged.presets if p.name == 'default')
        assert default.uri == 'custom/uri'

    def test_add_and_remove_user_entry(self, monkeypatch, tmp_path):
        from rbx import utils
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset

        monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
        registry.add_to_user_registry(
            RegistryPreset(name='foo', uri='o/r', description='bar')
        )
        assert any(p.name == 'foo' for p in registry.get_user_registry().presets)
        removed = registry.remove_from_user_registry('foo')
        assert removed is True
        assert not any(p.name == 'foo' for p in registry.get_user_registry().presets)

    def test_add_replaces_existing_user_entry(self, monkeypatch, tmp_path):
        from rbx import utils
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import RegistryPreset

        monkeypatch.setattr(utils, 'get_app_path', lambda: tmp_path)
        registry.add_to_user_registry(
            RegistryPreset(name='foo', uri='a', description='1')
        )
        registry.add_to_user_registry(
            RegistryPreset(name='foo', uri='b', description='2')
        )
        entries = [p for p in registry.get_user_registry().presets if p.name == 'foo']
        assert len(entries) == 1
        assert entries[0].uri == 'b'


class TestPicker:
    def test_pick_returns_selected_entry(self, monkeypatch):
        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset

        entry = RegistryPreset(name='default', uri='default', description='d')
        monkeypatch.setattr(
            registry,
            'get_merged_registry',
            lambda: PresetRegistry(presets=[entry]),
        )

        class FakeSelect:
            def ask(self_inner):
                return 'default'

        monkeypatch.setattr(
            registry.questionary, 'select', lambda *a, **k: FakeSelect()
        )
        chosen = registry.pick_preset()
        assert chosen is entry

    def test_pick_raises_exit_on_cancel(self, monkeypatch):
        import click

        from rbx.box.presets import registry
        from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset

        monkeypatch.setattr(
            registry,
            'get_merged_registry',
            lambda: PresetRegistry(
                presets=[RegistryPreset(name='default', uri='default')]
            ),
        )

        class FakeSelect:
            def ask(self_inner):
                return None  # user hit Ctrl-C

        monkeypatch.setattr(
            registry.questionary, 'select', lambda *a, **k: FakeSelect()
        )
        with pytest.raises(click.exceptions.Exit):
            registry.pick_preset()
