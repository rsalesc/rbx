import contextlib
from unittest import mock

from rbx.box.packaging.boca.boca_language_utils import (
    get_rbx_language_from_boca_language,
)
from rbx.box.packaging.boca.extension import BocaExtension
from rbx.box.packaging.boca.packager import (
    BocaPackager,
    _compute_reps,
    _fmt_seconds,
)
from rbx.box.schema import TaskType


def test_fmt_seconds_is_exact():
    assert _fmt_seconds(1234) == '1.234'
    assert _fmt_seconds(2000) == '2.000'
    assert _fmt_seconds(500) == '0.500'
    assert _fmt_seconds(50) == '0.050'
    assert _fmt_seconds(1200) == '1.200'
    assert _fmt_seconds(0) == '0.000'


def test_compute_reps_single_run_when_no_minimum():
    assert _compute_reps(1200, None) == (1, False)
    assert _compute_reps(50, None) == (1, False)


def test_compute_reps_ceil_to_reach_minimum_budget():
    # 0.3s TL, 1s minimum -> ceil(1000/300) = 4 reps, budget 1.2s, not capped.
    assert _compute_reps(300, 1000) == (4, False)
    # exact multiple: 0.5s TL, 1s minimum -> 2 reps.
    assert _compute_reps(500, 1000) == (2, False)
    # TL already >= minimum -> 1 rep.
    assert _compute_reps(1500, 1000) == (1, False)


def test_compute_reps_caps_at_max_reps_and_flags():
    # 0.05s TL, 2s minimum would need 40 reps; cap at 10 and flag capped=True.
    assert _compute_reps(50, 2000) == (10, True)


def test_compute_reps_handles_nonpositive_tl():
    assert _compute_reps(0, 1000) == (1, False)
    assert _compute_reps(-5, 1000) == (1, False)


class _StubPackage:
    def __init__(self, task_type=TaskType.BATCH, output_limit=65536):
        self.type = task_type
        self.outputLimit = output_limit


@contextlib.contextmanager
def _patched_packager(tl_ms, task_type=TaskType.BATCH, extension=None):
    pkg = _StubPackage(task_type=task_type)
    packager = BocaPackager(testcase_entries=[])
    with (
        mock.patch.object(packager, '_get_pkg_timelimit', return_value=tl_ms),
        mock.patch.object(packager, '_get_pkg_memorylimit', return_value=256),
        mock.patch(
            'rbx.box.packaging.boca.packager.package.find_problem_package_or_die',
            return_value=pkg,
        ),
        mock.patch(
            'rbx.box.packaging.boca.packager.get_extension_or_default',
            return_value=extension if extension is not None else BocaExtension(),
        ),
    ):
        yield packager


def _echo_lines(script):
    return [line for line in script.splitlines() if line.startswith('echo ')]


def test_get_limits_batch_emits_exact_budget_single_run():
    with _patched_packager(1200) as packager:
        echos = _echo_lines(packager._get_limits('cpp'))  # noqa: SLF001
    assert echos[0] == 'echo 1.200'
    assert echos[1] == 'echo 1'
    assert echos[2] == 'echo 256'
    assert echos[3] == 'echo 65536'


def test_get_limits_batch_honors_min_running_time():
    ext = BocaExtension(minRunningTime=1000)
    with _patched_packager(300, extension=ext) as packager:
        echos = _echo_lines(packager._get_limits('cpp'))  # noqa: SLF001
    assert echos[0] == 'echo 1.200'
    assert echos[1] == 'echo 4'
    assert echos[2] == 'echo 256'
    assert echos[3] == 'echo 65536'


def test_get_limits_communication_is_single_run_and_exact():
    with _patched_packager(1234, task_type=TaskType.COMMUNICATION) as packager:
        echos = _echo_lines(packager._get_limits('cpp'))  # noqa: SLF001
    assert echos[0] == 'echo 1.234'
    assert echos[1] == 'echo 1'
    assert echos[2] == 'echo 256'
    assert echos[3] == 'echo 65536'


_WALL_SAMPLE = (
    'rtime=$(awk "BEGIN {print int($time+0.9999999)}")\n'
    'if [ "$rtime" -le "0" ]; then\n'
    '  time=1\n'
    'fi\n'
    'ttime=$(awk "BEGIN {print int($time * {{rbxWallMultiplier}} '
    '+ {{rbxWallIncrement}} * $nruns + 0.9999999)}")\n'
)


@contextlib.contextmanager
def _patched_coeffs(multiplier, increment_ms):
    with (
        mock.patch(
            'rbx.box.packaging.boca.packager.environment.resolve_walltime_coeffs',
            return_value=(multiplier, increment_ms),
        ),
        mock.patch(
            'rbx.box.packaging.boca.packager.environment.get_environment',
        ),
        mock.patch(
            'rbx.box.packaging.boca.packager.environment.get_language_or_nil',
        ),
    ):
        yield BocaPackager(testcase_entries=[])


def test_replace_walltime_uses_default_formula_no_plus_30():
    # Default coefficients: multiplier=2.0, increment=0ms.
    with _patched_coeffs(2.0, 0) as packager:
        out = packager._replace_walltime(_WALL_SAMPLE, 'cc')  # noqa: SLF001
    assert '* 2' in out
    assert '+ 0.000' in out
    assert '* $nruns' in out
    assert '{{rbxWallMultiplier}}' not in out
    assert '{{rbxWallIncrement}}' not in out
    assert '+ 30' not in out
    assert 'ttime=30' not in out


def test_replace_walltime_on_real_run_template():
    from rbx.config import get_default_app_path

    template = (
        get_default_app_path() / 'packagers' / 'boca' / 'run' / 'cc'
    ).read_text()
    with _patched_coeffs(2.0, 0) as packager:
        out = packager._replace_walltime(template, 'cc')  # noqa: SLF001
    assert '* 2' in out
    assert '+ 0.000' in out
    assert '+ 30' not in out
    assert 'ttime=30' not in out


def test_replace_walltime_uses_single_formula_with_wall_floor():
    # The wall formula now appears exactly once; the degenerate branch only
    # forces time=1 (so wall stays >= the forced 1s CPU) before the shared
    # awk expression runs. No increment-only expression (which would yield
    # ttime=0 under increment=0) survives.
    from rbx.config import get_default_app_path

    template = (
        get_default_app_path() / 'packagers' / 'boca' / 'run' / 'cc'
    ).read_text()
    with _patched_coeffs(2.0, 0) as packager:
        out = packager._replace_walltime(template, 'cc')  # noqa: SLF001
    awk_expr = 'int($time * 2 + 0.000 * $nruns + 0.9999999)'
    assert out.count(awk_expr) == 1
    assert 'int(0.000+0.9999999)' not in out
    assert 'int(0.000 + 0.9999999)' not in out


def test_cc_and_cpp_map_to_same_rbx_language_and_substitution():
    assert get_rbx_language_from_boca_language(
        'cc'
    ) == get_rbx_language_from_boca_language('cpp')
    with _patched_coeffs(2.0, 0) as packager:
        cc_out = packager._replace_walltime(_WALL_SAMPLE, 'cc')  # noqa: SLF001
        cpp_out = packager._replace_walltime(_WALL_SAMPLE, 'cpp')  # noqa: SLF001
    assert cc_out == cpp_out


def test_replace_walltime_honors_per_language_increment_override():
    # Simulate an override of the increment to 3000ms.
    with _patched_coeffs(2.0, 3000) as packager:
        out = packager._replace_walltime(_WALL_SAMPLE, 'java')  # noqa: SLF001
    assert '+ 3.000' in out
    assert '+ 30' not in out
