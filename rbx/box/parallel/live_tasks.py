import abc
import dataclasses
import enum
from typing import Generic, List, Optional, TypeVar

from rich.align import AlignMethod
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.measure import Measurement
from rich.padding import Padding, PaddingDimensions
from rich.rule import Rule
from rich.spinner import Spinner
from rich.style import StyleType
from rich.table import Table
from rich.text import Text, TextType

from rbx import console as rbx_console
from rbx.box.exception import RbxException
from rbx.box.schema import CodeItem
from rbx.box.ui.rich import live_utils


@dataclasses.dataclass(frozen=True)
class TaskRenderable:
    columns: List[RenderableType]
    panel: Optional[RenderableType] = None


class TaskGrid:
    """Renders TaskRenderables as aligned columns with interleaved panel content.

    Each TaskRenderable's columns are aligned across all rows (like a table),
    and if a TaskRenderable has a panel, it is rendered below its row.
    """

    align: Optional[AlignMethod]

    def __init__(
        self,
        renderables: Optional[List[TaskRenderable]] = None,
        padding: PaddingDimensions = (0, 1),
        *,
        align: Optional[AlignMethod] = None,
        panel_indent: int = 2,
        title: Optional[TextType] = None,
        rule_title: bool = True,
        title_style: StyleType = 'status',
        skip_empty: bool = True,
    ) -> None:
        self.renderables = list(renderables or [])
        self.padding = padding
        self.align = align
        self.panel_indent = panel_indent
        self.title = title
        self.rule_title = rule_title
        self.title_style = title_style
        self.skip_empty = skip_empty

    def _make_table(self, col_widths: List[int]) -> Table:
        table = Table.grid(padding=self.padding, collapse_padding=True, pad_edge=False)
        for w in col_widths:
            table.add_column(
                width=w,
                justify=self.align or 'left',
            )
        return table

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        if self.skip_empty and not self.renderables:
            return

        table_title: Optional[TextType] = None
        if (self.rule_title or not self.renderables) and self.title is not None:
            if isinstance(self.title, str):
                title_text = Text.from_markup(self.title, style=self.title_style)
            else:
                title_text = self.title.copy()
                title_text.stylize(self.title_style)
            yield Rule(title_text, style=self.title_style)
        else:
            table_title = self.title

        try:
            column_count = max(len(r.columns) for r in self.renderables)
        except ValueError:
            return

        if column_count == 0:
            return

        # Measure max width for each column position across all rows.
        col_widths = [0] * column_count
        for renderable in self.renderables:
            for i, col in enumerate(renderable.columns):
                width = Measurement.get(console, options, col).maximum
                col_widths[i] = max(col_widths[i], width)

        # Yield row tables and panels as separate renderables so that panels
        # span the full width rather than being confined to a single column.
        table = self._make_table(col_widths)
        if table_title is not None:
            table.title = table_title

        for renderable in self.renderables:
            # Pad row to column_count if needed.
            cells: List[RenderableType] = list(renderable.columns)
            while len(cells) < column_count:
                cells.append(Text(''))
            table.add_row(*cells)

            if renderable.panel is not None:
                # Flush the current table segment, yield the panel, start new.
                yield table
                panel = renderable.panel
                if self.panel_indent > 0:
                    panel = Padding(panel, (0, 0, 0, self.panel_indent))
                yield panel
                table = self._make_table(col_widths)

        yield table


class LiveTask(abc.ABC):
    finished: bool = False

    @abc.abstractmethod
    def render(self) -> Optional[TaskRenderable]:
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
            CompilationStatus.RUNNING: '',
            CompilationStatus.SUCCESS: '[success]SUCCESS[/success]',
            CompilationStatus.SKIPPED: '[status]SKIPPED[/status]',
            CompilationStatus.FAILED: '[error]FAILED[/error]',
            CompilationStatus.WARNINGS: '[warning]WARNINGS[/warning]',
        }[self]


