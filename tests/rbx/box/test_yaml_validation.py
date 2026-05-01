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


def test_locate_list_index():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - a\n  - b\n  - c\n'
    root = _parse(text)

    line, col, span = _locate(('items', 2), root)

    assert line == 4  # third item is on line 4
    assert col == 5  # column of the scalar after "- "


def test_locate_list_of_maps():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - name: alice\n  - name: bob\n  - name: carol\n'
    root = _parse(text)

    line, col, span = _locate(('items', 2, 'name'), root)

    assert line == 4
    assert col == 5
    assert span == len('name')
