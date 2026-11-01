"""`rbx time` through a MOJ Kattis calibration: the package, the wait, the read-back.

The shapes the fakes answer with are the ones the park returned on 2026-10-31
(`contando-mex`, 5 accepted + 4 slow solutions, three judges); see
`docs/plans/2026-11-01-moj-parallel-run-and-kattis-calibration-design.md`.
"""

import pathlib
import shutil
from typing import Dict, List, Optional, Tuple

import pytest

from rbx.box.runners.moj import cli, kattis
from rbx.box.runners.moj import runner as runner_module
from rbx.box.runners.moj.runner import MojRunner, MojRunnerError
from rbx.box.schema import ExpectedOutcome, Solution, TimingMultipliers
from rbx.box.timing_config import TimingStrategy
from tests.rbx.box.packaging.moj.conftest import build_entries, minimal_package

pytestmark = pytest.mark.shared_cache


def _test(name: str, code: str, time: Optional[float]) -> cli.TestrunTest:
    return cli.TestrunTest(name=name, code=code, time=time, tl=0.6)


def _sol(file: str, category: str, tests: List[cli.TestrunTest]) -> cli.CalibSolution:
    return cli.CalibSolution(file=file, category=category, tests=tests, etl=2.8)


def _host(name: str, sols: List[cli.CalibSolution], at: int = 200) -> cli.CalibHost:
    return cli.CalibHost(host=name, at=at, sols=sols, tl_kattis={'cpp': '0.6'})


def _solution(path: str, outcome=ExpectedOutcome.ACCEPTED) -> Solution:
    return Solution(path=pathlib.Path(path), outcome=outcome)


# -- reading a calibration -------------------------------------------------------


def test_an_accepted_solution_takes_its_worst_test_on_its_slowest_judge():
    """MOJ publishes the max across judges, so that is the time it came from."""
    ac = _solution('sols/ac.cpp')
    hosts = [
        _host(
            'a',
            [_sol('ac.cpp', 'good', [_test('t1', 'AC', 0.1), _test('t2', 'AC', 0.26)])],
        ),
        _host(
            'b',
            [_sol('ac.cpp', 'good', [_test('t1', 'AC', 0.2), _test('t2', 'AC', 0.19)])],
        ),
    ]

    measured = kattis.measure_solutions(hosts, {('good', 'ac.cpp'): ac}, 2)

    assert measured['sols/ac.cpp'].time_ms == 260
    assert measured['sols/ac.cpp'].complete
    assert not measured['sols/ac.cpp'].timed_out
    assert measured['sols/ac.cpp'].hosts == ('a', 'b')


def test_a_slow_solution_keeps_the_weakest_judges_evidence():
    """Killed at `etl` on every judge: it survived the *shortest* of those."""
    slow = _solution('sols/slow.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    hosts = [
        _host(
            'a',
            [
                _sol(
                    'slow.cpp',
                    'slow',
                    [_test('t1', 'AC', 0.1), _test('t2', 'TLE', 2.81)],
                )
            ],
        ),
        _host(
            'b',
            [
                _sol(
                    'slow.cpp',
                    'slow',
                    [_test('t1', 'AC', 0.1), _test('t2', 'TLE', 2.8)],
                )
            ],
        ),
    ]

    measured = kattis.measure_solutions(hosts, {('slow', 'slow.cpp'): slow}, 5)

    assert measured['sols/slow.cpp'].timed_out
    assert measured['sols/slow.cpp'].time_ms == 2800
    # Stopped at its first timeout (`STOPWHEN_TLE`): not every test has a verdict.
    assert not measured['sols/slow.cpp'].complete


