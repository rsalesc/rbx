# Async FileLock migration

Issue: rsalesc/rbx#394.

## Problem

`FileCacher`, `FileCacheStorage`, `DependencyCache`, and `box.package.get_preprocessed_file_lock` all use synchronous `filelock.FileLock` to guard their critical sections. Callers run as multiple asyncio tasks on a single event loop. Today no locked operation yields, so the bug is latent — but a future change that introduces an `await` inside a lock would deadlock the loop: a yielding task would let another task take over, and that other task would then block on the same `FileLock` while still on the loop thread.

The fix is to switch the locks to `filelock.AsyncFileLock`, which suspends via `asyncio.sleep` instead of blocking the thread.

## Approach

Approach **B** from brainstorming: async-primary API with thin sync wrappers where legitimately needed.

- Locked methods on the three lock-owning classes become `async def` and use `async with self.lock` against an `AsyncFileLock`.
- Callers that already live inside `async def` (the vast majority) gain `await`.
- For the small set of methods that have legitimate sync callers, keep a sibling sync method that uses a sync `FileLock` on the same lockfile path (filelock interoperates fine — both async and sync variants coordinate via the OS file lock, so cross-process and cross-context exclusion still hold).
- We do NOT add `asyncio.run` / `syncer` shims at random call sites; we only keep sync versions where a sync caller actually exists.

This keeps the cascade narrow: only methods that hold a lock get colored async, and only their async callers gain `await`.

## Scope

In scope:
- `rbx/grading/judge/storage.py`: `FileCacheStorage` (12 lock sites).
- `rbx/grading/judge/cacher.py`: `FileCacher` (14 lock sites).
- `rbx/grading/caching.py`: `DependencyCache` (2 lock sites).
- `rbx/box/package.py`: `get_preprocessed_file_lock` (1 site, used by `mark_problem_as_preprocessed`).
- All callers of the above whose paths reach a locked method, transitively. Most are already `async def`; a handful (`is_executable_sanitized`, `warning_stack` consumers, validators) need either conversion or sync wrappers.

Out of scope:
- Reorganizing the cacher / storage interfaces beyond what async forces.
- Replacing the `FileLock` used in test fixtures or unrelated tools.
- Behavioural changes (timeouts, retries, granularity).

## API decisions

For each class, the policy is:

1. **Lock-holding method becomes `async def`** by default.
2. **Sync sibling is added only when an existing sync caller cannot reasonably be made async.** Naming convention: append `_sync` (e.g. `FileCacher.exists_sync`).
3. The sync sibling reuses a `FileLock` constructed against the same path; the async sibling uses `AsyncFileLock` against the same path. Both are stored as instance attributes (`self.lock` async, `self.sync_lock` sync) only when a sync sibling actually exists.

Concretely we expect sync siblings on, at most:
- `FileCacher.exists` (called from sync `is_executable_sanitized`, possibly Pydantic-side helpers).
- `FileCacher.path_for_symlink` / `transient_path_for_symlink` if any sync site uses them.
- `get_preprocessed_file_lock` keeps a sync entry for current sync callers; we add an async variant.

We will only add a sync sibling after confirming a real sync caller — not preemptively.

## Cascade plan

The cascade is mechanical:

1. Convert leaf methods (those that only use `with self.lock`) to async first.
2. For each caller, pick: (a) it's already `async def` → add `await`; (b) it can become `async def` cheaply → make it async; (c) it's a sync entry point → add a sync sibling on the callee.
3. Repeat outward until callers no longer call a converted method.

Order: storage.py → cacher.py → caching.py → package.py, since cacher depends on storage and caching depends on cacher.

## Testing

- Unit tests for cacher / storage / caching that exercise the async path. Reuse existing fixtures where possible.
- Add a regression test asserting that two concurrent asyncio tasks that both acquire a `FileCacher` lock do not deadlock — i.e. each task includes an `await asyncio.sleep(0)` between its operations, simulating future code paths that yield. Without `AsyncFileLock` this would deadlock today (well — it wouldn't, because nothing yields under the lock; the test exists to lock in the new invariant).
- Run `uv run pytest --ignore=tests/rbx/box/cli` to catch regressions.

## Risks

- **Hidden sync callers** in test fixtures or rarely-exercised CLI paths. Mitigation: run the test suite end-to-end, including CLI tests once the bulk of changes land.
- **Pydantic validators** that touch the cacher synchronously. Mitigation: handle case-by-case with sync siblings.
- **Lock semantics drift**: `AsyncFileLock` and `FileLock` are interoperable for the same file path, but `thread_local=False` on the sync lock matters. We preserve this on sync siblings.
