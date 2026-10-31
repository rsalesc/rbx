import pathlib

from rbx import console as rconsole
from rbx import utils
from rbx.box import issues
from rbx.box.cli.commands import run as run_cmd
from rbx.box.issues import schema as issues_schema
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


_SHADOW = "sols/a.cpp:1:1: warning: shadows 'x' [-Wshadow]\n"


def test_report_is_silent_when_issues_reported_everything():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    stack.add_warning(
        CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp'),
        logs=[_log(_SHADOW)],
    )
    stack.sanitizer_warnings[pathlib.Path('sols/a.cpp')] = pathlib.Path('a.log')
    stack.mark_reported(
        compilation=[pathlib.Path('sols/a.cpp')],
        sanitizer=[pathlib.Path('sols/a.cpp')],
    )

    out = _capture_print(warning_stack.print_warning_stack_report)

    assert out == ''
    stack.clear()


def test_report_keeps_what_issues_did_not_cover():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    stack.add_warning(
        CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp'),
        logs=[_log(_SHADOW)],
    )
    stack.add_warning(
        CodeItem(path=pathlib.Path('gens/gen.cpp'), language='cpp'),
        logs=[_log(_SHADOW)],
    )
    stack.sanitizer_warnings[pathlib.Path('gens/gen.cpp')] = pathlib.Path('g.log')
    stack.mark_reported(compilation=[pathlib.Path('sols/a.cpp')])

    out = _capture_print(warning_stack.print_warning_stack_report)

    assert 'sols/a.cpp' not in out
    assert '1 compilation warnings' in out
    assert 'gens/gen.cpp (1× -Wshadow)' in out
    assert '1 sanitizer warnings' in out
    stack.clear()


def test_report_keeps_linter_messages_of_a_reported_file():
    # The issues view never sees linter messages, so a covered file that also
    # carries them stays -- without the compiler summary issues already gave.
    stack = warning_stack.get_warning_stack()
    stack.clear()
    code = CodeItem(path=pathlib.Path('sols/a.cpp'), language='cpp')
    stack.add_warning(code, logs=[_log(_SHADOW)])
    stack.add_linter_warning(code, [_linter_warning('lint me', 1, 1)])
    stack.mark_reported(compilation=[pathlib.Path('sols/a.cpp')])

    out = _capture_print(warning_stack.print_warning_stack_report)

    assert 'sols/a.cpp' in out
    assert '-Wshadow' not in out
    assert 'lint me' in out
    stack.clear()


def test_clear_forgets_what_was_reported():
    stack = warning_stack.get_warning_stack()
    stack.mark_reported(compilation=[pathlib.Path('sols/a.cpp')])

    stack.clear()

    assert stack.reported_compilation == set()
    assert stack.reported_sanitizer == set()


def test_run_hands_issue_covered_solutions_over_including_ignored_ones():
    stack = warning_stack.get_warning_stack()
    stack.clear()
    report = issues.IssueReport(
        ranAt=1.0,
        issues=[
            issues_schema.CompilationWarningsIssue(
                solution='sols/a.cpp', log=pathlib.Path('compilation/0.log')
            ),
            issues_schema.SanitizerFindingIssue(solution='sols/b.cpp'),
            issues_schema.BorderlineTleIssue(solution='sols/c.cpp'),
        ],
        ignored=[
            issues_schema.CompilationWarningsIssue(
                solution='sols/d.cpp', log=pathlib.Path('compilation/1.log')
            ),
        ],
    )

    run_cmd.hand_over_to_issues(report)

    assert stack.reported_compilation == {
        pathlib.Path('sols/a.cpp'),
        pathlib.Path('sols/d.cpp'),
    }
    assert stack.reported_sanitizer == {pathlib.Path('sols/b.cpp')}
    stack.clear()
