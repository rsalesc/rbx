# TaskQueue Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract a pure `TaskQueue` class that owns command scheduling, replacing ad-hoc parallel/sequential logic in `rbxCommandApp`.

**Architecture:** A standalone `TaskQueue` class manages an ordered queue of `Task` objects, tracks terminal idle state, and fires a callback when tasks become ready. The app wires the callback to a Textual `Message`, keeping scheduling logic fully separated from UI. `TabState`/`SubCommand` remain for UI state; `SubCommand` gains a `task_id` to bridge the two.

**Tech Stack:** Python dataclasses, enum, Textual messages, pytest

**Design doc:** `docs/plans/2026-02-26-task-queue-design.md`

---

### Task 1: Add TaskQueue class with tests

**Files:**
- Create: `rbx/box/ui/task_queue.py`
- Create: `tests/rbx/box/ui/__init__.py`
- Create: `tests/rbx/box/ui/test_task_queue.py`

**Step 1: Create test directory and empty init**

Create `tests/rbx/box/ui/__init__.py` (empty file).

**Step 2: Write failing tests for TaskQueue**

Create `tests/rbx/box/ui/test_task_queue.py`:

```python
from rbx.box.ui.task_queue import Task, TaskQueue, TaskStatus


class TestTaskQueue:
    def _make_queue(self, num_terminals=3, parallel=True):
        self.ready_tasks = []
        return TaskQueue(
            num_terminals=num_terminals,
            parallel=parallel,
            on_task_ready=lambda t: self.ready_tasks.append(t),
        )

    def test_enqueue_starts_immediately_when_idle(self):
        q = self._make_queue()
        task = q.enqueue('echo hello', terminal_id=0)
        assert task.status == TaskStatus.RUNNING
        assert len(self.ready_tasks) == 1
        assert self.ready_tasks[0] is task

    def test_enqueue_stays_pending_when_terminal_busy(self):
        q = self._make_queue()
        t1 = q.enqueue('echo first', terminal_id=0)
        t2 = q.enqueue('echo second', terminal_id=0)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        assert len(self.ready_tasks) == 1

    def test_notify_complete_starts_next_in_same_terminal(self):
        q = self._make_queue()
        t1 = q.enqueue('echo first', terminal_id=0)
        t2 = q.enqueue('echo second', terminal_id=0)
        q.notify_complete(t1.task_id)
        assert t1.status == TaskStatus.COMPLETED
        assert t2.status == TaskStatus.RUNNING
        assert len(self.ready_tasks) == 2

    def test_parallel_different_terminals_run_concurrently(self):
        q = self._make_queue(parallel=True)
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=1)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.RUNNING
        assert len(self.ready_tasks) == 2

    def test_exclusive_waits_for_all_idle(self):
        q = self._make_queue(parallel=False)
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=1)
        # Sequential mode: all exclusive. t1 runs, t2 waits.
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        # Complete t1 -> t2 starts.
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING

    def test_exclusive_blocks_behind_running_other_terminal(self):
        """An exclusive task must wait even if its own terminal is idle."""
        q = self._make_queue(parallel=True)
        t1 = q.enqueue('echo a', terminal_id=0)
        # Manually enqueue an exclusive task on terminal 1.
        t2 = Task(
            task_id=0, command='exclusive cmd', terminal_id=1,
            exclusive=True, status=TaskStatus.PENDING,
        )
        # Use internal API to force an exclusive task in parallel mode.
        q._queue.append(t2)
        q._next_id = max(q._next_id, t2.task_id + 1)
        q._drain()
        # t1 is running on terminal 0, so exclusive t2 can't start.
        assert t2.status == TaskStatus.PENDING
        # Complete t1 -> now all idle -> t2 starts.
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING

    def test_ordering_same_terminal_preserved(self):
        """Tasks on the same terminal run in FIFO order."""
        q = self._make_queue()
        t1 = q.enqueue('echo 1', terminal_id=0)
        t2 = q.enqueue('echo 2', terminal_id=0)
        t3 = q.enqueue('echo 3', terminal_id=0)
        assert [t.status for t in [t1, t2, t3]] == [
            TaskStatus.RUNNING, TaskStatus.PENDING, TaskStatus.PENDING,
        ]
        q.notify_complete(t1.task_id)
        assert t2.status == TaskStatus.RUNNING
        assert t3.status == TaskStatus.PENDING
        q.notify_complete(t2.task_id)
        assert t3.status == TaskStatus.RUNNING

    def test_non_exclusive_skips_blocked_terminal(self):
        """A task on terminal 1 can start even if terminal 0 has a pending task blocked behind a running one."""
        q = self._make_queue()
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=0)  # blocked behind t1
        t3 = q.enqueue('echo c', terminal_id=1)
        assert t1.status == TaskStatus.RUNNING
        assert t2.status == TaskStatus.PENDING
        assert t3.status == TaskStatus.RUNNING

    def test_auto_increments_task_id(self):
        q = self._make_queue()
        t1 = q.enqueue('echo a', terminal_id=0)
        t2 = q.enqueue('echo b', terminal_id=1)
        assert t1.task_id == 0
        assert t2.task_id == 1

    def test_notify_complete_unknown_id_is_noop(self):
        q = self._make_queue()
        q.notify_complete(999)  # Should not raise.
```

**Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/ui/test_task_queue.py -v`
Expected: ImportError — `rbx.box.ui.task_queue` does not exist.

**Step 4: Implement TaskQueue**

Create `rbx/box/ui/task_queue.py`:

```python
import dataclasses
import enum
from typing import Callable, List, Optional


class TaskStatus(enum.Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'


@dataclasses.dataclass
class Task:
    task_id: int
    command: str
    terminal_id: int
    exclusive: bool
    status: TaskStatus


class TaskQueue:
    def __init__(
        self,
        num_terminals: int,
        parallel: bool,
        on_task_ready: Callable[[Task], None],
    ):
        self._num_terminals = num_terminals
        self._parallel = parallel
        self._on_task_ready = on_task_ready
        self._queue: List[Task] = []
        self._next_id: int = 0
        self._terminal_running: List[bool] = [False] * num_terminals

    def enqueue(self, command: str, terminal_id: int) -> Task:
        exclusive = self._is_exclusive(command, terminal_id)
        task = Task(
            task_id=self._next_id,
            command=command,
            terminal_id=terminal_id,
            exclusive=exclusive,
            status=TaskStatus.PENDING,
        )
        self._next_id += 1
        self._queue.append(task)
        self._drain()
        return task

    def notify_complete(self, task_id: int) -> None:
        task = self._find_task(task_id)
        if task is None:
            return
        task.status = TaskStatus.COMPLETED
        self._terminal_running[task.terminal_id] = False
        self._drain()

    def _is_exclusive(self, command: str, terminal_id: int) -> bool:
        return not self._parallel

    def _find_task(self, task_id: int) -> Optional[Task]:
        for task in self._queue:
            if task.task_id == task_id:
                return task
        return None

    def _drain(self) -> None:
        # Track which terminals we've seen a PENDING task for
        # (to enforce "no older pending task for same terminal" rule).
        seen_pending: set[int] = set()

        for task in self._queue:
            if task.status != TaskStatus.PENDING:
                continue

            terminal = task.terminal_id
            # Rule 1: no older pending task for same terminal.
            if terminal in seen_pending:
                continue
            # Rule 2: terminal is idle.
            if self._terminal_running[terminal]:
                seen_pending.add(terminal)
                continue
            # Rule 3: if exclusive, all terminals must be idle.
            if task.exclusive and any(self._terminal_running):
                seen_pending.add(terminal)
                continue

            # Start this task.
            task.status = TaskStatus.RUNNING
            self._terminal_running[terminal] = True
            self._on_task_ready(task)

            seen_pending.add(terminal)
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/ui/test_task_queue.py -v`
Expected: All 10 tests PASS.

**Step 6: Commit**

```
feat(ui): add TaskQueue class for command scheduling
```

---

### Task 2: Integrate TaskQueue into rbxCommandApp

**Files:**
- Modify: `rbx/box/ui/command_app.py`

**Step 1: Add TaskReady message and task_id to SubCommand**

In `command_app.py`, add import for `Task` and `TaskQueue` from `rbx.box.ui.task_queue`. Add `task_id: Optional[int] = None` field to the `SubCommand` dataclass. Add a `TaskReady` message class inside `rbxCommandApp`:

```python
class TaskReady(Message):
    def __init__(self, task: Task):
        self.task = task
        super().__init__()
```

**Step 2: Create TaskQueue in __init__ and remove old scheduling state**

In `rbxCommandApp.__init__`:
- Remove `self._sequential_event`
- Create `self._task_queue = TaskQueue(num_terminals=len(commands), parallel=parallel, on_task_ready=lambda t: self.post_message(self.TaskReady(t)))`

**Step 3: Replace on_mount scheduling with queue.enqueue**

Replace the initial command starting logic at the end of `on_mount` (the `if self.parallel` / `else` block and `_run_initial_sequential`) with:

```python
for i, tab in enumerate(self._tabs):
    for sub in tab.sub_commands:
        task = self._task_queue.enqueue(sub.shell_command, terminal_id=i)
        sub.task_id = task.task_id
```

Remove the `_run_initial_sequential` method entirely.

**Step 4: Add TaskReady handler**

Add handler that starts the command in the pane:

```python
def on_rbx_command_app_task_ready(self, event: TaskReady) -> None:
    task = event.task
    tab = self._tabs[task.terminal_id]
    # Find the sub-command linked to this task.
    sub = next((s for s in tab.sub_commands if s.task_id == task.task_id), None)
    if sub is None:
        return
    sub.status = CommandStatus.RUNNING
    self._update_sidebar(task.terminal_id)
    self._refresh_select_if_active(task.terminal_id)
    pane = self.query_one(f'#{sub.pane_id}', CommandPane)
    pane.execute(task.command)
```

**Step 5: Simplify on_command_pane_command_complete**

Replace the scheduling logic in the completion handler. After finding the completed sub-command and updating its status, just call:

```python
self._task_queue.notify_complete(sub.task_id)
```

Remove the `if self.parallel` / `else` branching and `_sequential_event` logic.

**Step 6: Simplify _queue_command_in_tab**

Replace the idle-check and start logic at the bottom of `_queue_command_in_tab` with:

```python
task = self._task_queue.enqueue(sub.shell_command, terminal_id=tab_index)
sub.task_id = task.task_id
```

Remove the `was_idle` check and `self.parallel or not self._any_tab_running()` logic.

**Step 7: Remove dead methods**

Delete these methods from `rbxCommandApp`:
- `_start_next_in_tab`
- `_start_next_sequentially`
- `_run_initial_sequential`
- `_any_tab_running`

**Step 8: Remove unused imports/fields**

- Remove `self._sequential_event` field
- Remove `asyncio` import if no longer used (check if anything else uses it)

**Step 9: Run the app manually to verify**

Run: `uv run python -m rbx.box.ui.command_app`
Expected: Three echo commands run. In default (non-parallel) mode they should run sequentially.

**Step 10: Commit**

```
refactor(ui): integrate TaskQueue into rbxCommandApp
```

---

### Task 3: Verify no regressions

**Files:** None (verification only)

**Step 1: Run linter**

Run: `uv run ruff check rbx/box/ui/command_app.py rbx/box/ui/task_queue.py`
Expected: No errors.

**Step 2: Run all unit tests**

Run: `uv run pytest tests/rbx/box/ui/test_task_queue.py -v`
Expected: All pass.

**Step 3: Run full test suite (excluding CLI)**

Run: `uv run pytest --ignore=tests/rbx/box/cli -x`
Expected: All pass, no import errors.

**Step 4: Commit if any fixes were needed**

```
fix(ui): address linting issues from TaskQueue integration
```
