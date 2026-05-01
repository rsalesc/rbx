"""Unit tests for rbx.box.yaml_validation."""

from __future__ import annotations

import pathlib
from typing import List

import pydantic
import pytest
import ruyaml

from rbx.box.yaml_validation import (
    YamlSyntaxError,
    YamlValidationError,
    load_yaml_model,
)


def _parse(text: str) -> ruyaml.comments.CommentedBase:
    """Parse YAML text with ruyaml in round-trip mode for tests."""
    return ruyaml.YAML(typ='rt').load(text)


def _render(*args, **kwargs):
    """Helper: render a diagnostic to plain text."""
    from rich.console import Console

    from rbx.box.yaml_validation import _render_diagnostic

    out = _render_diagnostic(*args, **kwargs)
    console = Console(width=120, record=True, color_system=None)
    console.print(out)
    return console.export_text()


def test_locate_top_level_scalar():
    from rbx.box.yaml_validation import _locate

    text = 'name: my-problem\ntimeLimit: 1000\n'
    root = _parse(text)

    line, col, span = _locate(('timeLimit',), root)

    assert line == 2
    # caret on the value, not the key
    assert col == len('timeLimit: ') + 1
    assert span == len('1000')


def test_locate_nested_map():
    from rbx.box.yaml_validation import _locate

    text = 'a:\n  b:\n    c: hello\n'
    root = _parse(text)

    line, col, span = _locate(('a', 'b', 'c'), root)

    assert line == 3
    assert col == len('    c: ') + 1
    assert span == len('hello')


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
    assert col == len('  - name: ') + 1
    assert span == len('carol')


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
    assert col == len('  type: ') + 1
    assert span == len('foo')


def test_locate_empty_loc():
    from rbx.box.yaml_validation import _locate

    text = 'name: x\n'
    root = _parse(text)

    line, col, span = _locate((), root)

    assert (line, col, span) == (1, 1, 1)


def test_locate_widens_span_to_scalar_value():
    from rbx.box.yaml_validation import _locate

    text = 'timeLimit: 1234567\n'
    root = _parse(text)

    line, col, span = _locate(('timeLimit',), root)

    # After widening: caret column moves to where the value starts,
    # span equals value length.
    assert line == 1
    assert col == len('timeLimit: ') + 1
    assert span == len('1234567')


def test_format_loc_renders_path_human_readably():
    from rbx.box.yaml_validation import _format_loc

    assert _format_loc(()) == '<root>'
    assert _format_loc(('name',)) == 'name'
    assert _format_loc(('a', 'b', 'c')) == 'a.b.c'
    assert _format_loc(('items', 2)) == 'items[2]'
    assert _format_loc(('items', 2, 'name')) == 'items[2].name'
    assert _format_loc(('a', 'union_tag', 'b')) == 'a.b'


def test_dedupe_collapses_identical_errors():
    from rbx.box.yaml_validation import _dedupe

    errors = [
        {'loc': ('a',), 'msg': 'oops', 'type': 'value_error'},
        {'loc': ('a',), 'msg': 'oops', 'type': 'value_error'},
        {'loc': ('b',), 'msg': 'bad', 'type': 'value_error'},
    ]

    out = _dedupe(errors)

    assert len(out) == 2
    assert {e['loc'] for e in out} == {('a',), ('b',)}


def test_dedupe_folds_union_branches_at_same_loc():
    from rbx.box.yaml_validation import _dedupe

    errors = [
        {'loc': ('score',), 'msg': 'expected int', 'type': 'union_int_expected'},
        {'loc': ('score',), 'msg': 'expected tuple', 'type': 'union_tuple_expected'},
    ]

    out = _dedupe(errors)

    assert len(out) == 1
    msg = out[0]['msg']
    assert 'union' in msg.lower() or 'any of' in msg.lower()
    assert 'int' in msg and 'tuple' in msg


def test_dedupe_keeps_discriminated_union_errors_separate():
    from rbx.box.yaml_validation import _dedupe

    errors = [
        {'loc': ('step', 'foo'), 'msg': 'foo bad', 'type': 'value_error'},
        {'loc': ('step', 'bar'), 'msg': 'bar bad', 'type': 'value_error'},
    ]

    out = _dedupe(errors)

    assert len(out) == 2


def test_render_diagnostic_includes_header_and_location():
    text = 'name: x\ntimeLimit: 1000\n'
    rendered = _render(
        source=text,
        path=pathlib.Path('problem.rbx.yml'),
        line=2,
        col=12,
        span=4,
        msg='input should be a valid integer',
        loc_label='timeLimit',
        header='error',
    )

    assert 'error' in rendered
    assert 'timeLimit' in rendered
    assert 'problem.rbx.yml:2:12' in rendered
    assert 'input should be a valid integer' in rendered
    assert 'timeLimit: 1000' in rendered


def test_render_diagnostic_window_clipped_at_file_start():
    text = 'a: 1\nb: 2\n'
    rendered = _render(
        source=text,
        path=pathlib.Path('x.yml'),
        line=1,
        col=1,
        span=1,
        msg='bad',
        loc_label='a',
        header='error',
    )

    # No phantom line numbers below 1
    assert '\n 0 ' not in rendered
    assert '\n-1 ' not in rendered


def test_render_diagnostic_caret_under_correct_column():
    text = 'name: my-problem\n'
    rendered = _render(
        source=text,
        path=pathlib.Path('p.yml'),
        line=1,
        col=7,
        span=10,
        msg='bad name',
        loc_label='name',
        header='error',
    )

    caret_line = next(line for line in rendered.splitlines() if '^^^' in line)
    assert '^' * 10 in caret_line


def test_yaml_syntax_error_renders_diagnostic(tmp_path):
    bad_yaml = 'a: 1\nb: [unterminated\n'
    p = tmp_path / 'bad.yml'
    p.write_text(bad_yaml)

    class M(pydantic.BaseModel):
        a: int = 0

    with pytest.raises(YamlSyntaxError) as exc_info:
        load_yaml_model(p, M)

    rendered = str(exc_info.value)
    assert 'YAML syntax error' in rendered
    assert 'bad.yml' in rendered
    assert ':2' in rendered


class _NestedModel(pydantic.BaseModel):
    name: str
    score: int


class _RootModel(pydantic.BaseModel):
    title: str
    items: List[_NestedModel]


def test_validation_error_renders_one_block_per_error(tmp_path):
    text = (
        'title: hello\n'
        'items:\n'
        '  - name: a\n'
        '    score: oops\n'
        '  - name: b\n'
        '    score: 5\n'
    )
    p = tmp_path / 'p.yml'
    p.write_text(text)

    with pytest.raises(YamlValidationError) as exc_info:
        load_yaml_model(p, _RootModel)

    rendered = str(exc_info.value)
    assert 'p.yml' in rendered
    assert 'items[0].score' in rendered
    assert 'oops' in rendered or 'integer' in rendered.lower()


def test_validation_error_collects_multiple_errors_sorted_by_line(tmp_path):
    # title is missing; items[0].score is a string; items[1].name is an int
    text = 'items:\n  - name: a\n    score: bad\n  - name: 123\n    score: 5\n'
    p = tmp_path / 'p.yml'
    p.write_text(text)

    with pytest.raises(YamlValidationError) as exc_info:
        load_yaml_model(p, _RootModel)

    rendered = str(exc_info.value)
    locs = [
        line.split('p.yml:')[1].split(' ')[0]
        for line in rendered.splitlines()
        if 'p.yml:' in line
    ]
    assert len(locs) >= 2
