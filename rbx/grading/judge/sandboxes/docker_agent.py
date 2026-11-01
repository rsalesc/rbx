"""The process that runs programs on behalf of `DockerSandbox`, and its client.

`DockerSandbox` does not run anything itself. It prepares a box on the host,
exactly as `StupidSandbox` does, and asks an agent living in a container to run
the program in it. The agent runs it with `StupidSandbox` -- the same class, the
same rlimits, the same watchdog -- pointed at that box, which the container sees
at the same absolute path. So every byte of execution logic stays in one place;
this module only moves `SandboxParams` in and `SandboxLog`s out.

The wire is the agent's stdin and stdout: one JSON object per line, each request
carrying an `id` its response echoes, so one agent serves many concurrent
requests (rbx runs testcases in parallel). The host reaches it through a single
`docker exec -i`, which is why there is no port, and why the container can run
with `--network none`.

This module must stay importable inside the container with nothing but rbx's
grading layer: it never imports `rbx.box`.

Usage (inside the container):

    python -m rbx.grading.judge.sandboxes.docker_agent serve
    python -m rbx.grading.judge.sandboxes.docker_agent keep --idle-timeout 900
"""

from __future__ import annotations

import argparse
import concurrent.futures
import itertools
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import IO, Any, Dict, List, Optional, Tuple

from rbx.grading.judge.program import ProgramError, ProgramNotFoundError
from rbx.grading.judge.sandbox import CommunicationParams, SandboxLog, SandboxParams

# Each live agent registers itself here by pid, so the keeper can tell whether
# the container is still in use. It lives on the container's private /tmp.
AGENTS_DIR = pathlib.Path('/tmp/rbx-agents')
KEEPER_POLL_SECONDS = 5.0
# How long the agent waits for the host's writes to become visible in here (see
# `await_files`), and how often it looks.
SYNC_TIMEOUT_SECONDS = 5.0
SYNC_POLL_SECONDS = 0.01


class AgentError(RuntimeError):
    """The agent could not be reached, or failed outside any program."""


# --------------------------------------------------------------------------
# Server side (inside the container)
# --------------------------------------------------------------------------


def _serialize_error(e: BaseException) -> Dict[str, Any]:
    if isinstance(e, ProgramNotFoundError):
        return {
            'kind': 'not_found',
            'executable': e.executable,
            'permission_denied': e.permission_denied,
        }
    if isinstance(e, ProgramError):
        return {'kind': 'program', 'message': str(e)}
    return {
        'kind': 'internal',
        'message': f'{type(e).__name__}: {e}',
        'traceback': traceback.format_exc(),
    }


def manifest(root: pathlib.Path) -> Dict[str, int]:
    """Size of every file in the box, following symlinks, as this side sees it."""
    sizes: Dict[str, int] = {}
    for path in root.rglob('*'):
        try:
            if path.is_file():
                sizes[str(path.relative_to(root))] = path.stat().st_size
        except OSError:
            continue
    return sizes


def await_files(root: pathlib.Path, expected: Dict[str, int]) -> None:
    """Wait until every file in `expected` has the size the host saw.

    The box is a bind mount, and Docker Desktop's file sharing caches file
    attributes in the guest for a short while: a file the host has just written
    -- an 89 MB precompiled header, a large test input -- can read as *empty* in
    here for ~100ms after the host closed it (measured while building this). A
    program started in that window sees a truncated input and fails or, worse,
    silently answers about the wrong data. So the agent waits for its view to
    agree with the host's before starting anything. On a Linux host, where both
    sides share one kernel, the first check always passes.
    """
    deadline = time.monotonic() + SYNC_TIMEOUT_SECONDS
    pending = dict(expected)
    while True:
        for name, size in list(pending.items()):
            try:
                if (root / name).stat().st_size == size:
                    del pending[name]
            except OSError:
                pass
        if not pending:
            return
        if time.monotonic() >= deadline:
            name, size = next(iter(pending.items()))
            raise AgentError(
                f'{root / name} did not reach its {size} bytes inside the '
                f'container within {SYNC_TIMEOUT_SECONDS:.0f}s; the host and the '
                'container disagree about its contents.'
            )
        time.sleep(SYNC_POLL_SECONDS)


def handle_request(request: Dict[str, Any]) -> Any:
    """Run one request and return its JSON-able result."""
    # Imported here so `keep` never pays for it.
    from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox

    op = request['op']
    if op == 'ping':
        return {'pid': os.getpid()}

    root = pathlib.Path(request['root'])
    await_files(root, request.get('expect') or {})
    sandbox = StupidSandbox(path=root)
    params = SandboxParams.model_validate(request['params'])
    if op == 'run':
        log = sandbox.run(request['command'], params)
        return log.model_dump(mode='json')
    if op == 'run_communication':
        solution_log, interactor_log = sandbox.run_communication(
            request['command'],
            params,
            request['interactor_command'],
            SandboxParams.model_validate(request['interactor_params']),
            CommunicationParams.model_validate(request['communication_params']),
        )
        return [
            solution_log.model_dump(mode='json'),
            interactor_log.model_dump(mode='json'),
        ]
    raise ValueError(f'unknown op {op!r}')


def serve(stdin: IO[str], stdout: IO[str]) -> None:
    """Answer requests from `stdin` until it closes, each on its own thread."""
    write_lock = threading.Lock()

    def answer(line: str) -> None:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get('id')
            response = {'id': request_id, 'ok': True, 'result': handle_request(request)}
        except BaseException as e:  # reported back, never swallowed
            response = {'id': request_id, 'ok': False, 'error': _serialize_error(e)}
        payload = json.dumps(response)
        with write_lock:
            stdout.write(payload + '\n')
            stdout.flush()

    threads: List[threading.Thread] = []
    for line in stdin:
        if not line.strip():
            continue
        thread = threading.Thread(target=answer, args=(line,), daemon=True)
        thread.start()
        threads.append(thread)
        threads = [t for t in threads if t.is_alive()]
    for thread in threads:
        thread.join()


