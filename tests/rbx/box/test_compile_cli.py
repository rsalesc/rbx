"""What `rbx compile -- <flags>` hands to the compiler.

Everything after `--` is meant to reach the compiler verbatim, including tokens
that collide with rbx's own options. Click fills positional arguments in order
and does not report where the separator was, so the parsing is a decision the
command takes itself and is pinned here rather than through a real compilation.
"""

import asyncio
from typing import Any, Dict, List
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli
from rbx.box.testing import testing_package


@pytest.fixture
def runner() -> CliRunner:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


@pytest.fixture(autouse=True)
def _skip_preset_check():
    # The root Typer callback checks the active preset's compatibility, which is
    # unrelated to the wiring under test and fails for the bare testing package.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


def _invoke_compile(runner: CliRunner, *args: str):
    calls: List[Dict[str, Any]] = []

    async def compile_any(path, sanitized=False, warnings=False, extra_flags=None):
        calls.append(
            {
                'path': path,
                'sanitized': sanitized,
                'warnings': warnings,
                'extra_flags': extra_flags,
            }
        )

    with mock.patch('rbx.box.compile.any', compile_any):
        result = runner.invoke(cli.app, ['compile', *args])
    return result, calls


def test_flags_after_the_separator_reach_the_compiler(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, calls = _invoke_compile(runner, 'sol.cpp', '--', '-DLOCAL', '-O0')

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]['path'] == 'sol.cpp'
    assert calls[0]['extra_flags'] == ['-DLOCAL', '-O0']


def test_the_separator_shields_rbx_own_options(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    # `-s` is `--sanitized` to rbx, but after `--` it belongs to the compiler.
    result, calls = _invoke_compile(runner, 'sol.cpp', '--', '-s', '-g')

    assert result.exit_code == 0, result.output
    assert calls[0]['sanitized'] is False
    assert calls[0]['extra_flags'] == ['-s', '-g']


def test_rbx_options_before_the_separator_are_still_rbx_options(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, calls = _invoke_compile(runner, '-s', '-w', 'sol.cpp', '--', '-DLOCAL')

    assert result.exit_code == 0, result.output
    assert calls[0]['sanitized'] is True
    assert calls[0]['warnings'] is True
    assert calls[0]['extra_flags'] == ['-DLOCAL']


def test_a_leading_dash_is_a_flag_not_a_path(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    # `rbx compile -- -O0 -g` has no path: Click would otherwise bind `-O0` to it.
    # With no path left, the command falls through to asking for one.
    with mock.patch('questionary.path') as path_prompt:
        path_prompt.return_value.ask_async = mock.AsyncMock(return_value='sol.cpp')
        result, calls = _invoke_compile(runner, '--', '-O0', '-g')

    assert result.exit_code == 0, result.output
    assert calls[0]['path'] == 'sol.cpp'
    assert calls[0]['extra_flags'] == ['-O0', '-g']


def test_no_extra_flags_is_an_empty_list(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, calls = _invoke_compile(runner, 'sol.cpp')

    assert result.exit_code == 0, result.output
    assert calls[0]['extra_flags'] == []
