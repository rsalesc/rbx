import pytest
from pydantic import ValidationError

from rbx.box.environment import (
    DEFAULT_TIMING_FORMULA,
    TimingConfig,
    TimingMultipliers,
)


def test_multipliers_defaults():
    m = TimingMultipliers(acToTimeLimit=2.0)
    assert m.timeLimitToTle is None
    assert m.inferenceTimeout == 10000
    assert m.timeResolution == 100


def test_ac_to_time_limit_is_required():
    with pytest.raises(ValidationError):
        TimingMultipliers(timeLimitToTle=1.5)


def test_ratios_must_be_positive():
    with pytest.raises(ValidationError):
        TimingMultipliers(acToTimeLimit=0)
    with pytest.raises(ValidationError):
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=0)
    with pytest.raises(ValidationError):
        TimingMultipliers(acToTimeLimit=2.0, timeResolution=0)


def test_formula_and_multipliers_are_mutually_exclusive():
    with pytest.raises(ValidationError, match='mutually exclusive'):
        TimingConfig(
            formula='slowest * 2',
            multipliers=TimingMultipliers(acToTimeLimit=2.0),
        )


def test_neither_set_resolves_to_the_legacy_formula():
    config = TimingConfig()
    assert config.multipliers is None
    assert config.resolved_formula() == DEFAULT_TIMING_FORMULA


def test_multipliers_set_leaves_no_formula():
    config = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    assert config.resolved_formula() is None