def test_a_repeated_test_reads_last_and_an_unexecuted_one_not_at_all():
    """Same `{name, code, time, tl}` vector as a testrun, so the same two rules."""
    ac = _solution('sols/ac.cpp')
    hosts = [
        _host(
            'a',
            [
                _sol(
                    'ac.cpp',
                    'good',
                    [
                        _test('t1', 'TLE', 2.8),
                        _test('t2', 'NT', None),
                        _test('t1', 'AC', 0.3),
                    ],
                )
            ],
        )
    ]

    measured = kattis.measure_solutions(hosts, {('good', 'ac.cpp'): ac}, 2)

    assert measured['sols/ac.cpp'].time_ms == 300
    assert not measured['sols/ac.cpp'].timed_out
    assert not measured['sols/ac.cpp'].complete


def test_a_wrong_answer_is_a_bad_code_and_a_missing_solution_is_unmeasured():
    wa = _solution('sols/wa.cpp')
    gone = _solution('sols/gone.cpp')
    hosts = [_host('a', [_sol('wa.cpp', 'good', [_test('t1', 'WA', 0.1)])])]

    measured = kattis.measure_solutions(
        hosts, {('good', 'wa.cpp'): wa, ('good', 'gone.cpp'): gone}, 1
    )

    assert measured['sols/wa.cpp'].bad_codes == ('WA',)
    assert not measured['sols/gone.cpp'].measured


def test_only_judges_newer_than_the_request_count():
    calibration = cli.MojCalibration(
        checksum='x',
        hosts=[
            _host('old', [_sol('ac.cpp', 'good', [])], at=100),
            _host('new', [_sol('ac.cpp', 'good', [])], at=300),
            # A judge that calibrated but measured nothing describes nothing.
            cli.CalibHost(host='empty', at=400),
        ],
    )

    assert [h.host for h in calibration.hosts_after(200)] == ['new']


def test_the_published_limits_are_read_in_ms():
    calibration = cli.MojCalibration.model_validate(
        {
            'time_limits_by_method': {
                'kattis': {'calibrated': {'cpp': '0.6', 'default': '.4115'}}
            }
        }
    )

    assert kattis.limits_ms(calibration) == {'cpp': 600, 'default': 412}


# -- the calibration itself ------------------------------------------------------


