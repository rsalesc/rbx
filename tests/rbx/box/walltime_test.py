from rbx.box.environment import (
    EnvironmentLanguage,
    ExecutionConfig,
    LanguageTimingConfig,
    TimingConfig,
    apply_walltime_formula,
    compute_walltime,
    resolve_walltime_coeffs,
)
from rbx.box.testing import testing_package


def test_timing_config_walltime_defaults():
    cfg = TimingConfig()
    assert cfg.wallTimeMultiplier == 2.0
    assert cfg.wallTimeIncrement == 0


def test_language_timing_config_optional_fields():
    cfg = LanguageTimingConfig()
    assert cfg.wallTimeMultiplier is None
    assert cfg.wallTimeIncrement is None


def test_environment_language_accepts_timing():
    lang = EnvironmentLanguage(
        name='java',
        extension='java',
        execution=ExecutionConfig(),
        timing=LanguageTimingConfig(wallTimeIncrement=3000),
    )
    assert lang.timing is not None
    assert lang.timing.wallTimeIncrement == 3000
    assert lang.timing.wallTimeMultiplier is None


def test_resolve_coeffs_uses_env_default_when_no_language_override():
    env_timing = TimingConfig(wallTimeMultiplier=2.0, wallTimeIncrement=1000)
    lang = EnvironmentLanguage(name='cpp', extension='cpp', execution=ExecutionConfig())
    assert resolve_walltime_coeffs(env_timing, lang) == (2.0, 1000)


def test_resolve_coeffs_language_override_wins_field_by_field():
    env_timing = TimingConfig(wallTimeMultiplier=2.0, wallTimeIncrement=1000)
    lang = EnvironmentLanguage(
        name='java',
        extension='java',
        execution=ExecutionConfig(),
        timing=LanguageTimingConfig(wallTimeIncrement=3000),
    )
    assert resolve_walltime_coeffs(env_timing, lang) == (2.0, 3000)


def test_resolve_coeffs_with_none_language():
    env_timing = TimingConfig(wallTimeMultiplier=3.0, wallTimeIncrement=500)
    assert resolve_walltime_coeffs(env_timing, None) == (3.0, 500)


def test_apply_walltime_formula():
    assert apply_walltime_formula(1000, (2.0, 0)) == 2000
    assert apply_walltime_formula(1000, (2.0, 1000)) == 3000
    assert apply_walltime_formula(1500, (1.5, 250)) == 2500


def test_apply_walltime_formula_truncates():
    # 1001 * 1.5 = 1501.5 -> int() truncates toward zero to 1501.
    assert apply_walltime_formula(1001, (1.5, 0)) == 1501


def test_compute_walltime_uses_active_environment(
    testing_pkg: testing_package.TestingPackage,
):
    # The default preset environment has wallTimeMultiplier=2.0,
    # wallTimeIncrement=0, so the wall time is twice the CPU time limit.
    assert compute_walltime(1000, 'cpp') == 2000
    assert compute_walltime(1000, None) == 2000
