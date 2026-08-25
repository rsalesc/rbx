"""Telling a backend that nothing more will be asked of it.

A backend may dispatch work **ahead** of the consumer -- that is the whole point
of a per-solution seam over a remote judge -- so a run that ends early leaves
jobs in flight whose results nobody will ever read. `RunSolutionResult.close`
is where they are dropped, and *when* it is called is the entire design: after
the deferreds are consumed, from a `finally`, never from inside `run_solutions`
(which returns before a single deferred resolves -- the mistake the removed
`finalize` hook made).

So these tests are mostly about the call sites: every consumer of a run must
close it, and must close it even when it is leaving by way of an exception.
"""

import asyncio
import pathlib
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import builder, cli, timing, timing_validation
from rbx.box.deferred import Deferred
from rbx.box.environment import (
    TimingConfig,
    TimingMultipliers,
    VerificationLevel,
)
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.runners.base import RunContext, RunnerCapabilities
from rbx.box.runners.local import LocalRunner
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.box.solutions import (
    RunSolutionResult,
    SolutionSkeleton,
    run_solutions,
)
from rbx.box.testing import testing_package
from rbx.grading import steps
from rbx.grading.steps import CheckerResult, Evaluation, Outcome

pytestmark = pytest.mark.shared_cache


class ClosingRunner:
    """A backend that records how often it was told the run was over.

    Runs nothing: `run_solution` hands back deferreds over canned verdicts, which
    is all any of these tests need -- what is under test is the call site, not the
    execution.
    """

    name = 'closing'
    caps = RunnerCapabilities(supports_nruns=False)

    def __init__(self) -> None:
        self.closed = 0

    async def prepare(self, ctx: RunContext) -> None:
        return None

    def run_solution(
        self,
        solution: SolutionSkeleton,
        entries: List[GenerationTestcaseEntry],
        ctx: RunContext,
    ) -> List[Deferred[Evaluation]]:
        def make(entry: GenerationTestcaseEntry) -> Deferred[Evaluation]:
            async def run_fn() -> Evaluation:
                return Evaluation(
                    result=CheckerResult(outcome=Outcome.ACCEPTED),
                    testcase=steps.TestcaseIO(index=entry.group_entry.index),
                    log=steps.TestcaseLog(exitcode=0, exitstatus='ok'),
                )

            return Deferred(run_fn)

        return [make(entry) for entry in entries]

    async def close(self) -> None:
        self.closed += 1


# -- the result knows its backend ----------------------------------------------


@pytest.mark.test_pkg('problems/abort-groups')
async def test_a_run_carries_the_backend_that_produced_it(
    pkg_from_testdata: pathlib.Path,
):
    """Without this, the consumer has nothing to close: it holds the result, and
    only `run_solutions` ever sees the runner."""
    runner = ClosingRunner()

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=runner,
    )

    assert result.runner is runner
    await result.close()
    assert runner.closed == 1


async def test_a_result_built_without_a_run_has_nothing_to_close():
    """Reports are also built from results nothing produced (the timing tests do
    exactly that), and closing one must not go looking for a backend."""
    await RunSolutionResult(skeleton=mock.Mock(), items=[]).close()


async def test_the_local_backend_takes_a_close_and_does_nothing():
    """Every consumer closes, including the ones that only ever run locally, so
    the no-op has to really be one -- twice over, since `close` is idempotent."""
    local = LocalRunner()

    assert await local.close() is None
    assert await local.close() is None


# -- every consumer closes, and closes on the way out too -----------------------


async def _ok(*args, **kwargs):
    return True


def _recording_result() -> RunSolutionResult:
    return RunSolutionResult(skeleton=mock.Mock(), items=[], runner=ClosingRunner())


def _closes(result: RunSolutionResult) -> int:
    runner = result.runner
    assert isinstance(runner, ClosingRunner)
    return runner.closed


async def test_verify_closes_the_run_it_reported(monkeypatch):
    result = _recording_result()

    async def run_solutions_stub(**kwargs):
        return result

    with (
        mock.patch('rbx.box.builder.build', _ok),
        mock.patch('rbx.box.builder.run_solutions', run_solutions_stub),
        mock.patch('rbx.box.builder.print_run_report', _ok),
    ):
        assert await builder.verify(VerificationLevel.ALL_SOLUTIONS.value)

    assert _closes(result) == 1


async def test_verify_closes_the_run_even_when_the_report_blows_up():
    """The case that matters: the report stopping early is exactly when a backend
    still has jobs in flight for solutions nobody will now look at."""
    result = _recording_result()

    async def run_solutions_stub(**kwargs):
        return result

    async def exploding_report(*args, **kwargs):
        raise RuntimeError('boom')

    with (
        mock.patch('rbx.box.builder.build', _ok),
        mock.patch('rbx.box.builder.run_solutions', run_solutions_stub),
        mock.patch('rbx.box.builder.print_run_report', exploding_report),
        pytest.raises(RuntimeError),
    ):
        await builder.verify(VerificationLevel.ALL_SOLUTIONS.value)

    assert _closes(result) == 1


