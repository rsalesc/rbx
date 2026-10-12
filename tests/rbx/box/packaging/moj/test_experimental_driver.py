"""`rbx package moj --experimental`: rbx's own interactive driver.

The arbiter becomes a supervisor that runs the contestant itself, so these tests
compile it once and judge small shell-script contestants with it, the way the
language's run.sh would (`arbitro <input> -- <command...>`).
"""

import pathlib
import shutil
import subprocess
import time

import pytest

from rbx.box.packaging.moj import mojtools
from rbx.box.packaging.moj.packager import supervised_run_script
from rbx.box.schema import TaskType
from rbx.config import get_default_app_path
from tests.rbx.box.packaging.moj.conftest import build_entries, run_packager

INTERACTIVE_DIR = get_default_app_path() / 'packagers' / 'moj' / 'interactive'
SCRIPTS_DIR = get_default_app_path() / 'packagers' / 'moj' / 'scripts'
TESTLIB_DIR = get_default_app_path() / 'predownloaded'

# Reads the hidden number from the input and one guess from the contestant.
INTERACTOR = """#include "testlib.h"
int main(int argc, char *argv[]) {
  registerInteraction(argc, argv);
  int x = inf.readInt();
  int guess = ouf.readInt();
  if (guess != x)
    quitf(_wa, "expected %d, got %d", x, guess);
  quitf(_ok, "guessed %d", x);
}
"""


# -- the package ----------------------------------------------------------------


@pytest.fixture
def experimental_package(testing_pkg, tmp_path) -> pathlib.Path:
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('interactor.cpp').write_text(INTERACTOR)
    testing_pkg.set_interactor('interactor.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()
    return run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['tests']),
        experimental=True,
    )


def test_the_arbiter_ends_in_the_supervisor(experimental_package):
    text = (experimental_package / 'scripts' / 'arbitro.cpp').read_text()
    assert text.endswith((INTERACTIVE_DIR / 'supervisor_epilogue.cpp').read_text())


def test_every_language_hands_its_own_run_command_to_the_arbiter(
    experimental_package,
):
    lang_dirs = [d for d in (experimental_package / 'scripts').iterdir() if d.is_dir()]
    assert lang_dirs
    for lang_dir in lang_dirs:
        run = (lang_dir / 'run.sh').read_text()
        assert 'exec /tmp/dir/arbitro /tmp/in -- ' in run
        assert '< /tmp/in > /tmp/out' not in run
        assert (lang_dir / 'run.sh').stat().st_mode & 0o111
        # The host-side stubs stay mojtools': prep.sh still compiles arbitro.cpp,
        # which now carries the supervisor.
        assert (lang_dir / 'prep.sh').read_bytes() == mojtools.vendored(
            mojtools.INTERACTIVE_PREP_STUB
        )
    assert (experimental_package / 'scripts' / 'compare.sh').read_bytes() == (
        mojtools.vendored(mojtools.INTERACTIVE_COMPARE_STUB)
    )


@pytest.mark.parametrize('template', ['c', 'cpp', 'py', 'java', 'kt'])
def test_every_batch_template_can_be_supervised(template):
    batch = (SCRIPTS_DIR / template / 'run.sh').read_text()
    supervised = supervised_run_script(batch)
    assert supervised.startswith('#!/bin/bash\n# EXPERIMENTAL')
    assert supervised.count('exec /tmp/dir/arbitro /tmp/in -- ') == batch.count(
        '< /tmp/in > /tmp/out'
    )
    assert '< /tmp/in > /tmp/out' not in supervised


def test_a_multiline_run_command_keeps_its_continuations():
    batch = (
        '#!/bin/bash\n'
        'exec &>/tmp/stderrlog\n'
        'exec java -Dx=1 \\\n'
        '     -jar "$BIN" < /tmp/in > /tmp/out\n'
    )
    assert supervised_run_script(batch).endswith(
        'exec &>/tmp/stderrlog\n'
        'exec /tmp/dir/arbitro /tmp/in -- java -Dx=1 \\\n'
        '     -jar "$BIN"\n'
    )


def test_a_run_script_without_a_run_command_is_refused():
    with pytest.raises(ValueError):
        supervised_run_script('#!/bin/bash\nexec ./main\n')


# -- the supervisor, compiled and run ----------------------------------------------


