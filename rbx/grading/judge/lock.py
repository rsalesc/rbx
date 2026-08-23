import contextlib
import os
import pathlib
import threading
import time
from typing import Callable, Iterator, Optional

from filelock import AsyncFileLock, BaseAsyncFileLock

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms.
    fcntl = None  # type: ignore[assignment]


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


class CacheBusyError(RuntimeError):
    """Raised when an exclusive lock could not be taken in time.

    In practice this means other rbx processes are still using the cache the
    caller wanted to wipe.
    """


class SharedFileLock:
    """A cross-process reader/writer lock over a single file.

    Every rbx process takes the lock of the cache directories it uses in
    *shared* mode, and holds it for as long as it runs. The only operation that
    takes it *exclusively* is wiping such a directory, so a wipe can never run
    while another process is reading from or writing to it -- which used to
    leave the running process with sqlite and storage handles pointing at
    deleted inodes (issue #700).

    The lock file lives inside the directory it guards, so wiping has to
    preserve it; see ``rbx.box.global_package.wipe_cache_dir``. Keeping it there
    is what makes the lock discoverable from the directory alone, with no
    side-channel state.

    On platforms without ``fcntl`` the lock degrades to a no-op, exactly like
    the rest of the sandboxing layer.
    """

    path: pathlib.Path

    def __init__(self, path: 'os.PathLike[str]'):
        self.path = pathlib.Path(path)
        self._fd: Optional[int] = None
        self._shared = False
        self._guard = threading.RLock()

    def _open(self) -> int:
        if self._fd is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o666)
        return self._fd

    def acquire_shared(self) -> None:
        """Take the lock in shared mode, blocking until every writer is gone."""
        if fcntl is None:
            return
        with self._guard:
            if self._shared:
                return
            fcntl.flock(self._open(), fcntl.LOCK_SH)
            self._shared = True

    def release(self) -> None:
        with self._guard:
            if self._fd is None:
                return
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None
                self._shared = False

    def __del__(self):
        try:
            self.release()
        except Exception:  # pragma: no cover - interpreter shutdown.
            pass

    @contextlib.contextmanager
    def exclusive(
        self,
        timeout: Optional[float] = None,
        on_wait: Optional[Callable[[], None]] = None,
    ) -> Iterator[None]:
        """Hold the lock exclusively for the duration of the block.

        A descriptor that already holds the lock in shared mode is upgraded in
        place and downgraded back on exit, so the caller can keep using the
        cache afterwards. ``on_wait`` is called once if other processes force us
        to wait; ``CacheBusyError`` is raised if they still hold it after
        ``timeout`` seconds (``None`` waits forever).
        """
        if fcntl is None:
            yield
            return

        with self._guard:
            fd = self._open()
            was_shared = self._shared
            deadline = None if timeout is None else time.monotonic() + timeout
            notified = False
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    # Upgrading can drop the shared lock, so from here on we
                    # hold nothing until the exclusive lock is granted.
                    self._shared = False
                    if not notified and on_wait is not None:
                        on_wait()
                        notified = True
                    if deadline is not None and time.monotonic() >= deadline:
                        if was_shared:
                            fcntl.flock(fd, fcntl.LOCK_SH)
                            self._shared = True
                        raise CacheBusyError(
                            f'Could not exclusively lock {self.path} in {timeout}s.'
                        ) from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                if was_shared:
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    self._shared = True
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
