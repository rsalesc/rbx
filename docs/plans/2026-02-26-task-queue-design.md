# TaskQueue Design for command_app.py

**Date:** 2026-02-26

## Problem

The execution scheduling logic in `rbxCommandApp` is spread across multiple methods
(`_start_next_in_tab`, `_start_next_sequentially`, `_run_initial_sequential`,
`_queue_command_in_tab`, `on_command_pane_command_complete`) interleaved with UI concerns.
The parallel vs sequential distinction is handled via ad-hoc branching throughout the app.

## Solution

Extract a pure `TaskQueue` class that owns the scheduling lifecycle: enqueue → drain
eligible → signal ready → notify complete → drain again.

## Data Model

```python
class TaskStatus(enum.Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'

@dataclasses.dataclass
class Task:
    task_id: int        # Auto-assigned by queue
    command: str        # Shell command to execute
    terminal_id: int    # Which terminal/tab this runs in
    exclusive: bool     # If True, runs alone (all terminals idle)
    status: TaskStatus  # PENDING → RUNNING → COMPLETED
```

## TaskQueue Class

```python
class TaskQueue:
    def __init__(self, num_terminals, parallel, on_task_ready):
        ...

    def enqueue(self, command: str, terminal_id: int) -> Task
    def notify_complete(self, task_id: int) -> None
    def _is_exclusive(self, command: str, terminal_id: int) -> bool
    def _drain(self) -> None
```

### Drain Rules

Iterates the queue in insertion order. A PENDING task can be popped if:

1. No older PENDING task for the same terminal exists ahead of it
2. The terminal is idle (no RUNNING task)
3. If exclusive, ALL terminals must be idle

When popped: mark RUNNING, update terminal state, fire `on_task_ready` callback.

### Exclusivity

`_is_exclusive(command, terminal_id)` is the override point. Current logic:
returns `not self._parallel`. User will add more logic later.

## Integration with rbxCommandApp

1. **Construction**: `TaskQueue` created in `__init__` with
   `on_task_ready=lambda t: self.post_message(TaskReady(t))`

2. **TaskReady message**: New Textual `Message` subclass carrying a `Task`.
   Handler finds the pane, updates status markup, calls `pane.execute(task.command)`.

3. **Completion**: `on_command_pane_command_complete` calls
   `queue.notify_complete(task_id)` instead of manual scheduling logic.

4. **Enqueuing**: `_queue_command_in_tab` calls `queue.enqueue()` instead of
   manually checking idle state and parallel mode.

5. **Initial commands**: `on_mount` enqueues all initial commands. The queue's
   drain logic handles both parallel and sequential automatically.

6. **Removed methods**: `_run_initial_sequential`, `_sequential_event`,
   `_start_next_in_tab`, `_start_next_sequentially`, `_any_tab_running`.

7. **SubCommand linkage**: `SubCommand` gains a `task_id` field to link UI
   state to queue tasks for the completion handler.

8. **TabState/SubCommand**: Remain for UI state (pane IDs, select widget,
   sidebar labels). Queue only owns scheduling.
