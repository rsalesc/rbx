import pathlib
import re
from typing import Optional

from pydantic import BaseModel


class PresetFetchInfo(BaseModel):
    # The actual name of this preset.
    name: str

    # The URI to associate with this preset.
    uri: Optional[str] = None

    # The actual URI from where to fetch the repo.
    fetch_uri: Optional[str] = None

    # Inner directory from where to pull the preset.
    inner_dir: str = ''

    def is_remote(self) -> bool:
        return self.fetch_uri is not None

    def is_local_dir(self) -> bool:
        return bool(self.inner_dir) and not self.is_remote()


def get_preset_fetch_info(uri: Optional[str]) -> Optional[PresetFetchInfo]:
    if uri is None:
        return None

    def get_github_fetch_info(s: str) -> Optional[PresetFetchInfo]:
        pattern = r'(https:\/\/(?:[\w\-]+\.)?github\.com\/([\w\-]+\/[\w\.\-]+))(?:\.git)?(?:\/(.*))?'
        compiled = re.compile(pattern)
        match = compiled.match(s)
        if match is None:
            return None
        return PresetFetchInfo(
            name=match.group(2),
            uri=match.group(0),
            fetch_uri=match.group(1),
            inner_dir=match.group(3) or '',
        )

    def get_short_github_fetch_info(s: str) -> Optional[PresetFetchInfo]:
        pattern = r'(?:\@gh/)?([\w\-]+\/[\w\.\-]+)(?:\/(.*))?'
        compiled = re.compile(pattern)
        match = compiled.match(s)
        if match is None:
            return None
        return PresetFetchInfo(
            name=match.group(1),
            uri=match.group(0),
            fetch_uri=f'https://github.com/{match.group(1)}',
            inner_dir=match.group(2) or '',
        )

    def get_local_dir_fetch_info(s: str) -> Optional[PresetFetchInfo]:
        try:
            path = pathlib.Path(s)
            if not path.exists():
                return None
        except Exception:
            return None
        return PresetFetchInfo(name=path.name, inner_dir=str(path))

    def get_local_fetch_info(s: str) -> Optional[PresetFetchInfo]:
        pattern = r'[\w\-]+'
        compiled = re.compile(pattern)
        match = compiled.match(s)
        if match is None:
            return None
        return PresetFetchInfo(name=s)

    extractors = [
        get_github_fetch_info,
        get_short_github_fetch_info,
        get_local_dir_fetch_info,
        get_local_fetch_info,
    ]

    for extract in extractors:
        res = extract(uri)
        if res is not None:
            return res

    return None
