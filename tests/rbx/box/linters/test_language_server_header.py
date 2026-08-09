"""Tests for `# yaml-language-server` header normalization."""

import pathlib

import pytest

from rbx.box import linting, schema_urls
from rbx.box.schema import Package

VERSIONED = 'https://rsalesc.github.io/rbx-schemas'


def _preset(root: pathlib.Path, min_version: str = '1.4.0') -> None:
    (root / '.local.rbx').mkdir(parents=True, exist_ok=True)
    (root / '.local.rbx' / 'preset.rbx.yml').write_text(
        f'name: "p"\nuri: "u"\nmin_version: "{min_version}"\n'
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    schema_urls.preset_min_version.cache_clear()
    yield
    schema_urls.preset_min_version.cache_clear()


class TestFixLanguageServer:
    def test_replaces_unversioned_header_with_pin(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        path.write_text(
            '---\n'
            '# yaml-language-server: $schema='
            'https://rsalesc.github.io/rbx/schemas/Package.json\n'
            'name: "problem"\n'
        )

        assert linting.fix_language_server(path, Package, tmp_path) is True
        assert f'$schema={VERSIONED}/1.4/Package.json' in path.read_text()

    def test_is_idempotent(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        path.write_text(
            f'---\n# yaml-language-server: $schema={VERSIONED}/1.4/Package.json\n'
            'name: "problem"\n'
        )

        assert linting.fix_language_server(path, Package, tmp_path) is False

    def test_adds_header_to_file_without_document_marker(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        path.write_text('name: "problem"\n')

        assert linting.fix_language_server(path, Package, tmp_path) is True
        content = path.read_text()
        assert content.splitlines()[0].startswith('# yaml-language-server:')
        assert 'name: "problem"' in content

    def test_keeps_header_after_document_marker(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        path.write_text('---\nname: "problem"\n')

        assert linting.fix_language_server(path, Package, tmp_path) is True
        lines = path.read_text().splitlines()
        assert lines[0] == '---'
        assert lines[1].startswith('# yaml-language-server:')

    def test_leaves_foreign_schema_url_untouched(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        original = (
            '---\n'
            '# yaml-language-server: $schema=./my-local-schema.json\n'
            'name: "problem"\n'
        )
        path.write_text(original)

        assert linting.fix_language_server(path, Package, tmp_path) is False
        assert path.read_text() == original

    def test_does_not_duplicate_when_header_already_present(self, tmp_path):
        _preset(tmp_path)
        path = tmp_path / 'problem.rbx.yml'
        path.write_text(
            '---\n'
            '# yaml-language-server: $schema='
            'https://rsalesc.github.io/rbx/schemas/Package.json\n'
            'name: "problem"\n'
        )

        linting.fix_language_server(path, Package, tmp_path)
        content = path.read_text()

        assert content.count('# yaml-language-server:') == 1
