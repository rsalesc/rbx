from rbx.box.linters.linter import LinterMessage, LinterSeverity
from rbx.box.sanitizers.warning_stack import WarningStack
from rbx.box.schema import CodeItem


def test_add_linter_warning_records_messages(tmp_path):
    stack = WarningStack(tmp_path)
    code = CodeItem(path='gen.cpp')
    stack.add_linter_warning(
        code,
        [LinterMessage(severity=LinterSeverity.WARNING, message='m', line=2, col=3)],
    )
    assert code.path in stack.warnings
    assert stack.linter_warnings[code.path][0].message == 'm'
