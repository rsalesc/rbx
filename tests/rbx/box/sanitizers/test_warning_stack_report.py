import pathlib

from rbx import console as rconsole
from rbx import utils
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
