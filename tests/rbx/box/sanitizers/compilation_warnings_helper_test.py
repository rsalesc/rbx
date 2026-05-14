from rbx.box.parallel import live_tasks
from rbx.box.sanitizers import compilation_warnings, warning_stack
from rbx.box.schema import CodeItem
from rbx.grading.steps import PreprocessLog


def _task(path: str = 'sols/a.cpp') -> live_tasks.CompilationTask:
    task = live_tasks.CompilationTask(CodeItem(path=path, language='cpp'))
    task.status = live_tasks.CompilationStatus.SUCCESS
    return task


def _log() -> PreprocessLog:
    return PreprocessLog(
        cmd=['g++', 'a.cpp'], log='a.cpp:1:1: warning: x', warnings=True
    )


def test_apply_warning_status_flips_to_warnings_when_in_stack():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    task = _task()
    stack.add_warning(task.item, logs=[_log()])

    compilation_warnings.apply_warning_status(task)

    assert task.status is live_tasks.CompilationStatus.WARNINGS
    # g++ matches the registered C++ summarizer, which produces a real summary.
    assert task.warning_summary == '1 warning'
    stack.clear()


def test_apply_warning_status_leaves_status_when_not_in_stack():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    task = _task()

    compilation_warnings.apply_warning_status(task)

    assert task.status is live_tasks.CompilationStatus.SUCCESS
    assert task.warning_summary is None


def test_apply_warning_status_uses_compiler_summarizer(monkeypatch):
    class FakeSummarizer(compilation_warnings.CompilationWarningSummarizer):
        def summarize(self, logs):
            return f'{len(logs)} warnings'

    monkeypatch.setattr(
        compilation_warnings,
        '_SUMMARIZERS',
        [(lambda exe: 'g++' in exe, FakeSummarizer())],
    )

    stack = warning_stack.get_warning_stack()
    stack.clear()
    task = _task()
    stack.add_warning(task.item, logs=[_log(), _log()])

    compilation_warnings.apply_warning_status(task)

    assert task.status is live_tasks.CompilationStatus.WARNINGS
    assert task.warning_summary == '2 warnings'
    stack.clear()


def test_apply_warning_status_skips_when_no_warning_bearing_logs():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    task = _task()
    non_warning_log = PreprocessLog(cmd=['g++', 'a.cpp'], log='', warnings=False)
    # Path is registered in stack.warnings, but no log has warnings=True.
    stack.add_warning(task.item, logs=[non_warning_log])

    compilation_warnings.apply_warning_status(task)

    assert task.status is live_tasks.CompilationStatus.SUCCESS
    assert task.warning_summary is None
    stack.clear()


def test_apply_warning_status_picks_cmd_from_warning_log(monkeypatch):
    class _Dummy(compilation_warnings.CompilationWarningSummarizer):
        def summarize(self, logs):
            return 'dummy-summary'

    # Only matches g++; if the dispatcher mistakenly used the first log's cmd
    # (python3), it would fall back to the default summarizer and return None.
    monkeypatch.setattr(
        compilation_warnings,
        '_SUMMARIZERS',
        [(lambda exe: 'g++' in exe, _Dummy())],
    )

    stack = warning_stack.get_warning_stack()
    stack.clear()
    task = _task()
    non_warning_log = PreprocessLog(cmd=['python3', 'foo.py'], log='', warnings=False)
    warning_log = PreprocessLog(
        cmd=['g++', 'foo.cpp'], log='foo.cpp:1:1: warning: x', warnings=True
    )
    stack.add_warning(task.item, logs=[non_warning_log, warning_log])

    compilation_warnings.apply_warning_status(task)

    assert task.status is live_tasks.CompilationStatus.WARNINGS
    assert task.warning_summary == 'dummy-summary'
    stack.clear()
