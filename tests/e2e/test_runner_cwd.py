"""Tests for ``Step.cwd`` handling in :func:`tests.e2e.runner.run_step`."""

import pathlib

import pytest

from tests.e2e.runner import run_step
from tests.e2e.spec import Step


def test_run_step_honors_cwd(tmp_path: pathlib.Path):
    sub = tmp_path / 'A'
    sub.mkdir()
    original = pathlib.Path.cwd()
    run_step(
        scenario_path=tmp_path / 'e2e.rbx.yml',
        scenario_name='probe',
        step=Step(cmd='--help', cwd='A', expect_exit=0),
        cwd=tmp_path,
    )
    # Runner must restore cwd even after chdir-ing into the subdir.
    assert pathlib.Path.cwd() == original


def test_run_step_default_cwd_is_package_root(tmp_path: pathlib.Path):
    original = pathlib.Path.cwd()
    run_step(
        scenario_path=tmp_path / 'e2e.rbx.yml',
        scenario_name='probe',
        step=Step(cmd='--help', expect_exit=0),
        cwd=tmp_path,
    )
    assert pathlib.Path.cwd() == original


def test_run_step_errors_on_missing_cwd(tmp_path: pathlib.Path):
    with pytest.raises(AssertionError, match='does not exist'):
        run_step(
            scenario_path=tmp_path / 'e2e.rbx.yml',
            scenario_name='probe',
            step=Step(cmd='--help', cwd='nope', expect_exit=0),
            cwd=tmp_path,
        )