@pytest.fixture
def cli_runner() -> CliRunner:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


@pytest.fixture(autouse=True)
def _skip_preset_check():
    # The root Typer callback checks the active preset's compatibility, which has
    # nothing to do with teardown and fails for a bare testing package.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


def _invoke_run(
    cli_runner: CliRunner, result: RunSolutionResult, report: Optional[Any] = None
):
    async def run_solutions_stub(**kwargs):
        return result

    with (
        mock.patch('rbx.box.builder.build', _ok),
        mock.patch('rbx.box.cli.commands.run.run_solutions', run_solutions_stub),
        mock.patch('rbx.box.cli.commands.run.print_run_report', report or _ok),
    ):
        return cli_runner.invoke(cli.app, ['run'])


def test_rbx_run_closes_the_run_it_reported(
    cli_runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result = _recording_result()

    invocation = _invoke_run(cli_runner, result)

    assert invocation.exit_code == 0, invocation.output
    assert _closes(result) == 1


def test_rbx_run_closes_the_run_even_when_the_report_blows_up(
    cli_runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    result = _recording_result()

    async def exploding_report(*args, **kwargs):
        raise RuntimeError('boom')

    invocation = _invoke_run(cli_runner, result, report=exploding_report)

    assert invocation.exit_code != 0
    assert _closes(result) == 1


async def _estimate(
    pkg: testing_package.TestingPackage,
    result: RunSolutionResult,
    report: Optional[Any] = None,
):
    """One `compute_time_limits` over a stubbed run, returning what it returned.

    Everything past the run itself is stubbed: what is under test is that the run
    gets closed, not what is estimated from it.
    """
    solution = Solution(
        path=pkg.path('ac.cpp'), language='cpp', outcome=ExpectedOutcome.ACCEPTED
    )
    result.skeleton.solutions = [solution]
    # The estimation phase always diagnoses its run now, and the diagnosis keys
    # the evaluations off the skeleton. Nothing ran, so there is nothing to key.
    result.skeleton.empty_structured_evaluation.return_value = {}

    async def run_solutions_stub(**kwargs):
        return result

    async def estimate_and_validate_stub(*args, **kwargs):
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.package.get_main_solution', return_value=mock.Mock()),
        mock.patch('rbx.box.timing.get_inference_solutions', return_value=[solution]),
        mock.patch('rbx.box.timing.run_solutions', run_solutions_stub),
        mock.patch('rbx.box.timing.print_run_report', report or _ok),
        # Both phases past the estimation run are stubbed out together: what is
        # under test is that the run gets closed, not what is estimated from it
        # or what the validation phase then does with the estimate.
        mock.patch('rbx.box.timing.build_estimation_context', return_value=mock.Mock()),
        mock.patch(
            'rbx.box.timing._estimate_and_validate',  # noqa: SLF001
            estimate_and_validate_stub,
        ),
        mock.patch('rbx.box.environment.get_environment') as mock_env,
    ):
        mock_env.return_value.timing = TimingConfig(
            multipliers=TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=7000)
        )
        return await timing.compute_time_limits(check=True, detailed=False, auto=True)


async def test_the_estimation_run_closes_its_backend(
    testing_pkg: testing_package.TestingPackage,
):
    result = _recording_result()

    assert await _estimate(testing_pkg, result) is not None

    assert _closes(result) == 1


async def test_the_estimation_run_closes_its_backend_when_the_report_blows_up(
    testing_pkg: testing_package.TestingPackage,
):
    result = _recording_result()

    async def exploding_report(*args, **kwargs):
        raise RuntimeError('boom')

    with pytest.raises(RuntimeError):
        await _estimate(testing_pkg, result, report=exploding_report)

    assert _closes(result) == 1


async def test_the_estimation_run_closes_its_backend_when_the_run_is_rejected(
    testing_pkg: testing_package.TestingPackage,
):
    """A report that says the run failed ends the estimate too, and it ends it by
    returning rather than by raising -- a second way out of the same function."""
    result = _recording_result()

    async def failing_report(*args, **kwargs):
        return False

    assert await _estimate(testing_pkg, result, report=failing_report) is None

    assert _closes(result) == 1


async def _estimated_profile(*args, **kwargs):
    """Everything past the estimation run, stubbed to a settled profile.

    `rbx time` runs in two phases and this file is about neither of them: what is
    under test is that the backend the setter chose reaches the run and is closed
    after it. Stubbing the pair together keeps that from depending on what the
    picker or the upper-bound check would have done.
    """
    return timing.TimingProfile(timeLimit=1000)


