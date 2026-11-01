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

    python -m rbx.grading.judge.sandboxes.docker_agent serve --slots 1
    python -m rbx.grading.judge.sandboxes.docker_agent keep --idle-timeout 900
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import fcntl
import itertools
import json
import os
import pathlib
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import IO, Any, Dict, Iterator, List, Optional, Tuple

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
# Execution slots shared by every agent in the container (see `execution_slot`).
SLOTS_DIR = pathlib.Path('/tmp/rbx-slots')
# Waiters sleep until whoever frees a slot wakes them (see `execution_slot`);
# this is only how often they look anyway, in case a holder died holding one.
SLOT_RECHECK_SECONDS = 0.5
# Once the host hangs up, how often the agent sweeps for programs it still runs,
# and for how long at most before it exits regardless.
HANGUP_POLL_SECONDS = 0.1
HANGUP_GRACE_SECONDS = 10.0
# Which rbx process gets a slot first when several are waiting: lower first.
# `rbx each` / `rbx on` set it to the problem's position in the run, so one
# problem's local work runs back to back instead of interleaving with every
# other problem's (see `execution_slot`).
PRIORITY_ENV_VAR = 'RBX_DOCKER_PRIORITY'
# What a request without a priority waits as: after every explicit one, so a
# standalone `rbx run` beside an `rbx each` never jumps ahead of it, and runs
# whenever that queue has nobody waiting (among themselves, unset requests are
# served first come, first served).
UNSET_PRIORITY = 999_999_999


class AgentError(RuntimeError):
    """The agent could not be reached, or failed outside any program."""


class HostGone(AgentError):
    """The host hung up, so a request still queued or starting is dropped."""


