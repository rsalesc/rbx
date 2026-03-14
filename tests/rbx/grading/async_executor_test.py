import asyncio

import pytest

from rbx.grading.async_executor import AsyncExecutor, IdentifiedResult, PendingResult


@pytest.fixture(params=[False, True], ids=['local', 'detached'])
def detach(request):
    return request.param


class TestAsyncExecutor:
    @pytest.mark.asyncio
    async def test_basic_submit_and_await(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def add(a, b):
            return a + b

        _, future = executor.submit(add, 1, 2)
        result = await future
        assert result == 3
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_submit_multiple(self, detach):
        executor = AsyncExecutor(max_workers=4, detach=detach)

        async def double(x):
            return x * 2

        futures = [executor.submit(double, i) for i in range(10)]
        results = [await f for _, f in futures]
        assert results == [i * 2 for i in range(10)]
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_as_completed(self, detach):
        executor = AsyncExecutor(max_workers=4, detach=detach)

        async def work(x):
            await asyncio.sleep(0.01 * x)
            return x

        pairs = [executor.submit(work, i) for i in range(5)]
        completed_futures = [f for _, f in pairs]
        results = []
        for fut in asyncio.as_completed(completed_futures):
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

        pairs = [executor.submit(tracked_work, 0.05) for _ in range(6)]
        for fut in asyncio.as_completed([f for _, f in pairs]):
            await fut
        assert max_running <= 2
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_exception_propagation(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def fail():
            raise ValueError('test error')

        _, future = executor.submit(fail)
        with pytest.raises(ValueError, match='test error'):
            await future
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_kwargs(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def greet(name, greeting='hello'):
            return f'{greeting} {name}'

        _, future = executor.submit(greet, 'world', greeting='hi')
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
        _, fut2 = executor.submit(blocking)
        fut2.cancel()
        assert fut2.cancelled()

        await executor.shutdown(cancel=True)

    @pytest.mark.asyncio
    async def test_shutdown_cancel(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def long_work():
            await asyncio.sleep(10)
            return 'done'

        pairs = [executor.submit(long_work) for _ in range(4)]
        await executor.shutdown(wait=True, cancel=True)

        # All completed futures should be done (cancelled or exception).
        for _, f in pairs:
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

        pairs = [
            executor.submit_with_identity(name, compile, name, dur)
            for name, dur in items.items()
        ]

        results = {}
        for coro in asyncio.as_completed([f for _, f in pairs]):
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

        _, future = executor.submit_with_identity('task_a', fail, 'boom')
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

        pairs = [
            executor.submit_with_identity('good', work, False),
            executor.submit_with_identity('bad', work, True),
        ]

        results = {}
        errors = {}
        for coro in asyncio.as_completed([f for _, f in pairs]):
            r = await coro
            if r.ok:
                results[r.key] = r.result()
            else:
                errors[r.key] = r.exception

        assert results == {'good': 'ok'}
        assert 'bad' in errors
        assert isinstance(errors['bad'], RuntimeError)
        await executor.shutdown()


class TestScheduledFuture:
    """Tests for the scheduled (first) future returned by submit."""

    @pytest.fixture(params=[False, True], ids=['local', 'detached'])
    def detach(self, request):
        return request.param

    @pytest.mark.asyncio
    async def test_scheduled_resolves_before_completed(self, detach):
        executor = AsyncExecutor(max_workers=1, detach=detach)

        async def slow():
            await asyncio.sleep(0.1)
            return 42

        scheduled, completed = executor.submit(slow)
        # Scheduled should resolve quickly (task starts immediately).
        await asyncio.wait_for(scheduled, timeout=1.0)
        assert scheduled.done()
        assert not completed.done()
        # Now wait for completion.
        result = await completed
        assert result == 42
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_scheduled_resolves_with_none(self, detach):
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def noop():
            return 'done'

        scheduled, completed = executor.submit(noop)
        await completed
        assert (await scheduled) is None
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_scheduled_waits_for_semaphore(self, detach):
        """Scheduled future should not resolve until a worker slot opens."""
        executor = AsyncExecutor(max_workers=1, detach=detach)
        gate = asyncio.Event() if not detach else None

        async def blocker():
            if gate:
                gate.set()
            await asyncio.sleep(0.2)
            return 'block'

        # Occupy the only worker slot.
        sched1, _ = executor.submit(blocker)
        if gate:
            await gate.wait()
        else:
            await asyncio.sleep(0.05)
        await sched1  # first task is scheduled

        # Second task should be queued.
        sched2, completed2 = executor.submit(blocker)
        # Give a moment — sched2 should NOT be done yet.
        await asyncio.sleep(0.05)
        assert not sched2.done()

        # Wait for everything.
        await completed2
        assert sched2.done()
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_scheduled_cancelled_on_shutdown(self, detach):
        """If a task never gets scheduled before shutdown, its scheduled
        future should be cancelled."""
        executor = AsyncExecutor(max_workers=1, detach=detach)
        gate = asyncio.Event() if not detach else None

        async def blocker():
            if gate:
                gate.set()
            await asyncio.sleep(10)

        # Occupy the slot.
        executor.submit(blocker)
        if gate:
            await gate.wait()
        else:
            await asyncio.sleep(0.05)

        # Queue a task that will never start.
        sched, _ = executor.submit(blocker)
        await executor.shutdown(cancel=True)
        assert sched.done()

    @pytest.mark.asyncio
    async def test_identity_scheduled_is_pending(self, detach):
        """submit_with_identity scheduled future resolves with a pending
        IdentifiedResult carrying the key."""
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def work():
            await asyncio.sleep(0.05)
            return 'result'

        scheduled, completed = executor.submit_with_identity('my_key', work)
        r_completed = await completed
        r_scheduled = await scheduled

        # The scheduled result is pending.
        assert r_scheduled.pending
        assert r_scheduled.key == 'my_key'
        assert not r_scheduled.ok
        assert isinstance(r_scheduled.exception, PendingResult)
        with pytest.raises(PendingResult):
            r_scheduled.result()

        # The completed result is not pending.
        assert not r_completed.pending
        assert r_completed.ok
        assert r_completed.key == 'my_key'
        assert r_completed.result() == 'result'
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_identity_flat_list_mixed(self, detach):
        """Both scheduled and completed futures can live in the same list
        and be distinguished via .pending."""
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def work(x):
            await asyncio.sleep(0.02)
            return x * 10

        keys = ['a', 'b']
        futures = []
        for k in keys:
            scheduled, completed = executor.submit_with_identity(k, work, k)
            futures.extend([scheduled, completed])

        pending_keys = []
        completed_results = {}
        for coro in asyncio.as_completed(futures):
            r = await coro
            if r.pending:
                pending_keys.append(r.key)
            else:
                completed_results[r.key] = r.result()

        assert sorted(pending_keys) == sorted(keys)
        assert completed_results == {'a': 'a' * 10, 'b': 'b' * 10}
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_identity_scheduled_before_completed(self, detach):
        """The scheduled future resolves before the completed one."""
        executor = AsyncExecutor(max_workers=1, detach=detach)

        async def slow():
            await asyncio.sleep(0.1)
            return 42

        scheduled, completed = executor.submit_with_identity('k', slow)
        await asyncio.wait_for(scheduled, timeout=1.0)
        assert scheduled.done()
        assert not completed.done()

        r = await scheduled
        assert r.pending
        assert r.key == 'k'

        r2 = await completed
        assert not r2.pending
        assert r2.result() == 42
        await executor.shutdown()

    @pytest.mark.asyncio
    async def test_as_completed_on_scheduled(self, detach):
        """Can use asyncio.as_completed on scheduled futures to react
        when tasks start running."""
        executor = AsyncExecutor(max_workers=2, detach=detach)

        async def work(x):
            await asyncio.sleep(0.05)
            return x

        pairs = [executor.submit(work, i) for i in range(4)]
        scheduled_futures = [s for s, _ in pairs]

        started = []
        for fut in asyncio.as_completed(scheduled_futures):
            await fut
            started.append(True)
        assert len(started) == 4

        # Clean up.
        for _, c in pairs:
            await c
        await executor.shutdown()


class TestIdentifiedResult:
    def test_pending_result(self):
        r = IdentifiedResult('key', exception=PendingResult())
        assert r.pending
        assert not r.ok
        assert r.key == 'key'
        with pytest.raises(PendingResult):
            r.result()

    def test_ok_result_not_pending(self):
        r = IdentifiedResult('key', value=42)
        assert not r.pending
        assert r.ok
        assert r.result() == 42

    def test_error_result_not_pending(self):
        r = IdentifiedResult('key', exception=ValueError('boom'))
        assert not r.pending
        assert not r.ok
        with pytest.raises(ValueError, match='boom'):
            r.result()


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
        _, future = executor.submit(get_thread_id)
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

        pairs = [executor.submit(get_thread_id) for _ in range(8)]
        thread_ids = set()
        for fut in asyncio.as_completed([f for _, f in pairs]):
            thread_ids.add(await fut)
        # All should run on the same detached thread.
        assert len(thread_ids) == 1
        await executor.shutdown()
