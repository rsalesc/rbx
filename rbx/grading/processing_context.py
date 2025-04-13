import contextlib
import os
import signal
import threading
from typing import Optional, Set

_processing_context_pids: Optional[Set[int]] = None
_lock = threading.Lock()

# Creating a processing context is not thread-safe, but adding to it is.


@contextlib.contextmanager
def new_processing_context():
    global _processing_context_pids
    with _lock:
        old_processing_context_pids = _processing_context_pids
        _processing_context_pids = set()
    try:
        yield
    finally:
        with _lock:
            _processing_context_pids = old_processing_context_pids


def get_processing_context() -> Set[int]:
    with _lock:
        return _processing_context_pids or set()


def add_to_processing_context(pid: int):
    global _processing_context_pids
    with _lock:
        if _processing_context_pids is None:
            return
        _processing_context_pids.add(pid)


def terminate_all_processes_in_context():
    with _lock:
        if _processing_context_pids is None:
            return
        for pid in _processing_context_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        _processing_context_pids.clear()
