import pathlib

from rbx import console as rconsole
from rbx import utils
from rbx.box.linters.linter import LinterMessage, LinterSeverity
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import CodeItem
from rbx.grading.steps import PreprocessLog


def _capture_print(fn) -> str:
    with rconsole.console.capture() as capture:
        fn()
    # Strip ANSI so assertions are not split by Rich's auto-highlight bolds.
    return utils.strip_ansi_codes(capture.get())


def _log(stderr: str, cmd=None) -> PreprocessLog:
    return PreprocessLog(cmd=cmd or ['g++', 'sol.cpp'], log=stderr, warnings=True)


def test_report_includes_per_file_warning_summary():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')
    stderr = (
        "sols/a.cpp:1:1: warning: unused variable 'x' [-Wunused-variable]\n"
        "sols/a.cpp:2:1: warning: unused variable 'y' [-Wunused-variable]\n"
    )
    stack.add_warning(code, logs=[_log(stderr)])

    out = _capture_print(warning_stack.print_warning_stack_report)

    assert 'sols/a.cpp' in out
    assert '2× -Wunused-variable' in out
    stack.clear()


def _linter_warning(message: str, line: int, col: int) -> LinterMessage:
    return LinterMessage(
        severity=LinterSeverity.WARNING, message=message, line=line, col=col
    )


def test_report_groups_repeated_linter_warnings_on_one_line():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    code = CodeItem(path=pathlib.Path('gens/gen.cpp'), language='cpp')
    msg = 'multiple side-effecting arguments'
    stack.add_linter_warning(
        code,
        [_linter_warning(msg, 2, 3), _linter_warning(msg, 5, 7)],
    )

    out = _capture_print(warning_stack.print_warning_stack_report)

    # The two occurrences collapse into a single grouped line listing both.
    assert f'lines 2:3, 5:7: {msg}' in out
    assert out.count(msg) == 1
    stack.clear()


def test_report_omits_parens_when_summarizer_returns_none():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    code = CodeItem(path=pathlib.Path('sols/b.py'), language='py')
    # python3 has no registered summarizer → default returns None.
    stack.add_warning(
        code,
        logs=[_log('irrelevant', cmd=['python3', 'sols/b.py'])],
    )

    out = _capture_print(warning_stack.print_warning_stack_report)

    assert 'sols/b.py' in out
    # No parenthesized summary appended.
    assert 'sols/b.py (' not in out
    stack.clear()
