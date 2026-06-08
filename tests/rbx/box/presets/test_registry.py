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
