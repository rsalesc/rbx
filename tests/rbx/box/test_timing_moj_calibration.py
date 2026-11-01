"""`rbx time --runner moj` with multipliers: one MOJ calibration, no testruns.

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
from rbx.box.runners.moj import cli, kattis
from rbx.box.runners.moj.kattis import KattisCalibrationResult, KattisMeasurement
from rbx.box.schema import ExpectedOutcome, InferenceRole, TimingMultipliers
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
        self.run_all: List[bool] = []

    async def estimate_by_calibration(
        self, entries, strategy, progress=None, run_all=False
    ):
        self.calls.append(strategy)
        self.run_all.append(run_all)
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

    The slow solution went over the 10 s cap every limit of the calibration is
    pinned at, which clears the 900 ms it needs: confirmed, by the calibration
    alone.
    """
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 260),
            _measure('sols/slow.cpp', 'slow', 10450, timed_out=True, complete=False),
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
    """W = 5000 ms: TL 10000, so the slow one must take 15000 ms -- but every
    limit of the calibration is pinned at the 10 s inferenceTimeout, and MOJ kills
    at `etl = cap + 2.2 s = 12200 ms`. The calibration cannot answer, and the
    estimate must not testrun to find out: the bound is recorded as skipped.
    """
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 5000),
            _measure('sols/slow.cpp', 'slow', 12200, timed_out=True, complete=False),
        ],
        limits={'cpp': 10000, 'default': 10000},
    )

    profile = _estimate(runner)

    assert profile is not None
    assert profile.timeLimit == 10000
    upper = _upper(profile)
    assert upper.skipped == ['sols/slow.cpp']
    assert upper.confirmed == []


@pytest.mark.usefixtures('pkg')
def test_a_slow_solution_that_finished_under_the_cap_can_still_be_too_slow():
    """`rollercoaster` on the park, 2026-11-01: W = 170 ms makes the limit 400 ms,
    so a slow solution must take 600 ms -- and it finished every test, the
    slowest in 6610 ms, under the 10 s cap. Finishing is not violating here: the
    cap is far above the bound, so the profile records it confirmed.
    """
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 170),
            _measure('sols/slow.cpp', 'slow', 6610),
        ],
        limits={'cpp': 400, 'default': 400},
    )

    profile = _estimate(runner)

    assert profile is not None
    assert profile.timeLimit == 400
    upper = _upper(profile)
    assert upper.confirmed == ['sols/slow.cpp']
    assert upper.violating == []


def _split_judges(category: str, file: str) -> List[cli.CalibHost]:
    """Judge `a` times the solution out at the 10 s cap and `STOPWHEN_TLE` halts it
    there, short of t3; judge `b` runs every test, the slowest in 6.61 s."""
    tests_a = [
        cli.TestrunTest(name='t1', code='AC', time=0.1, tl=10.0),
        cli.TestrunTest(name='t2', code='TLE', time=10.45, tl=10.0),
    ]
    tests_b = [
        cli.TestrunTest(name='t1', code='AC', time=0.1, tl=10.0),
        cli.TestrunTest(name='t2', code='AC', time=6.61, tl=10.0),
        cli.TestrunTest(name='t3', code='AC', time=1.2, tl=10.0),
    ]
    return [
        cli.CalibHost(
            host=host,
            at=200,
            sols=[cli.CalibSolution(file=file, category=category, tests=tests)],
        )
        for host, tests in (('a', tests_a), ('b', tests_b))
    ]


def _calibrated(hosts: List[cli.CalibHost], files: Dict[str, str]):
    """`measure_solutions` over `hosts`, for the solutions at `files` (path ->
    category), as the runner reads a calibration back."""
    solutions = {s.path.as_posix(): s for s in package.get_solutions()}
    return list(
        kattis.measure_solutions(
            hosts,
            {
                (category, path.split('/')[-1]): solutions[path]
                for path, category in files.items()
            },
            3,
        ).values()
    )


@pytest.mark.usefixtures('pkg')
def test_a_slow_solution_one_judge_finished_is_bounded_by_that_finish():
    """One judge timed it out, the other finished it in 6610 ms: the finish is the
    weakest judge's evidence, so the bound is checked against it -- the solution
    is not left unmeasured, which fails the upper-bound check."""
    hosts = _split_judges('slow', 'slow.cpp') + [
        cli.CalibHost(
            host=host,
            at=200,
            sols=[
                cli.CalibSolution(
                    file='ac.cpp',
                    category='good',
                    tests=[
                        cli.TestrunTest(name='t1', code='AC', time=0.1, tl=10.0),
                        cli.TestrunTest(name='t2', code='AC', time=0.17, tl=10.0),
                        cli.TestrunTest(name='t3', code='AC', time=0.1, tl=10.0),
                    ],
                )
            ],
        )
        for host in ('a', 'b')
    ]
    runner = _CalibratingRunner(
        _calibrated(hosts, {'sols/ac.cpp': 'good', 'sols/slow.cpp': 'slow'}),
        limits={'cpp': 400, 'default': 400},
    )

    profile = _estimate(runner)

    assert profile is not None
    assert profile.timeLimit == 400
    upper = _upper(profile)
    assert upper.confirmed == ['sols/slow.cpp']
    assert upper.violating == []


