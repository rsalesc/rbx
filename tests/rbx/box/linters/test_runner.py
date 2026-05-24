from rbx.box.environment import LinterConfig
from rbx.box.linters import runner
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity


class _WarnLinter(Linter):
    name = 'w_test'
    applies_to = set()

    def lint(self, code, source):
        return [LinterMessage(severity=LinterSeverity.WARNING, message='w')]


class _ErrLinter(Linter):
    name = 'e_test'
    applies_to = {AssetKind.GENERATOR}

    def lint(self, code, source):
        return [LinterMessage(severity=LinterSeverity.ERROR, message='boom')]


def test_applies_to_intersection_skips_out_of_scope():
    # _ErrLinter only applies to generators; a solution-kind asset is skipped.
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='e_test', applies_to=None)],
        linters=[_ErrLinter()],
        kind=AssetKind.SOLUTION,
        code=None,
        source='x',
    )
    assert msgs == []


def test_config_applies_to_further_restricts():
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='w_test', applies_to=[AssetKind.GENERATOR])],
        linters=[_WarnLinter()],
        kind=AssetKind.SOLUTION,
        code=None,
        source='x',
    )
    assert msgs == []


def test_disjoint_interface_and_config_scopes_never_apply():
    # Interface restricts to generators, config restricts to solutions: the
    # intersection is empty, so the linter must not run even on a generator.
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='e_test', applies_to=[AssetKind.SOLUTION])],
        linters=[_ErrLinter()],
        kind=AssetKind.GENERATOR,
        code=None,
        source='x',
    )
    assert msgs == []


def test_in_scope_linter_runs():
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='w_test', applies_to=None)],
        linters=[_WarnLinter()],
        kind=AssetKind.SOLUTION,
        code=None,
        source='x',
    )
    assert len(msgs) == 1
    assert msgs[0].message == 'w'


def test_suppression_directive_disables_linter():
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='w_test', applies_to=None)],
        linters=[_WarnLinter()],
        kind=AssetKind.SOLUTION,
        code=None,
        source='// w_test-linter: disable\nint main() {}',
    )
    assert msgs == []


def test_suppression_directive_is_per_linter():
    # Disabling w_test must not silence e_test.
    msgs = runner.run_linters_for_messages(
        configs=[
            LinterConfig(name='w_test', applies_to=None),
            LinterConfig(name='e_test', applies_to=None),
        ],
        linters=[_WarnLinter(), _ErrLinter()],
        kind=AssetKind.GENERATOR,
        code=None,
        source='// w_test-linter: disable\nint main() {}',
    )
    assert [m.message for m in msgs] == ['boom']


def test_suppression_requires_a_comment_marker():
    # A bare occurrence outside a comment must not disable the linter.
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='w_test', applies_to=None)],
        linters=[_WarnLinter()],
        kind=AssetKind.SOLUTION,
        code=None,
        source='const char* s = "w_test-linter: disable";',
    )
    assert len(msgs) == 1


def test_is_linter_suppressed_accepts_hash_comments_and_spacing():
    assert runner.is_linter_suppressed('w_test', '#  w_test-linter:disable')
    assert runner.is_linter_suppressed('w_test', '   // w_test-linter:   disable')
    assert not runner.is_linter_suppressed('w_test', '// other-linter: disable')
    assert not runner.is_linter_suppressed('w_test', 'no directive here')