class Hangup:
    """Raised once the host hangs up; wakes every waiter of this agent at once.

    A waiter sleeps on its ticket (see `execution_slot`) and on `fileno()`,
    which turns readable for good -- end-of-file -- when this is set.
    """

    def __init__(self) -> None:
        self._read, self._write = os.pipe()
        self._event = threading.Event()
        self._lock = threading.Lock()

    def fileno(self) -> int:
        return self._read

    def is_set(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            os.close(self._write)

    def check(self) -> None:
        if self.is_set():
            raise HostGone('The host went away; the request was dropped.')


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


def normalize_priority(value: Any) -> int:
    """A request's priority as the queue orders it; anything unusable is unset."""
    if value is None or isinstance(value, bool):
        return UNSET_PRIORITY
    try:
        priority = int(value)
    except (TypeError, ValueError):
        return UNSET_PRIORITY
    return min(max(priority, 0), UNSET_PRIORITY)


def priority_from_env(environ: Optional[Dict[str, str]] = None) -> Optional[int]:
    """This process's `RBX_DOCKER_PRIORITY`, or None when unset or not a number."""
    raw = (os.environ if environ is None else environ).get(PRIORITY_ENV_VAR, '')
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _ticket_listening(path: pathlib.Path, wake: bool = False) -> bool:
    """Whether the waiter behind a ticket is still there; poke it if `wake`.

    A ticket is a named FIFO its waiter holds open for reading, so opening it
    for writing without blocking fails (`ENXIO`) exactly when that waiter is
    gone -- killed while queued, say, without running its cleanup. No pid
    lookup, and no false positive from a recycled pid.
    """
    try:
        if not stat.S_ISFIFO(path.lstat().st_mode):
            return False
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        if wake:
            os.write(fd, b'.')
    except OSError:
        # A full pipe already holds a wake-up the waiter has yet to read.
        pass
    finally:
        os.close(fd)
    return True


def _front_ticket(waiting_dir: pathlib.Path, wake: bool = False) -> Optional[str]:
    """The ticket to be served next, or None when nobody is waiting.

    Dead tickets ahead of it are removed on the way, so a waiter that died
    while queued never holds up the queue. With `wake`, its waiter is told to
    look again. Callers hold the queue lock.
    """
    for name in sorted(os.listdir(waiting_dir)):
        path = waiting_dir / name
        if _ticket_listening(path, wake=wake):
            return name
        path.unlink(missing_ok=True)
    return None


@contextlib.contextmanager
def _queue_lock(slots_dir: pathlib.Path) -> Iterator[None]:
    """Exclude every other agent, and thread, from the queue for a moment."""
    fd = os.open(slots_dir / 'queue.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _try_lock_a_slot(paths: List[pathlib.Path]) -> Optional[int]:
    for path in paths:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        return fd
    return None


def _a_slot_is_free(paths: List[pathlib.Path]) -> bool:
    # Only meaningful under the queue lock, where nobody else takes a slot.
    fd = _try_lock_a_slot(paths)
    if fd is None:
        return False
    os.close(fd)
    return True


def _enqueue(ticket: pathlib.Path) -> int:
    ticket.unlink(missing_ok=True)
    os.mkfifo(ticket, 0o600)
    # Read *and* write: with a writer of its own the FIFO never reads as EOF,
    # so it is readable only once somebody pokes it.
    return os.open(ticket, os.O_RDWR | os.O_NONBLOCK)


def _drain(fd: int) -> None:
    try:
        while os.read(fd, 512):
            pass
    except BlockingIOError:
        pass


def _lstat_mode(path: pathlib.Path) -> int:
    try:
        return path.lstat().st_mode
    except OSError:
        return 0


@contextlib.contextmanager
def execution_slot(
    slots: int,
    slots_dir: Optional[pathlib.Path] = None,
    priority: Any = None,
    hangup: Optional[Hangup] = None,
) -> Iterator[None]:
    """Hold one of `slots` execution slots, shared by every agent in here.

    Docker Desktop's file sharing misbehaves when several programs read through
    it at once: under parallel load a read in the middle of a file can come back
    as end-of-file, and paging in an executable can fail with SIGBUS (measured:
    9 in 400 runs of a 6.9 MB input with 13 at a time, 0 in 400 with one). The
    files are intact; the reads are not. So by default programs run one at a
    time across the whole container, whichever rbx process asked -- each rbx
    process has its own agent, which is why this is a file lock and not a
    `threading.Semaphore`. `slots` > 1 is the setter's opt-in to parallelism.

    `flock` locks belong to the open file description, so each holder opens its
    own descriptor, and two threads of one agent exclude each other as well as
    two agents do. The kernel releases a slot whose holder died.

    A slot that frees goes to the lowest `priority` waiting, ties first come,
    first served. Leaving it to whoever grabs it first interleaves the problems
    of an `rbx each` -- a test of A, one of F, one of A again -- so they all
    finish their local work together near the end, and a remote stage that
    could have started on A sits idle until then. Each waiter makes a ticket in
    `waiting/` named so that names sort in serving order (priority, then the
    monotonic clock every process in the container shares, then pid and
    thread), and only the first ticket may take a slot.

    Waiting costs no CPU, which matters: waiters share the machine with the
    program being timed. The queue is guarded by a short-lived lock
    (`queue.lock`), every ticket is a named FIFO its waiter sleeps on, and
    whoever frees a slot pokes the first live ticket. A waiter also looks again
    every `SLOT_RECHECK_SECONDS` on its own, the backstop for a holder that
    died without handing its slot on. All of this lives on the container's
    private /tmp, never the shared mount, so it is cheap and reliable.

    Once `hangup` is set the host that asked is gone: a waiter leaves the queue
    at once with `HostGone`, and never takes a slot to run something nobody
    will read.
    """
    slots_dir = slots_dir or SLOTS_DIR
    waiting_dir = slots_dir / 'waiting'
    waiting_dir.mkdir(parents=True, exist_ok=True)
    paths = [slots_dir / f'slot-{i}' for i in range(max(1, slots))]
    ticket = waiting_dir / (
        f'{normalize_priority(priority):010d}-{time.monotonic_ns():020d}-'
        f'{os.getpid()}-{threading.get_ident()}'
    )
    fd: Optional[int] = None
    reader: Optional[int] = None
    selector = selectors.DefaultSelector()
    if hangup is not None:
        selector.register(hangup, selectors.EVENT_READ)
    try:
        if hangup is not None:
            hangup.check()
        with _queue_lock(slots_dir):
            front = _front_ticket(waiting_dir)
            if front is None or ticket.name < front:
                fd = _try_lock_a_slot(paths)
            if fd is None:
                reader = _enqueue(ticket)
                selector.register(reader, selectors.EVENT_READ)
        while fd is None:
            assert reader is not None
            selector.select(SLOT_RECHECK_SECONDS)
            if hangup is not None:
                hangup.check()
            _drain(reader)
            with _queue_lock(slots_dir):
                if not stat.S_ISFIFO(_lstat_mode(ticket)):
                    # Someone emptied the queue under us; without a ticket
                    # this waiter could never be woken.
                    selector.unregister(reader)
                    os.close(reader)
                    reader = None
                    reader = _enqueue(ticket)
                    selector.register(reader, selectors.EVENT_READ)
                if _front_ticket(waiting_dir) != ticket.name:
                    continue
                fd = _try_lock_a_slot(paths)
                if fd is None:
                    continue
                ticket.unlink(missing_ok=True)
                # With more than one slot, the next waiter may fit too.
                if _a_slot_is_free(paths):
                    _front_ticket(waiting_dir, wake=True)
    finally:
        selector.close()
        if reader is not None:
            os.close(reader)
        if fd is None:
            # Leaving without a slot (an exception): drop out of the queue,
            # and pass on a wake-up this waiter may have swallowed.
            with _queue_lock(slots_dir):
                ticket.unlink(missing_ok=True)
                if _a_slot_is_free(paths):
                    _front_ticket(waiting_dir, wake=True)
    try:
        if hangup is not None:
            # Hung up while this one was being handed the slot.
            hangup.check()
        yield
    finally:
        with _queue_lock(slots_dir):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            _front_ticket(waiting_dir, wake=True)


def handle_request(
    request: Dict[str, Any],
    slots: int = 1,
    slots_dir: Optional[pathlib.Path] = None,
    hangup: Optional[Hangup] = None,
) -> Any:
    """Run one request and return its JSON-able result."""
    op = request['op']
    if op == 'ping':
        return {'pid': os.getpid()}
    # The wait for a slot happens before the program starts, so it never counts
    # towards the time the program is measured to take.
    with execution_slot(slots, slots_dir, request.get('priority'), hangup):
        return _run_request(request, hangup)


def _run_request(request: Dict[str, Any], hangup: Optional[Hangup] = None) -> Any:
    # Imported here so `keep` never pays for it.
    from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox

    op = request['op']
    root = pathlib.Path(request['root'])
    await_files(root, request.get('expect') or {})
    if hangup is not None:
        hangup.check()
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


def _kill_programs() -> None:
    """Kill every program this agent started, with their process groups.

    Each program runs in a process group of its own (`setpgid` in
    `program.get_preexec_fn`), so whatever it spawned goes too.
    """
    import psutil

    own_group = os.getpgid(0)
    try:
        children = psutil.Process().children(recursive=True)
    except psutil.Error:
        return
    for child in children:
        try:
            group = os.getpgid(child.pid)
            if group != own_group:
                os.killpg(group, signal.SIGKILL)
            child.kill()
        except (OSError, psutil.Error):
            pass


def serve(
    stdin: IO[str],
    stdout: IO[str],
    slots: int = 1,
    slots_dir: Optional[pathlib.Path] = None,
) -> None:
    """Answer requests from `stdin` until it closes, each on its own thread.

    `stdin` closing means the host is gone -- it exited, or was killed and
    `docker exec` closed the agent's input -- so nobody will read what is still
    being worked on. Leaving it be would be worse than wasteful: a request still
    queued would go on to take the container-wide slot, and a program without a
    time limit (sanitized runs have none) would hold it for good, stalling every
    other rbx process. So queued requests drop out, running programs are
    killed, and the agent exits.
    """
    write_lock = threading.Lock()
    hangup = Hangup()

    def answer(line: str) -> None:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get('id')
            response = {
                'id': request_id,
                'ok': True,
                'result': handle_request(request, slots, slots_dir, hangup),
            }
        except BaseException as e:  # reported back, never swallowed
            response = {'id': request_id, 'ok': False, 'error': _serialize_error(e)}
        payload = json.dumps(response)
        with write_lock:
            try:
                stdout.write(payload + '\n')
                stdout.flush()
            except (OSError, ValueError):
                # The host is gone; there is nobody to answer.
                pass

    threads: List[threading.Thread] = []
    for line in stdin:
        if not line.strip():
            continue
        thread = threading.Thread(target=answer, args=(line,), daemon=True)
        thread.start()
        threads.append(thread)
        threads = [t for t in threads if t.is_alive()]
    hangup.set()
    deadline = time.monotonic() + HANGUP_GRACE_SECONDS
    while True:
        threads = [t for t in threads if t.is_alive()]
        if not threads:
            return
        # Again on every round: a request may have started its program after
        # the previous sweep.
        _kill_programs()
        if time.monotonic() >= deadline:
            return
        threads[0].join(HANGUP_POLL_SECONDS)


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
    serve_parser = sub.add_parser('serve', help='Run programs requested over stdin.')
    serve_parser.add_argument(
        '--slots', type=int, default=1, help='Programs that may run at once.'
    )
    serve_parser.add_argument('--slots-dir', type=pathlib.Path, default=None)
    keep_parser = sub.add_parser('keep', help='Keep the container alive while used.')
    keep_parser.add_argument('--idle-timeout', type=float, default=900.0)
    args = parser.parse_args(argv)

    if args.cmd == 'keep':
        keep(args.idle_timeout)
        return

    marker = _register_agent()
    try:
        serve(sys.stdin, sys.stdout, args.slots, args.slots_dir)
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

    def __init__(self, command: List[str], priority: Optional[int] = None):
        self.command = command
        # Sent with every program this client asks for; see `execution_slot`.
        self.priority = priority
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
                'priority': self.priority,
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
                'priority': self.priority,
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
