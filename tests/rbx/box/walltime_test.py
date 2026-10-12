from unittest import mock

import pytest
from pydantic import ValidationError

from rbx.box import tasks
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
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.limits import Limits


def test_get_execution_config_uses_walltime_formula_for_language():
    limits = Limits(time=1000, memory=256, output=4096)
    with mock.patch.object(
        tasks.environment, 'compute_walltime', return_value=4242
    ) as m:
        cfg = tasks._get_execution_config(limits, StupidSandbox, language='java')  # noqa: SLF001
    assert cfg.sandbox is not None
    assert cfg.sandbox.timeLimit == 1000
    assert cfg.sandbox.wallTimeLimit == 4242
    m.assert_called_once_with(1000, 'java')


def test_get_execution_config_doubletl_passes_expanded_tl_as_x():
    limits = Limits(time=1000, memory=256, output=4096, isDoubleTL=True)
    with mock.patch.object(
        tasks.environment, 'compute_walltime', return_value=9999
    ) as m:
        cfg = tasks._get_execution_config(limits, StupidSandbox, language='cpp')  # noqa: SLF001
    m.assert_called_once_with(2000, 'cpp')
    assert cfg.sandbox.wallTimeLimit == 9999


def test_timing_config_walltime_defaults():
    cfg = TimingConfig()
    assert cfg.wallTimeMultiplier == 2.0
    assert cfg.wallTimeIncrement == 0


def test_language_timing_config_optional_fields():
    cfg = LanguageTimingConfig()
    assert cfg.wallTimeMultiplier is None
    assert cfg.wallTimeIncrement is None


def test_walltime_multiplier_must_be_at_least_one():
    with pytest.raises(ValidationError):
        TimingConfig(wallTimeMultiplier=0.5)


def test_walltime_increment_must_be_nonnegative():
    with pytest.raises(ValidationError):
        TimingConfig(wallTimeIncrement=-1)


def test_language_walltime_multiplier_must_be_at_least_one():
    with pytest.raises(ValidationError):
        LanguageTimingConfig(wallTimeMultiplier=0.5)


def test_language_walltime_increment_must_be_nonnegative():
    with pytest.raises(ValidationError):
        LanguageTimingConfig(wallTimeIncrement=-1)


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
    # The default preset environment has wallTimeMultiplier=2.0 and
    # wallTimeIncrement=500ms, so wall = 2 * cpu_tl + 500 for languages
    # without a per-language override (cpp, and the env default).
    assert compute_walltime(1000, 'cpp') == 2500
    assert compute_walltime(1000, None) == 2500
    # Slow languages add a larger per-language increment in the preset:
    # py +2000ms, java/kt +3000ms.
    assert compute_walltime(1000, 'py') == 4000
    assert compute_walltime(1000, 'java') == 5000
    assert compute_walltime(1000, 'kt') == 5000


def test_interactor_wall_time_is_solution_wall_plus_fixed_margin():
    # The interactor gets the solution's wall time plus a small fixed margin so
    # it always outlives the solution; it does NOT double the solution's wall.
    margin = tasks._INTERACTOR_WALL_MARGIN_MS  # noqa: SLF001
    assert tasks._interactor_wall_time(2000) == 2000 + margin  # noqa: SLF001
    assert tasks._interactor_wall_time(5000) == 5000 + margin  # noqa: SLF001


def test_interactor_cpu_limit_is_its_own_wall_not_the_solution_cpu():
    # #893: the interactor used to inherit the solution's CPU limit (2x TL here),
    # so a slow interactor was killed while the solution sat idle, and the
    # verdict blamed the solution.
    limits = Limits(time=1000, memory=256, output=4096, isDoubleTL=True)
    with mock.patch.object(tasks.environment, 'compute_walltime', return_value=4500):
        solution_cfg = tasks._get_execution_config(limits, StupidSandbox, 'cpp')  # noqa: SLF001
        cfg = tasks._get_interactor_execution_config(  # noqa: SLF001
            limits, StupidSandbox, solution_cfg
        )
    margin = tasks._INTERACTOR_WALL_MARGIN_MS  # noqa: SLF001
    assert cfg.sandbox is not None
    assert cfg.sandbox.wallTimeLimit == 4500 + margin
    assert cfg.sandbox.timeLimit == 4500 + margin
    # The solution's own limits are untouched.
    assert solution_cfg.sandbox is not None
    assert solution_cfg.sandbox.timeLimit == 2000
    assert solution_cfg.sandbox.wallTimeLimit == 4500


def test_interactor_outlives_the_solution_without_soft_timeouts():
    # A sandbox without soft timeouts gives the solution wall == CPU limit; the
    # interactor still gets the margin on top, for both limits.
    limits = Limits(time=1000, memory=256, output=4096)
    solution_cfg = tasks._get_execution_config(limits, SandboxBase)  # noqa: SLF001
    cfg = tasks._get_interactor_execution_config(limits, SandboxBase, solution_cfg)  # noqa: SLF001
    margin = tasks._INTERACTOR_WALL_MARGIN_MS  # noqa: SLF001
    assert cfg.sandbox is not None
    assert cfg.sandbox.wallTimeLimit == 1000 + margin
    assert cfg.sandbox.timeLimit == 1000 + margin


def test_interactor_is_unbounded_when_the_solution_is():
    # `use_timelimit=False` / the estimation sentinel null the solution's TL;
    # the interactor must not end up with a limit the solution lacks.
    limits = Limits(time=None, memory=256, output=4096)
    solution_cfg = tasks._get_execution_config(limits, StupidSandbox, 'cpp')  # noqa: SLF001
    cfg = tasks._get_interactor_execution_config(limits, StupidSandbox, solution_cfg)  # noqa: SLF001
    assert cfg.sandbox is not None
    assert cfg.sandbox.timeLimit is None
    assert cfg.sandbox.wallTimeLimit is None
