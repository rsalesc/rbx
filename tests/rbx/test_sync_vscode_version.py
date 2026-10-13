import json
import pathlib

import pytest

from scripts import sync_vscode_version


@pytest.mark.parametrize(
    'pep440, semver',
    [
        ('2.0.0', '2.0.0'),
        ('2.1.0rc0', '2.1.0-rc.0'),
        ('2.1.0a3', '2.1.0-alpha.3'),
        ('2.1.0b1', '2.1.0-beta.1'),
        ('2.1.0.dev4', '2.1.0-dev.4'),
        ('2.1.0rc1.dev2', '2.1.0-rc.1.dev.2'),
        ('2.0.0.post1', '2.0.0+post.1'),
    ],
)
def test_to_semver(pep440, semver):
    assert sync_vscode_version.to_semver(pep440) == semver


@pytest.mark.parametrize('version', ['2.0', '2!1.0.0', 'banana'])
def test_to_semver_refuses_what_it_cannot_express(version):
    with pytest.raises(ValueError):
        sync_vscode_version.to_semver(version)


def test_extension_version_matches_rbx():
    """The pin itself: a bump that skipped the hook fails here, not in a setter's editor."""
    version = sync_vscode_version.to_semver(sync_vscode_version.read_rbx_version())

    assert sync_vscode_version.stale_files(version) == []


def _write(path: pathlib.Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + '\n')


def test_sync_rewrites_only_the_extension_versions(tmp_path):
    package_json = tmp_path / 'package.json'
    package_lock = tmp_path / 'package-lock.json'
    _write(package_json, {'name': 'rbx-vscode', 'version': '0.1.1', 'license': 'MIT'})
    _write(
        package_lock,
        {
            'name': 'rbx-vscode',
            'version': '0.1.1',
            'packages': {
                '': {'name': 'rbx-vscode', 'version': '0.1.1'},
                # A dependency sharing the old version must be left alone: that
                # is the drift an unanchored `version_files` entry causes.
                'node_modules/yaml': {'version': '0.1.1'},
            },
        },
    )

    assert (
        len(sync_vscode_version.stale_files('2.0.0', package_json, package_lock)) == 3
    )
    sync_vscode_version.sync('2.0.0', package_json, package_lock)

    assert json.loads(package_json.read_text()) == {
        'name': 'rbx-vscode',
        'version': '2.0.0',
        'license': 'MIT',
    }
    lock = json.loads(package_lock.read_text())
    assert lock['version'] == '2.0.0'
    assert lock['packages'][''] == {'name': 'rbx-vscode', 'version': '2.0.0'}
    assert lock['packages']['node_modules/yaml'] == {'version': '0.1.1'}
    assert sync_vscode_version.stale_files('2.0.0', package_json, package_lock) == []


def test_sync_keeps_npm_formatting(tmp_path):
    """npm's own formatting survives a round trip, so a sync diffs only version lines."""
    for name in ('package.json', 'package-lock.json'):
        original = (sync_vscode_version.REPO_ROOT / 'vscode' / name).read_text()
        copy = tmp_path / name
        copy.write_text(original)
    version = json.loads((tmp_path / 'package.json').read_text())['version']

    sync_vscode_version.sync(
        version, tmp_path / 'package.json', tmp_path / 'package-lock.json'
    )

    for name in ('package.json', 'package-lock.json'):
        original = (sync_vscode_version.REPO_ROOT / 'vscode' / name).read_text()
        assert (tmp_path / name).read_text() == original
