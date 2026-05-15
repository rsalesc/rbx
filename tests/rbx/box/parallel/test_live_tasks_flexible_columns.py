import pathlib

from rich.console import Console
from rich.text import Text

from rbx.box.parallel.live_tasks import (
    CompilationStatus,
    CompilationTask,
    TaskGrid,
    TaskRenderable,
)
from rbx.box.schema import CodeItem


def _render(grid: TaskGrid, width: int) -> str:
    console = Console(width=width, force_terminal=False, record=True)
    console.print(grid)
    return console.export_text()


def test_flexible_column_ellipsizes_when_too_narrow():
    long_summary = '5× -Wunused-variable, 3× -Wsign-compare (+2 more)'
    grid = TaskGrid(
        renderables=[
            TaskRenderable(columns=[Text('short'), Text('STATUS'), Text(long_summary)])
        ],
        flexible_columns={2},
        rule_title=False,
    )
    # Flexible column gets ellipsized; output fits within terminal width.
    out = _render(grid, width=40).rstrip('\n')
    assert '…' in out
    # Every printed line must fit within the requested width.
    for line in out.split('\n'):
        assert len(line) <= 40


def test_non_flexible_column_unchanged():
    grid = TaskGrid(
        renderables=[TaskRenderable(columns=[Text('a'), Text('b'), Text('c')])],
        flexible_columns={2},
        rule_title=False,
    )
    out = _render(grid, width=80)
    assert '…' not in out


def test_compilation_task_render_includes_summary_column():
    item = CodeItem(path=pathlib.Path('sol.cpp'))
    task = CompilationTask(item=item)
    task.status = CompilationStatus.WARNINGS
    task.warning_summary = '1× -Wunused-variable'
    r = task.render()
    assert r is not None
    assert len(r.columns) == 3
    rendered_third = r.columns[2]
    assert '1× -Wunused-variable' in rendered_third.plain


def test_compilation_task_render_empty_summary_when_no_warning():
    item = CodeItem(path=pathlib.Path('sol.cpp'))
    task = CompilationTask(item=item)
    task.status = CompilationStatus.FAILED
    r = task.render()
    assert r is not None
    assert len(r.columns) == 3
    assert r.columns[2].plain == ''
