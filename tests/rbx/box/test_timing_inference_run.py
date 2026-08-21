"""How ``compute_time_limits`` drives the estimation run.

The whole behavior of the inference run lives in the arguments handed to
``run_solutions`` (which solutions are tracked, and under which cap) and in the
diagnostics derived from their verdicts, so that is what these tests assert on.
"""

import pathlib
import re
from typing import Dict, List, Optional
from unittest import mock

import pytest
import rich.console

from rbx.box import limits_info, timing
from rbx.box.deferred import Deferred
from rbx.box.environment import TimingConfig, VerificationLevel
from rbx.box.schema import (
    ExpectedOutcome,
    Solution,
    TimingGroupOrigin,
    TimingGroupReport,
    TimingMultipliers,
)
from rbx.box.solutions import _gates_report  # noqa: SLF001
from rbx.box.testing import testing_package
from rbx.box.timing import (
    _diagnose_inference_run,  # noqa: SLF001
    _timings_per_language,  # noqa: SLF001
)
from rbx.grading.steps import Outcome


def _printed(capsys) -> str:
    """Everything printed, without ANSI escapes and re-flowed onto one line, so
    an assertion is not at the mercy of where rich wrapped a message."""
    out = capsys.readouterr().out
    out = re.sub(r'\x1b\]8;;[^\x1b]*\x1b\\\\?', '', out)  # hyperlinks
    out = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', out)  # colors
    return ' '.join(out.split())


def _solution(pkg, name: str, outcome: ExpectedOutcome, **kwargs) -> Solution:
    return Solution(path=pkg.path(name), language='cpp', outcome=outcome, **kwargs)


def _evaluation(time_ms: Optional[int], outcome: Outcome):
    log = mock.Mock()
    log.time = None if time_ms is None else time_ms / 1000
    return mock.Mock(log=log, result=mock.Mock(outcome=outcome))


def _structured(evals: Dict[Solution, List]):
    """A ``StructuredEvaluation``-shaped dict: solution path -> group -> evals."""
    res = {}
    for solution, evaluations in evals.items():
        res[str(solution.path)] = {
            'main': [Deferred(_make_eval(ev)) for ev in evaluations]
        }
    return res


def _make_eval(ev):
    async def _get():
        return ev

    return _get


class _Run:
    """One mocked ``compute_time_limits`` invocation."""

    def __init__(self):
        self.run_solutions = None
        self.print_run_report = None
        self.estimate = None
        self.build_context = None

    @property
    def strategy(self):
        return self.build_context.call_args.args[2]

    @property
    def tracked(self) -> List[str]:
        return list(self.run_solutions.call_args.kwargs['tracked_solutions'])

    @property
    def timelimit_override(self) -> int:
        return self.run_solutions.call_args.kwargs['timelimit_override']


async def _compute(
    pkg,
    *,
    timing_config: TimingConfig,
    lower: List[Solution],
    upper: Optional[List[Solution]] = None,
    structured: Optional[Dict] = None,
    formula: Optional[str] = None,
    run_report_ok: bool = True,
    estimated: Optional[timing.TimingProfile] = None,
):
    upper = upper or []
    run = _Run()
    from rbx.box.schema import InferenceRole

    def _inference_solutions(role):
        return lower if role == InferenceRole.LOWER else upper

    solution_result = mock.Mock()
    solution_result.skeleton.solutions = [*lower, *upper]

    with (
        mock.patch('rbx.box.package.get_main_solution', return_value=mock.Mock()),
        mock.patch(
            'rbx.box.timing.get_inference_solutions', side_effect=_inference_solutions
        ),
        mock.patch(
            'rbx.box.timing.run_solutions', return_value=solution_result
        ) as mock_run,
        mock.patch(
            'rbx.box.timing.print_run_report', return_value=run_report_ok
        ) as mock_report,
        mock.patch(
            'rbx.box.timing.consume_and_key_evaluation_items',
            return_value=structured or {},
        ),
        mock.patch(
            'rbx.box.timing.build_estimation_context', return_value=mock.Mock()
        ) as mock_context,
        mock.patch(
            'rbx.box.timing._estimate_and_validate',
            return_value=estimated or timing.TimingProfile(timeLimit=1000),
        ) as mock_estimate,
        mock.patch(
            'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
        ),
        mock.patch('rbx.box.environment.get_environment') as mock_env,
    ):
        mock_env.return_value.timing = timing_config
        run.run_solutions = mock_run
        run.print_run_report = mock_report
        run.estimate = mock_estimate
        run.build_context = mock_context
        result = await timing.compute_time_limits(
            check=True, detailed=False, formula=formula, auto=True
        )
    return run, result