def _register_agent() -> pathlib.Path:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    marker = AGENTS_DIR / str(os.getpid())
    marker.touch()
    return marker


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_agents() -> int:
    """Count registered agents still running, forgetting the dead ones."""
    if not AGENTS_DIR.is_dir():
        return 0
    alive = 0
    for marker in AGENTS_DIR.iterdir():
        try:
            pid = int(marker.name)
        except ValueError:
            continue
        if _pid_alive(pid):
            alive += 1
        else:
            marker.unlink(missing_ok=True)
    return alive


def keep(idle_timeout: float) -> None:
    """Keep the container alive while agents use it, then exit.

    This is the container's main process. Once no agent has been connected for
    `idle_timeout` seconds it returns, the container stops, and `--rm` removes it.
    """
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    last_busy = time.monotonic()
    while True:
        if live_agents() > 0:
            last_busy = time.monotonic()
        elif time.monotonic() - last_busy >= idle_timeout:
            return
        time.sleep(KEEPER_POLL_SECONDS)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(prog='rbx-docker-agent')
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('serve', help='Run programs requested over stdin.')
    keep_parser = sub.add_parser('keep', help='Keep the container alive while used.')
    keep_parser.add_argument('--idle-timeout', type=float, default=900.0)
    args = parser.parse_args(argv)

    if args.cmd == 'keep':
        keep(args.idle_timeout)
        return

    marker = _register_agent()
    try:
        serve(sys.stdin, sys.stdout)
    finally:
        marker.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Client side (on the host)
# --------------------------------------------------------------------------


def _deserialize_error(error: Dict[str, Any]) -> BaseException:
    kind = error.get('kind')
    if kind == 'not_found':
        return ProgramNotFoundError(
            error['executable'], permission_denied=error.get('permission_denied', False)
        )
    if kind == 'program':
        return ProgramError(error.get('message', ''))
    message = error.get('message', 'unknown error')
    if error.get('traceback'):
        message = f'{message}\n\nAgent traceback:\n{error["traceback"]}'
    return AgentError(f'The sandbox agent failed: {message}')


class AgentClient:
    """Talk to one agent process, from as many threads as like.

    The agent is started on the first request, with `command` -- in production a
    `docker exec -i <container> ... serve`, in tests the agent run directly on
    the host. Requests block their calling thread (sandboxes are driven through
    `asyncio.to_thread`), while one reader thread hands every response to the
    request waiting for it.
    """

    def __init__(self, command: List[str]):
        self.command = command
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._stderr: Optional[IO[bytes]] = None
        self._pending: Dict[int, concurrent.futures.Future] = {}
        self._ids = itertools.count()
        self._dead: Optional[str] = None

    def _start(self) -> subprocess.Popen:
        self._stderr = tempfile.TemporaryFile()
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read, args=(process,), daemon=True).start()
        return process

    def _stderr_tail(self) -> str:
        if self._stderr is None:
            return ''
        try:
            self._stderr.seek(0)
            return self._stderr.read().decode(errors='replace')[-2000:].strip()
        except (OSError, ValueError):
            return ''

    def _read(self, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self._lock:
                future = self._pending.pop(response.get('id'), None)
            if future is not None:
                future.set_result(response)
        process.wait()
        tail = self._stderr_tail()
        reason = f'The sandbox agent exited (code {process.returncode}).'
        if tail:
            reason = f'{reason}\n{tail}'
        with self._lock:
            self._dead = reason
            pending, self._pending = self._pending, {}
        for future in pending.values():
            future.set_exception(AgentError(reason))

    def request(self, payload: Dict[str, Any]) -> Any:
        with self._lock:
            if self._dead is not None:
                raise AgentError(self._dead)
            if self._process is None:
                self._process = self._start()
            request_id = next(self._ids)
            future: concurrent.futures.Future = concurrent.futures.Future()
            self._pending[request_id] = future
            assert self._process.stdin is not None
            try:
                self._process.stdin.write(
                    json.dumps({**payload, 'id': request_id}) + '\n'
                )
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                self._pending.pop(request_id, None)
                raise AgentError(f'Could not reach the sandbox agent: {e}') from e
        response = future.result()
        if response.get('ok'):
            return response['result']
        raise _deserialize_error(response.get('error') or {})

    def ping(self) -> None:
        self.request({'op': 'ping'})

    def run(
        self, root: pathlib.Path, command: List[str], params: SandboxParams
    ) -> SandboxLog:
        result = self.request(
            {
                'op': 'run',
                'root': str(root),
                'expect': manifest(root),
                'command': command,
                'params': params.model_dump(mode='json'),
            }
        )
        return SandboxLog.model_validate(result)

    def run_communication(
        self,
        root: pathlib.Path,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
        communication_params: CommunicationParams,
    ) -> Tuple[SandboxLog, SandboxLog]:
        solution, interactor = self.request(
            {
                'op': 'run_communication',
                'root': str(root),
                'expect': manifest(root),
                'command': command,
                'params': params.model_dump(mode='json'),
                'interactor_command': interactor_command,
                'interactor_params': interactor_params.model_dump(mode='json'),
                'communication_params': communication_params.model_dump(mode='json'),
            }
        )
        return SandboxLog.model_validate(solution), SandboxLog.model_validate(
            interactor
        )

    def close(self) -> None:
        with self._lock:
            process = self._process
        if process is None or process.stdin is None:
            return
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == '__main__':
    main()
