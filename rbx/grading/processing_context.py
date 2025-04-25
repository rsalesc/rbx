import asyncio
import contextlib
import os
import signal
import threading
from typing import Optional, Set

_processing_context_pids: Optional[Set[int]] = None
_terminate_all_on_error = False
_lock = threading.Lock()

# Creating a processing context is not thread-safe, but adding to it is.


@contextlib.contextmanager
def new_processing_context(terminate_all_on_error: bool = False):
    global _processing_context_pids, _terminate_all_on_error
    with _lock:
        old_processing_context_pids = _processing_context_pids
        _old_terminate_all_on_error = _terminate_all_on_error
        _processing_context_pids = set()
        _terminate_all_on_error = terminate_all_on_error
    try:
        yield
    finally:
        with _lock:
            _processing_context_pids = old_processing_context_pids
            _terminate_all_on_error = _old_terminate_all_on_error


def get_processing_context() -> Set[int]:
    with _lock:
        return _processing_context_pids or set()


def add_to_processing_context(pid: int):
    global _processing_context_pids
    with _lock:
        if _processing_context_pids is None:
            return
        _processing_context_pids.add(pid)


def terminate_all_processes_in_context(clear: bool = True):
    global _processing_context_pids
    with _lock:
        if _processing_context_pids is None:
            return
        for pid in _processing_context_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        if clear:
            _processing_context_pids.clear()


async def wait_all_processes_in_context(wait_for: int):
    global _processing_context_pids, _terminate_all_on_error
    wait_pids = set()
    while len(get_processing_context()) < wait_for:
        await asyncio.sleep(0.01)

    with _lock:
        if _processing_context_pids is None:
            return
        wait_pids.update(_processing_context_pids)

    wait_lock = threading.Lock()
    finished_pids = []

    def process(pid: int, returncode: int):
        with wait_lock:
            finished_pids.append(pid)
        if returncode != 0 and _terminate_all_on_error:
            terminate_all_processes_in_context()

    def wait_all_processes():
        while len(finished_pids) < len(wait_pids):
            try:
                pid, status = os.wait()
            except ChildProcessError:
                return
            if pid in wait_pids:
                process(pid, os.waitstatus_to_exitcode(status))

    await asyncio.to_thread(wait_all_processes)
