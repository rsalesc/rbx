import pytest

from rbx.box.generators import generate_testcases
from rbx.box.testing import testing_package
from rbx.box.validators import (
    has_validation_errors,
    print_validation_report,
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
