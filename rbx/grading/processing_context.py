import contextlib
import os
import signal
import subprocess
from typing import List, Optional

from rbx.grading.judge.sandbox import SandboxBase


@contextlib.contextmanager
def new_process_group():
    p = subprocess.Popen(['/bin/bash', '-c', 'exec sleep infinity'])
    try:
        yield p.pid
    finally:
        p.terminate()
        p.wait()


def should_use_group(sandboxes: List[SandboxBase]) -> bool:
    if not sandboxes:
        return False
    uses_pgid = all(sandbox.use_pgid() for sandbox in sandboxes)
    all_pgids = set(
        sandbox.params.pgid for sandbox in sandboxes if sandbox.params.pgid is not None
    )
    return uses_pgid and len(all_pgids) == 1


async def _fetch_pids(sandboxes: List[SandboxBase]) -> List[int]:
    return [await sandbox.get_pid() for sandbox in sandboxes]


def _find_sandbox_idx(pids: List[int], pid: int) -> Optional[int]:
    try:
        return pids.index(pid)
    except ValueError:
        return None


async def _wait_for_group(sandboxes: List[SandboxBase]) -> List[int]:
    pgid = [
        sandbox.params.pgid for sandbox in sandboxes if sandbox.params.pgid is not None
    ][0]
    assert pgid is not None

    sandbox_pids = await _fetch_pids(sandboxes)

    finished = []
    while len(finished) < len(sandboxes):
        try:
            pid, status = os.waitpid(-pgid, 0)
        except ChildProcessError:
            break

        if os.waitstatus_to_exitcode(status) != 0:
            os.kill(pgid, signal.SIGKILL)

        sandbox_idx = _find_sandbox_idx(sandbox_pids, pid)
        if sandbox_idx is not None:
            finished.append(sandbox_idx)
            continue

    return finished


async def wait_all(sandboxes: List[SandboxBase]):
    if not should_use_group(sandboxes):
        raise RuntimeError('Sandboxes are not using a process group')

    await _wait_for_group(sandboxes)
