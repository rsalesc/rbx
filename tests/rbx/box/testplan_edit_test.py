import pathlib

import pytest

from rbx.box import testplan_edit

PLAN = """\
gen 1
# about the group
@testgroup main {
    gen 2
    @copy tests/main/edge-001.in
  @testgroup large {
    gen 3
  }
}
@input {
a
}
@testgroup main/large {
  gen 4
}
"""


def test_statements_carry_their_full_testgroup_path():
    assert [
        (s.start_line, s.kind, s.group) for s in testplan_edit.statements(PLAN)
    ] == [
        (1, 'generator_call', None),
        (4, 'generator_call', 'main'),
        (5, 'copy_test', 'main'),
        (7, 'generator_call', 'main/large'),
        (10, 'inline_input', None),
        (14, 'generator_call', 'main/large'),
    ]
    copy = testplan_edit.statement_at(PLAN, 5)
    assert copy is not None
    assert copy.copy_path == pathlib.Path('tests/main/edge-001.in')


def test_copy_path_leaves_out_allow_duplicate():
    copy = testplan_edit.statement_at('@copy tests/a.in @allow-duplicate\n', 1)
    assert copy is not None
    assert copy.copy_path == pathlib.Path('tests/a.in')


def test_blocks_name_nested_and_flat_paths_alike():
    assert [(b.path, b.start_line) for b in testplan_edit.blocks(PLAN)] == [
        ('main', 3),
        ('main/large', 6),
        ('main/large', 13),
    ]


def test_insert_at_top_level_appends_and_sets_a_comment_apart():
    assert (
        testplan_edit.insert_in_scope('gen 1\n', None, ['gen 2'], 'Found by: x')
        == 'gen 1\n\n# Found by: x\ngen 2\n'
    )
    assert testplan_edit.insert_in_scope('gen 1', None, ['gen 2']) == 'gen 1\ngen 2\n'
    assert testplan_edit.insert_in_scope('', None, ['gen 2'], 'x') == '# x\ngen 2\n'


def test_insert_into_a_block_goes_before_its_closing_brace_with_its_indent():
    after = testplan_edit.insert_in_scope(PLAN, 'main', ['gen 9'], 'note')
    assert after == PLAN.replace(
        '    gen 3\n  }\n}\n', '    gen 3\n  }\n    # note\n    gen 9\n}\n'
    )


def test_insert_goes_into_the_last_block_with_that_path():
    after = testplan_edit.insert_in_scope(PLAN, 'main/large', ['gen 9'])
    assert after == PLAN.replace('  gen 4\n}\n', '  gen 4\n  gen 9\n}\n')


def test_insert_into_a_missing_scope_opens_a_block_at_the_end():
    after = testplan_edit.insert_in_scope('gen 1\n', 'other', ['gen 9', 'gen 10'])
    assert after == 'gen 1\n\n@testgroup other {\n  gen 9\n  gen 10\n}\n'


def test_insert_into_an_empty_block():
    after = testplan_edit.insert_in_scope('@testgroup a {\n}\n', 'a', ['gen 1'])
    assert after == '@testgroup a {\n  gen 1\n}\n'


def test_replace_keeps_indentation_and_the_comments_above():
    after = testplan_edit.replace_statement(PLAN, 4, ['@copy tests/x.in'])
    assert after == PLAN.replace('    gen 2\n', '    @copy tests/x.in\n')


def test_replace_a_multiline_input():
    after = testplan_edit.replace_statement(PLAN, 10, ['@copy tests/x.in'])
    assert after == PLAN.replace('@input {\na\n}\n', '@copy tests/x.in\n')


def test_replace_needs_a_statement_there():
    with pytest.raises(ValueError):
        testplan_edit.replace_statement(PLAN, 2, ['gen 0'])


def test_remove_drops_the_comment_lines_right_above():
    plan = 'gen 1\n\n# found by stress\ngen 2\ngen 3\n'
    assert testplan_edit.remove_statements(plan, [4]) == 'gen 1\n\ngen 3\n'
