import pathlib

from rbx.box.linters.linter import LinterMessage, LinterSeverity
from rbx.box.sanitizers.warning_stack import WarningStack, group_linter_messages
from rbx.box.schema import CodeItem
from rbx.grading.steps import PreprocessLog


def _warning(message: str, line=None, col=None) -> LinterMessage:
    return LinterMessage(
        severity=LinterSeverity.WARNING, message=message, line=line, col=col
    )


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


def test_group_linter_messages_groups_identical_by_message():
    messages = [
        _warning('same message', line=2, col=3),
        _warning('same message', line=5, col=7),
    ]

    grouped = group_linter_messages(messages)

    assert grouped == [('same message', ['2:3', '5:7'])]


def test_group_linter_messages_keeps_distinct_messages_in_first_seen_order():
    messages = [
        _warning('first', line=1),
        _warning('second', line=2),
        _warning('first', line=3),
    ]

    grouped = group_linter_messages(messages)

    assert grouped == [('first', ['1', '3']), ('second', ['2'])]


def test_group_linter_messages_dedupes_repeated_locations():
    messages = [
        _warning('msg', line=4, col=1),
        _warning('msg', line=4, col=1),
    ]

    grouped = group_linter_messages(messages)

    assert grouped == [('msg', ['4:1'])]


def test_group_linter_messages_handles_missing_location():
    grouped = group_linter_messages([_warning('no location')])

    assert grouped == [('no location', [])]


def test_clear_resets_warning_logs(tmp_path: pathlib.Path):
    stack = WarningStack(tmp_path)
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')
    stack.add_warning(code, logs=[_log(True)])

    stack.clear()

    assert not stack.warnings
    assert not stack.warning_logs
