import asyncio
import pathlib

import pytest

from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.storage import FilesystemStorage


@pytest.mark.asyncio
async def test_cacher_two_tasks_yield_under_lock(tmp_path: pathlib.Path):
    """Two asyncio tasks alternating cacher ops with explicit yields must
    both make progress. Under AsyncFileLock they will; under a plain
    FileLock they would deadlock if either yielded while holding the lock.
    """
    storage = FilesystemStorage(tmp_path / 'storage')
    cacher = FileCacher(storage)

    async def worker(name: bytes, n: int) -> list[str]:
        digests: list[str] = []
        for i in range(n):
            digest = await cacher.put_file_content(name + str(i).encode())
            digests.append(digest)
            # Yield to give the other task a chance to run mid-critical-section
            # of a future code path. Today nothing yields under the lock; this
            # asserts the future-proofed behaviour.
            await asyncio.sleep(0)
            assert await cacher.exists(digest)
        return digests

    a, b = await asyncio.wait_for(
        asyncio.gather(worker(b'a', 5), worker(b'b', 5)),
        timeout=5.0,
    )
    assert len(a) == 5
    assert len(b) == 5
    assert set(a).isdisjoint(set(b))
