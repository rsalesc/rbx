"""The `rbx run` flags `rbx time` and `rbx preship` deliberately do not offer.

Each of these would either corrupt the measurement the command exists to make or
contradict what the command promises to run, so their absence is a decision
rather than an oversight. Pinned here so adding one is a deliberate act.
"""

import asyncio
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
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


@pytest.mark.parametrize(
    ('flag', 'why'),
    [
        # Sanitizers inflate a solution's runtime severalfold, so a limit
        # estimated under them is a limit for a binary nobody will ship.
        ('--sanitized', 'would corrupt every timing the estimate rests on'),
        # The estimation pins ALL_SOLUTIONS so `isDoubleTL` stays off; FULL would
        # double the very cap the accepted solutions are measured under.
        ('--verification-level', 'is pinned by the estimation'),
        # `rbx preship` promises to run every solution. A filter would leave the
        # ones it skipped looking checked.
        ('--outcome', 'would contradict "every solution runs"'),
        ('--tag', 'would contradict "every solution runs"'),
        ('--choice', 'would contradict "every solution runs"'),
    ],
)
def test_preship_does_not_offer(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
    flag: str,
    why: str,
):
    result = runner.invoke(cli.app, ['preship', flag, 'x'])

    assert result.exit_code != 0, f'{flag} {why}, but was accepted'
    assert 'No such option' in result.output


def test_preship_takes_no_solution_arguments(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    # `rbx run` takes solution paths positionally; `rbx preship` runs the whole
    # package, so a stray path is a mistake worth reporting rather than a filter.
    result = runner.invoke(cli.app, ['preship', 'sols/main.cpp'])

    assert result.exit_code != 0
    assert 'unexpected extra argument' in result.output.lower()
