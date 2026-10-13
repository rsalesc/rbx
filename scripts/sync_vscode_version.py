"""Keep the VS Code extension's version equal to rbx's.

`rbx vscode install` ships the extension as `rbx-vscode-<version>.vsix`, and
`rbx.box.vscode.extension.outdated_hint` tells a setter to reinstall when the
extension in their editor is older than the bundled one. That comparison is
only as good as the version in `vscode/package.json`, and nothing used to move
it: it read `0.1.1` from 1.2.2 through 2.0.0, so the hint never fired and an
upgraded rbx kept talking to an extension too old to read what it wrote (#901).

So the extension carries rbx's own version, and this script is what puts it
there. It runs as a commitizen `pre_bump_hook` -- after `version_files` have
rewritten `rbx/__version__.py`, before the bump commit, which is made with
`git commit -a` and so picks up what this rewrites. `--check` is what a test
calls to pin the two together between bumps.

Why a script rather than another `version_files` entry: rbx versions are PEP
440 (`2.1.0rc0`), and `vsce` refuses anything that is not semver. The script
converts (`2.1.0-rc.0`); commitizen would copy the string verbatim and break
the release at packaging time, after the tag is already pushed. It also has
to reach the lockfile's `packages[""]` entry, which sits at the same
indentation as every dependency's `version` -- no line regex can single it
out, and an unanchored one is how dependency pins got silently bumped before.
"""

import argparse
import json
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / 'rbx' / '__version__.py'
PACKAGE_JSON = REPO_ROOT / 'vscode' / 'package.json'
PACKAGE_LOCK = REPO_ROOT / 'vscode' / 'package-lock.json'

_RBX_VERSION = re.compile(r"""__version__\s*=\s*['"](?P<version>[^'"]+)['"]""")
_PEP440 = re.compile(
    r'^(?P<release>\d+\.\d+\.\d+)'
    r'(?:(?P<pre>a|b|rc)(?P<pre_n>\d+))?'
    r'(?:\.post(?P<post>\d+))?'
    r'(?:\.dev(?P<dev>\d+))?$'
)
_PRE_LABELS = {'a': 'alpha', 'b': 'beta', 'rc': 'rc'}


def read_rbx_version(path: pathlib.Path = VERSION_FILE) -> str:
    matched = _RBX_VERSION.search(path.read_text())
    if matched is None:
        raise ValueError(f'No __version__ in {path}.')
    return matched.group('version')


def to_semver(version: str) -> str:
    """The semver spelling of a PEP 440 release version.

    Pre-releases and dev releases become semver pre-releases, so they still
    sort before the release they lead to. A post-release becomes build
    metadata: semver has no "after the release" pre-release, and metadata at
    least keeps the vsix name unique.
    """
    matched = _PEP440.match(version)
    if matched is None:
        raise ValueError(f'Cannot express {version!r} as a semver version.')

    prerelease: List[str] = []
    if matched.group('pre') is not None:
        prerelease.append(
            f'{_PRE_LABELS[matched.group("pre")]}.{matched.group("pre_n")}'
        )
    if matched.group('dev') is not None:
        prerelease.append(f'dev.{matched.group("dev")}')

    semver = matched.group('release')
    if prerelease:
        semver += '-' + '.'.join(prerelease)
    if matched.group('post') is not None:
        semver += f'+post.{matched.group("post")}'
    return semver


def _load(path: pathlib.Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _dump(path: pathlib.Path, data: Dict[str, Any]) -> None:
    # npm writes `JSON.stringify(data, null, 2)` plus a trailing newline, which
    # is exactly this -- so a sync touches the version lines and nothing else.
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )


def stale_files(
    version: str,
    package_json: pathlib.Path = PACKAGE_JSON,
    package_lock: pathlib.Path = PACKAGE_LOCK,
) -> List[str]:
    """Every place that does not say `version` yet, as a readable location."""
    stale = []
    if _load(package_json).get('version') != version:
        stale.append(f'{package_json.name}: version')
    lock = _load(package_lock)
    if lock.get('version') != version:
        stale.append(f'{package_lock.name}: version')
    if lock.get('packages', {}).get('', {}).get('version') != version:
        stale.append(f'{package_lock.name}: packages[""].version')
    return stale


def sync(
    version: str,
    package_json: pathlib.Path = PACKAGE_JSON,
    package_lock: pathlib.Path = PACKAGE_LOCK,
) -> None:
    manifest = _load(package_json)
    manifest['version'] = version
    _dump(package_json, manifest)

    lock = _load(package_lock)
    lock['version'] = version
    root = lock.get('packages', {}).get('')
    if root is not None:
        root['version'] = version
    _dump(package_lock, lock)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--check',
        action='store_true',
        help='exit non-zero, changing nothing, when the extension version is stale',
    )
    args = parser.parse_args(argv)

    version = to_semver(read_rbx_version())
    if args.check:
        stale = stale_files(version)
        for location in stale:
            print(f'{location} is not {version}', file=sys.stderr)
        if stale:
            print(
                'Run `python scripts/sync_vscode_version.py` to fix.', file=sys.stderr
            )
        return 1 if stale else 0

    sync(version)
    print(f'VS Code extension version set to {version}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
