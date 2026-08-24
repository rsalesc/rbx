import contextlib
import functools
import pathlib
import shutil
from typing import Callable, Iterator, Optional, Type

from rbx.config import CACHE_DIR_NAME, get_app_path
from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.lock import SharedFileLock
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox
from rbx.grading.judge.storage import FilesystemStorage, Storage

CACHE_STEP_VERSION = 6

# How long to wait for other rbx processes to let go of a cache before giving
# up on wiping it.
CLEAR_TIMEOUT = 10.0

# Name of the reader/writer lock every process takes over a cache directory it
# uses. It sits next to the per-operation locks (`cache.lock`, `.storage.lock`),
# all of which have to survive a wipe -- see `wipe_cache_dir`.
SESSION_LOCK_NAME = 'session.lock'


def get_cache_fingerprint() -> str:
    return f'{CACHE_STEP_VERSION}'


def is_cache_valid(cache_dir: pathlib.Path) -> bool:
    if not cache_dir.is_dir():
        return True
    fingerprint_file = cache_dir / 'fingerprint'
    if not fingerprint_file.is_file():
        return False
    fingerprint = fingerprint_file.read_text()
    if fingerprint.strip() != get_cache_fingerprint():
        return False
    return True


@functools.cache
def _get_cache_session_lock(resolved_cache_dir: pathlib.Path) -> SharedFileLock:
    return SharedFileLock(resolved_cache_dir / SESSION_LOCK_NAME)


def get_cache_session_lock(cache_dir: pathlib.Path) -> SharedFileLock:
    """The reader/writer lock guarding a whole cache directory.

    Keyed by the resolved path: the same directory reached through a relative
    and an absolute path has to map to the same lock object, otherwise a
    process ends up with two descriptors on it and blocks against itself when
    upgrading one of them.
    """
    return _get_cache_session_lock(cache_dir.resolve())


def hold_cache_dir(cache_dir: pathlib.Path) -> None:
    """Announce that this process is using `cache_dir` until it exits.

    The lock is taken in shared mode, so any number of rbx processes can use
    the same cache concurrently; it only keeps them from having the directory
    wiped from under them mid-run.
    """
    get_cache_session_lock(cache_dir).acquire_shared()


def wipe_cache_dir(cache_dir: pathlib.Path) -> None:
    """Delete the contents of a cache directory, keeping locks intact.

    Removing the directory itself (or the lock files in it) would leave every
    process that already opened them holding descriptors to deleted inodes:
    sqlite then fails to create its journal and reports `attempt to write a
    readonly database`, the storage layer loses its temporary files, and two
    processes locking two different inodes both enter the critical section.
    """
    if not cache_dir.is_dir():
        return
    for entry in cache_dir.iterdir():
        if entry.suffix == '.lock':
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(str(entry), ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def stamp_cache_dir(cache_dir: pathlib.Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / 'fingerprint').write_text(get_cache_fingerprint())


def clear_cache_dir(
    cache_dir: pathlib.Path,
    timeout: Optional[float] = CLEAR_TIMEOUT,
    on_wait: Optional[Callable[[], None]] = None,
) -> None:
    """Wipe a cache directory once no other process is using it.

    Raises `CacheBusyError` if other processes are still holding it after
    `timeout` seconds.
    """
    with get_cache_session_lock(cache_dir).exclusive(timeout=timeout, on_wait=on_wait):
        wipe_cache_dir(cache_dir)
        stamp_cache_dir(cache_dir)


def ensure_cache_dir_is_valid(
    cache_dir: pathlib.Path,
    timeout: Optional[float] = CLEAR_TIMEOUT,
    on_wait: Optional[Callable[[], None]] = None,
) -> bool:
    """Clear `cache_dir` if it was written by an incompatible rbx version.

    Returns whether it had to be cleared. The check is repeated under the
    exclusive lock, so when several processes start at once only the first one
    wipes the cache and the others go straight to work.
    """
    if is_cache_valid(cache_dir):
        return False
    with get_cache_session_lock(cache_dir).exclusive(timeout=timeout, on_wait=on_wait):
        if is_cache_valid(cache_dir):
            return False
        wipe_cache_dir(cache_dir)
        stamp_cache_dir(cache_dir)
    return True


def clear_cache_session_locks() -> None:
    """Drop the cached locks, closing their descriptors.

    A real rbx process uses a handful of cache directories and holds them until
    it exits, which is the whole point. A test session creates one cache per
    test, so it has to let go of the ones it is done with.
    """
    _get_cache_session_lock.cache_clear()


def get_global_cache_dir_path() -> pathlib.Path:
    return get_app_path() / CACHE_DIR_NAME


@functools.cache
def get_global_cache_dir() -> pathlib.Path:
    cache_dir = get_global_cache_dir_path()
    cache_dir.mkdir(parents=True, exist_ok=True)
    fingerprint_file = cache_dir / 'fingerprint'
    if not fingerprint_file.is_file():
        fingerprint_file.write_text(get_cache_fingerprint())
    # From here on this process is a user of the cache, and nobody gets to wipe
    # it until we exit.
    hold_cache_dir(cache_dir)
    return cache_dir


def is_global_cache_valid() -> bool:
    return is_cache_valid(get_global_cache_dir())


@functools.cache
def get_global_storage_dir() -> pathlib.Path:
    storage_dir = get_global_cache_dir() / '.storage'
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


@functools.cache
def get_global_cache_storage() -> Storage:
    return FilesystemStorage(get_global_storage_dir())


@functools.cache
def get_global_file_cacher() -> FileCacher:
    return FileCacher(get_global_cache_storage())


@functools.cache
def get_global_dependency_cache() -> DependencyCache:
    return DependencyCache(get_global_cache_dir(), get_global_file_cacher())


@functools.cache
def get_global_sandbox_type() -> Type[SandboxBase]:
    return StupidSandbox


@contextlib.contextmanager
def get_new_global_sandbox() -> Iterator[SandboxBase]:
    sandbox = get_global_sandbox_type()(
        file_cacher=get_global_file_cacher(),
    )
    yield sandbox
    sandbox.cleanup(delete=True)


def clear_global_cache(
    timeout: Optional[float] = CLEAR_TIMEOUT,
    on_wait: Optional[Callable[[], None]] = None,
):
    clear_cache_dir(get_global_cache_dir(), timeout=timeout, on_wait=on_wait)
