import asyncio
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli
from rbx.box.schema import GeneratorCall
from rbx.box.stresses import StressFinding, StressReport
from rbx.box.testing import testing_package


def _scripted_prompt(*values):
    """Build a mock questionary prompt factory.

    Each call to the factory returns an object whose ``.ask_async()`` is an
    async function yielding the next scripted value.
    """
    values = list(values)

    def factory(*args, **kwargs):
        result = mock.MagicMock()

        async def ask_async():
            return values.pop(0)

        result.ask_async = ask_async
        return result

    return factory


@pytest.fixture
def runner() -> CliRunner:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


@pytest.fixture(autouse=True)
def _skip_preset_check():
    # The root Typer callback checks the active preset's compatibility, which is
    # unrelated to the stress-promote logic under test and fails for the bare
    # testing package preset.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


def _write_findings(testing_pkg: testing_package.TestingPackage, *contents: bytes):
    from rbx.box import package

    findings_dir = package.get_problem_runs_dir() / '.stress' / 'findings'
    findings_dir.mkdir(parents=True, exist_ok=True)
    findings = []
    for i, content in enumerate(contents):
        (findings_dir / f'{i}.in').write_bytes(content)
        findings.append(StressFinding(generator=GeneratorCall(name='gen', args=str(i))))
    return StressReport(findings=findings, executed=len(contents), skipped=0)


def _mock_run_stress(report: StressReport):
    async def run_stress(*args, **kwargs):
        return report

    return run_stress


def test_stress_promote_existing_manual_group(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    report = _write_findings(testing_pkg, b'5 7\n', b'8 9\n')

    with (
        mock.patch('rbx.box.stresses.run_stress', _mock_run_stress(report)),
        mock.patch('rbx.box.stresses.print_stress_report'),
        mock.patch('rich.prompt.Confirm.ask', return_value=True),
        mock.patch('questionary.select', _scripted_prompt('corner')),
        mock.patch('questionary.text', _scripted_prompt()),
    ):
        result = runner.invoke(
            cli.app, ['stress', '-g', 'gen 1', '-f', 'sols/main.cpp']
        )

    assert result.exit_code == 0, result.output
    folder = testing_pkg.root / 'tests/manual/corner'
    assert (folder / '000.in').is_file()
    assert (folder / '001.in').is_file()
    written = {(folder / '000.in').read_bytes(), (folder / '001.in').read_bytes()}
    assert written == {b'5 7\n', b'8 9\n'}
    # INPUT only -- no answer files.
    assert not any(folder.glob('*.out'))
    assert not any(folder.glob('*.ans'))


def test_stress_promote_create_new_manual_group(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    report = _write_findings(testing_pkg, b'42\n')

    glob = 'tests/manual/fresh/*.in'
    with (
        mock.patch('rbx.box.stresses.run_stress', _mock_run_stress(report)),
        mock.patch('rbx.box.stresses.print_stress_report'),
        mock.patch('rich.prompt.Confirm.ask', return_value=True),
        mock.patch('questionary.select', _scripted_prompt('(create new manual group)')),
        mock.patch('questionary.text', _scripted_prompt('fresh', glob)),
    ):
        result = runner.invoke(
            cli.app, ['stress', '-g', 'gen 1', '-f', 'sols/main.cpp']
        )

    assert result.exit_code == 0, result.output
    folder = testing_pkg.root / 'tests/manual/fresh'
    assert (folder / '000.in').is_file()
    assert (folder / '000.in').read_bytes() == b'42\n'

    from rbx.box import package

    package_obj = package.find_problem_package_or_die()
    groups = {g.name: g for g in package_obj.testcases}
    assert 'fresh' in groups
    assert groups['fresh'].testcaseGlob == glob


def test_stress_promote_create_new_manual_group_aborted_writes_nothing(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    report = _write_findings(testing_pkg, b'42\n')

    # select -> create new; the name prompt returns None (Ctrl-C). Nothing should
    # be written and no group added.
    with (
        mock.patch('rbx.box.stresses.run_stress', _mock_run_stress(report)),
        mock.patch('rbx.box.stresses.print_stress_report'),
        mock.patch('rich.prompt.Confirm.ask', return_value=True),
        mock.patch('questionary.select', _scripted_prompt('(create new manual group)')),
        mock.patch('questionary.text', _scripted_prompt(None)),
    ):
        result = runner.invoke(
            cli.app, ['stress', '-g', 'gen 1', '-f', 'sols/main.cpp']
        )

    assert result.exit_code == 0, result.output
    # No manual group folder was created and no static inputs were written.
    assert not (testing_pkg.root / 'tests/manual').exists()

    from rbx.box import package

    package_obj = package.find_problem_package_or_die()
    assert all(g.testcaseGlob is None for g in package_obj.testcases)


def test_stress_promote_skip_writes_nothing(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    report = _write_findings(testing_pkg, b'5 7\n')

    with (
        mock.patch('rbx.box.stresses.run_stress', _mock_run_stress(report)),
        mock.patch('rbx.box.stresses.print_stress_report'),
        mock.patch('rich.prompt.Confirm.ask', return_value=True),
        mock.patch('questionary.select', _scripted_prompt('(skip)')),
        mock.patch('questionary.text', _scripted_prompt()),
    ):
        result = runner.invoke(
            cli.app, ['stress', '-g', 'gen 1', '-f', 'sols/main.cpp']
        )

    assert result.exit_code == 0, result.output
    folder = testing_pkg.root / 'tests/manual/corner'
    assert not any(folder.glob('*.in'))