# -- what the estimation run hands the backend ---------------------------------


async def test_the_chosen_backend_reaches_the_run(
    testing_pkg: testing_package.TestingPackage,
):
    """`--runner` is only worth anything if the object it resolves to is the one
    that ends up running the solutions."""
    result = _recording_result()
    chosen = ClosingRunner()

    calls: Dict[str, Any] = {}

    async def run_solutions_stub(**kwargs):
        calls.update(kwargs)
        return result

    solution = Solution(
        path=testing_pkg.path('ac.cpp'),
        language='cpp',
        outcome=ExpectedOutcome.ACCEPTED,
    )
    result.skeleton.solutions = [solution]
    result.skeleton.empty_structured_evaluation.return_value = {}

    with (
        mock.patch('rbx.box.package.get_main_solution', return_value=mock.Mock()),
        mock.patch('rbx.box.timing.get_inference_solutions', return_value=[solution]),
        mock.patch('rbx.box.timing.run_solutions', run_solutions_stub),
        mock.patch('rbx.box.timing.print_run_report', _ok),
        mock.patch('rbx.box.timing.build_estimation_context', return_value=mock.Mock()),
        mock.patch(
            'rbx.box.timing._estimate_and_validate',  # noqa: SLF001
            _estimated_profile,
        ),
        mock.patch('rbx.box.environment.get_environment') as mock_env,
    ):
        mock_env.return_value.timing = TimingConfig(
            multipliers=TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=7000)
        )
        await timing.compute_time_limits(
            check=True, detailed=False, auto=True, runner=chosen
        )

    assert calls['runner'] is chosen


async def test_no_backend_asked_for_means_the_run_picks_its_own(
    testing_pkg: testing_package.TestingPackage,
):
    """`None` is not a special case to handle downstream: it is what
    `run_solutions` already reads as "the local sandbox"."""
    result = _recording_result()
    calls: Dict[str, Any] = {}

    async def run_solutions_stub(**kwargs):
        calls.update(kwargs)
        return result

    solution = Solution(
        path=testing_pkg.path('ac.cpp'),
        language='cpp',
        outcome=ExpectedOutcome.ACCEPTED,
    )
    result.skeleton.solutions = [solution]
    result.skeleton.empty_structured_evaluation.return_value = {}

    with (
        mock.patch('rbx.box.package.get_main_solution', return_value=mock.Mock()),
        mock.patch('rbx.box.timing.get_inference_solutions', return_value=[solution]),
        mock.patch('rbx.box.timing.run_solutions', run_solutions_stub),
        mock.patch('rbx.box.timing.print_run_report', _ok),
        mock.patch('rbx.box.timing.build_estimation_context', return_value=mock.Mock()),
        mock.patch(
            'rbx.box.timing._estimate_and_validate',  # noqa: SLF001
            _estimated_profile,
        ),
        mock.patch('rbx.box.environment.get_environment') as mock_env,
    ):
        mock_env.return_value.timing = TimingConfig(
            multipliers=TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=7000)
        )
        await timing.compute_time_limits(check=True, detailed=False, auto=True)

    assert calls['runner'] is None


# -- what the validation phase hands the backend -------------------------------


async def test_the_validation_phase_runs_on_the_same_backend(
    testing_pkg: testing_package.TestingPackage,
):
    """Phase 2 checks the estimate against the solutions expected to be too slow.

    It must do that on the backend the estimate was measured on: a limit derived
    from timings taken on a judge, then checked in the local sandbox, is not
    checked at all -- the two machines disagree by exactly the factor `rbx time`
    exists to measure.
    """
    result = _recording_result()
    chosen = ClosingRunner()
    calls: Dict[str, Any] = {}

    async def run_solutions_stub(**kwargs):
        calls.update(kwargs)
        return result

    slow = Solution(
        path=testing_pkg.path('slow.cpp'),
        language='cpp',
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
    )
    result.skeleton.solutions = [slow]
    result.skeleton.empty_structured_evaluation.return_value = {}

    profile = timing.TimingProfile(
        timeLimit=100,
        multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
    )

    with (
        mock.patch('rbx.box.timing.run_solutions', run_solutions_stub),
        mock.patch('rbx.box.timing.print_run_report', _ok),
        mock.patch('rbx.box.timing.find_language_name', return_value='cpp'),
    ):
        await timing._validate_upper_bound(  # noqa: SLF001
            profile,
            [slow],
            timing_validation.SlowKnowledge(),
            check=True,
            detailed=False,
            runs=0,
            runner=chosen,
        )

    assert calls['runner'] is chosen
    # `ceil(100 * 1.5)`: the bound this solution has to clear, per language.
    assert calls['timelimit_override'] == {'cpp': 150}
    # And the batch ends here too, not at the end of the command: the picker may
    # re-open right after, and this loop can run several times.
    assert _closes(result) == 1
