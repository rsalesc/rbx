"""`rbx time-inspect`: the JSON backend of the VS Code time-profile editor."""

import json
import pathlib
from unittest import mock

import pytest
import yaml
from typer.testing import CliRunner

from rbx.box import asset_listing, limits_info, limits_inspect, package, run_report
from rbx.box.cli import app
from rbx.box.schema import (
    EstimationSolutionTiming,
    ExpectedOutcome,
    InferenceRole,
    LimitModifiers,
    LimitsProfile,
    LimitsProfileRun,
    TimingBound,
    TimingGroupOrigin,
    TimingGroupReport,
    TimingGroupUpperValidation,
    TimingMultipliers,
)
from rbx.box.testing import testing_package
from rbx.grading.steps import Outcome

runner = CliRunner()


@pytest.fixture(autouse=True)
def _skip_preset_check():
    # The root callback checks preset compatibility, unrelated to what is tested.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage) -> testing_package.TestingPackage:
    testing_pkg.add_solution('sols/main.cpp', ExpectedOutcome.ACCEPTED)
    testing_pkg.add_solution('sols/wa.cpp', ExpectedOutcome.WRONG_ANSWER)
    testing_pkg.add_solution('sols/main.java', ExpectedOutcome.ACCEPTED)
    testing_pkg.add_solution('sols/quadratic.java', ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    return testing_pkg


def _profile() -> LimitsProfile:
    """Two estimated groups -- cpp and java, the latter's limit set by hand from
    1200 to 1500 -- and the solutions they were measured on."""
    return LimitsProfile(
        timeLimit=500,
        modifiers={
            'cpp': LimitModifiers(time=500),
            'java': LimitModifiers(time=1500),
        },
        multipliers=TimingMultipliers(
            acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100
        ),
        groups=[
            TimingGroupReport(
                languages=['cpp'],
                timeLimit=500,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=1,
                fastest=50,
                slowest=50,
                lowerBound=TimingBound(value=100, solution='sols/main.cpp'),
            ),
            TimingGroupReport(
                languages=['java'],
                timeLimit=1500,
                estimatedTimeLimit=1200,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=1,
                fastest=150,
                slowest=150,
                lowerBound=TimingBound(value=300, solution='sols/main.java'),
                upperBound=TimingBound(value=1400, solution='sols/quadratic.java'),
                upperValidation=TimingGroupUpperValidation(
                    violating=[TimingBound(value=2100, solution='sols/quadratic.java')]
                ),
            ),
        ],
        baseEstimate=TimingGroupReport(
            languages=[],
            timeLimit=500,
            origin=TimingGroupOrigin.ESTIMATED,
            solutionCount=2,
            fastest=50,
            slowest=150,
        ),
        solutions=[
            EstimationSolutionTiming(
                path='sols/main.cpp', language='cpp', role=InferenceRole.LOWER, time=50
            ),
            EstimationSolutionTiming(
                path='sols/main.java',
                language='java',
                role=InferenceRole.LOWER,
                time=150,
            ),
            EstimationSolutionTiming(
                path='sols/quadratic.java',
                language='java',
                role=InferenceRole.UPPER,
                time=2100,
            ),
        ],
    )


def _source(profile: LimitsProfile) -> str:
    return limits_info.profile_to_yaml(profile)


def _row(result, key):
    return next(row for row in result['rows'] if row['key'] == key)


def test_inspect_reports_checks_statuses_and_effective_limits(pkg):
    result = limits_inspect.inspect(_source(_profile()), 'local')

    assert result['errors'] == []
    assert result['version'] == limits_inspect.INSPECT_VERSION
    assert 'yaml' not in result  # nothing was edited
    java = _row(result, '1')
    assert java['editable'] is True
    assert java['check']['estimated'] == 1200
    assert java['check']['breaksUpper'] is True
    assert [(s['path'], s['status']) for s in java['solutions']] == [
        ('sols/main.java', 'ok'),
        # Finishes at 2100, before 1500 x 1.5: still TLE, but the margin is lost.
        ('sols/quadratic.java', 'passes'),
    ]
    cpp = _row(result, '0')
    assert cpp['check']['ok'] is True
    effective = {
        e['language']: e['timeLimit'] for e in result['effective']['languages']
    }
    assert effective['cpp'] == 500
    assert effective['java'] == 1500


def test_solutions_carry_their_declared_outcome(pkg):
    result = limits_inspect.inspect(_source(_profile()), 'local')

    declared = {
        s['path']: s['expectedOutcome']
        for row in result['rows']
        for s in row['solutions']
    }
    assert declared == {
        'sols/main.cpp': 'ACCEPTED',
        'sols/main.java': 'ACCEPTED',
        'sols/quadratic.java': 'TIME_LIMIT_EXCEEDED',
    }


def test_setting_a_group_limit_retargets_it_and_keeps_the_evidence(pkg):
    result = limits_inspect.inspect(
        _source(_profile()),
        'local',
        limits_inspect.Edit(set_time=('1', 1400)),
    )

    assert result['errors'] == []
    edited = LimitsProfile.model_validate(yaml.safe_load(result['yaml']))
    assert edited.groups[1].timeLimit == 1400
    assert edited.groups[1].estimatedTimeLimit == 1200
    assert edited.modifiers['java'].time == 1400
    assert edited.solutions == _profile().solutions
    # At 1400, quadratic.java (2100) is past 1400 x 1.5: the margin holds again.
    java = _row(result, '1')
    assert java['check']['breaksUpper'] is False
    assert [s['status'] for s in java['solutions']] == ['ok', 'ok']


def test_revert_puts_a_hand_set_limit_back_to_its_estimate(pkg):
    result = limits_inspect.inspect(
        _source(_profile()), 'local', limits_inspect.Edit(revert='1')
    )

    edited = LimitsProfile.model_validate(yaml.safe_load(result['yaml']))
    assert edited.groups[1].timeLimit == 1200
    assert edited.groups[1].estimatedTimeLimit is None
    assert edited.modifiers['java'].time == 1200


def test_memory_and_inherit_edits_keep_the_estimate(pkg):
    memory = limits_inspect.inspect(
        _source(_profile()), 'local', limits_inspect.Edit(memory=512)
    )
    assert (
        LimitsProfile.model_validate(yaml.safe_load(memory['yaml'])).memoryLimit == 512
    )

    inherit = limits_inspect.inspect(
        _source(_profile()), 'local', limits_inspect.Edit(inherit=True)
    )
    edited = LimitsProfile.model_validate(yaml.safe_load(inherit['yaml']))
    assert edited.inheritFromPackage is True
    assert edited.groups == _profile().groups
    assert inherit['inheritFromPackage'] is True
    # Inheriting, a run is judged against the package's own limits.
    assert inherit['effective']['timeLimit'] == pkg.yml.timeLimit


def test_a_profile_without_an_estimate_takes_a_base_limit_but_no_group_edit(pkg):
    bare = _source(LimitsProfile(timeLimit=700))

    base = limits_inspect.inspect(
        bare, 'local', limits_inspect.Edit(set_time=('base', 900))
    )
    assert base['errors'] == []
    assert base['editable'] is False
    assert LimitsProfile.model_validate(yaml.safe_load(base['yaml'])).timeLimit == 900

    group = limits_inspect.inspect(
        bare, 'local', limits_inspect.Edit(set_time=('0', 900))
    )
    assert group['errors'] != []
    assert 'yaml' not in group


@pytest.mark.parametrize(
    'edit',
    [
        limits_inspect.Edit(set_time=('base', 0)),
        limits_inspect.Edit(set_time=('7', 900)),
        limits_inspect.Edit(set_time=('java', 900)),
        limits_inspect.Edit(memory=-1),
    ],
)
def test_bad_edits_are_reported_not_raised(pkg, edit):
    result = limits_inspect.inspect(_source(_profile()), 'local', edit)

    assert result['errors'] != []
    assert 'yaml' not in result


@pytest.mark.parametrize(
    'source', ['timeLimit: [', '- just\n- a list\n', 'timeLimit: fast\n']
)
def test_unreadable_profiles_are_reported_not_raised(pkg, source):
    result = limits_inspect.inspect(source, 'local')

    assert result['errors'] != []
    assert 'rows' not in result


def test_an_empty_buffer_is_a_profile_with_nothing_set(pkg):
    result = limits_inspect.inspect('', 'local')

    assert result['errors'] == []
    assert result['effective']['timeLimit'] == pkg.yml.timeLimit


def test_staleness_is_the_bucket_the_checksum_says_moved(pkg):
    profile = _profile()
    profile.estimationChecksum = 'v1.h.0.-.0'
    with mock.patch(
        'rbx.box.estimation_checksum.compare',
        return_value=limits_inspect.estimation_checksum.ChecksumBucket.SOLUTIONS,
    ):
        assert limits_inspect.inspect(_source(profile), 'local')['stale'] == 'solutions'
    with mock.patch('rbx.box.estimation_checksum.compare', return_value=None):
        assert limits_inspect.inspect(_source(profile), 'local')['stale'] is None
    # No checksum at all: never estimated, so never stale.
    assert limits_inspect.inspect(_source(_profile()), 'local')['stale'] is None


def _write_last_run(profile_name: str, solutions, runner=None):
    runs_dir = package.get_problem_runs_dir()
    run_report.write_report(
        run_report.report_path(runs_dir),
        run_report.RunReport(solutions=solutions, finished=True),
    )
    skeleton = {'limits': {'cpp': {'time': 500, 'profile': profile_name}}}
    if runner is not None:
        skeleton['runner'] = runner
    (runs_dir / 'skeleton.yml').write_text(yaml.safe_dump(skeleton))


def _ran(path, expected, outcome, matches=True, max_time=0.012, tl=0.5):
    return run_report.RunSolutionReport(
        path=path,
        index=0,
        expectedOutcome=expected,
        outcome=outcome,
        status='OK',
        matchesExpectation=matches,
        complete=True,
        maxTime=max_time,
        timeLimit=tl,
    )


def test_the_last_run_adds_what_the_estimate_did_not_measure_to_each_group(pkg):
    _write_last_run(
        'local',
        [
            # Measured by the estimate already: not repeated.
            _ran('sols/main.cpp', ExpectedOutcome.ACCEPTED, Outcome.ACCEPTED),
            _ran('sols/wa.cpp', ExpectedOutcome.WRONG_ANSWER, Outcome.WRONG_ANSWER),
        ],
    )

    result = limits_inspect.inspect(_source(_profile()), 'local')

    assert result['lastRun']['profiles'] == ['local']
    assert result['lastRun']['finished'] is True
    assert _row(result, '0')['runSolutions'] == [
        {
            'path': 'sols/wa.cpp',
            'language': 'cpp',
            'expectedOutcome': 'WRONG_ANSWER',
            'outcome': 'wrong-answer',
            'matchesExpectation': True,
            'complete': True,
            'maxTime': 12,
            'timeLimit': 500,
        }
    ]
    assert _row(result, '1')['runSolutions'] == []


def test_a_slow_solution_the_estimate_never_ran_shows_its_run(pkg):
    profile = _profile()
    profile.solutions[2] = EstimationSolutionTiming(
        path='sols/quadratic.java', language='java', role=InferenceRole.UPPER
    )
    _write_last_run(
        'local',
        [
            _ran(
                'sols/quadratic.java',
                ExpectedOutcome.TIME_LIMIT_EXCEEDED,
                Outcome.ACCEPTED,
                matches=False,
                max_time=0.9,
                tl=1.5,
            )
        ],
    )

    java = _row(limits_inspect.inspect(_source(profile), 'local'), '1')

    assert [
        (r['path'], r['outcome'], r['matchesExpectation']) for r in java['runSolutions']
    ] == [('sols/quadratic.java', 'accepted', False)]


def _wa_run():
    return [_ran('sols/wa.cpp', ExpectedOutcome.WRONG_ANSWER, Outcome.WRONG_ANSWER)]


def _shown(result):
    return [r['path'] for row in result['rows'] for r in row['runSolutions']]


def test_a_run_under_another_profile_on_the_same_runner_is_shown(pkg):
    _write_last_run('other', _wa_run(), runner='local')
    profile = _profile()
    profile.runner = 'local'

    result = limits_inspect.inspect(_source(profile), 'local')

    assert result['lastRun']['runner'] == 'local'
    assert _shown(result) == ['sols/wa.cpp']


def test_a_local_run_is_not_shown_beside_a_profile_measured_on_moj(pkg):
    _write_last_run('moj', _wa_run(), runner='local')
    profile = _profile()
    profile.runner = 'moj'

    result = limits_inspect.inspect(_source(profile), 'moj')

    # The header still says what the last run was; only its verdicts are left out.
    assert result['lastRun']['runner'] == 'local'
    assert _shown(result) == []


def test_a_moj_run_is_not_shown_beside_a_profile_measured_locally(pkg):
    _write_last_run('local', _wa_run(), runner='moj')
    profile = _profile()
    profile.runner = 'local'

    assert _shown(limits_inspect.inspect(_source(profile), 'local')) == []


def test_without_a_recorded_runner_the_profile_name_implies_it(pkg):
    # Written before rbx recorded runners: `-p moj` ran on MOJ, the rest locally.
    _write_last_run('local', _wa_run())

    assert _shown(limits_inspect.inspect(_source(_profile()), 'moj')) == []
    assert _shown(limits_inspect.inspect(_source(_profile()), 'local')) == [
        'sols/wa.cpp'
    ]

    _write_last_run('moj', _wa_run())
    assert _shown(limits_inspect.inspect(_source(_profile()), 'moj')) == ['sols/wa.cpp']


def test_a_recorded_runner_wins_over_the_one_the_profile_name_implies(pkg):
    # `rbx time -p moj --runner local`: MOJ limits, measured on this machine.
    _write_last_run('local', _wa_run(), runner='local')
    profile = _profile()
    profile.runner = 'local'

    assert _shown(limits_inspect.inspect(_source(profile), 'moj')) == ['sols/wa.cpp']


def test_without_a_run_report_there_is_nothing_from_a_run(pkg):
    result = limits_inspect.inspect(_source(_profile()), 'local')

    assert result['lastRun'] is None
    assert all(row['runSolutions'] == [] for row in result['rows'])


def test_a_report_from_another_version_is_ignored(pkg):
    runs_dir = package.get_problem_runs_dir()
    run_report.report_path(runs_dir).write_text(
        yaml.safe_dump({'version': run_report.REPORT_VERSION + 1, 'solutions': []})
    )

    assert limits_inspect.inspect(_source(_profile()), 'local')['lastRun'] is None


# ------------------------------------------------------------------ the CLI


def test_cli_reads_the_buffer_from_stdin_and_applies_one_edit(pkg):
    result = runner.invoke(
        app,
        ['time-inspect', '-p', 'local', '--stdin', '--set', '0=900'],
        input=_source(_profile()),
    )

    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out['errors'] == []
    assert (
        LimitsProfile.model_validate(yaml.safe_load(out['yaml'])).groups[0].timeLimit
        == 900
    )


def test_cli_reads_the_saved_profile_without_stdin(pkg):
    path = package.get_limits_file('moj')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_source(_profile()))

    result = runner.invoke(app, ['time-inspect', '-p', 'moj'])

    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out['profile'] == 'moj'
    assert _row(out, '1')['timeLimit'] == 1500


