import asyncio
import datetime
import json
import pathlib
from typing import Optional
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli, package, stress_manifest
from rbx.box.schema import GeneratorCall
from rbx.box.testing import testing_package


@pytest.fixture
def runner() -> CliRunner:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


@pytest.fixture(autouse=True)
def _skip_preset_check():
    # The root Typer callback checks the active preset's compatibility, which
    # fails for the bare testing package preset and is unrelated to this command.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


def _write_session(*inputs: bytes, name: Optional[str] = None) -> None:
    """Write a finished stress session with one finding per input."""
    findings = []
    for i, content in enumerate(inputs):
        index = i + 1
        path = stress_manifest.finding_input_path(index)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        findings.append(
            stress_manifest.StressFindingEntry(
                index=index,
                generator=GeneratorCall(name='gen', args=f'{i} --seed=abc'),
            )
        )
    manifest = stress_manifest.StressManifest(
        state=stress_manifest.StressState.DONE,
        spec=stress_manifest.StressSpec(
            name=name,
            generator=None if name else 'gen [1..10]',
            finder='[sols/main.cpp ~ INCORRECT]',
            timeout=10,
            findingsLimit=len(inputs),
        ),
        startedAt=datetime.datetime(2026, 10, 15, 12, 0, 0),
        solutions=['sols/main.cpp'],
        findings=findings,
    )
    stress_manifest.manifest_path().parent.mkdir(parents=True, exist_ok=True)
    stress_manifest.write_manifest(manifest)


def _invoke(runner: CliRunner, *args: str):
    return runner.invoke(cli.app, ['testcases', 'add-finding', *args])


def _groups():
    return {g.name: g for g in package.find_problem_package_or_die().testcases}


def _setup_groups(testing_pkg: testing_package.TestingPackage) -> None:
    testing_pkg.add_testgroup_from_plan('main', 'gen 100\n')
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')
    testing_pkg.add_testgroup_from_script('dynamic', 'print("gen 1")\n')


def test_appends_all_findings_to_a_script_group(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n', b'2\n')

    result = _invoke(runner, '--group', 'main')

    assert result.exit_code == 0, result.output
    assert (testing_pkg.root / 'testplan/main.txt').read_text() == (
        'gen 100\n'
        "\n# Found by rbx stress -g 'gen [1..10]' -f '[sols/main.cpp ~ INCORRECT]'"
        '\ngen 0 --seed=abc'
        '\ngen 1 --seed=abc'
    )


def test_appends_selected_findings_naming_the_stress(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n', b'2\n', b'3\n', name='overflow')

    result = _invoke(runner, '3', '1', '--group', 'main')

    assert result.exit_code == 0, result.output
    assert (testing_pkg.root / 'testplan/main.txt').read_text() == (
        'gen 100\n\n# Found by rbx stress overflow\ngen 2 --seed=abc\ngen 0 --seed=abc'
    )


def test_copies_findings_into_a_manual_group(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n', b'2\n')

    result = _invoke(runner, '2', '--group', 'corner')

    assert result.exit_code == 0, result.output
    folder = testing_pkg.root / 'tests/manual/corner'
    assert sorted(p.name for p in folder.iterdir()) == ['000.in']
    assert (folder / '000.in').read_bytes() == b'2\n'


def test_rejects_a_group_of_another_kind(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n')

    result = _invoke(runner, '--group', 'dynamic')

    assert result.exit_code != 0
    assert 'generatorScript' in result.output
    assert 'manual' in result.output
    assert (testing_pkg.root / 'testplan/dynamic.py').read_text() == 'print("gen 1")\n'


def test_rejects_an_unknown_group(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n')

    result = _invoke(runner, '--group', 'nope')

    assert result.exit_code != 0
    assert 'nope' in result.output


def test_new_script_group(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _write_session(b'1\n')

    result = _invoke(runner, '--new-script', 'tests/stress.txt')

    assert result.exit_code == 0, result.output
    group = _groups()['stress']
    assert group.generatorScript is not None
    assert group.generatorScript.path == pathlib.Path('tests/stress.txt')
    assert (testing_pkg.root / 'tests/stress.txt').read_text().splitlines()[-1] == (
        'gen 0 --seed=abc'
    )


def test_new_manual_group(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _write_session(b'1\n', b'2\n')

    result = _invoke(
        runner, '--new-manual', 'fresh', '--glob', 'tests/manual/fresh/*.in'
    )

    assert result.exit_code == 0, result.output
    assert _groups()['fresh'].testcaseGlob == 'tests/manual/fresh/*.in'
    folder = testing_pkg.root / 'tests/manual/fresh'
    assert (folder / '000.in').read_bytes() == b'1\n'
    assert (folder / '001.in').read_bytes() == b'2\n'


def test_new_manual_group_needs_a_glob(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _write_session(b'1\n')

    result = _invoke(runner, '--new-manual', 'fresh')

    assert result.exit_code != 0
    assert '--glob' in result.output
    assert 'fresh' not in _groups()


def test_requires_exactly_one_destination(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n')

    assert _invoke(runner).exit_code != 0
    assert _invoke(runner, '--group', 'main', '--new-script', 'x.txt').exit_code != 0


def test_dry_run_prints_the_change_as_json_and_writes_nothing(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n', name='overflow')

    result = _invoke(runner, '--group', 'main', '--dry-run', '--json')

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        'file': str((testing_pkg.root / 'testplan/main.txt').resolve()),
        'before': 'gen 100\n',
        'after': 'gen 100\n\n# Found by rbx stress overflow\ngen 0 --seed=abc',
    }
    assert (testing_pkg.root / 'testplan/main.txt').read_text() == 'gen 100\n'


def test_dry_run_without_json_writes_nothing(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n')

    result = _invoke(runner, '--group', 'main', '--dry-run')

    assert result.exit_code == 0, result.output
    assert 'gen 0 --seed=abc' in result.output
    assert (testing_pkg.root / 'testplan/main.txt').read_text() == 'gen 100\n'


def test_dry_run_is_refused_for_a_manual_group(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n')

    result = _invoke(runner, '--group', 'corner', '--dry-run')

    assert result.exit_code != 0
    assert '--dry-run' in result.output
    assert not any((testing_pkg.root / 'tests/manual/corner').iterdir())


def test_json_reports_the_written_files(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n', b'2\n')

    result = _invoke(runner, '--group', 'corner', '--json')

    assert result.exit_code == 0, result.output
    folder = (testing_pkg.root / 'tests/manual/corner').resolve()
    assert json.loads(result.stdout) == {
        'group': 'corner',
        'kind': 'manual',
        'files': [str(folder / '000.in'), str(folder / '001.in')],
    }


def test_list_groups_as_json(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)

    result = _invoke(runner, '--list-groups', '--json')

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {'name': 'main', 'kind': 'script', 'path': 'testplan/main.txt'},
        {'name': 'corner', 'kind': 'manual', 'path': 'tests/manual/corner/*.in'},
    ]


def test_unknown_index_errors_and_writes_nothing(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)
    _write_session(b'1\n')

    result = _invoke(runner, '1', '2', '--group', 'main')

    assert result.exit_code != 0
    assert '2' in result.output
    assert (testing_pkg.root / 'testplan/main.txt').read_text() == 'gen 100\n'


def test_missing_manifest_errors(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup_groups(testing_pkg)

    result = _invoke(runner, '--group', 'main')

    assert result.exit_code != 0
    assert 'rbx stress' in result.output
    assert (testing_pkg.root / 'testplan/main.txt').read_text() == 'gen 100\n'
