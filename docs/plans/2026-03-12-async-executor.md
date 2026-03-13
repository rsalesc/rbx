# AsyncExecutor and Async Compilation Pipeline

## Summary

Built `rbx/grading/async_executor.py` — an async equivalent of `ThreadPoolExecutor` that:
- Accepts awaitable callables via `submit()`, respects `max_workers` concurrency via semaphore
- Returns `asyncio.Future` objects compatible with `asyncio.as_completed()`
- Supports `detach=True` to run all tasks on a dedicated background thread/event loop
- Provides `submit_with_identity(key, fn, ...)` returning `IdentifiedResult` — a wrapper that always carries the key even on failure, solving the problem that `asyncio.as_completed()` yields new wrapper coroutines (not original futures), making dict-based lookups impossible

## Key Design Decisions

### `IdentifiedResult`
`asyncio.as_completed()` yields internal coroutine wrappers, not original futures. You cannot map results back to submission keys via a dict. `submit_with_identity` solves this by wrapping results in `IdentifiedResult(key, value, exception)` that never raises on `await`. Access via `r.key`, `r.ok`, `r.result()`, `r.exception`.

### `sleep(0)` after `set_result` in local mode
Without this, fast/cached coroutines that never truly suspend monopolize the event loop. All tasks complete in one event loop turn, and `as_completed` done callbacks (scheduled via `call_soon`) only fire after all tasks finish. The `sleep(0)` yields control so callbacks fire between task completions.

### Cancellation handling
Internal tasks use a `_on_task_done` callback to propagate cancellation to caller futures. This handles the case where a cancelled task never runs its coroutine body (e.g. cancelled before starting). The `_cancel_task` callback on the caller future propagates cancellation in the reverse direction.

## Critical Discovery: Blocking Compilation Pipeline

`compile_item()` was marked `async` but its entire call chain is synchronous and blocking:

```
compile_item (async, but never awaits)
  -> steps_with_caching.compile (sync)
    -> steps.compile (sync)
      -> sandbox.run (sync)
        -> Program.wait (sync)
          -> os.wait4() — blocks the thread
```

### Impact
- **Local mode (`detach=False`)**: Blocks the event loop. All tasks run sequentially. `as_completed` notifications batch.
- **Detached mode (`detach=True`)**: All tasks run on one detached thread. `os.wait4()` blocks it, so tasks still execute sequentially. All `call_soon_threadsafe` notifications pile up and arrive at the caller loop in one batch.

### Fix
The blocking compilation must be offloaded via `asyncio.to_thread()` (or `loop.run_in_executor()`) so the event loop (local or detached) stays responsive. This enables true parallelism (thread pool handles blocking subprocesses) and proper streaming (event loop processes `as_completed` callbacks between completions). This fix was applied separately.

## Files

- `rbx/grading/async_executor.py` — executor implementation
- `tests/rbx/grading/async_executor_test.py` — 30 tests covering both local and detached modes
- `rbx/box/generators.py:compile_generators` — primary consumer using `submit_with_identity` + `as_completed`
