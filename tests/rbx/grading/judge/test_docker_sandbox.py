"""`DockerSandbox` and its agent, without Docker.

The agent's command is a parameter: in production it is a `docker exec -i`, and
here it is the agent run directly on this machine. That exercises everything
rbx owns -- the wire protocol, error passthrough, concurrency, the box staying on
the host -- and leaves only the container itself to the docker-gated suite.
"""

import pathlib
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

import pytest

from rbx.grading.judge.program import ProgramNotFoundError
from rbx.grading.judge.sandbox import SandboxParams
from rbx.grading.judge.sandboxes import docker_agent
from rbx.grading.judge.sandboxes.docker_agent import AgentClient, AgentError
from rbx.grading.judge.sandboxes.docker_sandbox import DockerSandbox
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.steps_with_caching import _with_executor

AGENT = [sys.executable, '-m', 'rbx.grading.judge.sandboxes.docker_agent', 'serve']


def _agent(slots_dir: pathlib.Path, slots: int = 1) -> AgentClient:
    # A private slots directory, so tests running in parallel never share slots.
    return AgentClient([*AGENT, '--slots', str(slots), '--slots-dir', str(slots_dir)])


class FakeBackend:
    def __init__(
        self,
        box_root: pathlib.Path,
        visible: List[pathlib.Path],
        slots: int = 1,
    ):
        self.root = box_root
        self.visible = visible
        self.agent = _agent(box_root.parent / 'slots', slots)

    def box_root(self) -> pathlib.Path:
        return self.root

    def client(self) -> AgentClient:
        return self.agent

    def fingerprint(self) -> str:
        return 'docker:fake'

    def not_found_hint(self, executable: str) -> str:
        return f'install {executable} in the image'

    def is_visible(self, path: pathlib.Path) -> bool:
        return any(path.is_relative_to(root) for root in [self.root, *self.visible])


@pytest.fixture
def backend(tmp_path: pathlib.Path):
    backend = FakeBackend(tmp_path / 'boxes', visible=[tmp_path / 'mounted'])
    yield backend
    backend.agent.close()


@pytest.fixture
def sandbox(backend: FakeBackend):
    sandbox = DockerSandbox.bind(backend)()
    yield sandbox
    sandbox.cleanup(delete=True)


def _params(**kwargs) -> SandboxParams:
    kwargs.setdefault('stdout_file', pathlib.Path('out.txt'))
    kwargs.setdefault('stderr_file', pathlib.Path('err.txt'))
    # A wall limit on everything, so a test that goes wrong fails instead of
    # hanging the suite.
    kwargs.setdefault('wallclock_timeout', 10000)
    return SandboxParams(**kwargs)


def test_boxes_live_under_the_backend_root_whatever_temp_dir_is_asked(
    backend: FakeBackend, tmp_path: pathlib.Path
):
    sandbox = DockerSandbox.bind(backend)(temp_dir=tmp_path / 'elsewhere')
    try:
        assert sandbox.get_root_path().parent == backend.root
    finally:
        sandbox.cleanup(delete=True)


def test_run_goes_through_the_agent_and_matches_a_direct_run(
    sandbox: DockerSandbox, tmp_path: pathlib.Path
):
    script = 'import sys; print(sys.stdin.read().upper()); sys.exit(3)'
    for sb in (sandbox, StupidSandbox()):
        sb.create_file_from_string(pathlib.Path('in.txt'), 'hello')
        log = sb.run(
            [sys.executable, '-c', script], _params(stdin_file=pathlib.Path('in.txt'))
        )
        assert log.exitcode == 3
        assert log.exitstatus == StupidSandbox.EXIT_NONZERO_RETURN
        assert sb.get_file_to_string(pathlib.Path('out.txt')) == 'HELLO\n'
        # The command log is written by whoever ran the program -- the agent,
        # here -- into the shared box.
        assert 'print' in sb.get_file_to_string(sb.cmd_file)


def test_limits_are_enforced_by_the_agent(sandbox: DockerSandbox):
    log = sandbox.run(
        [sys.executable, '-c', 'while True: pass'],
        _params(timeout=300, wallclock_timeout=3000),
    )
    assert log.exitstatus == StupidSandbox.EXIT_TIMEOUT


def test_program_not_found_is_raised_on_the_host(sandbox: DockerSandbox):
    with pytest.raises(ProgramNotFoundError) as exc:
        sandbox.run(['definitely-not-a-compiler-rbx'], _params())
    assert exc.value.executable == 'definitely-not-a-compiler-rbx'
    assert sandbox.program_not_found_hint('kotlinc') == 'install kotlinc in the image'


def test_run_communication_goes_through_the_agent(sandbox: DockerSandbox):
    sandbox.create_file_from_string(
        pathlib.Path('interactor.py'),
        'import sys\nprint(5, flush=True)\n'
        'sys.exit(0 if sys.stdin.readline().split() == ["6"] else 1)\n',
    )
    sandbox.create_file_from_string(
        pathlib.Path('solution.py'),
        'print(int(input()) + 1, flush=True)\n',
    )
    solution, interactor = sandbox.run_communication(
        [sys.executable, 'solution.py'],
        SandboxParams(timeout=5000, wallclock_timeout=10000),
        [sys.executable, 'interactor.py'],
        SandboxParams(timeout=5000, wallclock_timeout=10000),
    )
    assert solution.exitcode == 0
    assert interactor.exitcode == 0


TIMED = 'import time; s = time.time(); time.sleep(0.2); print(s, time.time())'


