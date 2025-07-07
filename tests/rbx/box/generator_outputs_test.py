import pytest
import typer

from rbx.box.generators import generate_outputs_for_testcases, generate_testcases
from rbx.box.schema import ExpectedOutcome
from rbx.box.testcase_utils import TestcaseEntry
from rbx.box.testing import testing_package

_SOL_DOUBLE_NUMBER = """
#include <iostream>

using namespace std;

int main() {
  int x; cin >> x;
  cout << x * 2 << endl;
}
"""


_SOL_COMPILE_ERROR = """
#include <iostream>

// Missing std;

int main() {
  int x; cin >> x;
  cout << x * 2 << endl;
}
"""


async def test_generator_outputs_are_generated(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123')
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOL_DOUBLE_NUMBER
    )

    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated.
    entries = [TestcaseEntry(group='main', index=0)]
    await generate_outputs_for_testcases(entries)

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.out'
    ).read_bytes() == b'246\n'


async def test_generator_outputs_no_main_solution_and_needs_output(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123')
    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated.
    entries = [TestcaseEntry(group='main', index=0)]

    with pytest.raises(typer.Exit):
        await generate_outputs_for_testcases(entries)

    out = capsys.readouterr().out
    assert 'No main solution found' in out


async def test_generator_outputs_no_main_solution_and_does_not_need_output(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('123\n')
    testing_pkg.add_file('manual_tests/000.ans').write_text('246\n')
    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated.
    entries = [TestcaseEntry(group='main', index=0)]

    await generate_outputs_for_testcases(entries)

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.out'
    ).read_bytes() == b'246\n'


async def test_generator_outputs_main_solution_does_not_compile_and_needs_output(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123')
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOL_COMPILE_ERROR
    )

    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated.
    entries = [TestcaseEntry(group='main', index=0)]

    with pytest.raises(typer.Exit):
        await generate_outputs_for_testcases(entries)

    out = capsys.readouterr().out
    assert 'Failed compiling main solution' in out


async def test_generator_outputs_main_solution_does_not_compile_and_does_not_need_output(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('123\n')
    testing_pkg.add_file('manual_tests/000.ans').write_text('246\n')
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOL_COMPILE_ERROR
    )
    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated.
    entries = [TestcaseEntry(group='main', index=0)]

    await generate_outputs_for_testcases(entries)

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.out'
    ).read_bytes() == b'246\n'
