"""Tests for `rbx presets create` (rbx.box.presets.create)."""

import pathlib
from types import SimpleNamespace
from unittest import mock

import pytest
import ruyaml
import typer

from rbx import utils
from rbx.box import presets
from rbx.box.presets.schema import Preset


def _install_preset_stub(dest_pkg: pathlib.Path, fetch_info=None, **kwargs):
    """Mimic presets.install_preset: create the folder and a minimal preset."""
    dest_pkg.mkdir(parents=True, exist_ok=True)
    (dest_pkg / 'preset.rbx.yml').write_text(
        'name: "placeholder"\nuri: "placeholder/uri"\n'
    )


def _read_field(dest: pathlib.Path, field: str):
    yaml = ruyaml.YAML()
    data = yaml.load((dest / 'preset.rbx.yml').read_text())
    return data[field]


@pytest.fixture
def mock_presets():
    with (
        mock.patch.object(
            presets,
            'get_preset_fetch_info_with_fallback',
            return_value=SimpleNamespace(),
        ),
        mock.patch.object(presets, 'install_preset', side_effect=_install_preset_stub),
    ):
        yield


def test_create_with_plain_name(cleandir, mock_presets):
    presets.create('my-preset', uri='rsalesc/rbx-preset')

    dest = pathlib.Path('my-preset')
    assert dest.is_dir()
    assert _read_field(dest, 'name') == 'my-preset'
    assert _read_field(dest, 'uri') == 'rsalesc/rbx-preset'


def test_create_with_relative_path_uses_basename_as_name(cleandir, mock_presets):
    presets.create('presets/my-preset', uri='rsalesc/rbx-preset')

    # Folder is created at the full relative path...
    dest = pathlib.Path('presets/my-preset')
    assert dest.is_dir()

    # ...but the preset name is only the basename, and it is a valid name.
    name = _read_field(dest, 'name')
    assert name == 'my-preset'
    utils.validate_field(Preset, 'name', name)


def test_create_with_invalid_derived_name_fails_fast(cleandir, mock_presets):
    # Basename `ab` is too short (min 3 chars): fail before creating anything.
    with pytest.raises(typer.Exit):
        presets.create('presets/ab', uri='rsalesc/rbx-preset')

    assert not pathlib.Path('presets/ab').exists()
    assert not pathlib.Path('presets').exists()
