import asyncio
import concurrent.futures
import threading
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

K = TypeVar('K')
T = TypeVar('T')


class PendingResult(Exception):
    """Sentinel exception used by IdentifiedResult to indicate the task
    has been scheduled but has not completed yet."""


class IdentifiedResult(Generic[K, T]):
    """Result wrapper that always carries a key, even on failure.

    Use with AsyncExecutor.submit_with_identity() and asyncio.as_completed().
    Call .result() to get the value or re-raise the original exception.

    A *scheduled* IdentifiedResult (where ``pending`` is True) signals that
    the task has acquired a worker slot and started running, but has not
    finished yet.  Calling ``.result()`` on it raises ``PendingResult``.
    """

    __slots__ = ('key', '_value', '_exception')

    def __init__(
        self, key: K, value: T | None = None, exception: BaseException | None = None
    ):
        self.key = key
        self._value = value
        self._exception = exception

    def result(self) -> T:
        """Return the result, or raise the original exception.

        Raises ``PendingResult`` if the task is still running.
        """
        if self._exception is not None:
            raise self._exception
        return self._value  # type: ignore[return-value]

    @property
    def pending(self) -> bool:
        """True if this is a scheduled-but-not-completed result."""
        return isinstance(self._exception, PendingResult)

    @property
    def ok(self) -> bool:
        return self._exception is None

    @property
    def exception(self) -> BaseException | None:
        return self._exception


def _run_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


