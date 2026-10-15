import asyncio
import json
import pathlib

import pytest
from typer.testing import CliRunner

from rbx.box.schema import ExpectedOutcome
from rbx.box.testcases import main as testcases_main
from rbx.box.testing import testing_package

pytestmark = pytest.mark.shared_cache


@pytest.fixture
def runner() -> CliRunner:
    # @syncer.sync needs an event loop bound to the current thread (Python 3.14).
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


def _setup(testing_pkg: testing_package.TestingPackage) -> None:
    # gen-id.cpp echoes its argument; int-validator.cpp accepts a single integer.
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    testing_pkg.add_testgroup_from_plan(
        'gen',
        '// a comment\ngens/gen.cpp 123\n\n@input "abc"\n',
    )


def _json(result) -> dict:
    # CliRunner mixes stderr into output by default; the JSON is the last line.
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_generate_by_script_line(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup(testing_pkg)

    result = runner.invoke(
        testcases_main.app, ['generate', 'testplan/gen.txt:2', '--json']
    )

    assert result.exit_code == 0, result.output
    doc = _json(result)
    assert doc['test'] == 'gen/0'
    assert doc['source'] == 'testplan/gen.txt:2'
    assert doc['call'] == 'gens/gen.cpp 123'
    assert doc['answer'] is None
    assert doc['validation'] is None
    assert pathlib.Path(doc['input']).read_text() == '123\n'


def test_generate_by_group_index(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup(testing_pkg)

    result = runner.invoke(testcases_main.app, ['generate', 'gen/1', '--json'])

    assert result.exit_code == 0, result.output
    doc = _json(result)
    assert doc['source'] == 'testplan/gen.txt:4'
    assert pathlib.Path(doc['input']).read_text().strip() == 'abc'


def test_generate_with_answer(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup(testing_pkg)
    sol = testing_pkg.add_solution('sol.py', ExpectedOutcome.ACCEPTED)
    sol.write_text('print(int(input()) * 2)\n')

    result = runner.invoke(
        testcases_main.app, ['generate', 'testplan/gen.txt:2', '-o', '--json']
    )

    assert result.exit_code == 0, result.output
    doc = _json(result)
    assert pathlib.Path(doc['answer']).read_text().strip() == '246'


def test_generate_validate_accepts(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup(testing_pkg)

    result = runner.invoke(
        testcases_main.app, ['generate', 'testplan/gen.txt:2', '--validate', '--json']
    )

    assert result.exit_code == 0, result.output
    assert _json(result)['validation'] == [
        {'validator': 'validator.cpp', 'ok': True, 'message': None}
    ]


def test_generate_validate_rejects_and_exits_1(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup(testing_pkg)

    result = runner.invoke(
        testcases_main.app, ['generate', 'testplan/gen.txt:4', '--validate', '--json']
    )

    assert result.exit_code == 1, result.output
    (row,) = _json(result)['validation']
    assert row['validator'] == 'validator.cpp'
    assert row['ok'] is False
    assert row['message']


def test_generate_line_without_statement_fails(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup(testing_pkg)

    result = runner.invoke(testcases_main.app, ['generate', 'testplan/gen.txt:3'])

    assert result.exit_code == 1
    assert 'No test starts at' in result.output


def test_generate_refuses_a_whole_group(
    runner: CliRunner, testing_pkg: testing_package.TestingPackage
):
    _setup(testing_pkg)

    result = runner.invoke(testcases_main.app, ['generate', 'gen'])

    assert result.exit_code == 1
    assert 'matches 2 tests' in result.output
