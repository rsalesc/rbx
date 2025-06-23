from typing import List

from pydantic import BaseModel

from rbx.box.presets.schema import TrackedAsset


class LockedAsset(TrackedAsset):
    hash: str


class PresetLock(BaseModel):
    name: str

    @property
    def preset_name(self) -> str:
        return self.name

    assets: List[LockedAsset] = []
