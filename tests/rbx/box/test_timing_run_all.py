"""`rbx time --run-all` runs, at the estimated limit, whatever the estimate did not.

The estimation phase runs the solutions that bound the limit from below and the
validation phase runs the ones that bound it from above -- so between them they
leave every other solution unrun, and the slow ones they were able to skip.
This phase picks those up, which is what makes `rbx time --run-all` a full
verification of the problem rather than only of its limit.
"""

import pathlib
from typing import Dict, List, Optional
from unittest import mock

from rbx.box import timing, timing_validation
from rbx.box.runners.base import RunPurpose
from rbx.box.schema import ExpectedOutcome, Solution, TimingMultipliers
from rbx.box.solutions import fail_fast_abort_predicate


def _solution(
    name: str,
    language: str = 'cpp',
    outcome: ExpectedOutcome = ExpectedOutcome.WRONG_ANSWER,
) -> Solution:
    return Solution(path=pathlib.Path(name), language=language, outcome=outcome)


def _profile(
    time_limit: int = 1000,
    per_language: Optional[Dict[str, int]] = None,
) -> timing.TimingProfile:
    return timing.TimingProfile(
        timeLimit=time_limit,
        timeLimitPerLanguage=per_language or {},
        multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
    )


class _Run:
    """One mocked run of the remaining solutions."""

    def __init__(self):
        self.run_solutions = None
        self.print_run_report = None
        self.ok = None

    @property
    def tracked(self) -> List[str]:
        return list(self.run_solutions.call_args.kwargs['tracked_solutions'])

    @property
    def kwargs(self):
        return self.run_solutions.call_args.kwargs

    @property
    def report_kwargs(self):
        return self.print_run_report.call_args.kwargs

    @property
    def ran(self) -> bool:
        return self.run_solutions.called


async def _run_remaining(
    solutions: List[Solution],
    already_run: List[str],
    profile: Optional[timing.TimingProfile] = None,
    report_ok: bool = True,
    **kwargs,
) -> _Run:
    run = _Run()
    result = mock.Mock()
    result.skeleton.solutions = list(solutions)
    result.close = mock.AsyncMock()
    with (
        mock.patch('rbx.box.package.get_solutions', return_value=solutions),
        mock.patch(
            'rbx.box.timing.run_solutions', return_value=result
        ) as mock_run_solutions,
        mock.patch(
            'rbx.box.timing.print_run_report', return_value=report_ok
        ) as mock_print_run_report,
        mock.patch(
            'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
        ),
    ):
        run.run_solutions = mock_run_solutions
        run.print_run_report = mock_print_run_report
        run.ok = await timing._run_remaining(  # noqa: SLF001
            profile if profile is not None else _profile(),
            set(already_run),
            check=False,
            detailed=False,
            runs=0,
            **kwargs,
        )
    return run


async def test_only_the_solutions_that_did_not_run_are_run():
    solutions = [
        _solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED),
        _solution('sols/slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED),
        _solution('sols/wa.cpp'),
    ]

    run = await _run_remaining(solutions, already_run=['sols/ac.cpp'])

    assert run.tracked == ['sols/slow.cpp', 'sols/wa.cpp']


async def test_a_slow_solution_the_validation_skipped_is_picked_up():
    # `--skip-slow`, a missing `timeLimitToTle` or a question `SlowKnowledge`
    # already answered all leave a slow solution unrun. It is a solution like
    # any other here.
    solutions = [
        _solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED),
        _solution('sols/slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED),
    ]

    run = await _run_remaining(solutions, already_run=['sols/ac.cpp'])

    assert run.tracked == ['sols/slow.cpp']


async def test_nothing_runs_when_every_solution_already_ran():
    solutions = [_solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED)]

    run = await _run_remaining(solutions, already_run=['sols/ac.cpp'])

    assert not run.ran
    assert run.ok


async def test_each_language_runs_at_its_own_estimated_limit():
    solutions = [
        _solution('sols/wa.cpp', language='cpp'),
        _solution('sols/wa.java', language='java'),
    ]

    run = await _run_remaining(
        solutions,
        already_run=[],
        profile=_profile(time_limit=1000, per_language={'java': 3000}),
    )

    assert run.kwargs['timelimit_override'] == {'cpp': 1000, 'java': 3000}


