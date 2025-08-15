import pathlib
import re
from typing import Optional

from pydantic import BaseModel

from rbx import utils
from rbx.box import git_utils

_RBX_REMOTE_URI = 'https://github.com/rsalesc/rbx'


class PresetFetchInfo(BaseModel):
    # The actual name of this preset.
    name: str

    # The URI to associate with this preset.
    uri: Optional[str] = None

    # The actual URI from where to fetch the repo.
    fetch_uri: Optional[str] = None

    # Inner directory from where to pull the preset.
    inner_dir: str = ''

    # Tool tag.
    tool_tag: Optional[str] = None

    def is_remote(self) -> bool:
        return self.fetch_uri is not None

    def is_local_dir(self) -> bool:
        return bool(self.inner_dir) and not self.is_remote()

    def is_tool(self) -> bool:
        return self.tool_tag is not None


def get_inner_dir_from_tool_preset(tool_preset: str) -> str:
    return f'rbx/resources/presets/{tool_preset}'


def get_remote_uri_from_tool_preset(tool_preset: str) -> str:
    return f'rsalesc/rbx/{get_inner_dir_from_tool_preset(tool_preset)}'


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

    def get_tool_fetch_info(s: str) -> Optional[PresetFetchInfo]:
        pattern = r'[\w\-]+'
        compiled = re.compile(pattern)
        match = compiled.match(s)
        if match is None:
            return None
        tool_tag = git_utils.latest_remote_tag(
            _RBX_REMOTE_URI, before=utils.get_version()
        )
        return PresetFetchInfo(name=s, tool_tag=tool_tag)

    extractors = [
        get_github_fetch_info,
        get_short_github_fetch_info,
        get_local_dir_fetch_info,
        get_tool_fetch_info,
    ]

    for extract in extractors:
        res = extract(uri)
        if res is not None:
            return res

    return None