@pytest.fixture(scope='module')
def supervisor(tmp_path_factory) -> pathlib.Path:
    gxx = shutil.which('g++')
    if gxx is None:
        pytest.skip('g++ not available')
    root = tmp_path_factory.mktemp('supervisor')
    source = root / 'arbitro.cpp'
    source.write_text(
        (INTERACTIVE_DIR / 'arbiter_prologue.cpp').read_text()
        + INTERACTOR
        + '\n'
        + (INTERACTIVE_DIR / 'supervisor_epilogue.cpp').read_text()
    )
    binary = root / 'arbitro'
    proc = subprocess.run(
        [
            gxx,
            '-O2',
            '-std=gnu++17',
            '-I',
            str(TESTLIB_DIR),
            '-o',
            str(binary),
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(proc.stderr)
    return binary


def _judge(supervisor: pathlib.Path, tmp_path: pathlib.Path, test: str, script: str):
    """Judge a contestant written as a shell script. Returns the exit code (3 is
    MOJ's Runtime Error), what landed in the result file (`WRONG ...` is WA, any
    other line AC, nothing at all a judge error), and the report."""
    input_path = tmp_path / 'in'
    input_path.write_text(test)
    out = tmp_path / 'out'
    out.write_text('')
    proc = subprocess.run(
        [str(supervisor), str(input_path), '--', 'sh', '-c', script],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            'RBX_MOJ_OUT': str(out),
            'RBX_MOJ_TMP': str(tmp_path),
            'PATH': '/usr/bin:/bin',
        },
    )
    return proc.returncode, out.read_text().strip(), proc.stderr


def test_a_correct_answer_is_accepted(supervisor, tmp_path):
    code, result, _ = _judge(supervisor, tmp_path, '7\n', 'echo 7')
    assert (code, result) == (0, 'OK ok guessed 7')


def test_a_wrong_answer_is_wrong(supervisor, tmp_path):
    code, result, _ = _judge(supervisor, tmp_path, '7\n', 'echo 3')
    assert (code, result) == (0, 'WRONG wrong answer expected 7, got 3')


def test_leaving_without_answering_is_wrong(supervisor, tmp_path):
    code, result, _ = _judge(supervisor, tmp_path, '7\n', 'exit 0')
    assert code == 0
    assert result.startswith('WRONG ')


@pytest.mark.parametrize(
    'script',
    [
        pytest.param('exit 2', id='nonzero-before-answering'),
        pytest.param('kill -SEGV $$', id='crash-before-answering'),
    ],
)
def test_a_crash_before_the_answer_is_a_runtime_error(supervisor, tmp_path, script):
    # The interactor then complains about EOF; that is the crash's consequence
    # (#895).
    code, result, report = _judge(supervisor, tmp_path, '7\n', script)
    assert (code, result) == (3, '')
    assert 'contestant ended first' in report


@pytest.mark.parametrize(
    'script',
    [
        pytest.param('echo 7; sleep 0.2; exit 1', id='nonzero-after-answer'),
        pytest.param('echo 7; sleep 0.2; kill -ABRT $$', id='abort-after-answer'),
    ],
)
def test_a_crash_after_a_correct_answer_is_a_runtime_error(
    supervisor, tmp_path, script
):
    code, result, _ = _judge(supervisor, tmp_path, '7\n', script)
    assert (code, result) == (3, '')


def test_a_crash_the_interactor_noticed_first_is_still_a_runtime_error(
    supervisor, tmp_path
):
    # A dying contestant closes its pipes before it can be reaped, so the
    # interactor's EOF rejection may be reaped first. The verdict must follow the
    # cause, not the reaping order.
    code, result, report = _judge(
        supervisor, tmp_path, '7\n', 'exec 1>&-; sleep 0.1; exit 1'
    )
    assert (code, result) == (3, '')
    assert 'interactor ended first' in report


def test_a_contestant_that_stops_writing_but_lingers_is_wrong(supervisor, tmp_path):
    start = time.monotonic()
    code, result, report = _judge(supervisor, tmp_path, '7\n', 'exec 1>&-; sleep 30')
    assert time.monotonic() - start < 10
    assert code == 0
    assert result.startswith('WRONG ')
    assert 'killed by the driver' in report


def test_a_rejected_contestant_is_stopped_and_judged_wrong(supervisor, tmp_path):
    # Once the interactor has rejected, a contestant that keeps running must not
    # turn the WA into a TLE (#894).
    start = time.monotonic()
    code, result, report = _judge(supervisor, tmp_path, '7\n', 'echo 3; sleep 30')
    assert time.monotonic() - start < 10
    assert (code, result) == (0, 'WRONG wrong answer expected 7, got 3')
    assert 'killed by the driver' in report


def test_a_crash_after_being_rejected_stays_wrong(supervisor, tmp_path):
    code, result, _ = _judge(
        supervisor, tmp_path, '7\n', 'echo 3; sleep 0.2; kill -SEGV $$'
    )
    assert (code, result) == (0, 'WRONG wrong answer expected 7, got 3')


def test_an_interactor_failure_is_a_judge_error(supervisor, tmp_path):
    code, result, report = _judge(supervisor, tmp_path, 'not-a-number\n', 'echo 7')
    assert (code, result) == (0, '')
    assert 'judge error' in report


def test_a_contestant_that_cannot_start_is_a_judge_error(supervisor, tmp_path):
    input_path = tmp_path / 'in'
    input_path.write_text('7\n')
    out = tmp_path / 'out'
    out.write_text('')
    proc = subprocess.run(
        [str(supervisor), str(input_path), '--', str(tmp_path / 'missing')],
        capture_output=True,
        text=True,
        timeout=30,
        env={'RBX_MOJ_OUT': str(out), 'RBX_MOJ_TMP': str(tmp_path)},
    )
    assert (proc.returncode, out.read_text()) == (0, '')
    assert 'cannot run' in proc.stderr


def test_the_contestant_stderr_reaches_the_report(supervisor, tmp_path):
    _, _, report = _judge(supervisor, tmp_path, '7\n', 'echo oops >&2; echo 7')
    assert 'oops' in report