@pytest.mark.usefixtures('pkg')
def test_an_accepted_solution_that_timed_out_on_one_judge_says_so(capsys):
    runner = _CalibratingRunner(
        _calibrated(
            _split_judges('good', 'ac.cpp'),
            {'sols/ac.cpp': 'good', 'sols/slow.cpp': 'slow'},
        ),
        limits={},
    )

    assert _estimate(runner) is None
    out = capsys.readouterr().out
    assert 'timed out on MOJ' in out
    assert 'did not report every test' not in out


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


def test_run_all_replays_what_the_calibration_judged_and_runs_the_rest(
    testing_pkg: testing_package.TestingPackage,
):
    """`--run-all` with every solution shipped: the wrong-answer one is shown from
    the calibration; one whose limit is above the cap is judged again for real.

    The accepted solution already ran for the estimate, so it is in neither.
    """
    testing_pkg.add_solution('sols/ac.cpp', ExpectedOutcome.ACCEPTED)
    testing_pkg.add_solution('sols/wa.cpp', ExpectedOutcome.WRONG_ANSWER)
    testing_pkg.add_solution('sols/slow.py', ExpectedOutcome.ACCEPTED_OR_TLE)
    calibration = KattisCalibrationResult(
        moj_id='alice#rbxt-x-kattis-all',
        hosts=('judge',),
        measurements={},
        moj_limits_ms={},
        reused=False,
        cap_ms=10_000,
        files={
            'sols/ac.cpp': ('good', 'ac.cpp'),
            'sols/wa.cpp': ('wrong', 'wa.cpp'),
            'sols/slow.py': ('pass', 'slow.py'),
        },
    )
    profile = timing.TimingProfile(timeLimit=1000, timeLimitPerLanguage={'py': 12_000})
    batches = []

    async def record(profile, batch, batch_runner, title, **kwargs):
        batches.append(
            (sorted(str(s.path) for s in batch), type(batch_runner).__name__)
        )
        return True

    real = object()
    with mock.patch('rbx.box.timing._run_batch', record):
        ok = asyncio.run(
            timing._run_remaining(  # noqa: SLF001
                profile,
                {'sols/ac.cpp'},
                check=False,
                detailed=False,
                runs=0,
                runner=real,  # type: ignore[arg-type]
                calibration=calibration,
            )
        )

    assert ok
    assert batches == [
        (['sols/wa.cpp'], 'CalibrationReplayRunner'),
        (['sols/slow.py'], 'object'),
    ]


def test_every_strategy_with_a_calibrating_backend_takes_this_path():
    """The calibration only measures; rbx computes the limit by either rule."""
    runner = _CalibratingRunner([], limits={})
    formula = timing_config.TimingStrategy(formula='2 * slowest', inferenceTimeout=1)

    assert timing.uses_moj_calibration(runner, _strategy())
    assert timing.uses_moj_calibration(runner, formula)
    assert not timing.uses_moj_calibration(None, _strategy())
    assert not timing.uses_moj_calibration(object(), _strategy())


@pytest.mark.usefixtures('pkg')
def test_a_formula_estimates_from_the_calibration_and_reads_no_slow_solution():
    """`2 * slowest` over a 260 ms accepted solution: 520 ms, nothing testrun.

    A formula has no upper bound, so the slow solution is not even read: its
    measurement here would be wrong to use, and it bounds nothing.
    """
    runner = _CalibratingRunner(
        [_measure('sols/ac.cpp', 'good', 260)],
        limits={},
    )
    formula = timing_config.TimingStrategy(
        formula='2 * slowest', inferenceTimeout=10000
    )

    profile = _estimate(runner, strategy=formula)

    assert profile is not None
    assert profile.timeLimit == 520
    assert not [g for g in profile.groups or [] if g.upperValidation]
    assert runner.run_all == [False]


@pytest.mark.usefixtures('pkg')
def test_the_profile_records_every_solution_timing():
    """`rbx time --edit` checks a hand-set limit per solution, so the profile
    keeps each one's measurement -- the slow one as the cap it survived, which is
    what lets the editor confirm it for limits well above the estimate."""
    runner = _CalibratingRunner(
        [
            _measure('sols/ac.cpp', 'good', 260),
            _measure('sols/slow.cpp', 'slow', 10450, timed_out=True, complete=False),
        ],
        limits={'cpp': 600, 'default': 600},
    )

    profile = _estimate(runner)

    by_path = {timing.path: timing for timing in profile.solutions or []}
    assert by_path['sols/ac.cpp'].role == InferenceRole.LOWER
    assert by_path['sols/ac.cpp'].time == 260
    assert by_path['sols/slow.cpp'].role == InferenceRole.UPPER
    assert by_path['sols/slow.cpp'].time is None
    assert by_path['sols/slow.cpp'].survivedAt is not None

    # Written at the end of the file, one solution per line.
    text = package.get_limits_file('local').read_text()
    tail = text[text.index('solutions:') :]
    assert '- {path: sols/ac.cpp, language: cpp, role: lower, time: 260}' in tail
    assert text.rstrip().endswith('}')
