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

from rbx.box import limits_info, timing
from rbx.box.deferred import Deferred
from rbx.box.environment import TimingConfig, VerificationLevel
from rbx.box.schema import ExpectedOutcome, Solution, TimingMultipliers
from rbx.box.solutions import _gates_report  # noqa: SLF001
from rbx.box.testing import testing_package
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
    assert run.print_run_report.call_args.kwargs['gating_solutions'] == set(run.tracked)
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


async def test_multipliers_with_tle_ratio_but_no_slow_solutions_stay_uncapped(pkg):
    # The path most existing packages take once the default preset ships
    # timeLimitToTle: nothing bounds the limit from above, so the cap would buy
    # nothing and only add a way for a legitimately slow accepted solution to
    # fail the estimate.
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
    assert run.timelimit_override == -1
    # And with no cap there is nothing to diagnose.
    assert result is not None
    assert run.estimate.call_args.kwargs['dropped_upper_per_language'] == {}


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
    assert run.print_run_report.call_args.kwargs['gating_solutions'] == {str(ac.path)}


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
    printed = _printed(capsys)
    # A warning, not an error: the estimate goes on without this solution.
    assert '⚠' in printed
    assert '✗' not in printed
    assert 'tle.cpp' in printed
    assert 'does not bound the time limit from above' in printed


async def test_an_upper_solution_crashing_as_declared_is_an_error_without_blame(
    pkg, capsys
):
    # `tle-or-rte` declares the crash, so the message must not accuse the setter
    # of a bug -- but a solution that stopped early still measures nothing, so
    # it stays an error the setter has to resolve deliberately.
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
    printed = _printed(capsys)
    assert '✗' in printed
    assert 'tle.cpp' in printed
    assert 'which is what its expectation declares' in printed
    assert 'inference: false' in printed
    # Nothing here says the solution is broken or asks for it to be fixed.
    assert 'instead of running out of time' not in printed
    assert 'Fix the solution' not in printed


async def test_an_upper_solution_failing_for_an_undeclared_reason_is_an_error(
    pkg, capsys
):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
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
                tle: [_evaluation(120, Outcome.WRONG_ANSWER)],
            }
        ),
        run_report_ok=False,
    )
    assert result is None
    run.estimate.assert_not_called()
    printed = _printed(capsys)
    assert '✗' in printed
    assert 'tle.cpp' in printed
    assert 'instead of running out of time' in printed
    assert 'inference: false' in printed


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
    printed = _printed(capsys)
    assert '⚠' in printed
    assert 'upper bound' in printed
    # The drop warning has scrolled past by now, so the solution is named again.
    assert printed.count('tle.cpp') >= 2


@pytest.mark.parametrize(
    ('limit', 'warns'),
    [
        # floor(7000 / 1.5) = 4666 is exactly what the cap still justifies.
        (4666, False),
        (4667, True),
    ],
)
async def test_the_cap_bounded_warning_fires_just_above_the_bound(
    pkg, capsys, limit, warns
):
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    await _compute(
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
                ac: [_evaluation(2333, Outcome.ACCEPTED)],
                tle: [_evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED)],
            }
        ),
        estimated=timing.TimingProfile(timeLimit=limit),
    )
    assert ('upper bound' in _printed(capsys)) is warns


async def test_a_per_language_limit_can_trip_the_cap_bounded_warning(pkg, capsys):
    # The base limit is under the bound but one language's is not, and that is
    # the limit a solution would actually run under.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    await _compute(
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
                ac: [_evaluation(2000, Outcome.ACCEPTED)],
                tle: [_evaluation(7000, Outcome.TIME_LIMIT_EXCEEDED)],
            }
        ),
        estimated=timing.TimingProfile(
            timeLimit=4000, timeLimitPerLanguage={'py': 9000}
        ),
    )
    assert 'upper bound' in _printed(capsys)


async def test_nothing_dropped_means_no_cap_bounded_warning(pkg, capsys):
    # A high limit alone is not suspicious; only a drop makes the cap the
    # suspect.
    ac = _solution(pkg, 'ac.cpp', ExpectedOutcome.ACCEPTED)
    tle = _solution(pkg, 'tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    await _compute(
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
                tle: [_evaluation(6900, Outcome.ACCEPTED)],
            }
        ),
        estimated=timing.TimingProfile(timeLimit=5000),
    )
    assert 'upper bound' not in _printed(capsys)


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
