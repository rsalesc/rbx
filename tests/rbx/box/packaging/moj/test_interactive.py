import pathlib
import shutil
import subprocess

import pytest
import typer

from rbx.box.packaging.moj.packager import MojPackager
from rbx.box.schema import TaskType
from rbx.config import get_default_app_path
from tests.rbx.box.packaging.moj.conftest import build_entries, run_packager

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

INTERACTIVE_DIR = get_default_app_path() / 'packagers' / 'moj' / 'interactive'


def _interactive_package(testing_pkg, interactor: str = INTERACTOR) -> None:
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('interactor.cpp').write_text(interactor)
    testing_pkg.set_interactor('interactor.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()


@pytest.fixture
def moj_interactive_package(testing_pkg, tmp_path) -> pathlib.Path:
    _interactive_package(testing_pkg)
    return run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))


def test_supports_interactive_problems():
    assert TaskType.COMMUNICATION in MojPackager.task_types()


def test_ships_the_interactor_as_the_arbiter_instead_of_a_checker(
    moj_interactive_package,
):
    scripts = moj_interactive_package / 'scripts'
    assert not (scripts / 'checker.cpp').exists()
    text = (scripts / 'arbitro.cpp').read_text()
    # One self-contained file: MOJ compiles scripts/arbitro.cpp alone.
    assert '#include "testlib.h"' not in text
    assert 'registerInteraction' in text
    assert text.startswith((INTERACTIVE_DIR / 'arbiter_prologue.cpp').read_text())
    assert text.endswith((INTERACTIVE_DIR / 'arbiter_epilogue.cpp').read_text())


def test_compare_is_the_interactive_stub(moj_interactive_package):
    emitted = moj_interactive_package / 'scripts' / 'compare.sh'
    assert emitted.read_bytes() == (INTERACTIVE_DIR / 'compare-stub.sh').read_bytes()
    assert emitted.stat().st_mode & 0o111


def test_every_language_runs_under_the_interactive_driver(moj_interactive_package):
    lang_dirs = [
        d for d in (moj_interactive_package / 'scripts').iterdir() if d.is_dir()
    ]
    assert lang_dirs
    for lang_dir in lang_dirs:
        run = lang_dir / 'run.sh'
        prep = lang_dir / 'prep.sh'
        assert run.read_bytes() == (INTERACTIVE_DIR / 'run.sh').read_bytes()
        assert prep.read_bytes() == (INTERACTIVE_DIR / 'prep-stub.sh').read_bytes()
        # rbx's own compile step is kept: the driver only replaces how it runs.
        assert (lang_dir / 'compile.sh').is_file()
        for script in (run, prep):
            assert script.stat().st_mode & 0o111


def test_conf_allows_the_extra_processes_and_hides_the_example_box(
    moj_interactive_package,
):
    lines = (moj_interactive_package / 'conf').read_text().splitlines()
    assert 'ULIMITS[-u]=10000' in lines
    assert 'SAMPLE=no' in lines


def test_batch_conf_is_untouched(moj_package):
    lines = (moj_package / 'conf').read_text().splitlines()
    assert not any(line.startswith('ULIMITS[-u]') for line in lines)
    assert not any(line.startswith('SAMPLE=') for line in lines)
    assert not (moj_package / 'scripts' / 'arbitro.cpp').exists()


def test_warns_that_the_pinned_limits_include_the_interactor(
    testing_pkg, tmp_path, capsys
):
    _interactive_package(testing_pkg)
    run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))
    assert 'interactor' in capsys.readouterr().out


def test_refuses_a_legacy_interactor(testing_pkg, tmp_path, capsys):
    _interactive_package(testing_pkg)
    testing_pkg.yml.interactor.legacy = True
    testing_pkg.add_file('check.cpp').write_text(
        '#include "testlib.h"\nint main(int c, char**v){ registerTestlibCmd(c, v);'
        ' quitf(_ok, "ok"); }\n'
    )
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))

    assert 'legacy interactors' in capsys.readouterr().out


def test_refuses_a_non_cpp_interactor(testing_pkg, tmp_path, capsys):
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('interactor.py').write_text('print(1)\n')
    testing_pkg.set_interactor('interactor.py')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))

    assert 'must be C++' in capsys.readouterr().out


def test_refuses_a_testlib_that_cannot_throw_its_exit_code(
    testing_pkg, tmp_path, capsys
):
    # A problem-local testlib.h wins over rbx's own; one too old to throw would
    # exit() before the arbiter can print MOJ's verdict line.
    testing_pkg.add_file('testlib.h').write_text(
        '#pragma once\nvoid registerInteraction(int, char **) {}\n'
    )
    _interactive_package(testing_pkg)

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))

    assert 'too old' in capsys.readouterr().out


# -- the arbiter, compiled and run --------------------------------------------


@pytest.fixture
def arbiter(moj_interactive_package, tmp_path) -> pathlib.Path:
    gxx = shutil.which('g++')
    if gxx is None:
        pytest.skip('g++ not available')
    binary = tmp_path / 'arbitro'
    proc = subprocess.run(
        [
            gxx,
            '-O2',
            '-std=gnu++17',
            '-o',
            str(binary),
            str(moj_interactive_package / 'scripts' / 'arbitro.cpp'),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(proc.stderr)
    return binary


def _judge(arbiter: pathlib.Path, tmp_path: pathlib.Path, test: str, contestant: str):
    """Run the arbiter the way MOJ's driver does: test path in argv[1], the
    contestant on stdin. Returns its exit code and last non-empty stderr line,
    which is the verdict MOJ reads."""
    input_path = tmp_path / 'in'
    input_path.write_text(test)
    proc = subprocess.run(
        [str(arbiter), str(input_path)],
        input=contestant,
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = [line for line in proc.stderr.splitlines() if line.strip()]
    return proc.returncode, lines[-1] if lines else ''


def test_arbiter_reports_accepted(arbiter, tmp_path):
    code, last = _judge(arbiter, tmp_path, '7\n', '7\n')
    assert code == 0
    assert last.startswith('OK ')
    assert 'guessed 7' in last


def test_arbiter_reports_wrong_answer_with_the_testlib_message(arbiter, tmp_path):
    code, last = _judge(arbiter, tmp_path, '7\n', '3\n')
    assert code == 0
    assert last == 'WRONG wrong answer expected 7, got 3'


def test_arbiter_reports_a_contestant_that_left_as_wrong(arbiter, tmp_path):
    code, last = _judge(arbiter, tmp_path, '7\n', '')
    assert code == 0
    assert last.startswith('WRONG ')


def test_arbiter_reports_an_interactor_failure_as_a_judge_error(arbiter, tmp_path):
    # An unreadable test is the interactor's fault: exiting non-zero without a
    # WRONG line is what MOJ turns into a judge error, never AC.
    code, last = _judge(arbiter, tmp_path, 'not-a-number\n', '7\n')
    assert code != 0
    assert not last.startswith(('OK', 'WRONG'))