def _group(
    time_limit: int,
    languages: Optional[List[str]] = None,
    dropped: Optional[List[Solution]] = None,
) -> TimingGroupReport:
    """One resolved language group of an estimated profile, as
    ``build_timing_profile`` records it: the group's limit and the slow solutions
    the cap stopped inside THAT group."""
    return TimingGroupReport(
        languages=languages or ['cpp'],
        timeLimit=time_limit,
        origin=TimingGroupOrigin.ESTIMATED,
        droppedUpper=[str(solution.path) for solution in dropped or []],
    )


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage):
    return testing_pkg


async def test_formula_mode_runs_only_lower_solutions_under_the_cap(pkg):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, result = await _compute(
        pkg,
        timing_config=TimingConfig(formula='slowest * 2', inferenceTimeout=7000),
        lower=[ac],
        upper=[tle],
    )
    assert run.tracked == [str(ac.path)]
    # A formula estimate has no upper bound to run the slow solutions for, but
    # the cap is a property of the estimation, not of the ratios: it still
    # bounds how long the accepted solutions may run.
    assert run.timelimit_override == 7000
    assert result is not None


async def test_multipliers_without_tle_ratio_runs_only_lower_solutions(pkg):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, _ = await _compute(
        pkg,
        timing_config=TimingConfig(
            multipliers=TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=7000)
        ),
        lower=[ac],
        upper=[tle],
    )
    assert run.tracked == [str(ac.path)]
    assert run.timelimit_override == 7000
    # Nothing about the run differs from the formula path: every solution that
    # ran still gates the report.
    assert run.print_run_report.call_args.kwargs['gating_solutions'] == set(run.tracked)


async def test_the_estimation_run_leaves_the_slow_solutions_alone(pkg):
    # Even with an upper bound to respect, the slow solutions do not run here:
    # nothing bounds how long they take, so the only limit that could stop them
    # is the cap -- which is set for the accepted solutions and says nothing
    # about the limit they are meant to bound. They are checked afterwards,
    # against the limit this run estimates.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, _ = await _compute(
        pkg,
        timing_config=TimingConfig(
            multipliers=TimingMultipliers(
                acToTimeLimit=2.0, timeLimitToTle=1.5, inferenceTimeout=7000
            )
        ),
        lower=[ac],
        upper=[tle],
        structured=_structured({ac: [_evaluation(400, Outcome.ACCEPTED)]}),
    )
    assert run.tracked == [str(ac.path)]
    assert run.timelimit_override == 7000


async def test_multipliers_with_tle_ratio_but_no_slow_solutions_still_cap(pkg):
    # The path most existing packages take once the default preset ships
    # timeLimitToTle: nothing bounds the limit from above, so there is nothing
    # to drop -- but the accepted solutions still run under the cap.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    run, result = await _compute(
        pkg,
        timing_config=TimingConfig(
            multipliers=TimingMultipliers(
                acToTimeLimit=2.0, timeLimitToTle=1.5, inferenceTimeout=7000
            )
        ),
        lower=[ac],
        upper=[],
    )
    assert run.tracked == [str(ac.path)]
    assert run.timelimit_override == 7000
    assert result is not None


async def test_custom_formula_forces_formula_mode_over_multipliers(pkg):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, _ = await _compute(
        pkg,
        timing_config=TimingConfig(
            inferenceTimeout=6000,
            multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5),
        ),
        lower=[ac],
        upper=[tle],
        formula='slowest * 3',
    )
    assert run.tracked == [str(ac.path)]
    # The custom formula overrides how the limit is derived, not the cap the
    # solutions are measured under -- that still comes from the configuration.
    assert run.timelimit_override == 6000
    assert run.strategy.formula == 'slowest * 3'


async def test_the_estimation_run_never_doubles_the_time_limit(pkg):
    # The cap exists to bound exactly the solutions doubleTL would un-bound.
    limits = limits_info.get_package_limits(VerificationLevel.ALL_SOLUTIONS)
    assert not limits.isDoubleTL


async def test_only_lower_solutions_gate_the_run_report(pkg):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, _ = await _compute(
        pkg,
        timing_config=TimingConfig(
            multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5)
        ),
        lower=[ac],
        upper=[tle],
        structured=_structured(
            {
                ac: [_evaluation(400, Outcome.ACCEPTED)],
                tle: [_evaluation(6000, Outcome.ACCEPTED)],
            }
        ),
    )
    assert run.print_run_report.call_args.kwargs['gating_solutions'] == {str(ac.path)}


async def test_a_lower_solution_at_the_cap_is_an_error(pkg, capsys):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, result = await _compute(
        pkg,
        timing_config=TimingConfig(
            multipliers=TimingMultipliers(
                acToTimeLimit=2.0, timeLimitToTle=1.5, inferenceTimeout=7000
            )
        ),
        lower=[ac],
        upper=[tle],
        structured=_structured(
            {
                ac: [_evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED)],
                tle: [_evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED)],
            }
        ),
        # The lower solution timing out also fails the report gate; the error
        # must name it either way.
        run_report_ok=False,
    )
    assert result is None
    run.estimate.assert_not_called()
    printed = _printed(capsys)
    assert '✗' in printed
    assert 'ac.cpp' in printed
    assert 'cannot bound the time limit from below' in printed


