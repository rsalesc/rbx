"""rbx's own interactive driver for MOJ.

The package ships BOCA's pipe.c (built by prep.sh next to the arbiter), the
plain testlib interactor as the arbiter, and a run.sh per language: the driver,
carrying the language's batch run.sh verbatim, which it runs as the contestant
through pipe before deciding the verdict. The verdict tests run that real run.sh
with a stand-in `pipe` reporting a chosen exit order and statuses; pipe.c itself
needs epoll, so it is exercised on Linux only (tests/rbx/box/packaging/boca).
"""

import pathlib
import shutil
import subprocess

import pytest

from rbx.box.packaging.moj import mojtools
from rbx.box.packaging.moj.packager import interactive_run_script
from rbx.box.schema import TaskType
from rbx.config import get_default_app_path
from tests.rbx.box.packaging.moj.conftest import build_entries, run_packager

APP = get_default_app_path() / 'packagers'
DRIVER = (APP / 'moj' / 'interactive' / 'pipe_driver.sh').read_text()

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
def interactive_package(testing_pkg, tmp_path) -> pathlib.Path:
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('interactor.cpp').write_text(INTERACTOR)
    testing_pkg.set_interactor('interactor.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()
    return run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['tests']),
    )


def test_the_arbiter_is_the_plain_interactor(interactive_package):
    text = (interactive_package / 'scripts' / 'arbitro.cpp').read_text()
    assert 'registerInteraction' in text
    # No rbx prologue or epilogue: the arbiter exits with testlib's own codes.
    assert 'rbx_interactor_main' not in text
    assert '#include "testlib.h"' not in text


def test_the_package_ships_bocas_pipe(interactive_package):
    assert (interactive_package / 'scripts' / 'pipe.c').read_bytes() == (
        APP / 'boca' / 'pipe.c'
    ).read_bytes()


def test_prep_builds_pipe_after_mojtools_stub(interactive_package):
    lang_dirs = [d for d in (interactive_package / 'scripts').iterdir() if d.is_dir()]
    assert lang_dirs
    stub = mojtools.vendored(mojtools.INTERACTIVE_PREP_STUB).rstrip(b'\n')
    for lang_dir in lang_dirs:
        prep = lang_dir / 'prep.sh'
        assert prep.read_bytes().startswith(stub)
        assert b'scripts/pipe.c' in prep.read_bytes()
        assert prep.stat().st_mode & 0o111
    assert (interactive_package / 'scripts' / 'compare.sh').read_bytes() == (
        mojtools.vendored(mojtools.INTERACTIVE_COMPARE_STUB)
    )


def test_every_language_runs_its_batch_script_through_the_driver(
    interactive_package,
):
    for lang_dir in (interactive_package / 'scripts').iterdir():
        if not lang_dir.is_dir():
            continue
        run = (lang_dir / 'run.sh').read_text()
        assert 'rbx_interact() {' in run
        assert "<<'RBX_BATCH_RUN_EOF'" in run
        assert (lang_dir / 'run.sh').stat().st_mode & 0o111


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_the_scripts_are_valid_bash(interactive_package):
    for script in (interactive_package / 'scripts').glob('*/*.sh'):
        proc = subprocess.run(
            ['bash', '-n', str(script)], capture_output=True, text=True
        )
        assert proc.returncode == 0, f'{script}: {proc.stderr}'


def _embedded(run: str) -> str:
    """The batch run.sh the driver carries in its heredoc."""
    opening = "<<'RBX_BATCH_RUN_EOF'\n"
    start = run.index(opening) + len(opening)
    return run[start : run.index('\nRBX_BATCH_RUN_EOF\n', start)] + '\n'


@pytest.mark.parametrize('template', ['c', 'cpp', 'py', 'java', 'kt'])
def test_the_driver_carries_the_batch_script_verbatim(template):
    batch = (APP / 'moj' / 'scripts' / template / 'run.sh').read_text()
    run = interactive_run_script(batch, DRIVER)
    assert run.startswith('#!/bin/bash\n')
    assert _embedded(run) == batch


