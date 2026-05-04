# Async FileLock migration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `filelock.FileLock` with `filelock.AsyncFileLock` in the four lock-owning sites so locked critical sections cannot deadlock the asyncio event loop if a future change introduces an `await` under the lock. Closes #394.

**Architecture:** Locked methods on `FileCacheStorage`, `FileCacher`, `DependencyCache`, and `get_preprocessed_file_lock` become `async def` and use `async with self.lock` against an `AsyncFileLock`. The cascade adds `await` to every caller; callers that are already `async def` (the majority) are unchanged in shape. Where a sync caller cannot reasonably be made async, we add a `_sync` sibling on the callee that uses a sync `FileLock` against the same lockfile path (the OS file-lock interoperates between sync and async usages, so cross-task and cross-process exclusion are preserved).

**Tech Stack:** Python 3, `filelock` (≥3.14, already pinned), `asyncio`, `pytest-asyncio` (already used).

**Reference:** Design doc at `docs/plans/2026-05-03-async-filelock-design.md`.

---

## Cascade order

storage → cacher → caching → package. Each task migrates its target class plus all of its callers in the same commit, so the tree always builds and the test suite always runs.

---

### Task 1: Concurrency regression test

**Goal:** Lock in the new invariant — two asyncio tasks contending for a `FileCacher` lock can interleave `await`s without deadlocking. This test must FAIL on `main` (it deadlocks because `FileLock.acquire()` blocks the loop thread) and PASS after the migration.

**Files:**
- Create: `tests/rbx/grading/judge/test_cacher_concurrency.py`

**Step 1: Write the failing test**

```python
import asyncio
import pathlib

import pytest

from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.storage import FilesystemStorage


@pytest.mark.asyncio
async def test_cacher_two_tasks_yield_under_lock(tmp_path: pathlib.Path):
    """Two asyncio tasks alternating cacher ops with explicit yields must
    both make progress under AsyncFileLock — they would deadlock under a
    plain FileLock if either yielded while holding the lock."""
    storage = FilesystemStorage(tmp_path / 'storage')
    cacher = FileCacher(storage)

    async def worker(name: bytes, n: int) -> list[str]:
        digests: list[str] = []
        for i in range(n):
            digest = await cacher.put_file_content(
                name + str(i).encode(), f'desc-{name!r}-{i}'
            )
            digests.append(digest)
            # Yield to give the other task a chance to run.
            await asyncio.sleep(0)
            assert await cacher.exists(digest)
        return digests

    a, b = await asyncio.wait_for(
        asyncio.gather(worker(b'a', 5), worker(b'b', 5)),
        timeout=5.0,
    )
    assert len(a) == 5 and len(b) == 5
```

**Step 2: Confirm it fails today**

Run: `uv run pytest tests/rbx/grading/judge/test_cacher_concurrency.py -v`
Expected: FAIL — `put_file_content` is sync (no `await`), `AttributeError`/`TypeError`. This is fine: it documents the contract we're moving toward.

**Step 3: Commit**

```bash
git add tests/rbx/grading/judge/test_cacher_concurrency.py
git commit -m "test(grading): add concurrency regression for async cacher locks"
```

---

### Task 2: Migrate `FileCacheStorage` to `AsyncFileLock`

**Files:**
- Modify: `rbx/grading/judge/storage.py`
- Modify: `rbx/grading/judge/storage.py` ABCs (`Storage`, `NullStorage`) — match the new async signatures.

**Step 1: Replace the lock construction**

`storage.py:11`:
```python
from filelock import AsyncFileLock, BaseAsyncFileLock
```

`storage.py:243`:
```python
    lock: BaseAsyncFileLock
```

`storage.py:251`:
```python
        self.lock = AsyncFileLock(path / 'storage.lock', thread_local=False)
```

**Step 2: Convert lock-holding methods to `async def`**

In `FileCacheStorage`, each method that contains `with self.lock:` becomes `async def` and uses `async with self.lock:`. The methods are: `get_file`, `create_file`, `commit_file`, `set_metadata`, `get_metadata`, `list_metadata`, `exists`, `get_size`, `delete`, `list`, `path_for_symlink`, `filename_from_symlink`.

`_set_metadata` and `_get_metadata_path` are private helpers that don't take the lock; leave sync.

Note: `commit_file` uses `pending.fd.close()` and shutil-style ops inside the lock. Those are blocking but *don't yield*, so converting just changes the lock idiom; the body stays the same.

