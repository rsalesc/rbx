import pathlib
from typing import List, Optional

from pydantic import BaseModel

from rbx.box.presets.schema import TrackedAsset


class SymlinkInfo(BaseModel):
    target: pathlib.Path
    is_broken: bool
    is_outside: bool


class LockedAsset(TrackedAsset):
    hash: Optional[str] = None
    symlink_info: Optional[SymlinkInfo] = None

    def is_symlink(self) -> bool:
        return self.symlink_info is not None or self.symlink

    def is_broken_symlink(self) -> bool:
        return self.symlink_info is not None and self.symlink_info.is_broken

    def was_modified(self, base: 'LockedAsset', follow_symlinks: bool = False) -> bool:
        if self.is_symlink() != base.is_symlink():
            return True
        if self.hash != base.hash and (follow_symlinks or self.symlink_info is None):
            return True
        if self.symlink_info is not None and self.symlink_info.is_broken:
            return True
        if (
            self.symlink_info is not None
            and base.symlink_info is not None
            and self.symlink_info.target != base.symlink_info.target
            and not follow_symlinks
        ):
            return True
        return False

    def __str__(self) -> str:
        if self.symlink_info is not None:
            res = f'{self.path} -> {self.symlink_info.target}'
            if self.symlink_info.is_broken:
                res += ' (broken)'
            if self.symlink_info.is_outside:
                res += ' (outside)'
            return res
        return f'{self.path} ({self.hash})'


class PresetLock(BaseModel):
    name: str

    @property
    def preset_name(self) -> str:
        return self.name

    assets: List[LockedAsset] = []
