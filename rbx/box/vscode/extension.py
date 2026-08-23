"""Where the editor extension lives, and whether the installed one is current.

The CLI ships the extension as a `.vsix` under `rbx/resources/vscode/`, so it
always knows which extension it wants the user to have. Inside an integrated
terminal it can also see which one they actually have, by reading the editor's
own `extensions.json`.
"""

import dataclasses
import importlib.resources
import pathlib
import re
from typing import Optional

from rbx import utils

EXTENSION_ID = 'rsalesc.rbx-vscode'

# vsce names its output `<name>-<version>.vsix`, which is the only place the
# bundled version is recorded -- no sidecar file to drift from the artifact.
_VSIX_NAME = re.compile(r'^rbx-vscode-(?P<version>.+)\.vsix$')


@dataclasses.dataclass(frozen=True)
class BundledVsix:
    path: pathlib.Path
    version: str


def vsix_dir() -> pathlib.Path:
    # Not `config.get_resources_dir`: that raises when the directory is absent,
    # and an absent vsix is a normal state in a checkout that never built one.
    return pathlib.Path(str(importlib.resources.files('rbx'))) / 'resources' / 'vscode'


def bundled_vsix(directory: Optional[pathlib.Path] = None) -> Optional[BundledVsix]:
    directory = directory if directory is not None else vsix_dir()
    if not directory.is_dir():
        return None

    candidates = []
    for entry in directory.glob('*.vsix'):
        matched = _VSIX_NAME.match(entry.name)
        if matched is None:
            continue
        version = matched.group('version')
        if not utils.is_valid_semver(version):
            continue
        candidates.append(BundledVsix(path=entry, version=version))

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: utils.get_semver(candidate.version))
