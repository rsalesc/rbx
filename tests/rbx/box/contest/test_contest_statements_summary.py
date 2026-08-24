"""Tests for the contest statement build summary heading."""

from rbx.box.contest import statements as contest_statements
from rbx.box.statements.schema import StatementKind


def test_built_rule_title_without_variant():
    assert (
        contest_statements.built_rule_title(StatementKind.STATEMENTS, None)
        == 'Built statements'
    )


def test_built_rule_title_with_variant():
    assert (
        contest_statements.built_rule_title(StatementKind.STATEMENTS, 'div2')
        == 'Built statements (variant: div2)'
    )


def test_built_rule_title_names_the_kind():
    assert (
        contest_statements.built_rule_title(StatementKind.TUTORIALS, 'div1')
        == 'Built tutorials (variant: div1)'
    )
