from rbx.box.parallel import live_tasks
from rbx.box.schema import CodeItem


def _task(
    status: live_tasks.CompilationStatus, summary=None
) -> live_tasks.CompilationTask:
    task = live_tasks.CompilationTask(CodeItem(path='sols/a.cpp', language='cpp'))
    task.status = status
    task.warning_summary = summary
    return task


def test_success_renders_nothing():
    assert _task(live_tasks.CompilationStatus.SUCCESS).render() is None


def test_warnings_without_summary_shows_plain_label():
    rendered = _task(live_tasks.CompilationStatus.WARNINGS).render()
    assert rendered is not None
    assert rendered.columns[1].plain == 'WARNINGS'


def test_warnings_with_summary_appends_it():
    rendered = _task(
        live_tasks.CompilationStatus.WARNINGS, summary='3 warnings'
    ).render()
    assert rendered is not None
    assert rendered.columns[1].plain == 'WARNINGS (3 warnings)'


def test_warning_summary_ignored_when_not_warnings_status():
    rendered = _task(live_tasks.CompilationStatus.FAILED, summary='x').render()
    assert rendered is not None
    assert rendered.columns[1].plain == 'FAILED'
