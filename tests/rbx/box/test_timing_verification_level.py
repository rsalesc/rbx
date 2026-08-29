"""The verification level each `rbx time` phase runs at.

Two of the three phases measure, and the level they run at is part of what they
measure: FULL is the only level that turns `isDoubleTL` on, and a doubled cap is
a doubled `inferenceTimeout` in the estimation phase and a doubled probe limit in
the upper-bound check. The remaining-solutions phase measures nothing -- it
judges, against the limit the other two produced -- so it runs at FULL, like
`rbx run`, and gets the 2x-TL diagnostics `rbx run` reports.

Pinned here because the difference between the phases is deliberate and invisible
from the call sites alone.
"""

import pathlib
from typing import List
from unittest import mock

from rbx.box import benchmark, timing, timing_validation
from rbx.box.environment import VerificationLevel
from rbx.box.schema import ExpectedOutcome, Solution, TimingMultipliers
from rbx.box.tasks import get_limits_for_language


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
    """What a phase asked of `run_solutions` and of the report."""

    def __init__(self, run_solutions, print_run_report):
        self.run_solutions = run_solutions
        self.print_run_report = print_run_report

    @property
    def ran_at(self) -> VerificationLevel:
        return self.run_solutions.call_args.kwargs['verification']

    @property
    def reported_at(self) -> VerificationLevel:
        # Third positional of `print_run_report`.
        return self.print_run_report.call_args.args[2]

    @property
    def skipped_printing_limits(self) -> bool:
        return self.print_run_report.call_args.kwargs['skip_printing_limits']


async def _run_phase(coro_factory, solutions: List[Solution]) -> _Phase:
    result = mock.Mock()
    result.skeleton.solutions = list(solutions)
    result.close = mock.AsyncMock()
    with (
        mock.patch('rbx.box.package.get_solutions', return_value=solutions),
        mock.patch(
            'rbx.box.timing.run_solutions', return_value=result
        ) as mock_run_solutions,
        mock.patch(
            'rbx.box.timing.print_run_report', return_value=True
        ) as mock_print_run_report,
        mock.patch('rbx.box.timing.consume_and_key_evaluation_items', return_value={}),
        mock.patch(
            'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
        ),
    ):
        await coro_factory()
    return _Phase(mock_run_solutions, mock_print_run_report)


async def _remaining_phase() -> _Phase:
    return await _run_phase(
        lambda: timing._run_remaining(  # noqa: SLF001
            _profile(),
            set(),
            check=False,
            detailed=False,
            runs=0,
            benchmark_level=benchmark.BenchmarkLevel.NONE,
        ),
        [_solution('sols/wa.cpp')],
    )


async def test_the_remaining_run_runs_at_full():
    # The solutions the estimate never needed -- every `wrong-answer`, every
    # `rte`, every slow one `--skip-slow` let through -- are judged here exactly
    # as `rbx run` would judge them.
    phase = await _remaining_phase()

    assert phase.ran_at is VerificationLevel.FULL


async def test_the_remaining_run_is_reported_at_the_level_it_ran_at():
    # The report reads this both for the `>TL ms` formatting and for the
    # double-TL verdict logic, so reporting a level the run did not use would
    # describe a run that did not happen.
    phase = await _remaining_phase()

    assert phase.reported_at is VerificationLevel.FULL


async def test_the_remaining_run_prints_the_limits_it_judged_against():
    # Unlike the two phases above, whose caps are internal to the estimation,
    # this one judges against the limit the setter is about to ship -- so the
    # limits table, and with it the `Running with 2*TL` warning, is printed.
    phase = await _remaining_phase()

    assert phase.skipped_printing_limits is False


async def test_the_upper_bound_check_stays_below_full():
    # It probes at `TL x timeLimitToTle` and feeds the measured time into
    # `violates_upper_bound`. Doubling that cap changes what it concludes.
    slow = _solution('sols/slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED)

    phase = await _run_phase(
        lambda: timing._validate_upper_bound(  # noqa: SLF001
            _profile(),
            [slow],
            timing_validation.SlowKnowledge(),
            check=False,
            detailed=False,
            runs=0,
            benchmark_level=benchmark.BenchmarkLevel.NONE,
        ),
        [slow],
    )

    assert phase.ran_at is timing._INFERENCE_VERIFICATION  # noqa: SLF001
    assert phase.ran_at.value < VerificationLevel.FULL.value


async def test_the_estimation_run_stays_below_full():
    # Its cap is the `inferenceTimeout` the accepted solutions are measured
    # against. Doubling it doubles the very bound the measurement rests on.
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
                benchmark_level=benchmark.BenchmarkLevel.NONE,
            ),
            [accepted],
        )

    assert phase.ran_at is timing._INFERENCE_VERIFICATION  # noqa: SLF001
    assert phase.ran_at.value < VerificationLevel.FULL.value


def test_full_is_what_turns_double_tl_on(testing_pkg):
    # What the levels above actually buy, stated once so the assertions on them
    # are readable: only FULL doubles the sandbox limit.
    assert (
        get_limits_for_language(
            'cpp', VerificationLevel.FULL, timelimit_override=None
        ).isDoubleTL
        is True
    )
    assert (
        get_limits_for_language(
            'cpp',
            timing._INFERENCE_VERIFICATION,  # noqa: SLF001
            timelimit_override=None,
        ).isDoubleTL
        is False
    )
