"""Tests for rbx.box.creation (the `rbx create` command)."""

import pathlib
from types import SimpleNamespace
from unittest import mock

import pytest
import ruyaml
import typer

from rbx import utils
from rbx.box import creation
from rbx.box.schema import Package


def _install_problem_stub(dest_pkg: pathlib.Path, fetch_info=None, materialize=True):
    """Mimic presets.install_problem: create the folder and a minimal package."""
    dest_pkg.mkdir(parents=True, exist_ok=True)
    (dest_pkg / 'problem.rbx.yml').write_text(
        'name: "placeholder"\ntimeLimit: 1000\nmemoryLimit: 256\n'
    )


def _read_name(dest: pathlib.Path) -> str:
    yaml = ruyaml.YAML()
    data = yaml.load((dest / 'problem.rbx.yml').read_text())
    return data['name']


@pytest.fixture
def mock_presets():
    with (
        mock.patch.object(
            creation.presets,
            'get_preset_fetch_info_with_fallback',
            return_value=SimpleNamespace(),
        ),
        mock.patch.object(
            creation.presets, 'install_problem', side_effect=_install_problem_stub
        ),
        mock.patch.object(creation.presets, 'generate_lock'),
    ):
        yield


def test_create_with_plain_name(cleandir, mock_presets):
    creation.create('my-problem')

    dest = pathlib.Path('my-problem')
    assert dest.is_dir()
    assert _read_name(dest) == 'my-problem'


def test_create_with_relative_path_uses_basename_as_name(cleandir, mock_presets):
    creation.create('problems/my-problem')

    # Folder is created at the full relative path...
    dest = pathlib.Path('problems/my-problem')
    assert dest.is_dir()

    # ...but the problem name is only the basename, and it is a valid name.
    name = _read_name(dest)
    assert name == 'my-problem'
    utils.validate_field(Package, 'name', name)


def test_create_with_invalid_derived_name_fails_fast(cleandir, mock_presets):
    # Basename `ab` is too short (min 3 chars): fail before creating anything.
    with pytest.raises(typer.Exit):
        creation.create('problems/ab')

    assert not pathlib.Path('problems/ab').exists()
    assert not pathlib.Path('problems').exists()
