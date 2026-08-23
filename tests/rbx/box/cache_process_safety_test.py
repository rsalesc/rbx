"""Regression tests for issue #700: the cache must be process-safe.

Two rbx processes sharing a cache directory used to crash with
`sqlite3.OperationalError: attempt to write a readonly database` (or a
`FileNotFoundError` from the storage layer), because clearing the cache
`rmtree`d the whole directory out from under whoever was still using it.

The three defects these tests pin down:

1. Clearing removed the directory itself, so live sqlite/storage handles
   pointed at deleted inodes.
2. The lock files live inside that directory, so after a clear two processes
   would lock two different inodes and both enter the critical section.
3. Nothing serialized a clear against a concurrent run, and the validity check
   was not re-done under the lock, so two processes starting at once both
   wiped the cache.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import textwrap

import pytest
from filelock import FileLock, Timeout

from rbx.box import global_package
from rbx.grading.judge.lock import CacheBusyError, SharedFileLock


def _populate(cache_dir: pathlib.Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / '.cache_db').write_text('db')
    (cache_dir / 'fingerprint').write_text(global_package.get_cache_fingerprint())
    (cache_dir / '.storage').mkdir(exist_ok=True)
    (cache_dir / '.storage' / 'digest').write_text('file')
    (cache_dir / 'cache.lock').touch()
    (cache_dir / '.storage.lock').touch()


def test_wipe_keeps_the_directory_and_its_lock_files(tmp_path: pathlib.Path):
    cache_dir = tmp_path / '.rbx'
    _populate(cache_dir)
    lock_inode = (cache_dir / 'cache.lock').stat().st_ino

    global_package.wipe_cache_dir(cache_dir)

    assert cache_dir.is_dir()
    assert (cache_dir / 'cache.lock').stat().st_ino == lock_inode
    assert (cache_dir / '.storage.lock').is_file()
    assert not (cache_dir / '.cache_db').exists()
    assert not (cache_dir / '.storage').exists()


def test_lock_still_excludes_after_a_clear(tmp_path: pathlib.Path):
    """The cache lock lives inside the cleared directory, so a clear that
    deleted it would silently break mutual exclusion between a process that
    already holds the lock and one that takes it afterwards."""
    cache_dir = tmp_path / '.rbx'
    _populate(cache_dir)
    lock_path = cache_dir / 'cache.lock'

    holder = FileLock(lock_path)
    holder.acquire()
    try:
        global_package.clear_cache_dir(cache_dir)

        with pytest.raises(Timeout):
            FileLock(lock_path).acquire(timeout=0.2)
    finally:
        holder.release()


def test_clear_restamps_the_fingerprint(tmp_path: pathlib.Path):
    """A cleared cache that is left without a fingerprint looks invalid to the
    next process, which would clear it all over again."""
    cache_dir = tmp_path / '.rbx'
    _populate(cache_dir)

    global_package.clear_cache_dir(cache_dir)

    assert (cache_dir / 'fingerprint').read_text() == (
        global_package.get_cache_fingerprint()
    )
    assert global_package.is_cache_valid(cache_dir)


def test_stale_cache_is_cleared_exactly_once(tmp_path: pathlib.Path):
    cache_dir = tmp_path / '.rbx'
    _populate(cache_dir)
    (cache_dir / 'fingerprint').write_text('stale')

    assert global_package.ensure_cache_dir_is_valid(cache_dir)
    # The fingerprint is restamped inside the same critical section, so a
    # process that was racing us for the clear finds nothing left to do.
    assert not global_package.ensure_cache_dir_is_valid(cache_dir)


def test_clear_refuses_to_wipe_a_cache_another_process_is_using(
    tmp_path: pathlib.Path,
):
    cache_dir = tmp_path / '.rbx'
    _populate(cache_dir)

    script = textwrap.dedent(f"""
        import sys, time
        from rbx.grading.judge.lock import SharedFileLock

        lock = SharedFileLock({str(cache_dir / 'session.lock')!r})
        lock.acquire_shared()
        print('held', flush=True)
        time.sleep(5)
    """)
    worker = subprocess.Popen(
        [sys.executable, '-c', script], stdout=subprocess.PIPE, text=True
    )
    try:
        assert worker.stdout is not None
        assert worker.stdout.readline().strip() == 'held'

        with pytest.raises(CacheBusyError):
            global_package.clear_cache_dir(cache_dir, timeout=0.5)

        # Nothing was destroyed: the other process can keep working.
        assert (cache_dir / '.cache_db').is_file()
        assert (cache_dir / '.storage' / 'digest').is_file()
    finally:
        worker.kill()
        worker.wait()


def test_shared_lock_allows_concurrent_readers(tmp_path: pathlib.Path):
    lock_path = tmp_path / 'session.lock'
    first = SharedFileLock(lock_path)
    second = SharedFileLock(lock_path)
    first.acquire_shared()
    second.acquire_shared()
    try:
        with pytest.raises(CacheBusyError):
            with SharedFileLock(lock_path).exclusive(timeout=0.2):
                pass
    finally:
        first.release()
        second.release()

    # Once every reader is gone the exclusive lock goes through.
    with SharedFileLock(lock_path).exclusive(timeout=0.5):
        pass


_WORKER = """
import asyncio, pathlib, sys

from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.storage import FilesystemStorage
from rbx.grading.steps import GradingArtifacts, GradingFileInput

cache_dir = pathlib.Path(sys.argv[1])
work = pathlib.Path(sys.argv[2])
work.mkdir(parents=True, exist_ok=True)

cacher = FileCacher(FilesystemStorage(cache_dir / '.storage'))
dep = DependencyCache(cache_dir, cacher)


async def main():
    for i in range(30):
        src = work / f'input{i % 3}.txt'
        src.write_text(str(i % 3))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(src=src, dest=pathlib.Path('input.txt'))
        )
        # Every worker uses the same handful of keys, so they contend on the
        # very same rows of the shared cache DB.
        async with dep([f'command {i % 3}'], [artifacts]):
            pass
    print('OK')


asyncio.run(main())
"""


def test_two_processes_can_share_a_cache_directory(tmp_path: pathlib.Path):
    cache_dir = tmp_path / '.rbx'
    cache_dir.mkdir()

    workers = [
        subprocess.Popen(
            [sys.executable, '-c', _WORKER, str(cache_dir), str(tmp_path / f'w{i}')],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for i in range(2)
    ]
    outputs = [worker.communicate()[0] for worker in workers]

    for worker, output in zip(workers, outputs):
        assert worker.returncode == 0, output
        assert 'OK' in output


def test_same_cache_dir_maps_to_one_lock(tmp_path: pathlib.Path, monkeypatch):
    """A process that reached the same cache through two different spellings
    would hold two descriptors on it, and block against itself when upgrading
    one of them to exclusive."""
    cache_dir = tmp_path / '.rbx'
    cache_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    absolute = global_package.get_cache_session_lock(cache_dir)
    relative = global_package.get_cache_session_lock(pathlib.Path('.rbx'))

    assert absolute is relative
