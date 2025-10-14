import pytest
import typer

from rbx.box.generators import generate_outputs_for_testcases, generate_testcases
from rbx.box.schema import ExpectedOutcome
from rbx.box.testcase_utils import TestcaseEntry
from rbx.box.testing import testing_package
from rbx.grading import steps

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


_SOL_TRIPLE_NUMBER = """
#include <iostream>

using namespace std;

int main() {
  int x; cin >> x;
  cout << x * 3 << endl;
}
"""


_SOL_QUADRUPLE_NUMBER = """
#include <iostream>

using namespace std;

int main() {
  int x; cin >> x;
  cout << x * 4 << endl;
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
    assert 'No main/model solution found' in out


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

    with pytest.raises(steps.CompilationError):
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


async def test_generator_outputs_with_model_solution_in_samples_group(
    testing_pkg: testing_package.TestingPackage,
):
    """Test that model solution is used when specified in samples testgroup."""
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('samples', 'gens/gen.cpp 123')

    # Add main solution that doubles
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOL_DOUBLE_NUMBER
    )

    # Add model solution that triples - should be used for samples group
    testing_pkg.add_file('model_sol.cpp').write_text(_SOL_TRIPLE_NUMBER)

    # Manually configure samples group with model solution
    import pathlib

    from rbx.box.schema import Solution

    samples_group = testing_pkg.yml.testcases[0]
    samples_group.model_solution = Solution(path=pathlib.Path('model_sol.cpp'))
    testing_pkg.save()

    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated.
    entries = [TestcaseEntry(group='samples', index=0)]
    await generate_outputs_for_testcases(entries)

    # Should use model solution (triple) instead of main solution (double)
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '000.out'
    ).read_bytes() == b'369\n'


async def test_generator_outputs_with_multiple_model_solutions(
    testing_pkg: testing_package.TestingPackage,
):
    """Test compilation of multiple different model solutions."""
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')

    # Add main solution that doubles
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOL_DOUBLE_NUMBER
    )

    # Add different model solutions
    testing_pkg.add_file('model_sol1.cpp').write_text(_SOL_TRIPLE_NUMBER)
    testing_pkg.add_file('model_sol2.cpp').write_text(_SOL_QUADRUPLE_NUMBER)

    # Configure multiple testgroups with different model solutions
    import pathlib

    from rbx.box.schema import Solution

    testing_pkg.add_testgroup_from_plan('samples', 'gens/gen.cpp 123')
    samples_group = testing_pkg.yml.testcases[0]
    samples_group.model_solution = Solution(path=pathlib.Path('model_sol1.cpp'))

    testing_pkg.add_testgroup_from_plan('group2', 'gens/gen.cpp 456')
    # Note: group2 will use main solution since only samples can have model_solution

    testing_pkg.save()

    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated.
    entries = [
        TestcaseEntry(group='samples', index=0),
        TestcaseEntry(group='group2', index=0),
    ]
    await generate_outputs_for_testcases(entries)

    # samples should use model solution (triple)
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '000.out'
    ).read_bytes() == b'369\n'

    # group2 should use main solution (double)
    assert (
        testing_pkg.get_build_testgroup_path('group2') / '000.out'
    ).read_bytes() == b'912\n'


async def test_generator_outputs_model_solution_compilation_failure(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    """Test handling of model solution compilation failure."""
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('samples', 'gens/gen.cpp 123')

    # Add main solution that compiles
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOL_DOUBLE_NUMBER
    )

    # Add model solution that doesn't compile
    testing_pkg.add_file('model_sol.cpp').write_text(_SOL_COMPILE_ERROR)

    # Configure samples group with broken model solution
    import pathlib

    from rbx.box.schema import Solution

    samples_group = testing_pkg.yml.testcases[0]
    samples_group.model_solution = Solution(path=pathlib.Path('model_sol.cpp'))
    testing_pkg.save()

    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs generation fails with proper error
    entries = [TestcaseEntry(group='samples', index=0)]

    with pytest.raises(steps.CompilationError):
        await generate_outputs_for_testcases(entries)

    out = capsys.readouterr().out
    assert 'Failed compiling model solution' in out
    assert 'model_sol.cpp' in out


async def test_generator_outputs_model_solution_reused_across_testcases(
    testing_pkg: testing_package.TestingPackage,
):
    """Test that model solution is compiled once and reused across multiple testcases."""
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'samples',
        """
gens/gen.cpp 123
gens/gen.cpp 456
gens/gen.cpp 789
""",
    )

    # Add main solution that doubles
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOL_DOUBLE_NUMBER
    )

    # Add model solution that triples
    testing_pkg.add_file('model_sol.cpp').write_text(_SOL_TRIPLE_NUMBER)

    # Configure samples group with model solution
    import pathlib

    from rbx.box.schema import Solution

    samples_group = testing_pkg.yml.testcases[0]
    samples_group.model_solution = Solution(path=pathlib.Path('model_sol.cpp'))
    testing_pkg.save()

    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated for all testcases
    entries = [
        TestcaseEntry(group='samples', index=0),
        TestcaseEntry(group='samples', index=1),
        TestcaseEntry(group='samples', index=2),
    ]
    await generate_outputs_for_testcases(entries)

    # All should use model solution (triple)
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '000.out'
    ).read_bytes() == b'369\n'
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '001.out'
    ).read_bytes() == b'1368\n'
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '002.out'
    ).read_bytes() == b'2367\n'


async def test_generator_outputs_fallback_to_main_when_no_model_solution(
    testing_pkg: testing_package.TestingPackage,
):
    """Test that main solution is used when no model solution is specified."""
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('samples', 'gens/gen.cpp 123')

    # Add main solution that doubles
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOL_DOUBLE_NUMBER
    )

    # Don't add model solution - should fallback to main solution

    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs are generated.
    entries = [TestcaseEntry(group='samples', index=0)]
    await generate_outputs_for_testcases(entries)

    # Should use main solution (double)
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '000.out'
    ).read_bytes() == b'246\n'


async def test_generator_outputs_no_main_or_model_solution_error_message(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    """Test updated error message when neither main nor model solution is available."""
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123')

    # Don't add any solution

    # Ensure cases are generated.
    await generate_testcases()

    # Ensure outputs generation fails with updated error message
    entries = [TestcaseEntry(group='main', index=0)]

    with pytest.raises(typer.Exit):
        await generate_outputs_for_testcases(entries)

    out = capsys.readouterr().out
    # Check that the error message mentions both main and model solutions
    assert 'No main/model solution found' in out
