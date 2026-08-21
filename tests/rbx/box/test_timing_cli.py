"""What `rbx time` reports to its caller.

An estimation that writes nothing to the limits profile is a failure, not a
no-op: a pipeline running `rbx time` has to be able to tell that no limit was
produced. Every path that leaves the profile untouched -- an unsatisfiable
range, a solution that bounds nothing, a failed run -- reaches the CLI as a
``None`` from ``compute_time_limits``, so pinning the exit code of that one
signal pins all of them.
"""

import asyncio
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli, timing
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
    # unrelated to the exit codes under test and fails for the bare testing
    # package preset.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


def _mock_compute(result):
    async def compute_time_limits(*args, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    return compute_time_limits


async def _build_ok(*args, **kwargs):
    return True


def _invoke_time(runner: CliRunner, result, extra_args=None):
    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.timing.compute_time_limits', _mock_compute(result)),
    ):
        return runner.invoke(cli.app, ['time', '--auto', *(extra_args or [])])


def test_time_exits_nonzero_when_no_limit_was_estimated(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    # The estimation refused to produce a limit and wrote nothing; `rbx time`
    # must not report success for it.
    result = _invoke_time(runner, None)

    assert result.exit_code == 1, result.output


def test_time_exits_zero_when_a_limit_was_estimated(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    # Warnings (a dropped slow solution, a cap-bounded estimate) still produce a
    # profile, so they must keep the command successful.
    result = _invoke_time(runner, timing.TimingProfile(timeLimit=1000))

    assert result.exit_code == 0, result.output


def test_time_exits_nonzero_when_nothing_bounds_the_limit_from_below(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    # MissingLowerBoundError is an RbxException: `rbx/box/main.py` prints it and
    # exits 1 rather than letting it surface as a traceback.
    from rbx.box.exception import RbxException

    assert issubclass(timing.MissingLowerBoundError, RbxException)

    result = _invoke_time(runner, timing.MissingLowerBoundError('nope'))

    assert result.exit_code != 0


def test_skip_slow_reaches_the_estimation(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    seen = {}

    async def compute_time_limits(*args, **kwargs):
        seen.update(kwargs)
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.timing.compute_time_limits', compute_time_limits),
    ):
        result = runner.invoke(cli.app, ['time', '--auto', '--skip-slow'])

    assert result.exit_code == 0, result.output
    assert seen['skip_slow'] is True


def test_the_slow_check_runs_unless_it_is_skipped(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    seen = {}

    async def compute_time_limits(*args, **kwargs):
        seen.update(kwargs)
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.timing.compute_time_limits', compute_time_limits),
    ):
        result = runner.invoke(cli.app, ['time', '--auto'])

    assert result.exit_code == 0, result.output
    assert seen['skip_slow'] is False