async def test_a_language_without_its_own_limit_runs_at_the_base_limit():
    # The override is a mapping, and `resolve_timelimit_override` falls back to
    # the *profile on disk* for a language it does not mention -- which is the
    # limit this estimate is replacing. Every language present must be named.
    solutions = [_solution('sols/wa.cpp', language='cpp')]

    run = await _run_remaining(
        solutions, already_run=[], profile=_profile(time_limit=1234)
    )

    assert run.kwargs['timelimit_override'] == {'cpp': 1234}


async def test_it_is_a_plain_run():
    solutions = [_solution('sols/wa.cpp')]

    run = await _run_remaining(solutions, already_run=[])

    assert run.kwargs['purpose'] is RunPurpose.RUN


async def test_without_fail_fast_the_run_stops_on_nothing():
    solutions = [_solution('sols/wa.cpp')]

    run = await _run_remaining(solutions, already_run=[])

    assert run.kwargs['abort_on'] is None
    assert run.report_kwargs['timing'] is True


async def test_fail_fast_stops_a_solution_at_its_first_bad_verdict():
    solutions = [_solution('sols/wa.cpp')]

    run = await _run_remaining(solutions, already_run=[], fail_fast=True)

    assert run.kwargs['abort_on'] is fail_fast_abort_predicate


async def test_fail_fast_drops_the_timing_summary():
    # A solution that stopped early was not timed on the testcases that never
    # ran, so every extreme in the summary would be a lower bound.
    solutions = [_solution('sols/wa.cpp')]

    run = await _run_remaining(solutions, already_run=[], fail_fast=True)

    assert run.report_kwargs['timing'] is False


async def test_a_solution_that_misbehaves_fails_the_phase():
    solutions = [_solution('sols/wa.cpp')]

    run = await _run_remaining(solutions, already_run=[], report_ok=False)

    assert not run.ok


async def test_the_batch_is_closed_even_when_the_run_fails():
    solutions = [_solution('sols/wa.cpp')]
    result = mock.Mock()
    result.skeleton.solutions = list(solutions)
    result.close = mock.AsyncMock()

    with (
        mock.patch('rbx.box.package.get_solutions', return_value=solutions),
        mock.patch('rbx.box.timing.run_solutions', return_value=result),
        mock.patch('rbx.box.timing.print_run_report', side_effect=RuntimeError('boom')),
        mock.patch(
            'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
        ),
    ):
        try:
            await timing._run_remaining(  # noqa: SLF001
                _profile(), set(), check=False, detailed=False, runs=0
            )
        except RuntimeError:
            pass

    result.close.assert_awaited()


# The ledger: which solutions the estimate actually executed. `--run-all` runs
# the complement of it, so it has to be recorded where the runs happen rather
# than guessed back from the roles -- the validation phase skips slow solutions
# for several reasons, and none of them is visible in `problem.rbx.yml`.


async def test_the_validation_phase_records_what_it_ran():
    slow = _solution('sols/slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    ledger = set()
    result = mock.Mock()
    result.skeleton.solutions = [slow]
    result.close = mock.AsyncMock()

    with (
        mock.patch('rbx.box.timing.run_solutions', return_value=result),
        mock.patch('rbx.box.timing.print_run_report', return_value=True),
        mock.patch('rbx.box.timing.consume_and_key_evaluation_items', return_value={}),
        mock.patch(
            'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
        ),
    ):
        await timing._validate_upper_bound(  # noqa: SLF001
            _profile(),
            [slow],
            timing_validation.SlowKnowledge(),
            check=False,
            detailed=False,
            runs=0,
            ran=ledger,
        )

    assert ledger == {'sols/slow.cpp'}


async def test_a_slow_solution_the_validation_never_ran_stays_off_the_ledger():
    # Its answer was already known, so `SlowKnowledge` skipped it -- and that is
    # exactly the case `--run-all` exists to pick up.
    slow = _solution('sols/slow.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_timeout('sols/slow.cpp', 10_000)
    ledger = set()

    with (
        mock.patch('rbx.box.timing.run_solutions') as mock_run_solutions,
        mock.patch(
            'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
        ),
    ):
        await timing._validate_upper_bound(  # noqa: SLF001
            _profile(),
            [slow],
            knowledge,
            check=False,
            detailed=False,
            runs=0,
            ran=ledger,
        )

    assert not mock_run_solutions.called
    assert ledger == set()
