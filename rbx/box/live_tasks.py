import abc
import dataclasses
import enum
from typing import List

from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.live import Live
from rich.text import Text

from rbx import console
from rbx.box.schema import CodeItem


@dataclasses.dataclass(frozen=True)
class TaskRenderable:
    columns: List[RenderableType]


class LiveTask(abc.ABC):
    finished: bool = False

    @abc.abstractmethod
    def render(self) -> TaskRenderable:
        pass

    def is_finished(self) -> bool:
        return self.finished


class CompilationStatus(enum.Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    SKIPPED = 'skipped'
    FAILED = 'failed'
    WARNINGS = 'warnings'

    def markup(self) -> str:
        return {
            CompilationStatus.PENDING: '',
            CompilationStatus.RUNNING: '[info]RUNNING[/info]',
            CompilationStatus.SUCCESS: '[success]SUCCESS[/success]',
            CompilationStatus.SKIPPED: '[status]SKIPPED[/status]',
            CompilationStatus.FAILED: '[error]FAILED[/error]',
            CompilationStatus.WARNINGS: '[warning]WARNINGS[/warning]',
        }[self]


class CompilationTask(LiveTask):
    item: CodeItem
    status: CompilationStatus

    def __init__(self, item: CodeItem) -> None:
        self.item = item
        self.status = CompilationStatus.PENDING

    def render(self) -> TaskRenderable:
        return TaskRenderable(
            columns=[
                Text.from_markup(
                    f'[info]Compiling {self.item.href()}...[/info]',
                ),
                Text.from_markup(self.status.markup()),
            ]
        )

    def is_finished(self) -> bool:
        return self.status not in (CompilationStatus.PENDING, CompilationStatus.RUNNING)


class LiveTasks:
    live: Live
    tasks: List[LiveTask]

    _dumped: List[bool]
    _dump: bool

    def __init__(self, dump: bool = False) -> None:
        self.tasks = []
        self._dumped = []
        self._dump = dump

    def __enter__(self) -> 'LiveTasks':
        self.live = Live(
            console=console.console, auto_refresh=False, vertical_overflow='visible'
        )
        self.live.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.update()
        self.live.stop()

    def update(self) -> None:
        # TODO: implement dumping
        # TODO: implement panels
        rows: List[List[RenderableType]] = [
            task.render().columns for task in self.tasks
        ]
        transposed_columns = list(zip(*rows))
        self.live.update(Columns([Group(*column) for column in transposed_columns]))

    def append(self, task: LiveTask, update: bool = False) -> None:
        self.tasks.append(task)
        self._dumped.append(False)
        if update:
            self.update()
