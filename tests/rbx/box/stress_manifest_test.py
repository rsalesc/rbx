import datetime

import yaml

from rbx.box import stress_manifest
from rbx.box.schema import GeneratorCall
from rbx.box.stress_manifest import (
    StressFindingEntry,
    StressManifest,
    StressSolutionResult,
    StressSpec,
    StressState,
)
from rbx.box.testing import testing_package
from rbx.grading.steps import Outcome


def _manifest() -> StressManifest:
    return StressManifest(
        state=StressState.RUNNING,
        spec=StressSpec(
            name=None,
            generator='gen [1..10]',
            finder='[sols/wa.cpp] ~ INCORRECT',
            timeout=10,
            findingsLimit=2,
        ),
        startedAt=datetime.datetime(2026, 10, 15, 12, 0, tzinfo=datetime.timezone.utc),
        solutions=['sols/ac.cpp', 'sols/wa.cpp'],
        findings=[
            StressFindingEntry(
                index=1,
                generator=GeneratorCall(name='gen', args='3'),
                duration=12,
                results=[
                    StressSolutionResult(
                        solution=1,
                        outcome=Outcome.WRONG_ANSWER,
                        time=0.012,
                        memory=1024,
                    )
                ],
            )
        ],
    )


def test_paths(testing_pkg: testing_package.TestingPackage):
    from rbx.box import package

    stress_dir = package.get_problem_runs_dir() / '.stress'
    assert stress_manifest.stress_dir() == stress_dir
    assert stress_manifest.manifest_path() == stress_dir / 'stress.yml'
    assert stress_manifest.finding_dir(3) == stress_dir / 'findings' / '3'
    assert (
        stress_manifest.finding_input_path(3)
        == stress_dir / 'findings' / '3' / 'input.in'
    )


def test_round_trip(testing_pkg: testing_package.TestingPackage):
    manifest = _manifest()
    stress_manifest.write_manifest(manifest)

    assert stress_manifest.read_manifest() == manifest


def test_written_as_structured_values(testing_pkg: testing_package.TestingPackage):
    stress_manifest.write_manifest(_manifest())

    data = yaml.safe_load(stress_manifest.manifest_path().read_text())
    assert data['version'] == stress_manifest.STRESS_MANIFEST_VERSION
    assert data['state'] == 'running'
    assert data['findings'][0]['results'] == [
        {'solution': 1, 'outcome': 'wrong-answer', 'time': 0.012, 'memory': 1024}
    ]
    assert data['findings'][0]['generator'] == {'name': 'gen', 'args': '3'}


def test_atomic_write_leaves_no_temp_file(
    testing_pkg: testing_package.TestingPackage,
):
    stress_manifest.write_manifest(_manifest())
    stress_manifest.write_manifest(_manifest())

    assert [p.name for p in stress_manifest.stress_dir().iterdir()] == ['stress.yml']


def test_read_missing_manifest(testing_pkg: testing_package.TestingPackage):
    assert stress_manifest.read_manifest() is None


def test_read_unknown_version(testing_pkg: testing_package.TestingPackage):
    stress_manifest.write_manifest(_manifest())
    path = stress_manifest.manifest_path()
    data = yaml.safe_load(path.read_text())
    data['version'] = 99
    path.write_text(yaml.safe_dump(data))

    assert stress_manifest.read_manifest() is None


def test_read_unparsable_manifest(testing_pkg: testing_package.TestingPackage):
    path = stress_manifest.manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('state: [unclosed\n')

    assert stress_manifest.read_manifest() is None


def test_finish_open_session_stamps_a_running_session(
    testing_pkg: testing_package.TestingPackage,
):
    stress_manifest.write_manifest(_manifest())
    stress_manifest.begin_session(stress_manifest.manifest_path())

    stress_manifest.finish_open_session('interrupted')

    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    assert manifest.state == StressState.INTERRUPTED


def test_finish_open_session_stamps_errors_as_failed(
    testing_pkg: testing_package.TestingPackage,
):
    stress_manifest.write_manifest(_manifest())
    stress_manifest.begin_session(stress_manifest.manifest_path())

    stress_manifest.finish_open_session('error')

    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    assert manifest.state == StressState.FAILED


def test_finish_open_session_leaves_a_finished_session_alone(
    testing_pkg: testing_package.TestingPackage,
):
    done = _manifest().model_copy(update={'state': StressState.DONE})
    stress_manifest.write_manifest(done)
    stress_manifest.begin_session(stress_manifest.manifest_path())

    stress_manifest.finish_open_session('interrupted')

    assert stress_manifest.read_manifest() == done


def test_finish_open_session_without_a_session_is_a_no_op(
    testing_pkg: testing_package.TestingPackage,
):
    stress_manifest.write_manifest(_manifest())
    stress_manifest.end_session()

    stress_manifest.finish_open_session('interrupted')

    manifest = stress_manifest.read_manifest()
    assert manifest is not None
    assert manifest.state == StressState.RUNNING


def test_finish_open_session_never_raises(
    testing_pkg: testing_package.TestingPackage,
):
    path = stress_manifest.manifest_path()
    # Not a file: reading it fails.
    path.mkdir(parents=True)
    stress_manifest.begin_session(path)

    stress_manifest.finish_open_session('interrupted')
