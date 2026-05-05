import os

from filelock import AsyncFileLock, BaseAsyncFileLock


def make_async_file_lock(path: 'os.PathLike[str]') -> BaseAsyncFileLock:
    """Construct an ``AsyncFileLock`` with the parameters this codebase relies on.

    ``thread_local=False`` keeps the lock state shared across coroutines, and
    ``run_in_executor=False`` runs the underlying ``fcntl.flock`` call directly
    on the event loop. Both are required: with the executor variant, mutations
    to the internal counter and ``lock_file_fd`` happen on the loop while the
    syscall runs in a thread, which races between concurrent acquire/release
    pairs and surfaces as ``fcntl.flock(None, ...)`` raising ``TypeError``.
    """
    return AsyncFileLock(path, thread_local=False, run_in_executor=False)
