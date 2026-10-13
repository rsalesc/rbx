"""rbx's own interactive driver for MOJ.

The package ships BOCA's pipe.c (built by prep.sh next to the arbiter), the
plain testlib interactor as the arbiter, and a run.sh per language that runs
the two through pipe and decides the verdict. The verdict tests run that real
run.sh with a stand-in `pipe` reporting a chosen exit order and statuses;
pipe.c itself needs epoll, so it is exercised on Linux judges only.
"""

import pathlib
import shutil
import subprocess

import pytest

from rbx.box.packaging.moj import mojtools
from rbx.box.packaging.moj.packager import supervised_run_script
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


def test_every_language_runs_its_own_command_through_the_driver(
    interactive_package,
):
    for lang_dir in (interactive_package / 'scripts').iterdir():
        if not lang_dir.is_dir():
            continue
        run = (lang_dir / 'run.sh').read_text()
        assert 'rbx_interact() {' in run
        assert '< /tmp/in > /tmp/out' not in run
        assert (lang_dir / 'run.sh').stat().st_mode & 0o111


@pytest.mark.skipif(shutil.which('bash') is None, reason='needs bash')
def test_the_scripts_are_valid_bash(interactive_package):
    for script in (interactive_package / 'scripts').glob('*/*.sh'):
        proc = subprocess.run(
            ['bash', '-n', str(script)], capture_output=True, text=True
        )
        assert proc.returncode == 0, f'{script}: {proc.stderr}'


@pytest.mark.parametrize('template', ['c', 'cpp', 'py', 'java', 'kt'])
def test_every_batch_template_can_be_supervised(template):
    batch = (APP / 'moj' / 'scripts' / template / 'run.sh').read_text()
    supervised = supervised_run_script(batch, DRIVER)
    head = '#!/bin/bash\n' + DRIVER.rstrip() + '\n'
    assert supervised.startswith(head)
    body = supervised[len(head) :]
    assert body.count('rbx_interact ') == batch.count('< /tmp/in > /tmp/out')
    assert '< /tmp/in > /tmp/out' not in supervised


def test_a_multiline_run_command_keeps_its_continuations():
    batch = (
        '#!/bin/bash\n'
        'exec &>/tmp/stderrlog\n'
        'exec java -Dx=1 \\\n'
        '     -jar "$BIN" < /tmp/in > /tmp/out\n'
    )
    assert supervised_run_script(batch, '# driver\n').endswith(
        'exec &>/tmp/stderrlog\nrbx_interact java -Dx=1 \\\n     -jar "$BIN"\n'
    )


def test_a_run_script_without_a_run_command_is_refused():
    with pytest.raises(ValueError):
        supervised_run_script('#!/bin/bash\nexec ./main\n', DRIVER)


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
    script = supervised_run_script(batch, DRIVER).replace('/tmp/', f'{jail}/')
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
