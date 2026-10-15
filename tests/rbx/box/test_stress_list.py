import asyncio
import json
import pathlib
from typing import Iterator
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli
from rbx.box.schema import ExpectedOutcome, GeneratorCall, Solution, Stress
from rbx.box.testing import testing_package


@pytest.fixture
def runner() -> Iterator[CliRunner]:
    # `rbx stress` is wrapped in @syncer.sync, which needs a loop bound to the
    # thread; bind a fresh one rather than asking asyncio for the current one.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield CliRunner()
    asyncio.set_event_loop(None)
    loop.close()


@pytest.fixture(autouse=True)
def _skip_preset_check():
    # The root Typer callback checks the active preset's compatibility, which
    # fails for the bare testing package preset and is unrelated to this flag.
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage) -> testing_package.TestingPackage:
    testing_pkg.add_solution('sols/main.cpp', ExpectedOutcome.ACCEPTED)
    for name in ('sols/wa-1.cpp', 'sols/wa-2.cpp', 'sols/wa-notes.txt'):
        testing_pkg.add_file(name)
    testing_pkg.yml.solutions = testing_pkg.yml.solutions + [
        # `wa-notes.txt` matches but has no language: skipped.
        Solution(
            path=pathlib.Path('sols/wa-*.*'), outcome=ExpectedOutcome.WRONG_ANSWER
        ),
        # Already matched by the glob above: de-duplicated.
        Solution(path=pathlib.Path('sols/wa-2.cpp'), outcome=ExpectedOutcome.ANY),
    ]
    testing_pkg.add_generator('gens/gen.cpp', alias='gen')
    testing_pkg.add_generator('gens/big.cpp', alias='big')
    testing_pkg.add_testgroup_from_plan('samples', 'gen 1\n')
    testing_pkg.add_testgroup_from_plan('main', 'gen 2\n')
    testing_pkg.yml.stresses = [
        Stress(
            name='overflow',
            generator=GeneratorCall(name='big', args='[1..10] @'),
            finder='[sols/main.cpp ~ INCORRECT]',
        )
    ]
    testing_pkg.save()
    return testing_pkg


def test_list_as_json(runner: CliRunner, pkg: testing_package.TestingPackage):
    result = runner.invoke(cli.app, ['stress', '--list', '--json'])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        'stresses': [
            {
                'name': 'overflow',
                'generator': {'name': 'big', 'args': '[1..10] @'},
                'finder': '[sols/main.cpp ~ INCORRECT]',
            }
        ],
        'solutions': [
            {'path': 'sols/main.cpp', 'outcome': 'ACCEPTED'},
            {'path': 'sols/wa-1.cpp', 'outcome': 'WRONG_ANSWER'},
            {'path': 'sols/wa-2.cpp', 'outcome': 'WRONG_ANSWER'},
        ],
        'generators': ['gen', 'big'],
        'groups': ['samples', 'main'],
    }


def test_list_for_humans(runner: CliRunner, pkg: testing_package.TestingPackage):
    result = runner.invoke(cli.app, ['stress', '--list'])

    assert result.exit_code == 0, result.output
    assert "overflow: -g 'big [1..10] @' -f '[sols/main.cpp ~ INCORRECT]'" in (
        result.output
    )
    assert 'sols/wa-1.cpp (WRONG_ANSWER)' in result.output
    assert 'wa-notes' not in result.output
    assert 'samples, main' in result.output


@pytest.mark.parametrize(
    'args',
    [
        ['overflow'],
        ['-g', 'gen 1', '-f', 'sols/main.cpp'],
        ['-f', 'sols/main.cpp'],
        ['--fuzz'],
        ['--fuzz-on', 'main'],
    ],
)
def test_list_refuses_a_stress_to_run(
    runner: CliRunner, pkg: testing_package.TestingPackage, args
):
    result = runner.invoke(cli.app, ['stress', '--list', '--json', *args])

    assert result.exit_code == 1
    assert result.stdout == ''
    assert '--list' in result.stderr


def test_json_needs_list(runner: CliRunner, pkg: testing_package.TestingPackage):
    result = runner.invoke(cli.app, ['stress', '--json'])

    assert result.exit_code == 1
    assert result.stdout == ''