class FakeKattisMoj:
    """The `moj` CLI for one calibration: `check` answers from a script."""

    def __init__(self, snapshots: pathlib.Path, checks: List[cli.MojCheck]):
        self.snapshots = snapshots
        self.check_script = checks
        self.uploads: List[Tuple[str, pathlib.Path]] = []
        self.calibrations: List[Tuple[str, bool]] = []
        self.checks: List[str] = []
        self.calib_answer = cli.MojCalibration()
        # When set, `calib` answers these in order (the last one repeating),
        # which is how a judge whose results arrive late is played.
        self.calib_script: List[cli.MojCalibration] = []
        self.calibs = 0
        # What `moj calibrate` says it queued.
        self.queued: List[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> 'FakeKattisMoj':
        monkeypatch.setattr(cli, 'whoami', self.whoami)
        monkeypatch.setattr(cli, 'upload', self.upload)
        monkeypatch.setattr(cli, 'calibrate', self.calibrate)
        monkeypatch.setattr(cli, 'check', self.check)
        monkeypatch.setattr(cli, 'calib', self.calib)
        monkeypatch.setattr(runner_module, 'CALIBRATION_POLL_INTERVAL_SECONDS', 0)
        return self

    async def whoami(self) -> str:
        return 'alice'

    async def upload(self, problem_id: str, directory: pathlib.Path) -> None:
        dest = self.snapshots / f'upload-{len(self.uploads)}'
        shutil.copytree(directory, dest)
        self.uploads.append((problem_id, dest))

    async def calibrate(
        self, problem_id: str, *, all_judges: bool = False
    ) -> List[str]:
        self.calibrations.append((problem_id, all_judges))
        return list(self.queued)

    async def check(self, problem_id: str) -> cli.MojCheck:
        self.checks.append(problem_id)
        index = min(len(self.checks) - 1, len(self.check_script) - 1)
        return self.check_script[index]

    async def calib(self, problem_id: str) -> cli.MojCalibration:
        self.calibs += 1
        if self.calib_script:
            return self.calib_script[min(self.calibs, len(self.calib_script)) - 1]
        return self.calib_answer


def _check(ready: bool, **at: int) -> cli.MojCheck:
    return cli.MojCheck(
        calibrated=ready,
        being_calibrated=not ready,
        hosts={host: cli.MojCheckHost(at=value) for host, value in at.items()},
    )


def _strategy(**overrides) -> TimingStrategy:
    multipliers = dict(acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100)
    multipliers.update(overrides)
    return TimingStrategy(
        multipliers=TimingMultipliers(**multipliers), inferenceTimeout=10000
    )


def _conf(package_path: pathlib.Path) -> Dict[str, str]:
    lines = (package_path / 'conf').read_text().splitlines()
    return dict(
        line.split('=', 1) for line in lines if '=' in line and not line.startswith('#')
    )


@pytest.fixture
def calibrating_pkg(testing_pkg):
    minimal_package(testing_pkg)
    testing_pkg.add_solution('slow.cpp', outcome='tle').write_text('int main(){}\n')
    testing_pkg.add_solution('wa.cpp', outcome='wa').write_text('int main(){}\n')
    return testing_pkg


async def test_the_package_asks_for_the_kattis_rule_with_the_problems_ratios(
    calibrating_pkg, tmp_path, monkeypatch
):
    fake = FakeKattisMoj(tmp_path / 'snapshots', [_check(False), _check(True, j=5)])
    fake.install(monkeypatch)
    fake.calib_answer = cli.MojCalibration(
        hosts=[_host('j', [_sol('sol.cpp', 'good', [_test('a', 'AC', 0.1)])], at=5)]
    )

    await MojRunner().estimate_by_calibration(
        build_entries(tmp_path, ['samples']), _strategy()
    )

    problem, uploaded = fake.uploads[-1]
    assert problem == 'alice#rbxt-' + problem.split('#rbxt-')[1]
    assert problem.endswith('-kattis')
    conf = _conf(uploaded)
    assert conf['TLMETHOD'] == 'kattis'
    assert conf['KATTIS_AC_TO_TIME_LIMIT'] == '2'
    assert conf['KATTIS_TIME_LIMIT_TO_TLE'] == '1.5'
    assert conf['KATTIS_TIME_RESOLUTION'] == '0.1'
    assert conf['CALIBRATIONTL'] == '10'
    assert not [key for key in conf if key.startswith('TLOVERRIDE')]
    # Exactly what the estimate is about, filed by role -- no wrong-answer one,
    # since calibration runs everything a package ships.
    shipped = sorted(
        str(path.relative_to(uploaded / 'sols'))
        for path in (uploaded / 'sols').rglob('*')
        if path.is_file()
    )
    assert shipped == ['good/sol.cpp', 'slow/slow.cpp']
    # The whole park, since MOJ publishes the max across judges.
    assert fake.calibrations == [(problem, True)]


async def test_without_a_tle_ratio_the_slow_solutions_are_not_shipped(
    calibrating_pkg, tmp_path, monkeypatch
):
    fake = FakeKattisMoj(tmp_path / 'snapshots', [_check(False), _check(True, j=5)])
    fake.install(monkeypatch)
    fake.calib_answer = cli.MojCalibration(
        hosts=[_host('j', [_sol('sol.cpp', 'good', [_test('a', 'AC', 0.1)])], at=5)]
    )

    await MojRunner().estimate_by_calibration(
        build_entries(tmp_path, ['samples']), _strategy(timeLimitToTle=None)
    )

    _, uploaded = fake.uploads[-1]
    assert not (uploaded / 'sols' / 'slow').exists()


async def test_a_previous_calibration_reporting_ready_is_not_read(
    calibrating_pkg, tmp_path, monkeypatch
):
    """Right after `moj calibrate`, `check` can still describe the last package.

    `is_ready` alone would read it. Only a judge whose calibration is newer than
    what was reported *before* queueing describes the package just sent.
    """
    fake = FakeKattisMoj(
        tmp_path / 'snapshots',
        [
            _check(True, j=100),  # read before queueing
            _check(True, j=100),  # still the old one
            _check(True, j=100),
            _check(True, j=250),  # the new one
        ],
    )
    fake.install(monkeypatch)
    fake.calib_answer = cli.MojCalibration(
        hosts=[
            _host('old', [_sol('sol.cpp', 'good', [_test('a', 'AC', 0.9)])], at=100),
            _host('j', [_sol('sol.cpp', 'good', [_test('a', 'AC', 0.1)])], at=250),
        ]
    )

    result = await MojRunner().estimate_by_calibration(
        build_entries(tmp_path, ['samples']), _strategy()
    )

    assert len(fake.checks) == 4
    assert result.hosts == ('j',)
    assert result.measurements['sol.cpp'].time_ms == 100


async def test_every_queued_judge_is_waited_for_in_the_calibration_itself(
    calibrating_pkg, tmp_path, monkeypatch
):
    """Observed live: `moj check` called a judge done ~13 s before its results
    reached `moj calib`. Reading then saw two judges of three -- and MOJ
    publishes the max across all of them, so the slow judge is the one that
    matters."""
    fake = FakeKattisMoj(
        tmp_path / 'snapshots', [_check(False), _check(True, a=5, b=5)]
    )
    fake.install(monkeypatch)
    fake.queued = ['a', 'b']
    early = cli.MojCalibration(
        hosts=[_host('a', [_sol('sol.cpp', 'good', [_test('t', 'AC', 0.1)])], at=5)]
    )
    complete = cli.MojCalibration(
        hosts=[
            _host('a', [_sol('sol.cpp', 'good', [_test('t', 'AC', 0.1)])], at=5),
            _host('b', [_sol('sol.cpp', 'good', [_test('t', 'AC', 0.3)])], at=6),
        ]
    )
    fake.calib_script = [early, early, complete]

    result = await MojRunner().estimate_by_calibration(
        build_entries(tmp_path, ['samples']), _strategy()
    )

    assert result.hosts == ('a', 'b')
    assert result.measurements['sol.cpp'].time_ms == 300
    assert fake.calibs == 3


def test_the_hosts_moj_calibrate_queued_are_read_from_its_output():
    out = 'calibração de alice#rbxt-x-kattis: goiabada-judge, judge, judge-sp1\n'

    assert cli.queued_hosts(out) == ['goiabada-judge', 'judge', 'judge-sp1']
    assert cli.queued_hosts('something else entirely\n') == []


async def test_an_unchanged_package_reads_the_calibration_again(
    calibrating_pkg, tmp_path, monkeypatch
):
    fake = FakeKattisMoj(tmp_path / 'snapshots', [_check(False), _check(True, j=5)])
    fake.install(monkeypatch)
    fake.calib_answer = cli.MojCalibration(
        hosts=[_host('j', [_sol('sol.cpp', 'good', [_test('a', 'AC', 0.1)])], at=5)]
    )
    entries = build_entries(tmp_path, ['samples'])

    first = await MojRunner().estimate_by_calibration(entries, _strategy())
    second = await MojRunner().estimate_by_calibration(entries, _strategy())

    assert not first.reused
    assert second.reused
    assert len(fake.uploads) == 1
    assert len(fake.calibrations) == 1
    assert second.measurements == first.measurements


async def test_ratios_moj_cannot_take_are_refused_before_uploading(
    calibrating_pkg, tmp_path, monkeypatch
):
    fake = FakeKattisMoj(tmp_path / 'snapshots', [_check(True)])
    fake.install(monkeypatch)

    with pytest.raises(MojRunnerError, match='acToTimeLimit'):
        await MojRunner().estimate_by_calibration(
            build_entries(tmp_path, ['samples']), _strategy(acToTimeLimit=0.5)
        )

    assert fake.uploads == []