class AsyncExecutor:
    """An executor for async callables with bounded concurrency.

    Similar to ThreadPoolExecutor, but for awaitables. Submitted work
    starts immediately (up to max_workers), and returns asyncio.Future
    objects that support asyncio.as_completed() and similar patterns.

    If detach=True, all tasks run in a new event loop on a dedicated
    background thread. The returned futures are still usable from the
    caller's loop via asyncio.as_completed(), await, etc.
    """

    def __init__(self, max_workers: int, detach: bool = False):
        if max_workers < 1:
            raise ValueError('max_workers must be at least 1')
        self._detach = detach
        self._tasks: set[asyncio.Task] = set()

        if detach:
            self._loop = asyncio.new_event_loop()
            self._semaphore = asyncio.Semaphore(max_workers)
            self._thread = threading.Thread(
                target=_run_loop, args=(self._loop,), daemon=True
            )
            self._thread.start()
        else:
            self._loop = None
            self._semaphore = asyncio.Semaphore(max_workers)
            self._thread = None

    def submit(
        self, fn: Callable[..., Awaitable[T]], *args, **kwargs
    ) -> tuple[asyncio.Future[None], asyncio.Future[T]]:
        """Submit an async callable for execution.

        The callable is started immediately if a worker slot is available,
        otherwise it waits for a slot. Returns a tuple of two futures:
        - **scheduled**: resolves (with ``None``) as soon as the task
          acquires a worker slot and starts running.
        - **completed**: resolves with the callable's return value (or
          raises its exception) when the task finishes.

        Both futures support asyncio.as_completed(), asyncio.gather(), etc.
        """
        if self._detach:
            return self._submit_detached(fn, *args, **kwargs)
        return self._submit_local(fn, *args, **kwargs)

    def submit_with_identity(
        self, key: K, fn: Callable[..., Awaitable[T]], *args, **kwargs
    ) -> tuple[
        asyncio.Future[IdentifiedResult[K, T]],
        asyncio.Future[IdentifiedResult[K, T]],
    ]:
        """Submit an async callable, tagging the result with a key.

        Returns a tuple of two futures that both resolve to
        ``IdentifiedResult`` (never raise):

        - **scheduled**: resolves with a *pending* ``IdentifiedResult``
          (``r.pending == True``) as soon as the task acquires a worker
          slot.  The key is available but ``.result()`` raises
          ``PendingResult``.
        - **completed**: resolves with the final ``IdentifiedResult``.
          The key is always accessible, even when the callable failed.

        Because both futures share the same type you can mix them freely
        in a single list and distinguish them via ``r.pending``.

        Usage::

            futures = []
            for name, gen in generators.items():
                scheduled, completed = executor.submit_with_identity(
                    name, compile, gen,
                )
                futures.extend([scheduled, completed])
            for coro in asyncio.as_completed(futures):
                r = await coro          # never raises
                if r.pending:
                    print(f'{r.key} started')
                    continue
                digest = r.result()     # raises if the callable failed
        """

        async def _tagged() -> IdentifiedResult[K, T]:
            try:
                return IdentifiedResult(key, value=await fn(*args, **kwargs))
            except BaseException as exc:
                return IdentifiedResult(key, exception=exc)

        scheduled_none, completed = self.submit(_tagged)

        # Wrap the raw scheduled future so it resolves with a pending
        # IdentifiedResult instead of None.
        loop = scheduled_none.get_loop()
        scheduled: asyncio.Future[IdentifiedResult[K, T]] = loop.create_future()

        def _propagate_scheduled(f: asyncio.Future[None]):
            if f.cancelled():
                scheduled.cancel()
            elif (exc := f.exception()) is not None:
                _safe_set_exception(scheduled, exc)
            else:
                _safe_set_result(
                    scheduled, IdentifiedResult(key, exception=PendingResult())
                )

        scheduled_none.add_done_callback(_propagate_scheduled)

        return scheduled, completed

    def _submit_local(
        self, fn: Callable[..., Awaitable[T]], *args, **kwargs
    ) -> tuple[asyncio.Future[None], asyncio.Future[T]]:
        loop = asyncio.get_running_loop()
        scheduled: asyncio.Future[None] = loop.create_future()
        future: asyncio.Future[T] = loop.create_future()

        async def _run():
            try:
                async with self._semaphore:
                    if future.cancelled():
                        return
                    _safe_set_result(scheduled, None)
                    result = await fn(*args, **kwargs)
                    _safe_set_result(future, result)
                    # Yield to the event loop so that done callbacks (e.g.
                    # from as_completed) fire before the next task starts.
                    # Without this, fast/cached coroutines that never truly
                    # suspend will monopolize the loop and batch all results.
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                if not future.done():
                    future.cancel()
            except BaseException as exc:
                _safe_set_exception(future, exc)
            finally:
                self._tasks.discard(task)

        task = asyncio.ensure_future(_run())
        self._tasks.add(task)

        def _on_task_done(_: asyncio.Task):
            # Safety net: if the task was cancelled before _run could execute
            # (e.g. during shutdown), _run never resolves the future. Catch
            # that here so the future doesn't stay pending forever.
            if not future.done():
                future.cancel()
            if not scheduled.done():
                scheduled.cancel()

        task.add_done_callback(_on_task_done)

        def _cancel_task(f: asyncio.Future):
            if f.cancelled():
                task.cancel()

        future.add_done_callback(_cancel_task)

        return scheduled, future

    def _submit_detached(
        self, fn: Callable[..., Awaitable[T]], *args, **kwargs
    ) -> tuple[asyncio.Future[None], asyncio.Future[T]]:
        assert self._loop is not None
        caller_loop = asyncio.get_running_loop()
        scheduled: asyncio.Future[None] = caller_loop.create_future()
        caller_future: asyncio.Future[T] = caller_loop.create_future()

        async def _run():
            try:
                async with self._semaphore:
                    if caller_future.cancelled():
                        return
                    caller_loop.call_soon_threadsafe(_safe_set_result, scheduled, None)
                    result = await fn(*args, **kwargs)
                    # Resolve immediately — no extra callback scheduling.
                    caller_loop.call_soon_threadsafe(
                        _safe_set_result, caller_future, result
                    )
            except asyncio.CancelledError:
                caller_loop.call_soon_threadsafe(caller_future.cancel)
                caller_loop.call_soon_threadsafe(scheduled.cancel)
            except BaseException as exc:
                caller_loop.call_soon_threadsafe(
                    _safe_set_exception, caller_future, exc
                )

        # Schedule on the detached loop from the caller thread.
        inner_future = asyncio.run_coroutine_threadsafe(_run(), self._loop)

        def _cancel_inner(f: asyncio.Future):
            if f.cancelled():
                inner_future.cancel()

        caller_future.add_done_callback(_cancel_inner)

        return scheduled, caller_future

    async def shutdown(self, wait: bool = True, cancel: bool = False):
        """Shut down the executor.

        If cancel is True, cancel all pending tasks.
        If wait is True, wait for all tasks to complete.
        """
        if self._detach:
            await self._shutdown_detached(wait=wait, cancel=cancel)
        else:
            await self._shutdown_local(wait=wait, cancel=cancel)

    async def _shutdown_local(self, wait: bool = True, cancel: bool = False):
        # Snapshot before cancelling — _run's finally block discards from
        # self._tasks as tasks complete, so the set may shrink during iteration.
        tasks = list(self._tasks)
        if cancel:
            for task in tasks:
                task.cancel()
        if wait and tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Yield control so that callbacks (e.g. future.cancel()) scheduled
        # by completed tasks have a chance to fire.
        await asyncio.sleep(0)

    async def _shutdown_detached(self, wait: bool = True, cancel: bool = False):
        assert self._loop is not None
        assert self._thread is not None

        if cancel:
            # Cancel all tasks on the detached loop.
            async def _cancel_all():
                for task in asyncio.all_tasks(self._loop):
                    task.cancel()

            future = asyncio.run_coroutine_threadsafe(_cancel_all(), self._loop)
            try:
                future.result()
            except concurrent.futures.CancelledError:
                pass

        if wait:
            # Wait for all tasks on the detached loop to finish.
            async def _wait_all():
                tasks = [
                    t
                    for t in asyncio.all_tasks(self._loop)
                    if t is not asyncio.current_task()
                ]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            future = asyncio.run_coroutine_threadsafe(_wait_all(), self._loop)
            # Await in a thread-safe manner without blocking the caller loop.
            caller_loop = asyncio.get_running_loop()
            await asyncio.wrap_future(future, loop=caller_loop)

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()


def _safe_set_result(future: asyncio.Future, result):
    if not future.done():
        future.set_result(result)


def _safe_set_exception(future: asyncio.Future, exc: BaseException):
    if not future.done():
        future.set_exception(exc)