def _intervals(backends: List[FakeBackend], jobs: int) -> List[tuple]:
    """Run `jobs` timed programs concurrently, round-robin over `backends`."""

    def job(i: int) -> tuple:
        sb = DockerSandbox.bind(backends[i % len(backends)])()
        try:
            sb.run([sys.executable, '-c', TIMED], _params())
            start, end = sb.get_file_to_string(pathlib.Path('out.txt')).split()
            return float(start), float(end)
        finally:
            sb.cleanup(delete=True)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return sorted(pool.map(job, range(jobs)))


def _overlaps(intervals: List[tuple]) -> bool:
    return any(b[0] < a[1] for a, b in zip(intervals, intervals[1:]))


def test_programs_run_one_at_a_time_by_default(backend: FakeBackend):
    # Concurrent requests to one agent are accepted, but run in turn.
    assert not _overlaps(_intervals([backend], 4))


def test_agents_share_the_slot_across_processes(tmp_path: pathlib.Path):
    # Two agents stand for two rbx processes using the same container.
    backends = [
        FakeBackend(tmp_path / 'boxes', visible=[]),
        FakeBackend(tmp_path / 'boxes', visible=[]),
    ]
    try:
        assert not _overlaps(_intervals(backends, 4))
    finally:
        for backend in backends:
            backend.agent.close()


def test_more_slots_let_programs_run_together(tmp_path: pathlib.Path):
    backend = FakeBackend(tmp_path / 'boxes', visible=[], slots=4)
    try:
        assert _overlaps(_intervals([backend], 4))
    finally:
        backend.agent.close()


def test_a_dead_agent_fails_requests_instead_of_hanging(tmp_path: pathlib.Path):
    client = AgentClient([sys.executable, '-c', 'import sys; sys.exit(7)'])
    with pytest.raises(AgentError, match='exited'):
        client.run(tmp_path, ['true'], SandboxParams())
    with pytest.raises(AgentError):
        client.ping()


def test_symlinks_the_container_cannot_see_become_copies(
    sandbox: DockerSandbox, tmp_path: pathlib.Path
):
    mounted = tmp_path / 'mounted'
    mounted.mkdir()
    (mounted / 'visible.txt').write_text('v')
    hidden = tmp_path / 'hidden.txt'
    hidden.write_text('h')

    assert sandbox.create_symlink(pathlib.Path('a'), mounted / 'visible.txt')
    assert sandbox.relative_path(pathlib.Path('a')).is_symlink()
    assert sandbox.create_symlink(pathlib.Path('b'), hidden) is None


@pytest.mark.asyncio
async def test_invisible_executables_are_copied_into_the_box(
    sandbox: DockerSandbox, tmp_path: pathlib.Path
):
    hidden = tmp_path / 'hidden-exe'
    hidden.write_text('#!/bin/sh\necho hi\n')
    hidden.chmod(0o755)
    await sandbox.create_file_from_other_file(
        pathlib.Path('exe'), hidden, executable=True, try_symlink=True
    )
    exe = sandbox.relative_path(pathlib.Path('exe'))
    assert not exe.is_symlink()
    assert exe.read_text() == hidden.read_text()


def test_runs_off_the_host_and_keys_the_cache_on_the_image(sandbox: DockerSandbox):
    assert not DockerSandbox.runs_on_host()
    assert StupidSandbox.runs_on_host()
    assert _with_executor({'a': 1}, sandbox) == {
        'a': 1,
        '__executor__': 'docker:fake',
    }
    plain = StupidSandbox()
    try:
        assert _with_executor({'a': 1}, plain) == {'a': 1}
    finally:
        plain.cleanup(delete=True)


def test_await_files_waits_for_a_late_write(tmp_path: pathlib.Path):
    target = tmp_path / 'input.txt'
    target.write_text('')

    def write_later():
        time.sleep(0.2)
        target.write_text('12345')

    thread = threading.Thread(target=write_later)
    thread.start()
    docker_agent.await_files(tmp_path, {'input.txt': 5})
    thread.join()
    assert target.read_text() == '12345'


def test_await_files_gives_up_loudly(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(docker_agent, 'SYNC_TIMEOUT_SECONDS', 0.1)
    (tmp_path / 'input.txt').write_text('')
    with pytest.raises(AgentError, match='did not reach its 5 bytes'):
        docker_agent.await_files(tmp_path, {'input.txt': 5})


def test_manifest_follows_symlinks(tmp_path: pathlib.Path):
    (tmp_path / 'real.txt').write_text('abc')
    box = tmp_path / 'box'
    (box / 'sub').mkdir(parents=True)
    (box / 'sub' / 'f.txt').write_text('xy')
    (box / 'link.txt').symlink_to(tmp_path / 'real.txt')
    assert docker_agent.manifest(box) == {'sub/f.txt': 2, 'link.txt': 3}


def test_keeper_returns_once_idle(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(docker_agent, 'AGENTS_DIR', tmp_path / 'agents')
    monkeypatch.setattr(docker_agent, 'KEEPER_POLL_SECONDS', 0.05)
    start = time.monotonic()
    docker_agent.keep(idle_timeout=0.2)
    assert time.monotonic() - start < 2


def test_live_agents_forgets_dead_ones(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    agents = tmp_path / 'agents'
    monkeypatch.setattr(docker_agent, 'AGENTS_DIR', agents)
    agents.mkdir()
    (agents / str(_pid_of_exited_process())).touch()
    import os

    (agents / str(os.getpid())).touch()
    assert docker_agent.live_agents() == 1
    assert sorted(p.name for p in agents.iterdir()) == [str(os.getpid())]


def _pid_of_exited_process() -> int:
    import subprocess

    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


def test_unbound_docker_sandbox_says_so():
    with pytest.raises(RuntimeError, match='bind'):
        DockerSandbox()
