import abc
import dataclasses
import enum
from typing import List, Optional

from rich.align import AlignMethod
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.live import Live
from rich.measure import Measurement
from rich.padding import Padding, PaddingDimensions
from rich.rule import Rule
from rich.style import StyleType
from rich.table import Table
from rich.text import Text, TextType

from rbx import console
from rbx.box.exception import RbxException
from rbx.box.schema import CodeItem


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
    ) -> None:
        self.renderables = list(renderables or [])
        self.padding = padding
        self.align = align
        self.panel_indent = panel_indent
        self.title = title
        self.rule_title = rule_title
        self.title_style = title_style

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
        if not self.renderables:
            return

        column_count = max(len(r.columns) for r in self.renderables)
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
        if self.rule_title and self.title is not None:
            if isinstance(self.title, str):
                title_text = Text.from_markup(self.title, style=self.title_style)
            else:
                title_text = self.title.copy()
                title_text.stylize(self.title_style)
            yield Rule(title_text, style=self.title_style)
        else:
            table.title = self.title

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
    exception: Optional[RbxException] = None

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


class LiveTasks:
    live: Live
    tasks: List[LiveTask]

    _dumped: List[bool]
    _dump: bool
    _panel_indent: int
    _title: Optional[TextType]
    _rule_title: bool

    def __init__(
        self,
        title: Optional[TextType] = None,
        dump: bool = False,
        panel_indent: int = 0,
        rule_title: bool = True,
    ) -> None:
        self.tasks = []
        self._dumped = []
        self._dump = dump
        self._panel_indent = panel_indent
        self._title = title
        self._rule_title = rule_title

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
        renderables = [task.render() for task in self.tasks]
        self.live.update(
            TaskGrid(
                renderables,
                panel_indent=self._panel_indent,
                title=self._title,
                rule_title=self._rule_title,
            )
        )

    def append(self, task: LiveTask, update: bool = False) -> None:
        self.tasks.append(task)
        self._dumped.append(False)
        if update:
            self.update()
