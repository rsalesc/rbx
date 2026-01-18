import pytest

from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.testcase_extractors import extract_generation_testcases
from rbx.box.testcase_utils import TestcaseEntry
from rbx.box.testing import testing_package
from rbx.box.validators import (
    check_output_from_entries,
    has_validation_errors,
    print_validation_report,
    validate_outputs_from_entries,
    validate_testcases,
)


async def test_no_validator_does_not_validate(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('123 456\n')

    await generate_testcases()

    validation_infos = await validate_testcases()

    assert not has_validation_errors(validation_infos)


async def test_main_validator_works(testing_pkg: testing_package.TestingPackage):
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('123\n')

    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

    await generate_testcases()
    validation_infos = await validate_testcases()

    assert not has_validation_errors(validation_infos)


async def test_main_validator_catches_invalid_case(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('123 456\n')

    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

    await generate_testcases()

    validation_infos = await validate_testcases()
    print_validation_report(validation_infos)

    assert has_validation_errors(validation_infos)

    out = capsys.readouterr().out
    assert 'failed verification on validator validator.cpp' in out


async def test_main_validator_report_hit_bound_issues(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('59\n')
    testing_pkg.add_file('manual_tests/001.in').write_text('73\n')

    testing_pkg.set_validator(
        'validator.cpp', src='validators/int-validator-bounded.cpp'
    )

    await generate_testcases()

    validation_infos = await validate_testcases()
    print_validation_report(validation_infos)

    assert not has_validation_errors(validation_infos)

    assert validation_infos[0].hit_bounds == {'"x"': (False, False)}
    assert validation_infos[1].hit_bounds == {'"x"': (False, False)}

    out = capsys.readouterr().out
    assert '- "x": min-value not hit' in out
    assert '- "x": max-value not hit' in out


async def test_main_validator_skip_hit_bound_issues_on_samples(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_testgroup_from_glob('samples', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('59\n')
    testing_pkg.add_file('manual_tests/001.in').write_text('73\n')

    testing_pkg.set_validator(
        'validator.cpp', src='validators/int-validator-bounded.cpp'
    )

    await generate_testcases()

    validation_infos = await validate_testcases()
    print_validation_report(validation_infos)

    assert not has_validation_errors(validation_infos)

    assert validation_infos[0].hit_bounds == {'"x"': (False, False)}
    assert validation_infos[1].hit_bounds == {'"x"': (False, False)}

    out = capsys.readouterr().out
    assert '- "x": min-value not hit' not in out
    assert '- "x": max-value not hit' not in out
    assert 'No validation issues found' in out


async def test_main_validator_no_hit_bound_issues(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('1\n')
    testing_pkg.add_file('manual_tests/001.in').write_text('100\n')

    testing_pkg.set_validator(
        'validator.cpp', src='validators/int-validator-bounded.cpp'
    )

    await generate_testcases()

    validation_infos = await validate_testcases()
    print_validation_report(validation_infos)

    for info in validation_infos:
        assert info.ok

    assert validation_infos[0].hit_bounds == {'"x"': (True, False)}
    assert validation_infos[1].hit_bounds == {'"x"': (False, True)}

    out = capsys.readouterr().out
    assert '- "x": min-value not hit' not in out
    assert '- "x": max-value not hit' not in out


async def test_group_specific_validator_catches_invalid_cases(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/main/*.in')
    testing_pkg.add_file('manual_tests/main/000.in').write_text('1\n')
    testing_pkg.add_file('manual_tests/main/001.in').write_text('100\n')

    testing_pkg.add_testgroup_from_glob(
        'stricter',
        'manual_tests/stricter/*.in',
        validator='validator_stricter.cpp',
    )
    testing_pkg.add_file('manual_tests/stricter/000.in').write_text('1\n')
    testing_pkg.add_file('manual_tests/stricter/001.in').write_text('100\n')

    testing_pkg.set_validator(
        'validator.cpp', src='validators/int-validator-bounded.cpp'
    )
    testing_pkg.add_from_testdata(
        'validator_stricter.cpp', src='validators/int-validator-bounded-stricter.cpp'
    )

    await generate_testcases()

    validation_infos = await validate_testcases()
    print_validation_report(validation_infos)

    assert validation_infos[0].ok
    assert validation_infos[1].ok
    assert validation_infos[2].ok
    assert not validation_infos[3].ok

    out = capsys.readouterr().out
    print(out)
    assert 'failed verification on validator validator_stricter.cpp' in out


async def test_group_specific_validator_overrides_main_validator(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/main/*.in')
    testing_pkg.add_file('manual_tests/main/000.in').write_text('1\n')
    testing_pkg.add_file('manual_tests/main/001.in').write_text('10\n')

    testing_pkg.add_testgroup_from_glob(
        'stricter',
        'manual_tests/stricter/*.in',
        validator='validator.cpp',
    )
    testing_pkg.add_file('manual_tests/stricter/000.in').write_text('1\n')
    testing_pkg.add_file('manual_tests/stricter/001.in').write_text('100\n')

    testing_pkg.set_validator(
        'validator_stricter.cpp', src='validators/int-validator-bounded-stricter.cpp'
    )
    testing_pkg.add_from_testdata(
        'validator.cpp', src='validators/int-validator-bounded.cpp'
    )

    await generate_testcases()

    validation_infos = await validate_testcases()
    print_validation_report(validation_infos)

    assert not has_validation_errors(validation_infos)


async def test_group_specific_extra_validators_catch_invalid_cases(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/main/*.in')
    testing_pkg.add_file('manual_tests/main/000.in').write_text('1\n')
    testing_pkg.add_file('manual_tests/main/001.in').write_text('100\n')

    testing_pkg.add_testgroup_from_glob(
        'odd',
        'manual_tests/odd/*.in',
        extra_validators=['extra-validator-odd.cpp'],
    )
    testing_pkg.add_file('manual_tests/odd/000.in').write_text('1\n')
    testing_pkg.add_file('manual_tests/odd/001.in').write_text('100\n')

    testing_pkg.set_validator(
        'validator.cpp', src='validators/int-validator-bounded.cpp'
    )
    testing_pkg.add_from_testdata(
        'extra-validator-odd.cpp', src='validators/extra-validator-odd.cpp'
    )

    await generate_testcases()

    validation_infos = await validate_testcases()
    print_validation_report(validation_infos)

    assert validation_infos[0].ok
    assert validation_infos[1].ok
    assert validation_infos[2].ok
    assert (
        validation_infos[3].ok
        and validation_infos[3].validator.path.name == 'extra-validator-odd.cpp'
    )
    assert validation_infos[4].ok
    assert (
        not validation_infos[5].ok
        and validation_infos[5].validator.path.name == 'extra-validator-odd.cpp'
    )

    out = capsys.readouterr().out
    assert 'failed verification on validator extra-validator-odd.cpp' in out


async def test_output_validator_catches_invalid_output(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    """Test that output validators can detect invalid outputs."""
    testing_pkg.add_generator('gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gen.cpp 123')

    # Solution that outputs double (incorrect)
    testing_pkg.add_solution(
        'sol.cpp',
        outcome='accepted',
    ).write_text("""
#include <iostream>
using namespace std;
int main() {
    int x; cin >> x;
    cout << x * 2 << endl;
}
""")

    # Output validator expects the output to be odd (double is always even)
    testing_pkg.add_from_testdata(
        'output_validator.cpp', src='validators/extra-validator-odd.cpp'
    )

    # Configure group with output validator
    import pathlib

    from rbx.box.schema import CodeItem

    main_group = testing_pkg.yml.testcases[0]
    main_group.outputValidators = [CodeItem(path=pathlib.Path('output_validator.cpp'))]
    testing_pkg.save()

    await generate_testcases()
    await generate_outputs_for_testcases([TestcaseEntry(group='main', index=0)])

    # Validate outputs
    entries = await extract_generation_testcases([TestcaseEntry(group='main', index=0)])
    validation_infos = await validate_outputs_from_entries(entries)
    print_validation_report(validation_infos, output_validation=True)

    assert has_validation_errors(validation_infos)

    out = capsys.readouterr().out
    assert 'failed verification on output validator output_validator.cpp' in out


async def test_output_validator_accepts_valid_output(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    """Test that output validators accept valid outputs."""
    testing_pkg.add_generator('gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gen.cpp 121')

    # Solution that outputs the same number (odd input = odd output)
    testing_pkg.add_solution(
        'sol.cpp',
        outcome='accepted',
    ).write_text("""
#include <iostream>
using namespace std;
int main() {
    int x; cin >> x;
    cout << x << endl;
}
""")

    # Output validator expects the output to be odd
    testing_pkg.add_from_testdata(
        'output_validator.cpp', src='validators/extra-validator-odd.cpp'
    )

    # Configure group with output validator
    import pathlib

    from rbx.box.schema import CodeItem

    main_group = testing_pkg.yml.testcases[0]
    main_group.outputValidators = [CodeItem(path=pathlib.Path('output_validator.cpp'))]
    testing_pkg.save()

    await generate_testcases()
    await generate_outputs_for_testcases([TestcaseEntry(group='main', index=0)])

    # Validate outputs
    entries = await extract_generation_testcases([TestcaseEntry(group='main', index=0)])
    validation_infos = await validate_outputs_from_entries(entries)

    assert not has_validation_errors(validation_infos)


async def test_output_validators_work_across_multiple_testcases(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    """Test that output validators work correctly across multiple testcases."""
    testing_pkg.add_generator('gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gen.cpp 121\ngen.cpp 122\ngen.cpp 123')

    # Solution that outputs the same number
    testing_pkg.add_solution(
        'sol.cpp',
        outcome='accepted',
    ).write_text("""
#include <iostream>
using namespace std;
int main() {
    int x; cin >> x;
    cout << x << endl;
}
""")

    # Output validator expects the output to be odd
    testing_pkg.add_from_testdata(
        'output_validator.cpp', src='validators/extra-validator-odd.cpp'
    )

    # Configure group with output validator
    import pathlib

    from rbx.box.schema import CodeItem

    main_group = testing_pkg.yml.testcases[0]
    main_group.outputValidators = [CodeItem(path=pathlib.Path('output_validator.cpp'))]
    testing_pkg.save()

    await generate_testcases()
    await generate_outputs_for_testcases(
        [
            TestcaseEntry(group='main', index=0),
            TestcaseEntry(group='main', index=1),
            TestcaseEntry(group='main', index=2),
        ]
    )

    # Validate outputs
    entries = await extract_generation_testcases(
        [
            TestcaseEntry(group='main', index=0),
            TestcaseEntry(group='main', index=1),
            TestcaseEntry(group='main', index=2),
        ]
    )
    validation_infos = await validate_outputs_from_entries(entries)
    print_validation_report(validation_infos, output_validation=True)

    # First testcase (121) is odd - should pass
    assert validation_infos[0].ok
    # Second testcase (122) is even - should fail
    assert not validation_infos[1].ok
    # Third testcase (123) is odd - should pass
    assert validation_infos[2].ok

    out = capsys.readouterr().out
    assert 'failed verification on output validator output_validator.cpp' in out


async def test_output_validators_at_package_level(
    testing_pkg: testing_package.TestingPackage,
):
    """Test that package-level output validators are applied to all testcases."""
    testing_pkg.add_generator('gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gen.cpp 121')

    # Solution that outputs the same number (odd input = odd output)
    testing_pkg.add_solution(
        'sol.cpp',
        outcome='accepted',
    ).write_text("""
#include <iostream>
using namespace std;
int main() {
    int x; cin >> x;
    cout << x << endl;
}
""")

    # Output validator expects the output to be odd
    testing_pkg.add_from_testdata(
        'output_validator.cpp', src='validators/extra-validator-odd.cpp'
    )

    # Configure package-level output validator
    import pathlib

    from rbx.box.schema import CodeItem

    testing_pkg.yml.outputValidators = [
        CodeItem(path=pathlib.Path('output_validator.cpp'))
    ]
    testing_pkg.save()

    await generate_testcases()
    await generate_outputs_for_testcases([TestcaseEntry(group='main', index=0)])

    # Validate outputs
    entries = await extract_generation_testcases([TestcaseEntry(group='main', index=0)])
    validation_infos = await validate_outputs_from_entries(entries)

    assert not has_validation_errors(validation_infos)


async def test_output_validators_at_subgroup_level(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    """Test that subgroup-level output validators are applied correctly."""
    testing_pkg.add_generator('gen.cpp', src='generators/gen-id.cpp')

    # Add output validator
    testing_pkg.add_from_testdata(
        'output_validator.cpp', src='validators/extra-validator-odd.cpp'
    )

    # Solution that outputs the same number
    testing_pkg.add_solution(
        'sol.cpp',
        outcome='accepted',
    ).write_text("""
#include <iostream>
using namespace std;
int main() {
    int x; cin >> x;
    cout << x << endl;
}
""")

    # Configure group with subgroups - only sub2 has output validator

    testing_pkg.add_testgroup_with_subgroups(
        'main',
        [
            {'name': 'sub1', 'generators': [{'name': 'gen.cpp', 'args': '121'}]},
            {
                'name': 'sub2',
                'generators': [{'name': 'gen.cpp', 'args': '122'}],
                'outputValidators': ['output_validator.cpp'],
            },
        ],
    )

    await generate_testcases()
    await generate_outputs_for_testcases(
        [
            TestcaseEntry(group='main', index=0),
            TestcaseEntry(group='main', index=1),
        ]
    )

    # Validate outputs
    entries = await extract_generation_testcases(
        [
            TestcaseEntry(group='main', index=0),
            TestcaseEntry(group='main', index=1),
        ]
    )
    validation_infos = await validate_outputs_from_entries(entries)
    print_validation_report(validation_infos, output_validation=True)

    # First testcase has no output validator - should have no validation info
    # Second testcase (122) is even and has output validator - should fail
    assert len(validation_infos) == 1
    assert not validation_infos[0].ok

    out = capsys.readouterr().out
    assert 'failed verification on output validator output_validator.cpp' in out


async def test_output_validation_skips_when_no_output_validators(
    testing_pkg: testing_package.TestingPackage,
):
    """Test that output validation is skipped when no output validators are configured."""
    testing_pkg.add_generator('gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gen.cpp 123')

    testing_pkg.add_solution(
        'sol.cpp',
        outcome='accepted',
    ).write_text("""
#include <iostream>
using namespace std;
int main() {
    int x; cin >> x;
    cout << x * 2 << endl;
}
""")

    await generate_testcases()
    await generate_outputs_for_testcases([TestcaseEntry(group='main', index=0)])

    # Validate outputs (should be empty)
    entries = await extract_generation_testcases([TestcaseEntry(group='main', index=0)])
    validation_infos = await validate_outputs_from_entries(entries)

    assert len(validation_infos) == 0


async def test_validator_receives_group_argument(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    """Test that validators receive the --group argument."""
    # Simple C++ validator that enforces limits based on group name
    # small -> limit 10
    # large -> limit 100
    testing_pkg.add_from_testdata(
        'validator_group.cpp', src='validators/group-validator.cpp'
    )
    testing_pkg.set_validator('validator_group.cpp')

    # Create groups with different constraints
    testing_pkg.add_testgroup_from_glob('small', 'manual_tests/small/*.in')
    testing_pkg.add_file('manual_tests/small/pass.in').write_text('5\\n')
    testing_pkg.add_file('manual_tests/small/fail.in').write_text('15\\n')

    testing_pkg.add_testgroup_from_glob('large', 'manual_tests/large/*.in')
    testing_pkg.add_file('manual_tests/large/pass.in').write_text('50\\n')
    testing_pkg.add_file('manual_tests/large/fail.in').write_text('150\\n')

    testing_pkg.add_testgroup_from_glob('default', 'manual_tests/default/*.in')
    testing_pkg.add_file('manual_tests/default/pass.in').write_text('500\\n')

    await generate_testcases()
    validation_infos = await validate_testcases()
    print_validation_report(validation_infos)

    results = {}
    for info in validation_infos:
        assert info.testcase is not None
        assert info.generation_metadata is not None
        assert info.generation_metadata.copied_from is not None

        group = info.testcase.group
        name = info.generation_metadata.copied_from.inputPath.name
        results[(group, name)] = info.ok

    assert results[('small', 'pass.in')] is True
    assert results[('small', 'fail.in')] is False
    assert results[('large', 'pass.in')] is True
    assert results[('large', 'fail.in')] is False
    assert results[('default', 'pass.in')] is True


async def test_check_output_from_entries_with_checker(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    """Test that check_output_from_entries validates manual outputs against the checker."""
    # Checker that fails if input is > 100
    testing_pkg.add_file('checker.cpp').write_text("""
#include "testlib.h"
using namespace std;

int main(int argc, char* argv[]) {
    registerTestlibCmd(argc, argv);
    string token = ouf.readToken();
    int userVal = atoi(token.c_str());
    if (userVal > 100) quitf(_wa, "Value too large");
    quitf(_ok, "OK");
}
""")
    testing_pkg.set_checker('checker.cpp')

    # Add manual testcases
    testing_pkg.add_file('manual/good.in').write_text('10\\n')
    testing_pkg.add_file('manual/good.out').write_text('50\\n')  # OK

    testing_pkg.add_file('manual/bad.in').write_text('20\\n')
    testing_pkg.add_file('manual/bad.out').write_text('150\\n')  # Fail > 100

    testing_pkg.add_testgroup_with_manual_testcases(
        'manual',
        [
            {'inputPath': 'manual/good.in', 'outputPath': 'manual/good.out'},
            {'inputPath': 'manual/bad.in', 'outputPath': 'manual/bad.out'},
        ],
    )

    await generate_testcases()

    # Extract entries to check
    entries = await extract_generation_testcases(
        [
            TestcaseEntry(group='manual', index=0),
            TestcaseEntry(group='manual', index=1),
        ]
    )

    # Run check_output_from_entries
    validation_infos = await check_output_from_entries(entries)
    print_validation_report(validation_infos)

    # Should have 1 failure (bad.out)
    assert len(validation_infos) == 1
    assert not validation_infos[0].ok
    assert (
        validation_infos[0].message is not None
        and 'Value too large' in validation_infos[0].message
    )
    assert validation_infos[0].path.name == 'bad.out'

    out = capsys.readouterr().out
    assert 'Checker failed on manual output' in out


async def test_check_output_from_entries_ignores_missing_outputs(
    testing_pkg: testing_package.TestingPackage,
):
    """Test that check_output_from_entries ignores entries without manual outputs."""
    testing_pkg.add_file('checker.cpp').write_text("""
#include "testlib.h"
int main(int argc, char* argv[]) {
    registerTestlibCmd(argc, argv);
    quitf(_ok, "OK");
}
""")
    testing_pkg.set_checker('checker.cpp')

    testing_pkg.add_file('manual/test.in').write_text('10\\n')
    # No output file provided

    testing_pkg.add_testgroup_with_manual_testcases(
        'manual',
        [
            {'inputPath': 'manual/test.in'},  # No outputPath
        ],
    )

    await generate_testcases()

    entries = await extract_generation_testcases(
        [TestcaseEntry(group='manual', index=0)]
    )

    validation_infos = await check_output_from_entries(entries)

    # Should be empty as there are no outputs to check
    assert len(validation_infos) == 0
