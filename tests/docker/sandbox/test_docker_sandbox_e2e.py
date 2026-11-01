"""`DockerSandbox` against a real container.

Disabled by default like everything under `tests/docker/`: needs a docker
daemon, and the first run builds the image (a few minutes). Run with

    RBX_DOCKER_TESTS=1 uv run pytest tests/docker/sandbox -v -s

What is pinned here is what the container is *for*: limits macOS cannot apply,
no network, a read-only view of the host, and the host's freshly written files
arriving whole (Docker Desktop caches attributes in the guest; see
`docker_agent.await_files`).
"""

import hashlib
import os
import pathlib
from typing import Iterator

import pytest

from rbx.box import docker_runtime
from rbx.box.setter_config import DockerConfig
from rbx.grading.judge.sandbox import SandboxParams
from rbx.grading.judge.sandboxes.docker_sandbox import DockerSandbox

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get('RBX_DOCKER_TESTS') != '1',
        reason='Docker-backed tests are disabled by default.',
    ),
]

DEEP = r"""
#include <cstdio>
int f(int n){ volatile char buf[1000]; buf[0]=(char)n; return n==0?0:f(n-1)+(buf[0]&1); }
int main(){ printf("%d\n", f(200000) * 0); }
"""


@pytest.fixture(scope='module')
def workspace(tmp_path_factory) -> pathlib.Path:
    return tmp_path_factory.mktemp('docker-workspace')


@pytest.fixture(scope='module')
def runtime(workspace: pathlib.Path) -> Iterator[docker_runtime.DockerRuntime]:
    mp = pytest.MonkeyPatch()
    mp.setattr(docker_runtime.config, 'get_app_path', lambda: workspace)
    mp.chdir(workspace)
    runtime = docker_runtime.DockerRuntime(
        DockerConfig(enabled=True, mounts=[str(workspace)], idle_timeout=120)
    )
    yield runtime
    runtime.close()
    runtime.down()
    mp.undo()


@pytest.fixture
def sandbox(runtime) -> Iterator[DockerSandbox]:
    sandbox = DockerSandbox.bind(runtime)()
    yield sandbox
    sandbox.cleanup(delete=True)


def _run(sandbox: DockerSandbox, command, **kwargs):
    params = SandboxParams(
        stdout_file=pathlib.Path('out.txt'),
        stderr_file=pathlib.Path('err.txt'),
        wallclock_timeout=60000,
        **kwargs,
    )
    log = sandbox.run(command, params)
    out = sandbox.relative_path(pathlib.Path('out.txt'))
    return log, out.read_text() if out.exists() else ''


def test_stack_follows_the_configured_limit(sandbox: DockerSandbox):
    sandbox.create_file_from_string(pathlib.Path('deep.cpp'), DEEP)
    log, _ = _run(sandbox, ['g++', '-O0', '-o', 'deep', 'deep.cpp'])
    assert log.exitcode == 0
    log, out = _run(sandbox, ['./deep'])
    assert (log.exitcode, out) == (0, '0\n')
    log, _ = _run(sandbox, ['./deep'], stack_space=8)
    assert log.exitcode != 0


def test_no_network(sandbox: DockerSandbox):
    log, out = _run(
        sandbox,
        [
            'python3',
            '-c',
            'import socket\n'
            'try:\n'
            '    socket.create_connection(("1.1.1.1", 53), timeout=3)\n'
            '    print("connected")\n'
            'except OSError:\n'
            '    print("refused")\n',
        ],
    )
    assert out.strip() == 'refused'


def test_host_is_read_only(sandbox: DockerSandbox, workspace: pathlib.Path):
    log, _ = _run(sandbox, ['touch', str(workspace / 'escaped')])
    assert log.exitcode != 0
    assert not (workspace / 'escaped').exists()


def test_large_fresh_input_arrives_whole(sandbox: DockerSandbox):
    data = os.urandom(96 * 1024 * 1024)
    with sandbox.create_file(pathlib.Path('big.bin')) as f:
        f.write(data)  # one write: the pattern Docker Desktop shows stale
    log, out = _run(sandbox, ['sha1sum', 'big.bin'])
    assert out.split()[0] == hashlib.sha1(data).hexdigest()
