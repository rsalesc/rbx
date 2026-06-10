"""Unit tests for seeding an e2e scenario's temp package from a real preset.

These exercise the ``seed_from_preset`` scenario field (parsing) and the
``seed_package_from_preset`` runner helper that overlays a named preset's
``problem/`` package into a destination dir at run time, dereferencing
symlinks and skipping build cruft.
"""

import pathlib

import pytest

from rbx.config import CACHE_DIR_NAME, LEGACY_CACHE_DIR_NAME
from tests.e2e.runner import seed_package_from_preset
from tests.e2e.spec import Scenario


def test_scenario_parses_seed_from_preset():
    scenario = Scenario.model_validate({'name': 'works', 'seed_from_preset': 'default'})
    assert scenario.seed_from_preset == 'default'


def test_scenario_seed_from_preset_defaults_none():
    scenario = Scenario.model_validate({'name': 'works'})
    assert scenario.seed_from_preset is None


def test_seed_package_from_preset_overlays_real_files(tmp_path: pathlib.Path):
    dest = tmp_path / 'pkg'
    dest.mkdir()
    # The fixture's own e2e.rbx.yml is already present; it must survive.
    (dest / 'e2e.rbx.yml').write_text('scenarios: []\n')

    seed_package_from_preset('default', dest)

    # Sources from the preset package landed.
    assert (dest / 'sols' / 'main.cpp').is_file()
    # Statements v2: the problem statement lives under statement/, and the
    # contest (not the problem) owns the LaTeX chrome, so the problem package
    # carries no icpc.sty / template symlinks at all.
    assert (dest / 'statement' / 'statement.rbx.tex').is_file()
    assert (dest / 'statement' / 'samples' / '000.in').is_file()

    # The seed overlay never leaves symlinks behind (they are dereferenced).
    assert not any(p.is_symlink() for p in dest.rglob('*'))

    # Build cruft was skipped.
    assert not (dest / CACHE_DIR_NAME).exists()
    assert not (dest / LEGACY_CACHE_DIR_NAME).exists()
    assert not (dest / 'build').exists()

    # The fixture file survived the overlay.
    assert (dest / 'e2e.rbx.yml').read_text() == 'scenarios: []\n'


def test_seed_package_from_preset_unknown_raises(tmp_path: pathlib.Path):
    with pytest.raises(FileNotFoundError, match='nope-preset'):
        seed_package_from_preset('nope-preset', tmp_path)


def test_seed_package_from_preset_missing_dest_raises(tmp_path: pathlib.Path):
    missing = tmp_path / 'does-not-exist'
    with pytest.raises(FileNotFoundError, match='destination does not exist'):
        seed_package_from_preset('default', missing)
