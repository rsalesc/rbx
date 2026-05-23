from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity
from rbx.box.schema import CodeItem


class _DummyLinter(Linter):
    name = 'dummy'
    applies_to = {AssetKind.GENERATOR}

    def lint(self, code, source):
        return [LinterMessage(severity=LinterSeverity.WARNING, message='hi', line=1)]


def test_linter_metadata_and_lint():
    linter = _DummyLinter()
    assert linter.name == 'dummy'
    assert linter.applies_to == {AssetKind.GENERATOR}
    msgs = linter.lint(CodeItem(path='g.cpp'), 'source')
    assert msgs == [
        LinterMessage(severity=LinterSeverity.WARNING, message='hi', line=1)
    ]
