"""Tests for build path resolution in the stats command."""

import pathlib
from unittest import mock

from rbx.box import stats


def _write_artifact(directory: pathlib.Path, size: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'artifact.bin').write_bytes(b'x' * size)


def test_build_size_problem_honors_custom_build_dir(tmp_path: pathlib.Path):
    (tmp_path / 'problem.rbx.yml').write_text('name: prob\n')
    _write_artifact(tmp_path / 'out', 50)

    with mock.patch(
        'rbx.box.environment.get_build_dir', return_value=pathlib.Path('out')
    ):
        assert stats.get_build_size(tmp_path) == 50


def test_build_size_contest_honors_custom_build_dir(tmp_path: pathlib.Path):
    (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
    _write_artifact(tmp_path / 'out', 100)

    # Without honoring buildDir, this would look in tmp_path/'build' (empty) -> 0.
    with mock.patch(
        'rbx.box.environment.get_build_dir', return_value=pathlib.Path('out')
    ):
        assert stats.get_build_size(tmp_path) == 100


def test_build_size_contest_default_ignores_custom_dir(tmp_path: pathlib.Path):
    (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
    # Default buildDir is 'build'; artifacts under 'out' must not be counted.
    _write_artifact(tmp_path / 'out', 100)

    assert stats.get_build_size(tmp_path) == 0
