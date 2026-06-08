from typing import List

from pydantic import BaseModel

from rbx.box.presets.schema import NameField


class RegistryPreset(BaseModel):
    # Logical name of the preset (must be unique within the registry).
    name: str = NameField()

    # URI used to fetch the preset. Uses the same grammar as Preset.uri and is
    # resolved by get_preset_fetch_info (owner/repo, @gh/..., full URL, a local
    # path, or a bundled tool-preset name such as 'default').
    uri: str

    # Denormalized copy of the preset's description, captured at registration
    # time so the picker can display it without resolving the preset.
    description: str = ''


class PresetRegistry(BaseModel):
    presets: List[RegistryPreset] = []
