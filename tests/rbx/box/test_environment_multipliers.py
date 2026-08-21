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
    # Deprecated here: the cap is resolved from `timing.inferenceTimeout`.
    assert m.inferenceTimeout is None
    assert m.timeResolution == 100


def test_ac_to_time_limit_is_required():
    with pytest.raises(ValidationError, match='acToTimeLimit'):
        TimingMultipliers(timeLimitToTle=1.5)


def test_multipliers_are_frozen():
    m = TimingMultipliers(acToTimeLimit=2.0)
    with pytest.raises(ValidationError, match='frozen'):
        m.acToTimeLimit = 3.0


def test_ratios_must_be_positive():
    with pytest.raises(ValidationError, match='acToTimeLimit'):
        TimingMultipliers(acToTimeLimit=0)
    with pytest.raises(ValidationError, match='timeLimitToTle'):
        TimingMultipliers(acToTimeLimit=2.0, timeLimitToTle=0)


def test_durations_must_be_positive():
    with pytest.raises(ValidationError, match='timeResolution'):
        TimingMultipliers(acToTimeLimit=2.0, timeResolution=0)
    with pytest.raises(ValidationError, match='inferenceTimeout'):
        TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=0)


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


def test_explicit_formula_is_preserved():
    assert TimingConfig(formula='slowest * 2').resolved_formula() == 'slowest * 2'


def test_empty_formula_is_rejected():
    with pytest.raises(ValidationError, match='formula'):
        TimingConfig(formula='')


def test_multipliers_set_leaves_no_formula():
    config = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    assert config.resolved_formula() is None
