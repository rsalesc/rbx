"""How the validation phase checks an estimate against the slow solutions.

The whole behavior lives in the limits each slow solution is probed at, in which
of them are probed at all, and in what their verdicts are taken to mean, so that
is what these tests assert on.
"""

import pathlib
from typing import Dict, List, Optional
from unittest import mock

import pytest

from rbx.box import timing, timing_validation
from rbx.box.deferred import Deferred
from rbx.box.schema import ExpectedOutcome, Solution, TimingMultipliers
from rbx.grading.steps import Outcome


def _solution(name: str, language: str = 'cpp') -> Solution:
    return Solution(
        path=pathlib.Path(name),
        language=language,
        outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
    )


def _evaluation(time_ms: Optional[int], outcome: Outcome):
    log = mock.Mock()
    log.time = None if time_ms is None else time_ms / 1000
    return mock.Mock(log=log, result=mock.Mock(outcome=outcome))


def _structured(evals: Dict[Solution, List]):
    def _make(ev):
        async def _get():
            return ev

        return _get

    return {
        str(solution.path): {'main': [Deferred(_make(ev)) for ev in evaluations]}
        for solution, evaluations in evals.items()
    }


def _profile(
    time_limit: int = 1000,
    per_language: Optional[Dict[str, int]] = None,
    time_limit_to_tle: Optional[float] = 1.5,
) -> timing.TimingProfile:
    return timing.TimingProfile(
        timeLimit=time_limit,
        timeLimitPerLanguage=per_language or {},
        multipliers=TimingMultipliers(
            acToTimeLimit=2.0, timeLimitToTle=time_limit_to_tle
        ),
    )


class _Validation:
    """One mocked validation run."""

    def __init__(self):
        self.run_solutions = None
        self.outcome = None

    @property
    def tracked(self) -> List[str]:
        return list(self.run_solutions.call_args.kwargs['tracked_solutions'])

    @property
    def timelimit_override(self):
        return self.run_solutions.call_args.kwargs['timelimit_override']

    @property
    def ran(self) -> bool:
        return self.run_solutions.called


async def _validate(
    profile: timing.TimingProfile,
    upper: List[Solution],
    knowledge: Optional[timing_validation.SlowKnowledge] = None,
    structured: Optional[Dict] = None,
) -> _Validation:
    validation = _Validation()
    result = mock.Mock()
    result.skeleton.solutions = list(upper)
    # The validation run ends its batch in a `finally`, exactly as the estimation
    # run does: the picker may re-open right after, and this loop can run again.
    result.close = mock.AsyncMock()
    with (
        mock.patch(
            'rbx.box.timing.run_solutions', return_value=result
        ) as mock_run_solutions,
        mock.patch('rbx.box.timing.print_run_report', return_value=True),
        mock.patch(
            'rbx.box.timing.consume_and_key_evaluation_items',
            return_value=structured or {},
        ),
        mock.patch(
            'rbx.box.timing.find_language_name', side_effect=lambda sol: sol.language
        ),
    ):
        validation.run_solutions = mock_run_solutions
        validation.outcome = await timing._validate_upper_bound(  # noqa: SLF001
            profile,
            upper,
            knowledge if knowledge is not None else timing_validation.SlowKnowledge(),
            check=False,
            detailed=False,
            runs=0,
        )
    return validation


async def test_each_language_is_probed_at_its_own_limit():
    # Every language group gets its own estimated limit, so the bound each slow
    # solution has to clear differs by language.
    slow_cpp = _solution('sols/slow.cpp', language='cpp')
    slow_py = _solution('sols/slow.py', language='py')
    validation = await _validate(
        _profile(time_limit=1000, per_language={'cpp': 1000, 'py': 4000}),
        [slow_cpp, slow_py],
        structured=_structured(
            {
                slow_cpp: [_evaluation(None, Outcome.TIME_LIMIT_EXCEEDED)],
                slow_py: [_evaluation(None, Outcome.TIME_LIMIT_EXCEEDED)],
            }
        ),
    )
    assert validation.timelimit_override == {'cpp': 1500, 'py': 6000}


