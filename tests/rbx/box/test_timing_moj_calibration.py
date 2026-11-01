"""`rbx time --runner moj` with multipliers: one MOJ Kattis calibration, no testruns.

The runner is faked at the seam the estimation calls -- `estimate_by_calibration`
-- so what is under test is how a calibration's measurements become the profile:
which limit is written, which gates stop the estimate, and what the upper-bound
check concludes without running anything. The calibration itself (the package,
the upload, the freshness wait) is `tests/rbx/box/runners/moj/test_kattis.py`.
"""

import asyncio
from typing import Dict, List, Optional
from unittest import mock

import pytest

from rbx.box import package, timing, timing_config
from rbx.box.runners.moj.kattis import KattisCalibrationResult, KattisMeasurement
from rbx.box.schema import ExpectedOutcome, TimingMultipliers
from rbx.box.testing import testing_package


def _strategy(
    time_limit_to_tle: Optional[float] = 1.5,
) -> timing_config.TimingStrategy:
    return timing_config.TimingStrategy(
        multipliers=TimingMultipliers(
            acToTimeLimit=2.0, timeLimitToTle=time_limit_to_tle, timeResolution=100
        ),
        inferenceTimeout=10000,
    )


def _measure(
    path: str,
    category: str,
    time_ms: Optional[int],
    timed_out: bool = False,
    complete: bool = True,
    bad_codes=(),
) -> KattisMeasurement:
    solution = next(s for s in package.get_solutions() if str(s.path) == path)
    return KattisMeasurement(
        solution=solution,
        category=category,
        hosts=('judge',),
        time_ms=time_ms,
        timed_out=timed_out,
        complete=complete,
        bad_codes=tuple(bad_codes),
    )


class _CalibratingRunner:
    """A backend that answers the estimate with a canned calibration."""

    def __init__(self, measurements: List[KattisMeasurement], limits: Dict[str, int]):
        self.measurements = measurements
        self.limits = limits
        self.calls: List[timing_config.TimingStrategy] = []

    async def estimate_by_calibration(self, entries, strategy, progress=None):
        self.calls.append(strategy)
        return KattisCalibrationResult(
            moj_id='alice#rbxt-x-kattis',
            hosts=('judge',),
            measurements={str(m.solution.path): m for m in self.measurements},
            moj_limits_ms=self.limits,
            reused=False,
        )


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage):
    testing_pkg.add_solution('sols/ac.cpp', ExpectedOutcome.ACCEPTED)
    testing_pkg.add_solution('sols/slow.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    return testing_pkg


def _estimate(runner, strategy=None, **kwargs):
    async def no_entries():
        return []

    def refuse_testruns(*args, **kwargs):
        raise AssertionError('a Kattis calibration must not testrun anything')

    with (
        mock.patch(
            'rbx.box.timing._resolve_inference_strategy',
            return_value=strategy or _strategy(),
        ),
        mock.patch(
            'rbx.box.testcase_extractors.extract_generation_testcases_from_groups',
            no_entries,
        ),
        mock.patch('rbx.box.timing.run_solutions', refuse_testruns),
    ):
        return asyncio.run(
            timing.compute_time_limits(
                check=False, detailed=False, auto=True, runner=runner, **kwargs
            )
        )


def _upper(profile: timing.TimingProfile):
    reports = [g.upperValidation for g in profile.groups or [] if g.upperValidation]
    assert len(reports) == 1
    return reports[0]


@pytest.mark.usefixtures('pkg')
def test_the_limit_is_the_calibrations_and_nothing_is_testrun():
    """W = 260 ms, a = 2.0, r = 100 ms: 520 rounds up to 600, MOJ's own number.

    The slow solution was killed at MOJ's `etl` (TL + 2.2 s = 2800 ms), which
    clears the 900 ms it needs: confirmed, by the calibration alone.
    """
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 260),
            _measure('sols/slow.cpp', 'slow', 2800, timed_out=True, complete=False),
        ],
        limits={'cpp': 600, 'default': 600},
    )

    profile = _estimate(runner)

    assert profile is not None
    assert profile.timeLimit == 600
    assert _upper(profile).confirmed == ['sols/slow.cpp']
    assert len(runner.calls) == 1
    assert package.get_limits_file('local').exists()


@pytest.mark.usefixtures('pkg')
def test_an_accepted_solution_that_timed_out_stops_the_estimate():
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 12200, timed_out=True),
            _measure('sols/slow.cpp', 'slow', 2800, timed_out=True),
        ],
        limits={},
    )

    assert _estimate(runner) is None
    assert not package.get_limits_file('local').exists()


@pytest.mark.usefixtures('pkg')
def test_an_accepted_solution_with_a_wrong_answer_stops_the_estimate():
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 100, bad_codes=['WA']),
            _measure('sols/slow.cpp', 'slow', 2800, timed_out=True),
        ],
        limits={},
    )

    assert _estimate(runner) is None


@pytest.mark.usefixtures('pkg')
def test_a_slow_solution_that_finished_leaves_no_limit_to_write():
    """It ran every test in 700 ms, so the limit may be at most 466 ms -- while the
    accepted one needs at least 520 ms.

    The testrun path learns this on its second round; the calibration hands it
    over before the first build, so the range is empty from the start. With no
    picker to force through (`--auto`), nothing is written, as everywhere else an
    estimate has no valid limit.
    """
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 260),
            _measure('sols/slow.cpp', 'slow', 700),
        ],
        limits={'cpp': 600, 'default': 600},
    )

    assert _estimate(runner) is None
    assert not package.get_limits_file('local').exists()


@pytest.mark.usefixtures('pkg')
def test_a_slow_solution_the_calibration_cannot_settle_is_skipped_not_testrun():
    """W = 3000 ms: TL 6000, so the slow one must take 9000 ms -- but MOJ kills at
    `etl = TL + 2.2 s = 8200 ms`. The calibration cannot answer, and the
    estimate must not testrun to find out: the bound is recorded as skipped.
    """
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 3000),
            _measure('sols/slow.cpp', 'slow', 8200, timed_out=True, complete=False),
        ],
        limits={'cpp': 6000, 'default': 6000},
    )

    profile = _estimate(runner)

    assert profile is not None
    assert profile.timeLimit == 6000
    upper = _upper(profile)
    assert upper.skipped == ['sols/slow.cpp']
    assert upper.confirmed == []


@pytest.mark.usefixtures('pkg')
def test_a_slow_solution_that_crashed_is_reported_broken():
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 260),
            _measure('sols/slow.cpp', 'slow', 100, bad_codes=['RE']),
        ],
        limits={'cpp': 600, 'default': 600},
    )

    profile = _estimate(runner)

    # Written anyway under `auto`, as the testrun path does for a broken one.
    assert profile is not None
    assert _upper(profile).confirmed == []


def test_only_multipliers_with_a_calibrating_backend_take_this_path():
    runner = _CalibratingRunner([], limits={})
    formula = timing_config.TimingStrategy(formula='2 * slowest', inferenceTimeout=1)

    assert timing.uses_moj_calibration(runner, _strategy())
    assert not timing.uses_moj_calibration(runner, formula)
    assert not timing.uses_moj_calibration(None, _strategy())
    assert not timing.uses_moj_calibration(object(), _strategy())