**Step 3: Update the abstract `Storage` and `NullStorage` to match**

Make all corresponding methods `async def` in the ABC and `NullStorage`. `NullStorage` returns immediately (no I/O).

**Step 4: No callers to fix yet — `FileCacheStorage` is only consumed by `FileCacher`, which Task 3 covers**

But the test suite likely imports `FilesystemStorage` directly. After Task 2, those will fail until Task 3 + Task 6 update them. We accept that and don't commit until tasks 2+3 land together — see Step 6 below.

**Step 5: Defer commit**

Tasks 2 and 3 ship in one commit because `FileCacher` calls into `FileCacheStorage` everywhere; splitting them would leave `FileCacher` uncompilable.

---

### Task 3: Migrate `FileCacher` to `AsyncFileLock`

**Files:**
- Modify: `rbx/grading/judge/cacher.py`
- Modify: every caller of `FileCacher` methods (search below).
- Modify: `tests/rbx/grading/judge/test_cacher.py` and any direct tests.

**Step 1: Replace the lock**

`cacher.py:12`, `cacher.py:55`, `cacher.py:92` — analogous to Task 2 (`AsyncFileLock`, `BaseAsyncFileLock`).

**Step 2: Convert lock-holding methods to `async def`**

Methods with `with self.lock:` (per grep): `_load`, `exists`, `path_for_symlink`, `transient_path_for_symlink`, `get_file`, `get_file_content`, `get_file_to_fobj`, `get_file_to_path`, `put_file_from_fobj`, `put_file_content`, `put_file_from_path`, `delete`, `purge_cache`, `list`, `destroy_cache` (verify exact list — there are 14 sites).

Each `with self.lock:` → `async with self.lock:`. Each `storage.X(...)` call becomes `await self.storage.X(...)`. Each in-method call to a sibling that's now async becomes `await`.

**Step 3: Identify sync callers**

Run:
```bash
grep -rn "cacher\.\|FileCacher" --include="*.py" rbx tests | grep -v "^rbx/grading/judge/" > /tmp/cacher-callers.txt
```

For each callsite, determine the enclosing function. If it's `async def`, prepend `await`. If it's plain `def`:
- Check if the function can be made `async def` cheaply (its callers are async or few). Prefer this.
- Only if that's truly disruptive, add a `_sync` sibling on `FileCacher` (and on `FileCacheStorage`, see below) that constructs a parallel `FileLock(...)` against the same `cache.lock` / `storage.lock` path and uses sync I/O.

Known sync sites to handle:
- `rbx/box/code.py:102` — `is_executable_sanitized`. Convert to `async def`; its callers (search `is_executable_sanitized`) are likely already async or trivially convertible.
- `rbx/box/sanitizers/warning_stack.py` — uses `cacher.get_file_to_path`. Check enclosing async-ness; convert callers as needed.
- Any test fixtures in `tests/rbx/conftest.py` etc.

**Step 4: Sync siblings (only if Step 3 forces them)**

If a sync sibling is unavoidable, add it as a separate method:

```python
def exists_sync(self, digest: str, cache_only: bool = False) -> bool:
    with FileLock(self.file_dir / 'cache.lock', thread_local=False):
        ...  # body identical to async version, no awaits
```

Keep the async version as the canonical one; document `_sync` as "for use from sync entry points only."

**Step 5: Run the regression test**

Run: `uv run pytest tests/rbx/grading/judge/test_cacher_concurrency.py -v`
Expected: PASS.

**Step 6: Run cacher unit tests**

Run: `uv run pytest tests/rbx/grading/judge/ -v`
Expected: all pass after fixing test files (they likely call cacher methods directly — add `await` and `@pytest.mark.asyncio` where needed).

**Step 7: Commit (tasks 2 + 3 together)**

```bash
git add rbx/grading/judge/storage.py rbx/grading/judge/cacher.py \
        rbx/box/code.py rbx/box/sanitizers/warning_stack.py \
        tests/rbx/grading/judge/
# Plus any other caller files modified.
git commit -m "refactor(grading): make FileCacher and FileCacheStorage locks async (#394)"
```

---

### Task 4: Migrate `DependencyCache` to `AsyncFileLock`

**Files:**
- Modify: `rbx/grading/caching.py`
- Modify: callers — primarily `rbx/grading/steps_with_caching.py`, `rbx/box/code.py`.

**Step 1: Replace the lock**

