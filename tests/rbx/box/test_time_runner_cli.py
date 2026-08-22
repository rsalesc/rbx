"""What `rbx time --runner` selects, and what happens when it selects nothing.

The flag is the whole backend-selection surface (`runners/registry.py`), so the
wiring is pinned here, where it is: which object the estimation is handed, that
the default is unchanged, and that a name rbx does not know costs a message
rather than a run.
"""

import asyncio
from typing import Any, Dict, Tuple
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli, timing
from rbx.box.runners.local import LocalRunner
from rbx.box.runners.moj.runner import MojRunner
from rbx.box.runners.registry import UnknownRunnerError
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


async def _build_ok(*args, **kwargs):
    return True


def _invoke_time(runner: CliRunner, *args: str) -> Tuple[Any, Dict[str, Any]]:
    """`rbx time -s estimate`, with everything past the flag stubbed out.

    `-s estimate` because a bare `rbx time` opens a questionary prompt; the
    strategy has nothing to do with which backend runs the solutions.
    """
    calls: Dict[str, Any] = {}

    async def compute_time_limits(*positional, **kwargs):
        calls.update(kwargs)
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.timing.compute_time_limits', compute_time_limits),
    ):
        result = runner.invoke(cli.app, ['time', '-s', 'estimate', *args])
    return result, calls


def test_no_flag_estimates_on_the_local_sandbox(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    """The behaviour every existing `rbx time` has: the flag's absence must not
    change where a solution runs."""
    result, calls = _invoke_time(runner)

    assert result.exit_code == 0, result.output
    assert isinstance(calls['runner'], LocalRunner)


def test_asking_for_local_is_the_same_as_asking_for_nothing(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    default_result, default_calls = _invoke_time(runner)
    explicit_result, explicit_calls = _invoke_time(runner, '--runner', 'local')

    assert explicit_result.exit_code == default_result.exit_code == 0
    assert isinstance(explicit_calls['runner'], LocalRunner)
    # Everything else the command decides is decided the same way; only the
    # backend object differs, and only by identity.
    assert {k: v for k, v in explicit_calls.items() if k != 'runner'} == {
        k: v for k, v in default_calls.items() if k != 'runner'
    }


def test_asking_for_moj_estimates_on_the_judge(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result, calls = _invoke_time(runner, '--runner', 'moj')

    assert result.exit_code == 0, result.output
    assert isinstance(calls['runner'], MojRunner)


def test_a_profile_does_not_select_a_backend(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    """`-p moj` names the `limits/moj.yml` file this command *writes*. Letting it
    pick a transport too would leave no way to estimate MOJ limits locally, which
    is what a setter without judge access has to be able to do."""
    result, calls = _invoke_time(runner, '-p', 'moj')

    assert result.exit_code == 0, result.output
    assert isinstance(calls['runner'], LocalRunner)
    assert calls['profile'] == 'moj'


def test_an_unknown_backend_is_refused_before_anything_runs(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    """A typo in the command line should cost an error, not a build -- and the
    message has to name what to type instead, since nothing else will."""
    result, calls = _invoke_time(runner, '--runner', 'mog')

    assert result.exit_code != 0
    assert isinstance(result.exception, UnknownRunnerError)
    assert str(result.exception) == (
        'There is no runner called `mog`. The runners rbx knows are: `local`, `moj`.'
    )
    # Nothing was estimated, and nothing was written.
    assert calls == {}
