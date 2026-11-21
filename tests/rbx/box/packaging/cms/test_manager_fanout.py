"""rbx's CMS manager built for a fanout problem, run the way CMS runs it.

CMS starts the manager as `manager <from 0> <to 0> ... <from N-1> <to N-1>`
over fifos, with the test in `input.txt`, and starts process i with its stdin
and stdout on the other ends of the i-th pair and its index as `argv[1]`. The
outcome is the first line of the manager's stdout. The manager needs
`memfd_create`, so this runs on Linux only.
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

from rbx.box import header
from rbx.box.packaging.cms import communication
from rbx.box.schema import TaskType
from rbx.config import get_app_file

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith('linux') or shutil.which('g++') is None,
    reason='the CMS manager needs Linux (memfd_create) and g++',
)

PROCESSES = 2

# Process i answers v + i + 1, so the value comes back as n + 3.
INTERACTOR = r"""
#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  rbx::registerFanoutInteraction(argc, argv);
  long long v = inf.readLong();
  long long n = v;
  for (int i = 0; i < rbx::fanout::count(); i++) {
    rbx::fanout::to(i) << v << std::endl;
    v = rbx::fanout::from(i).readLong();
  }
  if (v != n + 3) quitf(_wa, "got %lld", v);
  quitf(_ok, "relayed");
}
"""

# Answers every value until end of file: it only exits once the manager closes
# its channel, which is what the test waits on.
USER = """
import sys
index = int(sys.argv[1])
step = index + 1 if sys.argv[2] == 'right' else 0
for line in sys.stdin:
    print(int(line) + step, flush=True)
"""


@pytest.fixture
def manager(testing_pkg, tmp_path) -> pathlib.Path:
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.set_interactor('interactor.cpp')
    testing_pkg.yml.interactor.processes = PROCESSES
    testing_pkg.save()
    header.generate_header()

    build = tmp_path / 'build'
    communication.write_sources(build)
    shutil.copyfile('rbx.h', build / 'rbx.h')
    shutil.copyfile(
        get_app_file(pathlib.Path('testlib.h'), predownloaded=True),
        build / 'testlib.h',
    )
    (build / 'interactor.cpp').write_text(INTERACTOR)
    binary = tmp_path / 'manager'
    subprocess.run(
        ['g++', '-std=gnu++20', '-O2', '-DRBX_CMS_FANOUT', '-I', str(build)]
        + ['-o', str(binary), str(build / communication.MANAGER_SOURCE)],
        check=True,
    )
    return binary


def _evaluate(manager: pathlib.Path, box: pathlib.Path, behaviour: str):
    box.mkdir()
    (box / 'input.txt').write_text('5\n')
    (box / 'user.py').write_text(USER)
    args = [str(manager)]
    for i in range(PROCESSES):
        for name in (f'u{i}_to_m', f'm_to_u{i}'):
            subprocess.run(['mkfifo', str(box / name)], check=True)
        args += [f'u{i}_to_m', f'm_to_u{i}']

    judge = subprocess.Popen(
        args, cwd=box, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    # The shell opens stdin before stdout, like a CMS sandbox.
    users = [
        subprocess.Popen(
            f'exec "{sys.executable}" user.py {i} {behaviour} < m_to_u{i} > u{i}_to_m',
            cwd=box,
            shell=True,
        )
        for i in range(PROCESSES)
    ]
    stdout, stderr = judge.communicate(timeout=30)
    for user in users:
        user.wait(timeout=30)
    return judge.returncode, stdout.decode(), stderr.decode()


@pytest.mark.parametrize(
    'behaviour, outcome, message',
    [('right', '1.0', 'translate:success'), ('wrong', '0.0', 'translate:wrong')],
)
def test_fanout_manager_relays_through_every_process(
    manager, tmp_path, behaviour, outcome, message
):
    code, stdout, stderr = _evaluate(manager, tmp_path / 'box', behaviour)

    assert code == 0, stderr
    assert stdout.splitlines()[0] == outcome
    assert stderr.splitlines()[0] == message