def test_cli_refuses_a_malformed_set(pkg):
    result = runner.invoke(
        app, ['time-inspect', '--stdin', '--set', 'base=fast'], input=''
    )

    assert result.exit_code == 2


def test_cli_inherit_flag(pkg):
    result = runner.invoke(
        app, ['time-inspect', '--stdin', '--inherit'], input=_source(_profile())
    )

    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert LimitsProfile.model_validate(yaml.safe_load(out['yaml'])).inheritFromPackage


# ------------------------------------------------------------------ assets


def test_every_profile_is_listed_as_a_time_profile_asset(pkg):
    for name in ('local', 'moj'):
        path = package.get_limits_file(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_source(_profile()))

    listing = asset_listing.problem_asset_listing()

    profiles = [
        (pathlib.Path(a.path).name, a.detail)
        for a in listing.problems[0].assets
        if a.category == 'time_profile'
    ]
    assert profiles == [
        ('local.yml', {'profile': 'local'}),
        ('moj.yml', {'profile': 'moj'}),
    ]


# ------------------------------------------------------------------ profile runs


def _profile_with_runs() -> LimitsProfile:
    profile = _profile()
    profile.runs = [
        LimitsProfileRun(
            path='sols/wa.cpp',
            language='cpp',
            timeLimit=500,
            expectedOutcome=ExpectedOutcome.WRONG_ANSWER,
            outcome=Outcome.WRONG_ANSWER,
            matchesExpectation=True,
            time=12,
        ),
        LimitsProfileRun(
            path='sols/slow.java',
            language='java',
            timeLimit=1200,
            expectedOutcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED,
            outcome=Outcome.ACCEPTED,
            matchesExpectation=False,
            time=900,
            complete=False,
        ),
    ]
    return profile