class CompilationTask(LiveTask):
    item: CodeItem
    status: CompilationStatus
    exception: Optional[RbxException] = None

    def __init__(self, item: CodeItem) -> None:
        self.item = item
        self.status = CompilationStatus.PENDING

    def render(self) -> Optional[TaskRenderable]:
        if self.status in (CompilationStatus.PENDING, CompilationStatus.SUCCESS):
            return None
        return TaskRenderable(
            columns=[
                Text.from_markup(
                    f'[info]Compiling {self.item.href()}...[/info]',
                ),
                Text.from_markup(self.status.markup()),
            ],
            panel=self.exception.cropped(
                max_lines=15,
                footer=Text.from_markup(
                    '[warning]The compilation error is too long to display. '
                    'Run [item]rbx compile[/item] to see the full error.[/warning]'
                ),
            )
            if self.exception is not None
            else None,
        )

    def is_finished(self) -> bool:
        return self.status not in (CompilationStatus.PENDING, CompilationStatus.RUNNING)


TypeVarTask = TypeVar('TypeVarTask', bound=LiveTask)


class LiveTasks(Generic[TypeVarTask]):
    live: Live
    tasks: List[TypeVarTask]

    _panel_indent: int
    _title: Optional[TextType]
    _rule_title: bool
    _console: Console
    _suspend_lives: bool
    _old_lives: List[Live]

    _progress_message: Optional[str]
    _final_message: Optional[str]
    _spinner: Optional[Spinner]

    def __init__(
        self,
        title: Optional[TextType] = None,
        panel_indent: int = 0,
        rule_title: bool = True,
        skip_empty: bool = True,
        console: Optional[Console] = None,
        suspend_lives: bool = True,
        progress_message: Optional[str] = None,
        progress_spinner: Optional[str] = 'simpleDots',
        progress_spinner_style: StyleType = 'green',
        final_message: Optional[str] = None,
    ) -> None:
        self.tasks = []
        self._panel_indent = panel_indent
        self._title = title
        self._rule_title = rule_title
        self._skip_empty = skip_empty
        self._console = console or rbx_console.console
        self._suspend_lives = suspend_lives
        self._old_lives = []
        self._progress_message = progress_message
        self._spinner = self._make_spinner(progress_spinner, progress_spinner_style)
        self._final_message = final_message

    def __enter__(self) -> 'LiveTasks':
        if self._suspend_lives:
            self._old_lives = live_utils.hold_lives(self._console)
        self.live = Live(
            console=self._console,
            auto_refresh=self._should_auto_refresh(),
            refresh_per_second=2,
            vertical_overflow='visible',
        )
        self.live.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.update(finished=True)
        self.live.stop()
        for live in self._old_lives:
            live.start()

    def _make_spinner(
        self, spinner: Optional[str], style: StyleType
    ) -> Optional[Spinner]:
        if spinner is None:
            return None
        return Spinner(spinner, style=style)

    def _should_auto_refresh(self) -> bool:
        return self._progress_message is not None and self._spinner is not None

    def _get_progress_renderable(
        self, finished_tasks: int, total_tasks: int
    ) -> RenderableType:
        assert self._progress_message is not None
        text = Text.from_markup(
            self._progress_message.format(
                processed=finished_tasks,
                total=total_tasks,
            )
        )
        if self._spinner is not None:
            self._spinner.text = text
            return self._spinner
        return text

    def update(self, finished: bool = False) -> None:
        renderables = [task.render() for task in self.tasks]
        renderables = [r for r in renderables if r is not None]
        update_renderable: List[RenderableType] = [
            TaskGrid(
                renderables,
                panel_indent=self._panel_indent,
                title=self._title,
                rule_title=self._rule_title,
                skip_empty=self._skip_empty,
            )
        ]
        finished_tasks = sum(1 for task in self.tasks if task.is_finished())
        total_tasks = len(self.tasks)
        has_finished = finished or finished_tasks == total_tasks
        if self._progress_message is not None and not has_finished:
            update_renderable.append(
                self._get_progress_renderable(finished_tasks, total_tasks)
            )
        if self._final_message is not None and has_finished:
            update_renderable.append(
                Text.from_markup(
                    self._final_message.format(
                        processed=finished_tasks, total=total_tasks
                    )
                )
            )
        self.live.update(
            Group(*update_renderable),
            refresh=True,
        )

    def append(self, task: TypeVarTask, update: bool = False) -> None:
        self.tasks.append(task)
        if update:
            self.update()
