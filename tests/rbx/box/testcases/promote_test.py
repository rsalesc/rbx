import pytest
import typer

from rbx.box.testcases import main as testcases_main
from rbx.box.testing import testing_package

# Unwrap the @app.command / @within_problem / @syncer.sync stack to reach the
# raw async coroutine; the testing_pkg fixture already provides the in-problem
# cwd that within_problem would otherwise establish.
_promote = testcases_main.promote.__wrapped__.__wrapped__


def _setup_pkg_with_generated_group(
    testing_pkg: testing_package.TestingPackage,
) -> None:
    # gen-id.cpp echoes its single integer argument back as the test input.
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_with_generators(
        'gen', [{'name': 'gens/gen.cpp', 'args': '123'}]
    )


async def test_promote_non_interactive_happy_path(
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    await _promote(['gen/0'], group='corner', name=None)

    dest = testing_pkg.root / 'tests/manual/corner/000.in'
    assert dest.is_file()
    assert dest.read_bytes() == b'123\n'
    # INPUT only -- no answer file is written.
    assert not (testing_pkg.root / 'tests/manual/corner/000.out').exists()


async def test_promote_non_interactive_with_explicit_name(
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    await _promote(['gen/0'], group='corner', name='special')

    dest = testing_pkg.root / 'tests/manual/corner/special.in'
    assert dest.is_file()
    assert dest.read_bytes() == b'123\n'


async def test_promote_non_interactive_nonexistent_group_errors(
    testing_pkg: testing_package.TestingPackage,
):
    _setup_pkg_with_generated_group(testing_pkg)

    with pytest.raises(typer.Exit) as exc_info:
        await _promote(['gen/0'], group='does-not-exist', name=None)

    assert exc_info.value.exit_code == 1