def test_the_profile_runs_are_shown_under_their_group(pkg):
    result = limits_inspect.inspect(_source(_profile_with_runs()), 'local')

    assert result['runsSource'] == 'profile'
    assert _row(result, '0')['runSolutions'] == [
        {
            'path': 'sols/wa.cpp',
            'language': 'cpp',
            'expectedOutcome': 'WRONG_ANSWER',
            'outcome': 'wrong-answer',
            'matchesExpectation': True,
            'complete': True,
            'maxTime': 12,
            'timeLimit': 500,
        }
    ]
    java = _row(result, '1')['runSolutions']
    assert [(r['path'], r['complete'], r['timeLimit']) for r in java] == [
        ('sols/slow.java', False, 1200)
    ]


def test_the_profile_runs_win_over_the_last_run(pkg):
    # A later `rbx run` overwrote the report; the profile still knows what
    # `--run-all` found at its own limit.
    _write_last_run(
        'local',
        [_ran('sols/wa.cpp', ExpectedOutcome.WRONG_ANSWER, Outcome.ACCEPTED, False)],
    )

    result = limits_inspect.inspect(_source(_profile_with_runs()), 'local')

    assert [r['outcome'] for r in _row(result, '0')['runSolutions']] == ['wrong-answer']


def test_without_profile_runs_the_last_run_is_the_source(pkg):
    result = limits_inspect.inspect(_source(_profile()), 'local')

    assert result['runsSource'] == 'lastRun'
