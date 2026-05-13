import pathlib

from rbx.box.sanitizers.warning_stack import WarningStack
from rbx.box.schema import CodeItem
from rbx.grading.steps import PreprocessLog


def _log(warnings: bool) -> PreprocessLog:
    return PreprocessLog(
        cmd=['g++', 'a.cpp'], log='some warning text', warnings=warnings
    )


def test_add_warning_records_path_and_logs(tmp_path: pathlib.Path):
    stack = WarningStack(tmp_path)
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')
    logs = [_log(True)]

    stack.add_warning(code, logs=logs)

    assert code.path in stack.warnings
    assert stack.warning_logs[code.path] == logs


def test_add_warning_without_logs_still_records_path(tmp_path: pathlib.Path):
    stack = WarningStack(tmp_path)
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')

    stack.add_warning(code)

    assert code.path in stack.warnings
    assert stack.warning_logs.get(code.path) in (None, [])


def test_clear_resets_warning_logs(tmp_path: pathlib.Path):
    stack = WarningStack(tmp_path)
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')
    stack.add_warning(code, logs=[_log(True)])

    stack.clear()

    assert not stack.warnings
    assert not stack.warning_logs
