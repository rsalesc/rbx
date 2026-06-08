import pathlib
from typing import Optional

import questionary
import ruyaml
import typer

from rbx import console, utils
from rbx.box.presets.registry_schema import PresetRegistry, RegistryPreset
from rbx.box.yaml_validation import load_yaml_model
from rbx.config import get_default_app_path


def builtin_registry_path() -> pathlib.Path:
    return get_default_app_path() / 'presets' / 'registry.yml'


def user_registry_path() -> pathlib.Path:
    return utils.get_app_path() / 'presets' / 'registry.yml'


def _load_registry_file(path: pathlib.Path) -> PresetRegistry:
    if not path.is_file():
        return PresetRegistry()
    # A hand-edited file that is empty or contains only the schema comment
    # parses to None; treat it as an empty registry rather than crashing.
    if ruyaml.YAML(typ='rt').load(path.read_text()) is None:
        return PresetRegistry()
    return load_yaml_model(path, PresetRegistry)


def get_builtin_registry() -> PresetRegistry:
    return _load_registry_file(builtin_registry_path())


def get_user_registry() -> PresetRegistry:
    return _load_registry_file(user_registry_path())


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
    # Use the codebase's standard model->YAML helper so the user file is written
    # the same way as every other rbx config (and gets the
    # `# yaml-language-server` schema header for free). The user registry is
    # machine-managed (add/rm only), so a full rewrite without comment
    # preservation is the right behavior here.
    utils.create_and_write(user_registry_path(), utils.model_to_yaml(reg))


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


def pick_preset() -> RegistryPreset:
    reg = get_merged_registry()
    if not reg.presets:
        console.console.print('[error]No presets available in the registry.[/error]')
        raise typer.Exit(1)

    by_name = {p.name: p for p in reg.presets}
    choices = [
        questionary.Choice(
            title=f'{p.name} — {p.description}' if p.description else p.name,
            value=p.name,
        )
        for p in reg.presets
    ]
    default_value = 'default' if 'default' in by_name else reg.presets[0].name
    answer = questionary.select(
        'Which preset do you want to use?',
        choices=choices,
        default=default_value,
    ).ask()
    if answer is None:
        raise typer.Exit(1)
    return by_name[answer]
