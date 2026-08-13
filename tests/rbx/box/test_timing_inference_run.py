"""How ``compute_time_limits`` drives the estimation run.

The whole behavior of the inference run lives in the arguments handed to
``run_solutions`` (which solutions are tracked, and under which cap) and in the
diagnostics derived from their verdicts, so that is what these tests assert on.
"""

import pathlib
from typing import Dict, List, Optional
from unittest import mock

import pytest

from rbx.box import limits_info, timing
from rbx.box.deferred import Deferred
from rbx.box.environment import TimingConfig, VerificationLevel
from rbx.box.schema import ExpectedOutcome, Solution, TimingMultipliers
from rbx.box.solutions import _gates_report  # noqa: SLF001
from rbx.box.testing import testing_package
from rbx.grading.steps import Outcome


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
            'rbx.box.timing.estimate_time_limit',
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
        result = await timing.compute_time_limits(
            check=True, detailed=False, formula=formula, auto=True
        )
    return run, result


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage):
    return testing_pkg


async def test_formula_mode_runs_only_lower_solutions_uncapped(pkg):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, result = await _compute(
        pkg,
        timing_config=TimingConfig(formula='slowest * 2'),
        lower=[ac],
        upper=[tle],
    )
    assert run.tracked == [str(ac.path)]
    assert run.timelimit_override == -1
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
    assert run.timelimit_override == -1
    # Nothing about the run differs from the formula path: every solution that
    # ran still gates the report, and nothing was dropped.
    assert run.print_run_report.call_args.kwargs['ok_solutions'] == set(run.tracked)
    assert run.estimate.call_args.kwargs['dropped_upper_per_language'] == {}


async def test_multipliers_with_tle_ratio_runs_both_capped(pkg):
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
        structured=_structured(
            {
                ac: [_evaluation(400, Outcome.ACCEPTED)],
                tle: [_evaluation(6000, Outcome.ACCEPTED)],
            }
        ),
    )
    assert run.tracked == [str(ac.path), str(tle.path)]
    assert run.timelimit_override == 7000


async def test_custom_formula_forces_formula_mode_over_multipliers(pkg):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    run, _ = await _compute(
        pkg,
        timing_config=TimingConfig(
            multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5)
        ),
        lower=[ac],
        upper=[tle],
        formula='slowest * 3',
    )
    assert run.tracked == [str(ac.path)]
    assert run.timelimit_override == -1
    assert run.estimate.call_args.args[2].formula == 'slowest * 3'


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
    assert run.print_run_report.call_args.kwargs['ok_solutions'] == {str(ac.path)}


async def test_an_upper_solution_at_the_cap_is_dropped_with_a_warning(pkg, capsys):
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
                ac: [_evaluation(400, Outcome.ACCEPTED)],
                tle: [_evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED)],
            }
        ),
    )
    assert result is not None
    assert run.estimate.call_args.kwargs['dropped_upper_per_language'] == {
        'cpp': [str(tle.path)]
    }
    out = capsys.readouterr().out
    assert 'tle.cpp' in out


async def test_an_upper_solution_failing_for_a_non_timing_reason_is_an_error(
    pkg, capsys
):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TLE_OR_RTE)
    run, result = await _compute(
        pkg,
        timing_config=TimingConfig(
            multipliers=TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=1.5)
        ),
        lower=[ac],
        upper=[tle],
        structured=_structured(
            {
                ac: [_evaluation(400, Outcome.ACCEPTED)],
                tle: [_evaluation(120, Outcome.RUNTIME_ERROR)],
            }
        ),
    )
    assert result is None
    run.estimate.assert_not_called()
    out = capsys.readouterr().out
    assert 'tle.cpp' in out
    assert 'inference' in out


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
    assert 'ac.cpp' in capsys.readouterr().out


async def test_a_cap_bounded_estimate_warns_that_the_upper_bound_is_untrustworthy(
    pkg, capsys
):
    # inferenceTimeout 7000 / timeLimitToTle 1.5 = 4666 ms; the resolved limit of
    # 5000 ms is above it, so the cap -- not the slow solutions -- bounded it.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    _, result = await _compute(
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
                ac: [_evaluation(2500, Outcome.ACCEPTED)],
                tle: [_evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED)],
            }
        ),
        estimated=timing.TimingProfile(timeLimit=5000),
    )
    assert result is not None
    out = capsys.readouterr().out
    assert 'upper bound' in out


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


def test_the_report_gate_ignores_solutions_outside_ok_solutions():
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
