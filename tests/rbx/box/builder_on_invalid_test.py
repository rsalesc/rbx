"""`rbx run --on-invalid`: what a build does with testcases that fail validation.

The default stops the run before anything is built past the inputs, which is
what a setter at the terminal wants. `warn` is for a client that starts runs on
the setter's behalf and has no way to act on an abort: the build goes on, and
the rejections are handed back for the run skeleton to carry.
"""

import pytest

from rbx.box import builder, package, run_validation
from rbx.box.environment import VerificationLevel
from rbx.box.run_validation import (
    InvalidTestcase,
    OnInvalid,
    RunValidation,
    RunValidationMode,
)
from rbx.box.testing import testing_package

pytestmark = pytest.mark.shared_cache


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage):
    """One valid and one invalid testcase, under a single-integer validator."""
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('123\n')
    testing_pkg.add_file('manual_tests/001.in').write_text('123 456\n')
    return testing_pkg


def _manifest_path():
    return package.get_build_path() / 'testset.yml'


async def test_fail_stops_the_build_and_writes_no_manifest(
    pkg: testing_package.TestingPackage,
):
    result = await builder.build_with_result(
        verification=VerificationLevel.VALIDATE.value, output=False, is_run=True
    )

    assert not result.ok
    assert not _manifest_path().exists()


async def test_warn_goes_on_and_hands_back_the_rejections(
    pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    result = await builder.build_with_result(
        verification=VerificationLevel.VALIDATE.value,
        output=False,
        is_run=True,
        on_invalid=OnInvalid.WARN,
    )

    assert result.ok
    # The build finished, so the Tests view gets its rejected cards.
    assert _manifest_path().is_file()
    assert result.input_validation is not None

    validation = run_validation.run_validation(OnInvalid.WARN, result.input_validation)
    assert validation.mode == RunValidationMode.WARN
    assert [(t.group, t.index, t.validator) for t in validation.invalid] == [
        ('main', 1, 'validator.cpp')
    ]
    out = ' '.join(capsys.readouterr().out.split())
    assert '1 testcase(s) failed validation, running them anyway' in out


async def test_a_build_that_did_not_validate_says_so(
    pkg: testing_package.TestingPackage,
):
    result = await builder.build_with_result(
        verification=VerificationLevel.VALIDATE.value,
        output=False,
        validate=False,
        is_run=True,
        on_invalid=OnInvalid.WARN,
    )

    assert result.ok
    assert result.input_validation is None
    assert run_validation.run_validation(
        OnInvalid.WARN, result.input_validation
    ) == RunValidation(mode=RunValidationMode.OFF)


def test_invalid_testcases_fall_back_to_the_given_testcase():
    from rbx.box.schema import CodeItem
    from rbx.box.testcase_schema import TestcaseEntry
    from rbx.box.validators import TestcaseValidationInfo

    info = TestcaseValidationInfo(
        validator=CodeItem(path='v.cpp'),
        testcase=None,
        generation_metadata=None,
        path='x.in',
        ok=False,
        hit_bounds={},
        message='  bad token  \n',
    )

    assert run_validation.invalid_testcases(
        [info], testcase=TestcaseEntry(group='irun', index=0)
    ) == [
        InvalidTestcase(group='irun', index=0, validator='v.cpp', message='bad token')
    ]
