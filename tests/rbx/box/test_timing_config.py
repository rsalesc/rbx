import pytest

from rbx.box.environment import (
    DEFAULT_TIMING_FORMULA,
    TimingConfig,
    TimingMultipliers,
)
from rbx.box.schema import PackageTiming, TimingMultipliersOverride
from rbx.box.timing_config import (
    ResolutionError,
    TimingStrategy,
    resolve_multipliers,
    resolve_strategy,
)


def test_no_override_returns_the_environment_block():
    env = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    assert resolve_multipliers(env, None) == env.multipliers


def test_override_merges_field_by_field():
    env = TimingConfig(
        multipliers=TimingMultipliers(
            acToTimeLimit=2.0, timeLimitToTle=1.5, timeResolution=100
        )
    )
    pkg = PackageTiming(multipliers=TimingMultipliersOverride(inferenceTimeout=120000))
    resolved = resolve_multipliers(env, pkg)
    assert resolved is not None
    assert resolved.inferenceTimeout == 120000
    assert resolved.acToTimeLimit == 2.0
    assert resolved.timeLimitToTle == 1.5
    assert resolved.timeResolution == 100


def test_formula_environment_rejects_a_multipliers_override():
    env = TimingConfig(formula='slowest * 2')
    pkg = PackageTiming(multipliers=TimingMultipliersOverride(acToTimeLimit=3.0))
    with pytest.raises(ResolutionError, match='formula'):
        resolve_multipliers(env, pkg)


def test_formula_environment_without_override_resolves_to_none():
    assert resolve_multipliers(TimingConfig(formula='slowest * 2'), None) is None


def test_empty_package_timing_block_keeps_the_environment_multipliers():
    env = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    assert resolve_multipliers(env, PackageTiming()) == env.multipliers


def test_strategy_of_an_explicit_formula_environment():
    assert resolve_strategy(
        TimingConfig(formula='slowest * 2'), None
    ) == TimingStrategy(formula='slowest * 2')


def test_strategy_of_an_unconfigured_environment_is_the_default_formula():
    assert resolve_strategy(TimingConfig(), None) == TimingStrategy(
        formula=DEFAULT_TIMING_FORMULA
    )


def test_strategy_of_a_multipliers_environment():
    multipliers = TimingMultipliers(acToTimeLimit=2.0)
    strategy = resolve_strategy(TimingConfig(multipliers=multipliers), None)
    assert strategy == TimingStrategy(multipliers=multipliers)


def test_strategy_applies_the_per_problem_override():
    env = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    pkg = PackageTiming(multipliers=TimingMultipliersOverride(acToTimeLimit=3.0))
    strategy = resolve_strategy(env, pkg)
    assert strategy == TimingStrategy(multipliers=TimingMultipliers(acToTimeLimit=3.0))


def test_strategy_requires_exactly_one_mode():
    with pytest.raises(ValueError, match='exactly one'):
        TimingStrategy()
    with pytest.raises(ValueError, match='exactly one'):
        TimingStrategy(
            formula='slowest * 2',
            multipliers=TimingMultipliers(acToTimeLimit=2.0),
        )