`caching.py:10`, `caching.py:366`, `caching.py:374` — `AsyncFileLock`, `BaseAsyncFileLock`.

**Step 2: Convert lock-holding methods**

Two sites at `caching.py:414` and `caching.py:489`. Identify which methods they live in (likely `get_compilation` / `put_compilation` or similar) and make those `async def` with `async with self.lock:`. Internal calls to `FileCacher` (now async) become `await`s.

**Step 3: Update callers**

Grep:
```bash
grep -rn "dependency_cache\.\|DependencyCache\b" --include="*.py" rbx tests | grep -v "^rbx/grading/caching.py:"
```

Top hits:
- `rbx/grading/steps_with_caching.py` — already async per its function signatures.
- `rbx/box/code.py` — most callers are inside `async def`.
Add `await`s.

**Step 4: Run targeted tests**

Run: `uv run pytest tests/rbx/grading/ -v`
Expected: pass.

**Step 5: Commit**

```bash
git add rbx/grading/caching.py rbx/grading/steps_with_caching.py rbx/box/code.py tests/
git commit -m "refactor(grading): make DependencyCache lock async (#394)"
```

---

### Task 5: Migrate `get_preprocessed_file_lock`

**Files:**
- Modify: `rbx/box/package.py`
- Modify: callers of `get_preprocessed_file_lock` and `mark_problem_as_preprocessed` (or whichever function uses it at line 216).

**Step 1: Replace**

`package.py:16`:
```python
from filelock import AsyncFileLock, BaseAsyncFileLock
```

`package.py:209-216`:
```python
def get_preprocessed_file_lock(root: pathlib.Path = pathlib.Path()) -> BaseAsyncFileLock:
    return AsyncFileLock(get_problem_cache_dir(root) / '.preprocessed' / '.lock')
```

The function at line 216 that does `with get_preprocessed_file_lock(root):` becomes `async def` with `async with`.

**Step 2: Update callers**

```bash
grep -rn "mark_problem_as_preprocessed\|get_preprocessed_file_lock" --include="*.py" rbx tests
```

Add `await` or convert to `async def` as needed. If a sync caller exists and conversion is awkward, add `mark_problem_as_preprocessed_sync` that uses a sync `FileLock` against the same path.

**Step 3: Run tests**

Run: `uv run pytest --ignore=tests/rbx/box/cli -x -q`
Expected: pass.

**Step 4: Commit**

```bash
git add rbx/box/package.py [callers]
git commit -m "refactor(box): make preprocessed-file lock async (#394)"
```

---

### Task 6: Full sweep — fix any remaining callers

**Step 1: Run the whole suite**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto
```

Triage failures: most will be missing `await`s or test functions that need `@pytest.mark.asyncio`.

**Step 2: Run CLI tests too (slower, but catches the long tail)**

```bash
uv run pytest tests/rbx/box/cli -n auto
```

**Step 3: Lint**

```bash
uv run ruff check . && uv run ruff format --check .
```

Fix any issues.

**Step 4: Commit fixes (if any)**

```bash
git commit -m "fix(grading): trailing async cacher caller fixes (#394)"
```

---

### Task 7: Final verification

**Step 1:** Re-run the regression test under load:
```bash
uv run pytest tests/rbx/grading/judge/test_cacher_concurrency.py -v --count=20
```
(or run it 20 times via `pytest-repeat` if installed; otherwise loop in shell). Must be deterministic.

**Step 2:** `git log` review — confirm commits are coherent and the diff matches the design doc.

**Step 3:** Open PR referencing #394.

---

## DRY / YAGNI / TDD reminders

- **DRY:** the sync `_sync` siblings are mechanical duplication. Only add them when a real sync caller exists; do not add them speculatively.
- **YAGNI:** don't redesign cacher / storage interfaces. Don't add timeouts / retries / new metrics. Just swap the lock and propagate `await`.
- **TDD:** Task 1's regression test is the single TDD anchor. Beyond that, existing unit tests provide coverage; add new tests only if a class of behaviour becomes uncovered.

## Risks & escape hatches

- If the cascade balloons unexpectedly (e.g. forces a Pydantic model validator into asyncland), pause and add a `_sync` sibling instead — that's exactly the safety valve.
- If `AsyncFileLock` interop with `FileLock` on the same lockfile turns out to be flaky on a target platform, document and fall back to async-only with `asyncio.run` shims for the sync entry points (worse ergonomics, same correctness).
