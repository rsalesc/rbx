"""`-b` and `--keep-checker-stderr` reach every run `rbx time` performs.

Both are `rbx run` flags about *how a run is reported and what it leaves behind*
rather than about what is measured, so they carry over unchanged -- and they
carry over to all three phases, not only to the one `--run-all` adds: a setter
asking what the package costs to judge means the whole package, and a checker's
stderr is worth keeping wherever the checker ran.

The `rbx run` flags that deliberately do *not* carry over are pinned in
`test_timing_run_flags_omitted.py`.
"""

import asyncio
import pathlib
from typing import List
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import benchmark, cli, timing, timing_validation
from rbx.box.schema import ExpectedOutcome, Solution, TimingMultipliers
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


# How the flags reach `compute_time_limits`.


def test_the_benchmark_level_is_off_by_default(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['preship'])

    assert result.exit_code == 0, result.output
    assert seen['benchmark_level'] is benchmark.BenchmarkLevel.NONE
    assert seen['keep_checker_stderr'] is False


def test_preship_takes_the_benchmark_flag(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['preship', '-b', '1'])

    assert result.exit_code == 0, result.output
    assert seen['benchmark_level'] is benchmark.BenchmarkLevel.SOLUTIONS


def test_time_takes_the_benchmark_flag(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['time', '--auto', '--benchmark', '1'])

    assert result.exit_code == 0, result.output
    assert seen['benchmark_level'] is benchmark.BenchmarkLevel.SOLUTIONS


def test_an_unimplemented_benchmark_level_is_refused(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    # Same rule as `rbx run`: silently treating `-b2` as `-b1` would hand back a
    # report quietly missing half of what was asked for.
    result, _ = _invoke(runner, ['preship', '-b', '2'])

    assert result.exit_code != 0
    assert 'not implemented yet' in result.output


def test_preship_takes_keep_checker_stderr(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['preship', '--keep-checker-stderr'])

    assert result.exit_code == 0, result.output
    assert seen['keep_checker_stderr'] is True


def test_time_takes_keep_checker_stderr(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    result, seen = _invoke(runner, ['time', '--auto', '--keep-checker-stderr'])

    assert result.exit_code == 0, result.output
    assert seen['keep_checker_stderr'] is True


# How they reach each of the three phases.


def _solution(
    name: str,
    language: str = 'cpp',
    outcome: ExpectedOutcome = ExpectedOutcome.WRONG_ANSWER,
) -> Solution:
    return Solution(path=pathlib.Path(name), language=language, outcome=outcome)


def _profile() -> timing.TimingProfile:
    return timing.TimingProfile(
        timeLimit=1000,
        multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
    )


class _Phase:
    def __init__(self, run_solutions, print_run_report):
        self.run_solutions = run_solutions
        self.print_run_report = print_run_report

    @property
    def kept_checker_stderr(self):
        return self.run_solutions.call_args.kwargs['keep_checker_stderr']

    @property
    def benchmark_level(self):
        return self.print_run_report.call_args.kwargs['benchmark_level']


def _phase_mocks(solutions: List[Solution], report_ok: bool = True):
    result = mock.Mock()
    result.skeleton.solutions = list(solutions)
    result.close = mock.AsyncMock()
    return result, (
        mock.patch('rbx.box.package.get_solutions', return_value=solutions),
        mock.patch('rbx.box.timing.run_solutions', return_value=result),
        mock.patch('rbx.box.timing.print_run_report', return_value=report_ok),
        mock.patch('rbx.box.timing.consume_and_key_evaluation_items', return_value={}),
        mock.patch(
            'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
        ),
    )


async def _run_phase(coro_factory, solutions: List[Solution]) -> _Phase:
    result, patches = _phase_mocks(solutions)
    with (
        patches[0],
        patches[1] as mock_run_solutions,
        patches[2] as mock_print_run_report,
        patches[3],
        patches[4],
    ):
        await coro_factory()
    del result
    return _Phase(mock_run_solutions, mock_print_run_report)


async def test_the_remaining_run_carries_both_flags():
    solutions = [_solution('sols/wa.cpp')]

    phase = await _run_phase(
        lambda: timing._run_remaining(  # noqa: SLF001
            _profile(),
            set(),
            check=False,
            detailed=False,
            runs=0,
            benchmark_level=benchmark.BenchmarkLevel.SOLUTIONS,
            keep_checker_stderr=True,
        ),
        solutions,
    )

    assert phase.kept_checker_stderr is True
    assert phase.benchmark_level is benchmark.BenchmarkLevel.SOLUTIONS


async def test_the_upper_bound_check_carries_both_flags():
    slow = _solution('sols/slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED)

    phase = await _run_phase(
        lambda: timing._validate_upper_bound(  # noqa: SLF001
            _profile(),
            [slow],
            timing_validation.SlowKnowledge(),
            check=False,
            detailed=False,
            runs=0,
            benchmark_level=benchmark.BenchmarkLevel.SOLUTIONS,
            keep_checker_stderr=True,
        ),
        [slow],
    )

    assert phase.kept_checker_stderr is True
    assert phase.benchmark_level is benchmark.BenchmarkLevel.SOLUTIONS


async def test_the_estimation_run_carries_both_flags():
    accepted = _solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED)

    with (
        mock.patch('rbx.box.timing.get_inference_solutions', return_value=[accepted]),
        mock.patch(
            'rbx.box.timing._diagnose_inference_run', mock.AsyncMock(return_value=None)
        ),
        mock.patch('rbx.box.timing._report_inference_diagnosis', return_value=True),
        mock.patch('rbx.box.timing._resolve_inference_strategy') as strategy,
    ):
        strategy.return_value.inferenceTimeout = 10_000
        phase = await _run_phase(
            lambda: timing._run_for_inference(  # noqa: SLF001
                check=False,
                detailed=False,
                runs=0,
                formula=None,
                benchmark_level=benchmark.BenchmarkLevel.SOLUTIONS,
                keep_checker_stderr=True,
            ),
            [accepted],
        )

    assert phase.kept_checker_stderr is True
    assert phase.benchmark_level is benchmark.BenchmarkLevel.SOLUTIONS
