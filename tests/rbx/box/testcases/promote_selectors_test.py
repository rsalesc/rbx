"""`rbx testcases promote` driven without prompts: by `[script]:[line]`, into a
new manual group, and with `--list-groups` / `--json` -- what an editor calls."""

import asyncio
import json

import pytest
from typer.testing import CliRunner

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


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage) -> testing_package.TestingPackage:
    # gen-id.cpp echoes its single integer argument back as the test input.
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('gen', 'gens/gen.cpp 123\ngens/gen.cpp 456\n')
    return testing_pkg


def _script(pkg: testing_package.TestingPackage):
    return pkg.root / 'testplan' / 'gen.txt'


def _last_json(result):
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_promote_by_script_line(runner: CliRunner, pkg):
    pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    result = runner.invoke(
        testcases_main.app,
        ['promote', 'testplan/gen.txt:2', '--group', 'corner', '--json'],
    )

    assert result.exit_code == 0, result.output
    dest = pkg.root / 'tests/manual/corner/000.in'
    assert _last_json(result) == {
        'group': 'corner',
        'promoted': [{'test': 'gen/1', 'from': 'testplan/gen.txt:2', 'to': str(dest)}],
    }
    assert dest.read_bytes() == b'456\n'
    assert _script(pkg).read_text() == 'gens/gen.cpp 123\n'


def test_promote_by_absolute_script_line_with_name(runner: CliRunner, pkg):
    pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    result = runner.invoke(
        testcases_main.app,
        ['promote', f'{_script(pkg)}:1', '-G', 'corner', '-n', 'big'],
    )

    assert result.exit_code == 0, result.output
    assert (pkg.root / 'tests/manual/corner/big.in').read_bytes() == b'123\n'
    assert _script(pkg).read_text() == 'gens/gen.cpp 456\n'


def test_a_shared_plan_line_names_one_test(runner: CliRunner, pkg):
    # A second group importing the same plan: line 1 makes `gen/0` and `twin/0`.
    from rbx.box.schema import GeneratorScript, TestcaseGroup

    pkg.yml.testcases = pkg.yml.testcases + [
        TestcaseGroup(name='twin', generatorScript=GeneratorScript(path=_script(pkg)))
    ]
    pkg.save()
    pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    generated = runner.invoke(
        testcases_main.app, ['generate', 'testplan/gen.txt:1', '--json']
    )
    assert generated.exit_code == 0, generated.output
    assert _last_json(generated)['test'] == 'gen/0'

    promoted = runner.invoke(
        testcases_main.app, ['promote', 'testplan/gen.txt:1', '-G', 'corner']
    )
    assert promoted.exit_code == 0, promoted.output
    assert sorted(p.name for p in (pkg.root / 'tests/manual/corner').iterdir()) == [
        '000.in'
    ]
    assert _script(pkg).read_text() == 'gens/gen.cpp 456\n'


def test_promote_script_line_without_statement_writes_nothing(runner: CliRunner, pkg):
    pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    result = runner.invoke(
        testcases_main.app, ['promote', 'testplan/gen.txt:9', '-G', 'corner']
    )

    assert result.exit_code == 1
    assert 'No test starts at' in result.output
    assert not (pkg.root / 'tests/manual/corner/000.in').exists()
    assert _script(pkg).read_text() == 'gens/gen.cpp 123\ngens/gen.cpp 456\n'


def test_promote_into_new_manual_group(runner: CliRunner, pkg):
    result = runner.invoke(
        testcases_main.app,
        [
            'promote',
            'testplan/gen.txt:1',
            '--new-manual',
            'handmade',
            '--glob',
            'tests/handmade/*.in',
            '--json',
        ],
    )

    assert result.exit_code == 0, result.output
    assert _last_json(result)['group'] == 'handmade'
    assert (pkg.root / 'tests/handmade/000.in').read_bytes() == b'123\n'
    assert 'name: handmade' in pkg.yml_path.read_text()
    assert 'tests/handmade/*.in' in pkg.yml_path.read_text()


def test_promote_new_manual_rejects_existing_name(runner: CliRunner, pkg):
    result = runner.invoke(
        testcases_main.app,
        ['promote', 'gen/0', '--new-manual', 'gen', '--glob', 'tests/x/*.in'],
    )

    assert result.exit_code == 1
    assert 'already exists' in result.output
    assert _script(pkg).read_text() == 'gens/gen.cpp 123\ngens/gen.cpp 456\n'


def test_promote_new_manual_needs_glob(runner: CliRunner, pkg):
    result = runner.invoke(
        testcases_main.app, ['promote', 'gen/0', '--new-manual', 'handmade']
    )

    assert result.exit_code == 1
    assert 'needs a --glob' in result.output


def test_promote_list_groups_json(runner: CliRunner, pkg):
    pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')

    result = runner.invoke(testcases_main.app, ['promote', '--list-groups', '--json'])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {'name': 'corner', 'kind': 'manual', 'path': 'tests/manual/corner/*.in'}
    ]


def test_promote_json_needs_a_destination(runner: CliRunner, pkg):
    result = runner.invoke(testcases_main.app, ['promote', 'gen/0', '--json'])

    assert result.exit_code == 1
    assert '--group or --new-manual' in result.output
