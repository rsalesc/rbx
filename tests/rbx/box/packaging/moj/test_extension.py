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


def test_serial_calibration_defaults_to_off_one_run_max():
    serial = MojExtension().calibration.serial
    assert (serial.enabled, serial.runs, serial.pick) == (False, 1, 'max')


def test_serial_calibration_is_read_off_the_environment_extensions():
    extensions = Extensions.model_validate(
        {
            'moj': {
                'calibration': {'serial': {'enabled': True, 'runs': 3, 'pick': 'min'}}
            }
        }
    )
    assert extensions.moj is not None
    serial = extensions.moj.calibration.serial
    assert (serial.enabled, serial.runs, serial.pick) == (True, 3, 'min')


@pytest.mark.parametrize('serial', [{'runs': 0}, {'pick': 'median'}, {'run': 2}])
def test_serial_calibration_rejects_bad_settings(serial):
    with pytest.raises(ValidationError):
        MojExtension.model_validate({'calibration': {'serial': serial}})


def test_package_serial_defaults_to_off():
    assert MojExtension().package.serial is False


def test_package_serial_is_read_off_the_environment_extensions():
    extensions = Extensions.model_validate({'moj': {'package': {'serial': True}}})
    assert extensions.moj is not None
    assert extensions.moj.package.serial is True
