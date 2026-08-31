"""How `--run-all`, `--fail-fast` and `rbx preship` reach the extra run.

`rbx preship` is `rbx time --auto --run-all` under another name, so what it has to
guarantee is that it lands on the same code path with those two switched on.
"""

import asyncio
import pathlib
from typing import List, Optional
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli, timing
from rbx.box.schema import ExpectedOutcome, Solution
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


async def _build_ok(*args, **kwargs):
    return True


def _invoke(runner: CliRunner, args: List[str]):
    seen = {}

    async def compute_time_limits(check, detailed, runs=0, **kwargs):
        seen.update(kwargs, check=check, detailed=detailed, runs=runs)
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.timing.compute_time_limits', compute_time_limits),
    ):
        result = runner.invoke(cli.app, args)
    return result, seen


def test_the_extra_run_is_off_by_default(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['time', '--auto'])

    assert result.exit_code == 0, result.output
    assert seen['run_all'] is False
    assert seen['fail_fast'] is False


def test_run_all_asks_for_the_extra_run(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['time', '--auto', '--run-all'])

    assert result.exit_code == 0, result.output
    assert seen['run_all'] is True


def test_fail_fast_reaches_the_extra_run(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['time', '--auto', '--run-all', '--fail-fast'])

    assert result.exit_code == 0, result.output
    assert seen['fail_fast'] is True


def test_the_short_alias_of_fail_fast_works(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['time', '--auto', '--run-all', '--ff'])

    assert result.exit_code == 0, result.output
    assert seen['fail_fast'] is True


def test_preship_is_an_automatic_run_all(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['preship'])

    assert result.exit_code == 0, result.output
    assert seen['run_all'] is True
    assert seen['auto'] is True


def test_preship_takes_the_remaining_flags(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(
        runner, ['preship', '--dry', '--skip-slow', '--fail-fast', '-r', '3']
    )

    assert result.exit_code == 0, result.output
    assert seen['dry'] is True
    assert seen['skip_slow'] is True
    assert seen['fail_fast'] is True
    assert seen['runs'] == 3


# What `compute_time_limits` does with the flag.


def _solution(name: str, outcome: ExpectedOutcome) -> Solution:
    return Solution(path=pathlib.Path(name), language='cpp', outcome=outcome)


# `compute_time_limits` operates on the package in the cwd throughout -- it stamps
# the estimate with `estimation_checksum.compute()`, which reads the solutions off
# disk -- so these need a real package under the cwd even though every step they
# assert on is mocked out.
async def _compute(
    tmp_path: pathlib.Path,
    run_all: bool,
    lower: Optional[List[Solution]] = None,
    remaining_ok: bool = True,
    run_remaining: Optional[mock.AsyncMock] = None,
    **kwargs,
):
    lower = lower or [_solution('sols/ac.cpp', ExpectedOutcome.ACCEPTED)]
    # Taken from the caller when it has to outlive the call -- `compute_time_limits`
    # raises on a failing extra run, so the test asserting that cannot read the mock
    # off the return value.
    if run_remaining is None:
        run_remaining = mock.AsyncMock(return_value=remaining_ok)

    async def _estimate_and_validate(*_, **__):
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.package.get_main_solution', return_value=lower[0]),
        mock.patch(
            'rbx.box.timing._run_for_inference',
            mock.AsyncMock(return_value=mock.Mock(result=mock.Mock())),
        ),
        mock.patch(
            'rbx.box.timing.build_estimation_context',
            mock.AsyncMock(return_value=mock.Mock()),
        ),
        mock.patch('rbx.box.timing._estimate_and_validate', _estimate_and_validate),
        mock.patch('rbx.box.timing.get_inference_solutions', return_value=lower),
        mock.patch('rbx.box.timing._run_remaining', run_remaining),
        mock.patch(
            'rbx.box.package.get_limits_file', return_value=tmp_path / 'local.yml'
        ),
        mock.patch('rbx.box.limits_info.render_limits_table'),
    ):
        profile = await timing.compute_time_limits(
            check=False, detailed=False, run_all=run_all, **kwargs
        )
    return profile, run_remaining


async def test_the_extra_run_only_happens_when_asked(
    tmp_path: pathlib.Path, testing_pkg: testing_package.TestingPackage
):
    _, run_remaining = await _compute(tmp_path, run_all=False)

    assert not run_remaining.called


async def test_the_solutions_the_estimate_ran_are_not_run_again(
    tmp_path: pathlib.Path, testing_pkg: testing_package.TestingPackage
):
    lower = [_solution('sols/ac.cpp', ExpectedOutcome.ACCEPTED)]

    _, run_remaining = await _compute(tmp_path, run_all=True, lower=lower)

    assert run_remaining.called
    already_run = run_remaining.call_args.args[1]
    assert 'sols/ac.cpp' in already_run


async def test_a_failing_extra_run_fails_the_command(
    tmp_path: pathlib.Path, testing_pkg: testing_package.TestingPackage
):
    import typer

    run_remaining = mock.AsyncMock(return_value=False)
    with pytest.raises(typer.Exit) as exc:
        await _compute(tmp_path, run_all=True, run_remaining=run_remaining)

    # Asserted so the test cannot pass on an exit raised before the extra run ever
    # happened -- which is exactly how it kept passing while #844 was open.
    assert run_remaining.called
    assert exc.value.exit_code == 1


async def test_a_passing_extra_run_still_returns_the_profile(
    tmp_path: pathlib.Path, testing_pkg: testing_package.TestingPackage
):
    profile, _ = await _compute(tmp_path, run_all=True)

    assert profile is not None
    assert profile.timeLimit == 1000
