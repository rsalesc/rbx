import pytest
from pydantic import ValidationError

from rbx.box.environment import (
    DEFAULT_INFERENCE_TIMEOUT,
    DEFAULT_TIMING_FORMULA,
    TimingConfig,
)
from rbx.box.exception import RbxException
from rbx.box.schema import (
    PackageTiming,
    TimingMultipliers,
    TimingMultipliersOverride,
)
from rbx.box.timing_config import (
    TimingStrategy,
    TimingStrategyError,
    resolve_inference_timeout,
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
    with pytest.raises(TimingStrategyError) as exc:
        resolve_multipliers(env, pkg)
    # Reported cleanly by the CLI instead of as a traceback.
    assert isinstance(exc.value, RbxException)
    assert 'the formula `slowest * 2`' in str(exc.value)
    assert 'env.rbx.yml' in str(exc.value)


def test_default_formula_environment_does_not_claim_a_declared_formula():
    pkg = PackageTiming(multipliers=TimingMultipliersOverride(acToTimeLimit=3.0))
    with pytest.raises(TimingStrategyError) as exc:
        resolve_multipliers(TimingConfig(), pkg)
    assert 'the default formula' in str(exc.value)


def test_every_multiplier_is_overridable():
    assert set(TimingMultipliersOverride.model_fields) == set(
        TimingMultipliers.model_fields
    )


def test_merging_does_not_touch_the_environment_multipliers():
    env = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    pkg = PackageTiming(multipliers=TimingMultipliersOverride(acToTimeLimit=3.0))
    resolve_multipliers(env, pkg)
    assert env.multipliers == TimingMultipliers(acToTimeLimit=2.0)


def test_an_override_declaring_nothing_keeps_the_environment_values():
    env = TimingConfig(multipliers=TimingMultipliers(acToTimeLimit=2.0))
    pkg = PackageTiming(multipliers=TimingMultipliersOverride())
    assert resolve_multipliers(env, pkg) == env.multipliers


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


def test_strategy_narrows_to_a_formula():
    strategy = resolve_strategy(TimingConfig(formula='slowest * 2'), None)
    assert not strategy.uses_multipliers
    assert strategy.formula_or_die() == 'slowest * 2'
    with pytest.raises(AssertionError):
        strategy.multipliers_or_die()


def test_strategy_narrows_to_multipliers():
    multipliers = TimingMultipliers(acToTimeLimit=2.0)
    strategy = resolve_strategy(TimingConfig(multipliers=multipliers), None)
    assert strategy.uses_multipliers
    assert strategy.multipliers_or_die() == multipliers
    with pytest.raises(AssertionError):
        strategy.formula_or_die()


def test_strategy_requires_exactly_one_mode():
    with pytest.raises(ValueError, match='exactly one'):
        TimingStrategy()
    with pytest.raises(ValueError, match='exactly one'):
        TimingStrategy(
            formula='slowest * 2',
            multipliers=TimingMultipliers(acToTimeLimit=2.0),
        )


def test_inference_timeout_defaults_when_nothing_declares_one():
    assert resolve_inference_timeout(TimingConfig(), None) == DEFAULT_INFERENCE_TIMEOUT


def test_environment_inference_timeout_applies_in_formula_mode():
    env = TimingConfig(formula='slowest * 2', inferenceTimeout=30000)
    assert resolve_inference_timeout(env, None) == 30000
    assert resolve_strategy(env, None) == TimingStrategy(
        formula='slowest * 2', inferenceTimeout=30000
    )


def test_the_deprecated_spelling_still_configures_the_cap():
    env = TimingConfig(
        multipliers=TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=25000)
    )
    assert resolve_inference_timeout(env, None) == 25000
    assert resolve_strategy(env, None).inferenceTimeout == 25000


def test_the_problem_overrides_the_environment_cap():
    env = TimingConfig(formula='slowest * 2', inferenceTimeout=30000)
    pkg = PackageTiming(inferenceTimeout=45000)
    assert resolve_inference_timeout(env, pkg) == 45000


def test_the_problem_overrides_the_cap_of_a_multipliers_environment():
    env = TimingConfig(
        multipliers=TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=25000)
    )
    pkg = PackageTiming(inferenceTimeout=45000)
    assert resolve_strategy(env, pkg).inferenceTimeout == 45000


def test_the_deprecated_problem_spelling_still_overrides_the_environment():
    env = TimingConfig(
        multipliers=TimingMultipliers(acToTimeLimit=2.0), inferenceTimeout=25000
    )
    pkg = PackageTiming(multipliers=TimingMultipliersOverride(inferenceTimeout=45000))
    assert resolve_inference_timeout(env, pkg) == 45000


def test_the_timing_level_spelling_wins_over_the_deprecated_one():
    # They cannot be declared together in one file, but a problem raising the cap
    # the new way must not be undercut by an environment still on the old one.
    env = TimingConfig(
        multipliers=TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=25000)
    )
    pkg = PackageTiming(inferenceTimeout=1000)
    assert resolve_inference_timeout(env, pkg) == 1000


def test_declaring_the_cap_twice_in_the_environment_is_an_error():
    with pytest.raises(ValidationError, match='keep only timing.inferenceTimeout'):
        TimingConfig(
            inferenceTimeout=1000,
            multipliers=TimingMultipliers(acToTimeLimit=2.0, inferenceTimeout=2000),
        )


def test_declaring_the_cap_twice_in_the_problem_is_an_error():
    with pytest.raises(ValidationError, match='keep only timing.inferenceTimeout'):
        PackageTiming(
            inferenceTimeout=1000,
            multipliers=TimingMultipliersOverride(inferenceTimeout=2000),
        )


def test_a_formula_environment_accepts_a_problem_cap():
    # The whole point of pulling the field up: raising the cap no longer drags in
    # a multipliers block the environment does not have.
    env = TimingConfig(formula='slowest * 2')
    strategy = resolve_strategy(env, PackageTiming(inferenceTimeout=45000))
    assert strategy == TimingStrategy(formula='slowest * 2', inferenceTimeout=45000)
