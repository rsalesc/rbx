"""Where the editor extension lives, and whether the installed one is current.

The CLI ships the extension as a `.vsix` under `rbx/resources/vscode/`, so it
always knows which extension it wants the user to have. Inside an integrated
terminal it can also see which one they actually have, by reading the editor's
own `extensions.json`.
"""

import dataclasses
import importlib.resources
import json
import os
import pathlib
import re
from typing import Mapping, Optional, Tuple

from rbx import console, utils

EXTENSION_ID = 'rsalesc.rbx-vscode'

# vsce names its output `<name>-<version>.vsix`, which is the only place the
# bundled version is recorded -- no sidecar file to drift from the artifact.
_VSIX_NAME = re.compile(r'^rbx-vscode-(?P<version>.+)\.vsix$')


@dataclasses.dataclass(frozen=True)
class BundledVsix:
    path: pathlib.Path
    version: str


@dataclasses.dataclass(frozen=True)
class Editor:
    key: str
    label: str
    binary: str
    # Substring looked for in the running app's path. Checked in EDITORS order,
    # so the forks must come before plain 'code' -- their paths contain it too.
    marker: str
    # Home directories, most specific first. A remote (SSH, devcontainer) keeps
    # its extensions under the *-server variant.
    homes: Tuple[str, ...]


EDITORS: Tuple[Editor, ...] = (
    Editor('cursor', 'Cursor', 'cursor', 'cursor', ('.cursor-server', '.cursor')),
    Editor(
        'windsurf',
        'Windsurf',
        'windsurf',
        'windsurf',
        ('.windsurf-server', '.windsurf'),
    ),
    Editor('codium', 'VSCodium', 'codium', 'codium', ('.vscode-oss',)),
    Editor(
        'code-insiders',
        'VS Code Insiders',
        'code-insiders',
        'code - insiders',
        ('.vscode-server-insiders', '.vscode-insiders'),
    ),
    Editor('code', 'VS Code', 'code', 'code', ('.vscode-server', '.vscode')),
)


def editor_by_key(key: str) -> Optional[Editor]:
    for editor in EDITORS:
        if editor.key == key:
            return editor
    return None


def detect_editor(env: Mapping[str, str]) -> Optional[Editor]:
    """Which editor's integrated terminal we are running in, if any.

    `TERM_PROGRAM=vscode` is set by VS Code *and every fork*, so it only says we
    are in an integrated terminal. The app path is what tells them apart.
    """
    if env.get('TERM_PROGRAM') != 'vscode':
        return None
    app_path = (
        env.get('VSCODE_GIT_ASKPASS_NODE') or env.get('VSCODE_GIT_ASKPASS_MAIN') or ''
    ).lower()
    for editor in EDITORS:
        if editor.marker in app_path:
            return editor
    # An integrated terminal that told us nothing else is VS Code.
    return editor_by_key('code')


def editor_home(
    editor: Editor, home: Optional[pathlib.Path] = None
) -> Optional[pathlib.Path]:
    home = home if home is not None else pathlib.Path.home()
    for candidate in editor.homes:
        root = home / candidate
        if root.is_dir():
            return root
    return None


def installed_version(root: pathlib.Path) -> Optional[str]:
    """The version of our extension the editor currently has enabled.

    The extensions *directory* can hold several versions of one extension at
    once, so `extensions.json` is the only authoritative record of which one is
    live.
    """
    path = root / 'extensions' / 'extensions.json'
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError):
        # A missing, unreadable or half-written extensions.json is not an error
        # worth surfacing -- it just means we cannot tell, so we say nothing.
        return None
    if not isinstance(entries, list):
        return None

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get('identifier') or {}
        if not isinstance(identifier, dict):
            continue
        if str(identifier.get('id', '')).lower() != EXTENSION_ID.lower():
            continue
        version = entry.get('version')
        if isinstance(version, str) and utils.is_valid_semver(version):
            return version
    return None


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


def outdated_hint(
    env: Optional[Mapping[str, str]] = None,
    home: Optional[pathlib.Path] = None,
    vsix_directory: Optional[pathlib.Path] = None,
) -> Optional[str]:
    """One line telling the user their editor extension lags the bundled one.

    None -- stay silent -- for every other state: not in an editor, nothing
    installed, already current, or anything unreadable. The question being
    answered is "is the extension in my editor older than the one my rbx
    ships?", so both sides of the comparison are extension versions; a newer
    extension from a marketplace is a fine state to be in and says nothing.
    """
    env = env if env is not None else os.environ

    editor = detect_editor(env)
    if editor is None:
        return None
    bundled = bundled_vsix(vsix_directory)
    if bundled is None:
        return None
    root = editor_home(editor, home)
    if root is None:
        return None
    installed = installed_version(root)
    if installed is None:
        return None
    if (
        utils.check_version_compatibility_between(installed, bundled.version)
        is not utils.SemVerCompatibility.OUTDATED
    ):
        return None

    return (
        f'[info]The rbx {editor.label} extension is outdated '
        f'({installed} < {bundled.version}). Run [item]rbx vscode install[/item] '
        f'to re-sync it.[/info]'
    )


def print_outdated_hint(**kwargs) -> None:
    hint = outdated_hint(**kwargs)
    if hint is not None:
        console.console.print(hint)
