"""Unit tests for rbx.box.yaml_validation."""

from __future__ import annotations

import ruyaml


def _parse(text: str) -> ruyaml.comments.CommentedBase:
    """Parse YAML text with ruyaml in round-trip mode for tests."""
    return ruyaml.YAML(typ='rt').load(text)


def test_locate_top_level_scalar():
    from rbx.box.yaml_validation import _locate

    text = 'name: my-problem\ntimeLimit: 1000\n'
    root = _parse(text)

    line, col, span = _locate(('timeLimit',), root)

    assert line == 2  # 1-based line of `timeLimit:`
    assert col == 1  # 1-based column of `t` in `timeLimit`
    assert span == len('timeLimit')


def test_locate_nested_map():
    from rbx.box.yaml_validation import _locate

    text = 'a:\n  b:\n    c: hello\n'
    root = _parse(text)

    line, col, span = _locate(('a', 'b', 'c'), root)

    assert line == 3
    assert col == 5
    assert span == len('c')
