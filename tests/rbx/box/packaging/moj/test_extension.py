import pytest
from pydantic import ValidationError

from rbx.box.extensions import Extensions
from rbx.box.packaging.moj.extension import MojExtension


def test_org_defaults_to_none():
    # Absent means "upload under my own login"; see `resolve_problem_id`.
    assert MojExtension().org is None


def test_org_is_read_off_the_environment_extensions():
    extensions = Extensions.model_validate({'moj': {'org': 'unicamp'}})
    assert extensions.moj is not None
    assert extensions.moj.org == 'unicamp'


def test_unknown_field_is_rejected():
    # `extra='forbid'`, as every other extension: a typo in `env.rbx.yml` must
    # fail loudly rather than be silently ignored at upload time.
    with pytest.raises(ValidationError):
        MojExtension.model_validate({'orgs': 'unicamp'})


def test_unified_time_limit_defaults_to_off():
    # MOJ's own default is a per-language limit; the bundled presets turn it on.
    assert MojExtension().unifiedTimeLimit is False


def test_unified_time_limit_is_read_off_the_environment_extensions():
    extensions = Extensions.model_validate({'moj': {'unifiedTimeLimit': True}})
    assert extensions.moj is not None
    assert extensions.moj.unifiedTimeLimit is True


def test_calibration_defaults_to_one_run_max_not_serial():
    calibration = MojExtension().calibration
    assert (calibration.runs, calibration.pick, calibration.serial) == (
        1,
        'max',
        False,
    )


def test_calibration_is_read_off_the_environment_extensions():
    extensions = Extensions.model_validate(
        {'moj': {'calibration': {'runs': 3, 'pick': 'min', 'serial': True}}}
    )
    assert extensions.moj is not None
    calibration = extensions.moj.calibration
    assert (calibration.runs, calibration.pick, calibration.serial) == (
        3,
        'min',
        True,
    )


@pytest.mark.parametrize(
    'calibration',
    [{'runs': 0}, {'pick': 'median'}, {'run': 2}, {'serial': {'enabled': True}}],
)
def test_calibration_rejects_bad_settings(calibration):
    with pytest.raises(ValidationError):
        MojExtension.model_validate({'calibration': calibration})


def test_package_serial_defaults_to_off():
    assert MojExtension().package.serial is False


def test_package_serial_is_read_off_the_environment_extensions():
    extensions = Extensions.model_validate({'moj': {'package': {'serial': True}}})
    assert extensions.moj is not None
    assert extensions.moj.package.serial is True
