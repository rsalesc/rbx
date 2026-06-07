import pathlib

import pytest

from rbx.box.packaging import flattening


def _p(*parts: str) -> pathlib.Path:
    return pathlib.Path(*parts)


def _assert_unique(names: dict) -> None:
    flat = list(names.values())
    assert len(set(flat)) == len(flat), f'duplicate flat names: {flat}'


def test_unique_basenames_keep_bare_name():
    names = flattening.assign_flat_names(
        [_p('check.cpp'), _p('lib', 'util.h'), _p('gens', 'gen.cpp')]
    )
    assert names == {
        _p('check.cpp'): 'check.cpp',
        _p('lib', 'util.h'): 'util.h',
        _p('gens', 'gen.cpp'): 'gen.cpp',
    }


def test_basename_collision_uses_double_underscore_path():
    names = flattening.assign_flat_names(
        [_p('gens', 'a', 'gen.cpp'), _p('gens', 'b', 'gen.cpp')]
    )
    assert names == {
        _p('gens', 'a', 'gen.cpp'): 'gens__a__gen.cpp',
        _p('gens', 'b', 'gen.cpp'): 'gens__b__gen.cpp',
    }


def test_reserved_names_are_honored_and_force_others_to_mangle():
    names = flattening.assign_flat_names(
        [_p('checker.cpp'), _p('sub', 'check.cpp')],
        reserved={_p('checker.cpp'): 'check.cpp'},
    )
    assert names[_p('checker.cpp')] == 'check.cpp'
    assert names[_p('sub', 'check.cpp')] == 'sub__check.cpp'


def test_enforce_stem_unique_mangles_same_stem_diff_ext():
    names = flattening.assign_flat_names(
        [_p('a', 'gen.cpp'), _p('b', 'gen.cc')], enforce_stem_unique=True
    )
    assert names[_p('a', 'gen.cpp')] == 'a__gen.cpp'
    assert names[_p('b', 'gen.cc')] == 'b__gen.cc'


def test_residual_mangle_collision_gets_counter():
    names = flattening.assign_flat_names([_p('a', 'b__c.h'), _p('a__b', 'c.h')])
    assert sorted(names.values()) == ['a__b__c.h', 'a__b__c__1.h']
    _assert_unique(names)


def test_sanitization_induced_collision_gets_counter():
    # 'a-b/c.h' and 'a_b/c.h' both sanitize+mangle to 'a_b__c.h'.
    names = flattening.assign_flat_names([_p('a-b', 'c.h'), _p('a_b', 'c.h')])
    assert sorted(names.values()) == ['a_b__c.h', 'a_b__c__1.h']
    _assert_unique(names)


def test_assignment_is_order_independent():
    a = flattening.assign_flat_names([_p('x', 'g.cpp'), _p('y', 'g.cpp')])
    b = flattening.assign_flat_names([_p('y', 'g.cpp'), _p('x', 'g.cpp')])
    assert a == b


def test_duplicate_reserved_names_raise():
    with pytest.raises(ValueError, match='mutually distinct'):
        flattening.assign_flat_names(
            [_p('a.cpp'), _p('b.cpp')],
            reserved={_p('a.cpp'): 'same.cpp', _p('b.cpp'): 'same.cpp'},
        )


def test_flatnamespace_materialize_writes_every_file(tmp_path):
    ns = flattening.FlatNamespace(
        files=[
            flattening.FlatFile('check.cpp', _p('check.cpp'), b'CHK', True, None),
            flattening.FlatFile('lib.h', _p('sub', 'lib.h'), b'LIB', False, None),
        ],
        name_of={_p('check.cpp'): 'check.cpp', _p('sub', 'lib.h'): 'lib.h'},
    )
    ns.materialize(tmp_path)
    assert (tmp_path / 'check.cpp').read_bytes() == b'CHK'
    assert (tmp_path / 'lib.h').read_bytes() == b'LIB'
    assert [f.flat_name for f in ns.dep_files()] == ['lib.h']
    assert [f.flat_name for f in ns.root_files()] == ['check.cpp']
