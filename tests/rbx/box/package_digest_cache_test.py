import asyncio
import threading
import time
from unittest import mock

from rbx.box import package
from rbx.box.testing import testing_package
from rbx.grading.judge.cacher import FileCacher


def _store_content(content: bytes) -> str:
    async def _put() -> str:
        cacher = package.get_file_cacher()
        return await cacher.put_file_content(content)

    return asyncio.run(_put())


def test_get_digest_as_string_caches_results(
    testing_pkg: testing_package.TestingPackage,
):
    digest = _store_content(b'cached payload')

    async def _scenario() -> None:
        assert await package.get_digest_as_string(digest) == 'cached payload'
        # Cached: a second call returns the memoized value.
        assert await package.get_digest_as_string(digest) == 'cached payload'
        assert await package.get_digest_as_string(None) is None

    asyncio.run(_scenario())


def test_get_digest_as_string_cache_clearable():
    assert hasattr(package.get_digest_as_string, 'cache_clear')
    package.get_digest_as_string.cache_clear()


def test_get_digest_as_string_safe_across_concurrent_event_loops(
    testing_pkg: testing_package.TestingPackage,
):
    """Regression test for #462.

    `rbx run` runs the checker (which calls `get_digest_as_string`) on the
    detached `AsyncExecutor` background loop, while the main loop is still
    alive. A loop-bound cache (``alru_cache``) shares an in-flight
    ``asyncio.Task`` across both loops and crashes. The cache must be
    loop-agnostic.
    """
    digest = _store_content(b'payload')
    package.get_digest_as_string.cache_clear()

    release = threading.Event()
    original_get_file_content = FileCacher.get_file_content

    async def slow_get_file_content(self, d):
        # Stay in-flight (off the event loop) until released, so the cache
        # entry is a not-yet-done task while a second loop reaches it.
        await asyncio.get_running_loop().run_in_executor(None, release.wait)
        return await original_get_file_content(self, d)

    # Background event loop, mirroring AsyncExecutor(detach=True).
    background_loop = asyncio.new_event_loop()

    def _run_background() -> None:
        asyncio.set_event_loop(background_loop)
        background_loop.run_forever()

    bg_thread = threading.Thread(target=_run_background, daemon=True)
    bg_thread.start()

    # Make sure both loops finish even if the (buggy) cross-loop path stalls.
    timer = threading.Timer(1.0, release.set)
    timer.start()

    try:
        with mock.patch.object(FileCacher, 'get_file_content', slow_get_file_content):
            # In-flight call on the background loop populates the cache entry.
            bg_future = asyncio.run_coroutine_threadsafe(
                package.get_digest_as_string(digest), background_loop
            )
            time.sleep(0.2)

            # Cache hit from a different, concurrently-alive loop.
            main_result = asyncio.run(package.get_digest_as_string(digest))

            assert main_result == 'payload'
            assert bg_future.result(timeout=5) == 'payload'
    finally:
        timer.cancel()
        release.set()
        background_loop.call_soon_threadsafe(background_loop.stop)
        bg_thread.join(timeout=5)
        background_loop.close()
