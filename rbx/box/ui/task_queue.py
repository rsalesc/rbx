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

    def enqueue(
        self,
        command: str,
        terminal_id: int,
        exclusive: Optional[bool] = None,
    ) -> Task:
        if exclusive is None:
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
        seen_pending: set[int] = set()

        for task in self._queue:
            if task.status != TaskStatus.PENDING:
                continue

            terminal = task.terminal_id
            if terminal in seen_pending:
                continue
            if self._terminal_running[terminal]:
                seen_pending.add(terminal)
                continue
            if task.exclusive and any(self._terminal_running):
                seen_pending.add(terminal)
                continue

            task.status = TaskStatus.RUNNING
            self._terminal_running[terminal] = True
            self._on_task_ready(task)

            seen_pending.add(terminal)
