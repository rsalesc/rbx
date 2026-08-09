"""Tests for the reusable schema exporter and the publishable site tree."""

import json

import pytest

from rbx.box.internal import schema_export


def test_exports_every_documented_model(tmp_path):
    schema_export.export_schemas(tmp_path)

    names = {p.stem for p in tmp_path.glob('*.json')}

    assert names == {m.__name__ for m in schema_export.MODELS}
    assert 'Package' in names


def _additional_properties_values(node):
    """Every `additionalProperties` value anywhere in the schema."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'additionalProperties':
                yield value
            yield from _additional_properties_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _additional_properties_values(item)


def test_exported_schema_is_valid_json_and_relaxed(tmp_path):
    schema_export.export_schemas(tmp_path)

    schema = json.loads((tmp_path / 'Package.json').read_text())

    assert schema['title'] == 'Package'
    # `additionalProperties: false` is what rejects keys added by newer rbx
    # versions. Dict-typed fields legitimately carry an additionalProperties
    # *schema*, which must survive.
    assert not [v for v in _additional_properties_values(schema) if v is False]
    assert 'vars' in schema['properties']


class TestSchemaPublish:
    def test_publish_layout(self, tmp_path):
        from rbx.box.internal import schema_publish

        schema_publish.build_site(tmp_path, version='1.4.2')

        assert (tmp_path / '1.4' / 'Package.json').is_file()
        assert (tmp_path / 'latest' / 'Package.json').is_file()
        # Pages must serve the tree verbatim, without a Jekyll build.
        assert (tmp_path / '.nojekyll').is_file()

        index = json.loads((tmp_path / 'index.json').read_text())
        assert index['latest'] == '1.4'
        assert '1.4' in index['versions']
        assert 'Package' in index['models']

    def test_publish_merges_with_existing_versions(self, tmp_path):
        from rbx.box.internal import schema_publish

        schema_publish.build_site(tmp_path, version='1.3.0')
        schema_publish.build_site(tmp_path, version='1.4.0')

        index = json.loads((tmp_path / 'index.json').read_text())

        assert index['versions'] == ['1.3', '1.4']
        assert index['latest'] == '1.4'
        assert (tmp_path / '1.3' / 'Package.json').is_file()

    def test_republishing_older_patch_does_not_demote_latest(self, tmp_path):
        from rbx.box.internal import schema_publish

        schema_publish.build_site(tmp_path, version='1.4.0')
        schema_publish.build_site(tmp_path, version='1.3.9')

        index = json.loads((tmp_path / 'index.json').read_text())

        assert index['latest'] == '1.4'

    def test_versions_sort_numerically_not_lexicographically(self, tmp_path):
        from rbx.box.internal import schema_publish

        for version in ('1.9.0', '1.10.0', '2.0.0'):
            schema_publish.build_site(tmp_path, version=version)

        index = json.loads((tmp_path / 'index.json').read_text())

        assert index['versions'] == ['1.9', '1.10', '2.0']
        assert index['latest'] == '2.0'

    def test_ignores_unrelated_directories(self, tmp_path):
        from rbx.box.internal import schema_publish

        (tmp_path / '.git').mkdir()
        (tmp_path / 'assets').mkdir()

        schema_publish.build_site(tmp_path, version='1.4.0')

        index = json.loads((tmp_path / 'index.json').read_text())

        assert index['versions'] == ['1.4']


class TestPublishScript:
    """The publish entrypoint shared by the local task and CI."""

    def _script(self):
        from scripts import publish_schemas

        return publish_schemas

    def test_skips_prerelease_versions(self, tmp_path, capsys):
        script = self._script()

        assert script.main(['--dir', str(tmp_path), '--version', '1.5.0rc1']) == 0

        assert 'prerelease' in capsys.readouterr().out
        assert not (tmp_path / '1.5').exists()

    def test_publishes_prerelease_when_forced(self, tmp_path):
        script = self._script()
        _init_repo(tmp_path)

        script.main(
            [
                '--dir',
                str(tmp_path),
                '--version',
                '1.5.0rc1',
                '--allow-prerelease',
                '--no-push',
            ]
        )

        assert (tmp_path / '1.5' / 'Package.json').is_file()

    def test_defaults_to_installed_version(self, tmp_path):
        from rbx import utils

        script = self._script()
        _init_repo(tmp_path)

        script.main(['--dir', str(tmp_path), '--no-push'])

        installed = utils.get_semver()
        assert (tmp_path / f'{installed.major}.{installed.minor}').is_dir()

    def test_commits_and_is_idempotent(self, tmp_path):
        script = self._script()
        _init_repo(tmp_path)

        script.main(['--dir', str(tmp_path), '--version', '1.4.0', '--no-push'])
        first = _commit_count(tmp_path)

        script.main(['--dir', str(tmp_path), '--version', '1.4.0', '--no-push'])

        assert _commit_count(tmp_path) == first, 'republishing should be a no-op'


def _init_repo(path):
    import subprocess

    for args in (
        ['git', 'init', '-q'],
        ['git', 'config', 'user.email', 'test@example.com'],
        ['git', 'config', 'user.name', 'test'],
        ['git', 'commit', '-q', '--allow-empty', '-m', 'init'],
    ):
        subprocess.run(args, cwd=str(path), check=True)


def _commit_count(path) -> int:
    import subprocess

    return int(
        subprocess.run(
            ['git', 'rev-list', '--count', 'HEAD'],
            cwd=str(path),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
    )


class TestPublishSafety:
    """Publishing writes files, `git add -A` and pushes -- it must never run
    against anything but a schemas checkout."""

    def test_refuses_empty_dir(self):
        from scripts import publish_schemas

        with pytest.raises(SystemExit):
            publish_schemas.main(['--dir', '', '--version', '1.4.0'])

    def test_refuses_a_source_checkout(self, tmp_path):
        from scripts import publish_schemas

        _init_repo(tmp_path)
        (tmp_path / 'pyproject.toml').write_text('[project]\n')

        with pytest.raises(SystemExit):
            publish_schemas.main(
                ['--dir', str(tmp_path), '--version', '1.4.0', '--no-push']
            )

    def test_refuses_a_non_git_directory(self, tmp_path):
        from scripts import publish_schemas

        with pytest.raises(SystemExit):
            publish_schemas.main(
                ['--dir', str(tmp_path), '--version', '1.4.0', '--no-push']
            )
