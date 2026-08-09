"""Tests for version-pinned schema URL resolution."""

import pathlib
import textwrap
from unittest import mock

import pytest
from pydantic import BaseModel

from rbx.box import schema_urls


class Package(BaseModel):
    pass


def _write_preset(root: pathlib.Path, min_version: str) -> None:
    local = root / '.local.rbx'
    local.mkdir(parents=True, exist_ok=True)
    (local / 'preset.rbx.yml').write_text(
        textwrap.dedent(f"""
        name: "test-preset"
        uri: "rsalesc/rbx"
        min_version: "{min_version}"
        """)
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    schema_urls.preset_min_version.cache_clear()
    yield
    schema_urls.preset_min_version.cache_clear()


class TestSchemaUrl:
    def test_pins_to_preset_minor(self, tmp_path):
        _write_preset(tmp_path, '1.4.2')

        assert schema_urls.schema_url(Package, tmp_path) == (
            'https://rsalesc.github.io/rbx-schemas/1.4/Package.json'
        )

    def test_pins_from_nested_problem_dir(self, tmp_path):
        _write_preset(tmp_path, '1.4.2')
        nested = tmp_path / 'problems' / 'A'
        nested.mkdir(parents=True)

        assert schema_urls.schema_url(Package, nested) == (
            'https://rsalesc.github.io/rbx-schemas/1.4/Package.json'
        )

    def test_falls_back_to_unversioned_below_floor(self, tmp_path):
        _write_preset(tmp_path, '0.14.0')

        assert schema_urls.schema_url(Package, tmp_path) == (
            'https://rsalesc.github.io/rbx/schemas/Package.json'
        )

    def test_uses_installed_version_without_preset(self, tmp_path):
        with mock.patch('rbx.utils.get_version', return_value='2.7.3'):
            assert schema_urls.schema_url(Package, tmp_path) == (
                'https://rsalesc.github.io/rbx-schemas/2.7/Package.json'
            )

    def test_malformed_preset_is_tolerated_silently(self, tmp_path, capsys):
        local = tmp_path / '.local.rbx'
        local.mkdir()
        (local / 'preset.rbx.yml').write_text('this: [is, not, valid\n')

        url = schema_urls.schema_url(Package, tmp_path)

        assert url.endswith('Package.json')
        assert capsys.readouterr().out == ''

    def test_incompatible_preset_does_not_raise(self, tmp_path):
        # min_version far above the installed version would make
        # _check_preset_compatibility exit; stamping a comment must not.
        _write_preset(tmp_path, '999.0.0')

        assert schema_urls.schema_url(Package, tmp_path).endswith('Package.json')

    def test_preset_read_is_cached(self, tmp_path):
        _write_preset(tmp_path, '1.4.2')

        schema_urls.schema_url(Package, tmp_path)
        (tmp_path / '.local.rbx' / 'preset.rbx.yml').unlink()

        assert schema_urls.schema_url(Package, tmp_path) == (
            'https://rsalesc.github.io/rbx-schemas/1.4/Package.json'
        )