async def test_a_language_without_its_own_limit_uses_the_base_one():
    slow = _solution('sols/slow.cpp')
    validation = await _validate(
        _profile(time_limit=1000, per_language={}),
        [slow],
        structured=_structured(
            {slow: [_evaluation(None, Outcome.TIME_LIMIT_EXCEEDED)]}
        ),
    )
    assert validation.timelimit_override == {'cpp': 1500}


async def test_a_slow_solution_that_times_out_is_confirmed():
    slow = _solution('sols/slow.cpp')
    knowledge = timing_validation.SlowKnowledge()
    validation = await _validate(
        _profile(),
        [slow],
        knowledge=knowledge,
        structured=_structured(
            {slow: [_evaluation(None, Outcome.TIME_LIMIT_EXCEEDED)]}
        ),
    )
    assert validation.outcome.ok
    assert validation.outcome.confirmed == [slow]
    assert validation.outcome.violating == []
    # It cleared the bound without being measured, so it bounds nothing.
    assert knowledge.measured_time('sols/slow.cpp') is None
    assert knowledge.is_confirmed('sols/slow.cpp')


async def test_a_slow_solution_that_finishes_violates_the_bound():
    slow = _solution('sols/slow.cpp')
    knowledge = timing_validation.SlowKnowledge()
    validation = await _validate(
        _profile(time_limit=1000),
        [slow],
        knowledge=knowledge,
        # Probed at 1500 ms and finished in 1200, which is under the 1500 ms the
        # limit of 1000 ms demands of it.
        structured=_structured({slow: [_evaluation(1200, Outcome.ACCEPTED)]}),
    )
    assert not validation.outcome.ok
    assert validation.outcome.violating == [(slow, 1200)]
    assert validation.outcome.confirmed == []
    # The real time is what makes the violation reportable and re-usable.
    assert knowledge.measured_time('sols/slow.cpp') == 1200


async def test_a_solution_exactly_on_the_bound_respects_it():
    # 1000 * 1.5 = 1500 exactly: taking 1500 ms is enough, and `compute_bounds`
    # agrees -- floor(1500 / 1.5) is 1000, which the limit does not exceed.
    slow = _solution('sols/slow.cpp')
    validation = await _validate(
        _profile(time_limit=1000),
        [slow],
        structured=_structured({slow: [_evaluation(1500, Outcome.ACCEPTED)]}),
    )
    assert validation.outcome.ok
    assert validation.outcome.violating == []


async def test_a_solution_that_breaks_for_another_reason_fails_the_validation():
    # A crash leaves no evidence about how long it would have run, so it can
    # neither confirm the bound nor violate it.
    slow = _solution('sols/slow.cpp')
    validation = await _validate(
        _profile(),
        [slow],
        structured=_structured({slow: [_evaluation(200, Outcome.RUNTIME_ERROR)]}),
    )
    assert not validation.outcome.ok
    assert validation.outcome.failed == [(slow, Outcome.RUNTIME_ERROR)]


async def test_skipped_evaluations_are_not_evidence():
    # A skipped testcase is the consequence of an earlier verdict, never
    # evidence of its own: counting it would read the abort as a crash.
    slow = _solution('sols/slow.cpp')
    validation = await _validate(
        _profile(),
        [slow],
        structured=_structured(
            {
                slow: [
                    _evaluation(None, Outcome.TIME_LIMIT_EXCEEDED),
                    _evaluation(None, Outcome.SKIPPED),
                ]
            }
        ),
    )
    assert validation.outcome.ok
    assert validation.outcome.confirmed == [slow]


async def test_only_the_solutions_whose_probe_grew_are_re_run():
    slow = _solution('sols/slow.cpp')
    knowledge = timing_validation.SlowKnowledge()
    # It already survived 1500 ms, which is what a 1000 ms limit demands.
    knowledge.record_timeout('sols/slow.cpp', 1500)

    unchanged = await _validate(_profile(time_limit=1000), [slow], knowledge=knowledge)
    assert not unchanged.ran
    assert unchanged.outcome.ok

    lower = await _validate(_profile(time_limit=600), [slow], knowledge=knowledge)
    assert not lower.ran
    assert lower.outcome.ok

    higher = await _validate(
        _profile(time_limit=1200),
        [slow],
        knowledge=knowledge,
        structured=_structured(
            {slow: [_evaluation(None, Outcome.TIME_LIMIT_EXCEEDED)]}
        ),
    )
    assert higher.ran
    assert higher.timelimit_override == {'cpp': 1800}


