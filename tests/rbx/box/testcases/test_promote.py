import asyncio

import pytest
from typer.testing import CliRunner

from rbx.box.testcases import main as testcases_main
from rbx.box.testing import testing_package


@pytest.fixture
def runner() -> CliRunner:
    # The promote command is wrapped in @syncer.sync, which calls
    # asyncio.get_event_loop() from CliRunner's synchronous context. On
    # Python 3.14 that raises unless a loop is bound to the current thread,
    # so we ensure one exists for the duration of the test.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


def _setup_pkg_with_generated_group(
    testing_pkg: testing_package.TestingPackage,
) -> None:
    # gen-id.cpp echoes its single integer argument back as the test input.
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_with_generators(
        'gen', [{'name': 'gens/gen.cpp', 'args': '123'}]
    )


def test_promote_non_interactive_happy_path(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    result = runner.invoke(
        testcases_main.app, ['promote', 'gen/0', '--group', 'corner']
    )

    assert result.exit_code == 0, result.output
    dest = testing_pkg.root / 'tests/manual/corner/000.in'
    assert dest.is_file()
    assert dest.read_bytes() == b'123\n'
    # INPUT only -- no answer file is written.
    assert not (testing_pkg.root / 'tests/manual/corner/000.out').exists()
    assert not (testing_pkg.root / 'tests/manual/corner/000.ans').exists()


def test_promote_non_interactive_with_explicit_name(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    result = runner.invoke(
        testcases_main.app,
        ['promote', 'gen/0', '--group', 'corner', '--name', 'special'],
    )

    assert result.exit_code == 0, result.output
    dest = testing_pkg.root / 'tests/manual/corner/special.in'
    assert dest.is_file()
    assert dest.read_bytes() == b'123\n'


def test_promote_non_interactive_nonexistent_group_errors(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)

    result = runner.invoke(
        testcases_main.app, ['promote', 'gen/0', '--group', 'does-not-exist']
    )

    assert result.exit_code != 0
    assert 'does-not-exist' in result.output
