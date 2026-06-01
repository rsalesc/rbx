from rbx.box.environment import (
    EnvironmentLanguage,
    ExecutionConfig,
    LanguageTimingConfig,
    TimingConfig,
)


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
