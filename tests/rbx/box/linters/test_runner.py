from rbx.box.environment import LinterConfig
from rbx.box.linters import runner
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity


class _WarnLinter(Linter):
    name = 'w_test'
    languages = {'cpp'}
    applies_to = set()

    def lint(self, code, source):
        return [LinterMessage(severity=LinterSeverity.WARNING, message='w')]


class _ErrLinter(Linter):
    name = 'e_test'
    languages = {'cpp'}
    applies_to = {AssetKind.GENERATOR}

    def lint(self, code, source):
        return [LinterMessage(severity=LinterSeverity.ERROR, message='boom')]


def test_applies_to_intersection_skips_out_of_scope():
    # _ErrLinter only applies to generators; a solution-kind asset is skipped.
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='e_test', applies_to=None)],
        linters=[_ErrLinter()],
        language_name='cpp',
        kind=AssetKind.SOLUTION,
        code=None,
        source='x',
    )
    assert msgs == []


def test_config_applies_to_further_restricts():
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='w_test', applies_to=[AssetKind.GENERATOR])],
        linters=[_WarnLinter()],
        language_name='cpp',
        kind=AssetKind.SOLUTION,
        code=None,
        source='x',
    )
    assert msgs == []


def test_in_scope_linter_runs():
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='w_test', applies_to=None)],
        linters=[_WarnLinter()],
        language_name='cpp',
        kind=AssetKind.SOLUTION,
        code=None,
        source='x',
    )
    assert len(msgs) == 1
    assert msgs[0].message == 'w'
