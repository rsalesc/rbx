import contextlib
from unittest import mock

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


def test_get_limits_batch_honors_min_running_time():
    ext = BocaExtension(minRunningTime=1000)
    with _patched_packager(300, extension=ext) as packager:
        echos = _echo_lines(packager._get_limits('cpp'))  # noqa: SLF001
    assert echos[0] == 'echo 1.200'
    assert echos[1] == 'echo 4'


def test_get_limits_communication_is_single_run_and_exact():
    with _patched_packager(1234, task_type=TaskType.COMMUNICATION) as packager:
        echos = _echo_lines(packager._get_limits('cpp'))  # noqa: SLF001
    assert echos[0] == 'echo 1.234'
    assert echos[1] == 'echo 1'