def test_a_batch_script_containing_the_delimiter_is_refused():
    with pytest.raises(ValueError):
        interactive_run_script('#!/bin/bash\necho RBX_BATCH_RUN_EOF\n', DRIVER)


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
@pytest.mark.parametrize('template', ['c', 'cpp', 'py'])
def test_the_batch_script_reads_and_writes_where_it_is_told(tmp_path, template):
    # The I/O contract the driver relies on: RBX_STDIN/RBX_STDOUT/RBX_STDERR
    # decide where the solution reads, writes and logs. (The JVM templates
    # follow the same lines; running them needs a JVM.)
    jail = tmp_path / 'jail'
    (jail / 'dir').mkdir(parents=True)
    (jail / 'dir' / 'binfile.sh').write_text('BIN=main\n')
    solution = jail / 'dir' / 'main'
    solution.write_text('#!/bin/sh\necho logged >&2\nexec tr a-z A-Z\n')
    solution.chmod(0o755)
    if template == 'py':
        # python3 runs ./main as a script: give it Python to run instead.
        solution.write_text(
            'import sys\nprint("logged", file=sys.stderr)\n'
            'sys.stdout.write(sys.stdin.read().upper())\n'
        )
    (tmp_path / 'in').write_text('hello\n')
    batch = (APP / 'moj' / 'scripts' / template / 'run.sh').read_text()
    (tmp_path / 'run.sh').write_text(batch.replace('/tmp/dir', str(jail / 'dir')))
    env = {
        'PATH': '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin',
        'RBX_STDIN': str(tmp_path / 'in'),
        'RBX_STDOUT': str(tmp_path / 'out'),
        'RBX_STDERR': str(tmp_path / 'err'),
    }
    if template == 'py' and shutil.which('python3') is None:
        pytest.skip('needs python3')
    subprocess.run(['bash', str(tmp_path / 'run.sh')], env=env, timeout=30, check=True)
    assert (tmp_path / 'out').read_text() == 'HELLO\n'
    assert 'logged' in (tmp_path / 'err').read_text()


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_the_driver_runs_the_batch_script_on_the_pipes(tmp_path):
    jail = tmp_path / 'jail'
    (jail / 'dir').mkdir(parents=True)
    (jail / 'out').write_text('')
    (jail / 'rbx-interactor.err').write_text('ok guessed 7\n')
    # A stand-in pipe that records how it was asked to run the contestant.
    pipe = jail / 'dir' / 'pipe'
    pipe.write_text(
        '#!/bin/sh\n'
        f'printf "%s\\n" "$@" > {tmp_path}/argv\n'
        f'env | grep "^RBX_" | sort > {tmp_path}/env\n'
        'printf "1\\n0\\n0\\n"\n'
    )
    pipe.chmod(0o755)
    batch = (APP / 'moj' / 'scripts' / 'cpp' / 'run.sh').read_text()
    script = interactive_run_script(batch, DRIVER).replace('/tmp/', f'{jail}/')
    (tmp_path / 'run.sh').write_text(script)
    subprocess.run(['bash', str(tmp_path / 'run.sh')], timeout=30)

    argv = (tmp_path / 'argv').read_text().splitlines()
    contestant = argv[argv.index('--') + 1 : argv.index('=')]
    assert contestant == ['/bin/bash', f'{jail}/rbx-solution.sh']
    # The script it runs is the batch run.sh, as shipped.
    assert (jail / 'rbx-solution.sh').read_text() == batch.replace('/tmp/', f'{jail}/')
    assert (tmp_path / 'env').read_text().splitlines() == [
        f'RBX_STDERR={jail}/rbx-contestant.err',
        f'RBX_STDIN={jail}/fifo.in',
        f'RBX_STDOUT={jail}/fifo.out',
    ]


# -- the verdict ------------------------------------------------------------------

EOF_MESSAGE = 'wrong output format Unexpected end of file - token expected'


