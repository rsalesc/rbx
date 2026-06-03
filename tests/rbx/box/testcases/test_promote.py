import asyncio
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box.testcases import main as testcases_main
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


def test_promote_interactive_existing_group(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    # checkbox -> select one test; select -> existing group; text -> accept default.
    with (
        mock.patch('questionary.checkbox', _scripted_prompt(['gen/0'])),
        mock.patch('questionary.select', _scripted_prompt('corner')),
        mock.patch('questionary.text', _scripted_prompt('')),
    ):
        result = runner.invoke(testcases_main.app, ['promote'])

    assert result.exit_code == 0, result.output
    dest = testing_pkg.root / 'tests/manual/corner/000.in'
    assert dest.is_file()
    assert dest.read_bytes() == b'123\n'
    assert not (testing_pkg.root / 'tests/manual/corner/000.out').exists()
    assert not (testing_pkg.root / 'tests/manual/corner/000.ans').exists()


def test_promote_interactive_create_new_group(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)

    glob = 'tests/manual/fresh/*.in'
    # checkbox -> select test; select -> create new; text -> name, then glob,
    # then filename stem (accept default).
    with (
        mock.patch('questionary.checkbox', _scripted_prompt(['gen/0'])),
        mock.patch('questionary.select', _scripted_prompt('(create new manual group)')),
        mock.patch('questionary.text', _scripted_prompt('fresh', glob, '')),
    ):
        result = runner.invoke(testcases_main.app, ['promote'])

    assert result.exit_code == 0, result.output
    folder = testing_pkg.root / 'tests/manual/fresh'
    assert folder.is_dir()
    dest = folder / '000.in'
    assert dest.is_file()
    assert dest.read_bytes() == b'123\n'

    from rbx.box import package

    package_obj = package.find_problem_package_or_die()
    groups = {g.name: g for g in package_obj.testcases}
    assert 'fresh' in groups
    assert groups['fresh'].testcaseGlob == glob


def _setup_pkg_with_two_generated_tests(
    testing_pkg: testing_package.TestingPackage,
) -> None:
    # gen-id.cpp echoes its single integer argument back as the test input.
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_with_generators(
        'gen',
        [
            {'name': 'gens/gen.cpp', 'args': '123'},
            {'name': 'gens/gen.cpp', 'args': '456'},
        ],
    )


def test_promote_interactive_two_defaults_sequential(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_two_generated_tests(testing_pkg)
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    # checkbox -> select both tests; select -> existing group; text -> accept
    # default for both (empty string each). The simulated counter must produce
    # 000 then 001, writing two distinct files.
    with (
        mock.patch('questionary.checkbox', _scripted_prompt(['gen/0', 'gen/1'])),
        mock.patch('questionary.select', _scripted_prompt('corner')),
        mock.patch('questionary.text', _scripted_prompt('', '')),
    ):
        result = runner.invoke(testcases_main.app, ['promote'])

    assert result.exit_code == 0, result.output
    folder = testing_pkg.root / 'tests/manual/corner'
    assert (folder / '000.in').is_file()
    assert (folder / '001.in').is_file()
    written = {(folder / '000.in').read_bytes(), (folder / '001.in').read_bytes()}
    assert written == {b'123\n', b'456\n'}


def test_promote_interactive_skip_writes_nothing(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    # checkbox -> select a test; select -> skip the group picker. Nothing should
    # be written and no group added.
    with (
        mock.patch('questionary.checkbox', _scripted_prompt(['gen/0'])),
        mock.patch('questionary.select', _scripted_prompt('(skip)')),
        mock.patch('questionary.text', _scripted_prompt()),
    ):
        result = runner.invoke(testcases_main.app, ['promote'])

    assert result.exit_code == 0, result.output
    folder = testing_pkg.root / 'tests/manual/corner'
    assert not any(folder.glob('*.in'))
