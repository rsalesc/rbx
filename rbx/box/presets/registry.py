import pathlib
from typing import Optional

import ruyaml

from rbx import utils
from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset
from rbx.box.yaml_validation import load_yaml_model
from rbx.config import get_default_app_path


def builtin_registry_path() -> pathlib.Path:
    return get_default_app_path() / 'presets' / 'registry.yml'


def user_registry_path() -> pathlib.Path:
    return utils.get_app_path() / 'presets' / 'registry.yml'


def get_builtin_registry() -> PresetRegistry:
    path = builtin_registry_path()
    if not path.is_file():
        return PresetRegistry()
    return load_yaml_model(path, PresetRegistry)


def get_user_registry() -> PresetRegistry:
    path = user_registry_path()
    if not path.is_file():
        return PresetRegistry()
    return load_yaml_model(path, PresetRegistry)


def get_merged_registry() -> PresetRegistry:
    builtin = get_builtin_registry()
    user = get_user_registry()
    user_by_name = {p.name: p for p in user.presets}

    merged = []
    seen = set()
    # Built-ins first; a user entry with the same name overrides it.
    for p in builtin.presets:
        merged.append(user_by_name.get(p.name, p))
        seen.add(p.name)
    # Then user-only entries, in their declared order.
    for p in user.presets:
        if p.name not in seen:
            merged.append(p)
            seen.add(p.name)
    return PresetRegistry(presets=merged)


def _save_user_registry(reg: PresetRegistry) -> None:
    path = user_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = ruyaml.YAML(typ='rt')
    with path.open('w') as f:
        yaml.dump(reg.model_dump(mode='python'), f)


def add_to_user_registry(entry: RegistryPreset) -> None:
    reg = get_user_registry()
    reg.presets = [p for p in reg.presets if p.name != entry.name]
    reg.presets.append(entry)
    _save_user_registry(reg)


def remove_from_user_registry(name: str) -> bool:
    reg = get_user_registry()
    before = len(reg.presets)
    reg.presets = [p for p in reg.presets if p.name != name]
    if len(reg.presets) == before:
        return False
    _save_user_registry(reg)
    return True


def find_in_registry(uri_or_name: str) -> Optional[RegistryPreset]:
    for p in get_merged_registry().presets:
        if p.name == uri_or_name or p.uri == uri_or_name:
            return p
    return None
