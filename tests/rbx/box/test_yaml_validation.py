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


def test_locate_missing_key_falls_back_to_parent():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - name: alice\n  - name: bob\n'
    root = _parse(text)

    # 'absent' is missing from items[1]; walk should stop at items[1]
    line, col, span = _locate(('items', 1, 'absent'), root)

    assert line == 3  # items[1] starts on line 3
    assert col == 5  # column of 'name' key inside items[1]
    # span should still be the last walked key length (== len('name'))
    assert span == len('name')


def test_locate_out_of_range_index_falls_back():
    from rbx.box.yaml_validation import _locate

    text = 'items:\n  - a\n  - b\n'
    root = _parse(text)

    line, col, span = _locate(('items', 99), root)

    # falls back to the 'items' key location
    assert line == 1
    assert col == 1
    assert span == len('items')


def test_locate_skips_pydantic_internal_segments():
    from rbx.box.yaml_validation import _locate

    text = 'step:\n  type: foo\n  arg: bar\n'
    root = _parse(text)

    # 'union_tag' is not a real key; walker should skip and resolve 'type'
    line, col, span = _locate(('step', 'union_tag', 'type'), root)

    assert line == 2
    assert col == 3
    assert span == len('type')


def test_locate_empty_loc():
    from rbx.box.yaml_validation import _locate

    text = 'name: x\n'
    root = _parse(text)

    line, col, span = _locate((), root)

    assert (line, col, span) == (1, 1, 1)