def _judge(
    tmp_path: pathlib.Path,
    first: int,
    contestant: int,
    interactor: int,
    message: str,
    with_pipe: bool = True,
):
    """Run the cpp run.sh with `/tmp` redirected to a scratch dir and a stand-in
    pipe that reports `first` (1 contestant, 2 interactor) and both statuses
    (bash-like: 128+signal). Returns run.sh's exit code (3 is RE) and what it
    left in the result file (`WRONG ...` WA, any other line AC, nothing UE)."""
    jail = tmp_path / 'jail'
    (jail / 'dir').mkdir(parents=True)
    (jail / 'dir' / 'binfile.sh').write_text('BIN=main\n')
    (jail / 'out').write_text('')
    (jail / 'rbx-interactor.err').write_text(message + '\n')
    if with_pipe:
        pipe = jail / 'dir' / 'pipe'
        pipe.write_text(
            f'#!/bin/sh\nprintf "{first}\\n{contestant}\\n{interactor}\\n"\n'
        )
        pipe.chmod(0o755)
    batch = (APP / 'moj' / 'scripts' / 'cpp' / 'run.sh').read_text()
    script = interactive_run_script(batch, DRIVER).replace('/tmp/', f'{jail}/')
    (tmp_path / 'run.sh').write_text(script)
    proc = subprocess.run(['bash', str(tmp_path / 'run.sh')], timeout=30)
    return proc.returncode, (jail / 'out').read_text().strip()


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
@pytest.mark.parametrize(
    'first, contestant, interactor, message, expected',
    [
        pytest.param(1, 0, 0, 'ok guessed 7', (0, 'OK ok guessed 7'), id='accepted'),
        pytest.param(
            2, 0, 1, 'wrong answer no', (0, 'WRONG wrong answer no'), id='wrong'
        ),
        # The interactor rejected first; pipe.c then SIGTERMed the contestant,
        # which must not turn the WA into anything else (#894).
        pytest.param(
            2, 143, 1, 'wrong answer no', (0, 'WRONG wrong answer no'), id='killed'
        ),
        # A real rejection stands even if the contestant crashed afterwards.
        pytest.param(
            1,
            139,
            1,
            'wrong answer no',
            (0, 'WRONG wrong answer no'),
            id='wa-then-crash',
        ),
        # A crash, and the EOF the interactor reported because of it (#895) --
        # in either reported order.
        pytest.param(1, 139, 2, EOF_MESSAGE, (3, ''), id='crash-then-eof'),
        pytest.param(2, 134, 2, EOF_MESSAGE, (3, ''), id='eof-reaped-first'),
        # pipe.c SIGTERMs the interactor once the contestant failed.
        pytest.param(1, 139, 143, '', (3, ''), id='crash-interactor-stopped'),
        pytest.param(2, 134, 0, 'ok guessed 7', (3, ''), id='crash-after-answer'),
        # Leaving without answering, cleanly, is wrong; so is lingering silently.
        pytest.param(1, 0, 2, EOF_MESSAGE, (0, f'WRONG {EOF_MESSAGE}'), id='left'),
        pytest.param(2, 143, 2, EOF_MESSAGE, (0, f'WRONG {EOF_MESSAGE}'), id='linger'),
        # SIGPIPE after the interactor left is no failure.
        pytest.param(2, 141, 0, 'ok guessed 7', (0, 'OK ok guessed 7'), id='sigpipe'),
        # The interactor's own failure is the judge's.
        pytest.param(2, 0, 3, 'FAIL bad input', (0, ''), id='interactor-fail'),
        pytest.param(2, 0, 139, '', (0, ''), id='interactor-crash'),
    ],
)
def test_the_verdict(tmp_path, first, contestant, interactor, message, expected):
    assert _judge(tmp_path, first, contestant, interactor, message) == expected


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_a_missing_pipe_is_a_judge_error(tmp_path):
    assert _judge(tmp_path, 1, 0, 0, 'ok', with_pipe=False) == (0, '')