async def test_a_measured_solution_is_never_re_run():
    slow = _solution('sols/slow.cpp')
    knowledge = timing_validation.SlowKnowledge()
    knowledge.record_time('sols/slow.cpp', 1200)

    validation = await _validate(_profile(time_limit=1000), [slow], knowledge=knowledge)
    assert not validation.ran
    # 1200 ms is under the 1500 ms a 1000 ms limit demands, so it still violates.
    assert validation.outcome.violating == [(slow, 1200)]

    # ...but a lower limit is a weaker demand, which the same measurement meets.
    relaxed = await _validate(_profile(time_limit=700), [slow], knowledge=knowledge)
    assert not relaxed.ran
    assert relaxed.outcome.ok


async def test_the_validation_run_never_doubles_the_time_limit():
    # FULL is the only verification level that turns `isDoubleTL` on, which
    # would double the very limit being probed at.
    slow = _solution('sols/slow.cpp')
    validation = await _validate(
        _profile(),
        [slow],
        structured=_structured(
            {slow: [_evaluation(None, Outcome.TIME_LIMIT_EXCEEDED)]}
        ),
    )
    kwargs = validation.run_solutions.call_args.kwargs
    assert kwargs['verification'] == timing._INFERENCE_VERIFICATION  # noqa: SLF001
    assert kwargs['verification'].value < 4  # FULL


async def test_the_validation_run_stops_a_solution_at_its_first_timeout():
    # One timeout settles the question; the remaining testcases only cost wall
    # clock.
    slow = _solution('sols/slow.cpp')
    validation = await _validate(
        _profile(),
        [slow],
        structured=_structured(
            {slow: [_evaluation(None, Outcome.TIME_LIMIT_EXCEEDED)]}
        ),
    )
    abort_on = validation.run_solutions.call_args.kwargs['abort_on']
    assert abort_on is not None
    ctx = mock.Mock()
    ctx.evaluation.result.outcome = Outcome.TIME_LIMIT_EXCEEDED
    assert abort_on(ctx)
    ctx.evaluation.result.outcome = Outcome.ACCEPTED
    assert not abort_on(ctx)


async def test_nothing_runs_when_there_are_no_slow_solutions():
    validation = await _validate(_profile(), [])
    assert not validation.ran
    assert validation.outcome.ok


def test_a_profile_without_a_tle_ratio_cannot_be_validated():
    assert not timing.can_validate_upper_bound(
        _profile(time_limit_to_tle=None), [_solution('sols/slow.cpp')]
    )
    assert not timing.can_validate_upper_bound(_profile(), [])
    assert timing.can_validate_upper_bound(_profile(), [_solution('sols/slow.cpp')])


@pytest.mark.parametrize(
    ('time', 'time_limit', 'ratio', 'violates'),
    [
        (1200, 1000, 1.5, True),
        (1500, 1000, 1.5, False),
        (1501, 1000, 1.5, False),
        (1499, 1000, 1.5, True),
        # The ratio the setter typed, not its binary approximation.
        (1100, 1000, 1.1, False),
        (1099, 1000, 1.1, True),
    ],
)
def test_violation_matches_the_bound_the_estimate_enforces(
    time, time_limit, ratio, violates
):
    assert timing.violates_upper_bound(time, time_limit, ratio) is violates


async def test_a_slow_solution_that_says_nothing_validates_nothing():
    # It was asked and produced no verdict at all -- it did not compile, say.
    # Silence is not confirmation.
    slow = _solution('sols/slow.cpp')
    validation = await _validate(_profile(), [slow], structured={})
    assert not validation.outcome.ok
    assert validation.outcome.unmeasured == [slow]
    assert validation.outcome.confirmed == []
    assert validation.outcome.violating == []