async def test_a_lower_solution_at_the_cap_is_an_error_in_formula_mode_too(pkg, capsys):
    # Nothing bounds a formula estimate from above, but a truncated measurement
    # is just as worthless there: the formula reads the measured times.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    run, result = await _compute(
        pkg,
        timing_config=TimingConfig(formula='slowest * 2', inferenceTimeout=7000),
        lower=[ac],
        upper=[],
        structured=_structured({ac: [_evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED)]}),
        run_report_ok=False,
    )
    assert result is None
    run.estimate.assert_not_called()
    printed = _printed(capsys)
    assert 'ac.cpp' in printed
    assert 'cannot bound the time limit from below' in printed
    assert '7000 ms' in printed


async def test_a_lower_solution_failing_for_a_non_timing_reason_uses_the_plain_gate(
    pkg, capsys
):
    # A wrong accepted solution is the report's job, not inference's: no
    # diagnostic claims anything about timing, and the generic gate stops it.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, result = await _compute(
        pkg,
        timing_config=TimingConfig(
            multipliers=TimingMultipliers(
                acToTimeLimit=2.0, timeLimitToTle=1.5, inferenceTimeout=7000
            )
        ),
        lower=[ac],
        upper=[tle],
        structured=_structured(
            {
                ac: [_evaluation(400, Outcome.WRONG_ANSWER)],
                tle: [_evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED)],
            }
        ),
        run_report_ok=False,
    )
    assert result is None
    run.estimate.assert_not_called()
    printed = _printed(capsys)
    assert '✗' not in printed
    assert 'Failed to run ACCEPTED solutions' in printed


async def test_a_package_with_no_lower_bound_solution_fails_before_running(pkg):
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    with pytest.raises(timing.MissingLowerBoundError):
        await _compute(
            pkg,
            timing_config=TimingConfig(
                multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5)
            ),
            lower=[],
            upper=[tle],
        )


async def _diagnose(structured: Dict) -> timing._InferenceDiagnosis:  # noqa: SLF001
    """``_diagnose_inference_run`` over an already-computed run."""
    result = mock.Mock()
    result.skeleton.solutions = list(structured)
    with mock.patch(
        'rbx.box.timing.consume_and_key_evaluation_items',
        return_value=_structured(structured),
    ):
        return await _diagnose_inference_run(result)


async def test_skipped_evaluations_do_not_truncate_a_lower_bound_solution(pkg):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    diagnosis = await _diagnose(
        {ac: [_evaluation(400, Outcome.ACCEPTED), _evaluation(None, Outcome.SKIPPED)]}
    )
    assert diagnosis == timing._InferenceDiagnosis()  # noqa: SLF001


async def test_an_aborted_lower_bound_solution_is_still_truncated(pkg):
    # The shape an aborted lower-bound run actually produces: the abort trips on
    # the very timeout that stopped the solution, so that TLE is the first
    # evaluation and every later one is skipped. Ignoring the skips must not
    # ignore the TLE with them -- an accepted solution killed at the cap leaves
    # the estimate resting on a truncated measurement, which is fatal.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    diagnosis = await _diagnose(
        {
            ac: [
                _evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED),
                _evaluation(None, Outcome.SKIPPED),
                _evaluation(None, Outcome.SKIPPED),
            ]
        }
    )
    assert diagnosis == timing._InferenceDiagnosis(truncated_lower=[ac])  # noqa: SLF001


async def test_skipped_evaluations_contribute_no_timing(pkg, capsys):
    # A skipped evaluation records no time today, but the exclusion must rest on
    # the verdict rather than on that: a testcase that never ran can never
    # measure anything, whatever its log happens to hold.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    structured = _structured(
        {
            ac: [
                _evaluation(400, Outcome.ACCEPTED),
                _evaluation(9999, Outcome.SKIPPED),
            ]
        }
    )
    with mock.patch(
        'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
    ):
        per_language = await _timings_per_language(
            rich.console.Console(), structured, [ac]
        )
    assert per_language == {'cpp': {str(ac.path): 400}}


def test_the_report_gate_ignores_solutions_outside_gating_solutions():
    # The contract compute_time_limits relies on: with no restriction every
    # solution decides the verdict; with one, only the listed solutions do.
    ac = Solution(path=pathlib.Path('ac.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    tle = Solution(
        path=pathlib.Path('tle.cpp'), outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    assert _gates_report(ac, None)
    assert _gates_report(tle, None)
    assert _gates_report(ac, {'ac.cpp'})
    assert not _gates_report(tle, {'ac.cpp'})
