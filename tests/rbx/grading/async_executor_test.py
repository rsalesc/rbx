import asyncio

import pytest

from rbx.grading.async_executor import AsyncExecutor


@pytest.fixture(params=[False, True], ids=['local', 'detached'])
def detach(request):
    return request.param


class TestAsyncExecutor:
    @pytest.mark.asyncio
    async def test_basic_submit_and_await(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def add(a, b):
            return a + b

        future = executor.submit(add, 1, 2)
        result = await future
        assert result == 3
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_submit_multiple(self, detach):
        executor = AsyncExecutor(max_workers=4, detach=detach)

        async def double(x):
            return x * 2

        futures = [executor.submit(double, i) for i in range(10)]
        results = [await f for f in futures]
        assert results == [i * 2 for i in range(10)]
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_as_completed(self, detach):
        executor = AsyncExecutor(max_workers=4, detach=detach)

        async def work(x):
            await asyncio.sleep(0.01 * x)
            return x

        futures = [executor.submit(work, i) for i in range(5)]
        results = []
        for fut in asyncio.as_completed(futures):
            results.append(await fut)
        assert sorted(results) == list(range(5))
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_max_workers_respected(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)
        running = 0
        max_running = 0
        # For detached mode we need a thread-safe counter.
        import threading

        tlock = threading.Lock()

        async def tracked_work(duration):
            nonlocal running, max_running
            if detach:
                with tlock:
                    running += 1
                    max_running = max(max_running, running)
            else:
                running += 1
                max_running = max(max_running, running)
            await asyncio.sleep(duration)
            if detach:
                with tlock:
                    running -= 1
            else:
                running -= 1

        futures = [executor.submit(tracked_work, 0.05) for _ in range(6)]
        for fut in asyncio.as_completed(futures):
            await fut
        assert max_running <= 2
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_exception_propagation(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def fail():
            raise ValueError('test error')

        future = executor.submit(fail)
        with pytest.raises(ValueError, match='test error'):
            await future
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_kwargs(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def greet(name, greeting='hello'):
            return f'{greeting} {name}'

        future = executor.submit(greet, 'world', greeting='hi')
        assert await future == 'hi world'
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_cancel_future(self, detach):
        executor = AsyncExecutor(max_workers=1, detach=detach)
        started = asyncio.Event() if not detach else None

        async def blocking():
            if started:
                started.set()
            await asyncio.sleep(10)
            return 'done'

        # Occupy the single worker slot.
        executor.submit(blocking)
        if started:
            await started.wait()
        else:
            await asyncio.sleep(0.05)

        # This one should be queued waiting for the semaphore.
        fut2 = executor.submit(blocking)
        fut2.cancel()
        assert fut2.cancelled()

        await executor.shutdown(cancel=True)

    @pytest.mark.asyncio
    async def test_shutdown_cancel(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def long_work():
            await asyncio.sleep(10)
            return 'done'

        futures = [executor.submit(long_work) for _ in range(4)]
        await executor.shutdown(wait=True, cancel=True)

        # All futures should be done (cancelled or exception).
        for f in futures:
            assert f.done()

    @pytest.mark.asyncio
    async def test_empty_shutdown(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_work_starts_immediately(self, detach):
        executor = AsyncExecutor(max_workers=4, detach=detach)
        started = []

        async def record_start(idx):
            started.append(idx)
            await asyncio.sleep(0.1)
            return idx

        for i in range(4):
            executor.submit(record_start, i)
        # Give a moment for tasks to start.
        await asyncio.sleep(0.05)
        assert len(started) == 4
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_submit_with_identity(self, detach):
        """Test submit_with_identity for mapping results back to keys
        when using asyncio.as_completed."""
        executor = AsyncExecutor(max_workers=2, detach=detach)

        items = {'gen_a': 0.03, 'gen_b': 0.01, 'gen_c': 0.02}

        async def compile(name, duration):
            await asyncio.sleep(duration)
            return f'digest_{name}'

        futures = [
            executor.submit_with_identity(name, compile, name, dur)
            for name, dur in items.items()
        ]

        results = {}
        for coro in asyncio.as_completed(futures):
            r = await coro
            assert r.ok
            results[r.key] = r.result()

        assert results == {
            'gen_a': 'digest_gen_a',
            'gen_b': 'digest_gen_b',
            'gen_c': 'digest_gen_c',
        }
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_submit_with_identity_exception(self, detach):
        """The key is accessible even when the callable fails."""
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def fail(msg):
            raise ValueError(msg)

        future = executor.submit_with_identity('task_a', fail, 'boom')
        r = await future  # never raises
        assert r.key == 'task_a'
        assert not r.ok
        assert isinstance(r.exception, ValueError)
        with pytest.raises(ValueError, match='boom'):
            r.result()
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_submit_with_identity_mixed(self, detach):
        """Mix of successes and failures, all identifiable."""
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def work(should_fail):
            if should_fail:
                raise RuntimeError('failed')
            return 'ok'

        futures = [
            executor.submit_with_identity('good', work, False),
            executor.submit_with_identity('bad', work, True),
        ]

        results = {}
        errors = {}
        for coro in asyncio.as_completed(futures):
            r = await coro
            if r.ok:
                results[r.key] = r.result()
            else:
                errors[r.key] = r.exception

        assert results == {'good': 'ok'}
        assert 'bad' in errors
        assert isinstance(errors['bad'], RuntimeError)
        await executor.shutdown()


class TestAsyncExecutorInit:
    def test_invalid_max_workers(self):
        with pytest.raises(ValueError, match='max_workers must be at least 1'):
            AsyncExecutor(max_workers=0)

    def test_negative_max_workers(self):
        with pytest.raises(ValueError, match='max_workers must be at least 1'):
            AsyncExecutor(max_workers=-1)


class TestDetachedSpecific:
    @pytest.mark.asyncio
    async def test_runs_on_different_thread(self):
        executor = AsyncExecutor(max_workers=2, detach=True)

        async def get_thread_id():
            import threading

            return threading.current_thread().ident

        caller_id = __import__('threading').current_thread().ident
        future = executor.submit(get_thread_id)
        worker_id = await future
        assert worker_id != caller_id
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_all_detached_tasks_share_thread(self):
        executor = AsyncExecutor(max_workers=4, detach=True)

        async def get_thread_id():
            import threading

            await asyncio.sleep(0.01)
            return threading.current_thread().ident

        futures = [executor.submit(get_thread_id) for _ in range(8)]
        thread_ids = set()
        for fut in asyncio.as_completed(futures):
            thread_ids.add(await fut)
        # All should run on the same detached thread.
        assert len(thread_ids) == 1
        await executor.shutdown()
