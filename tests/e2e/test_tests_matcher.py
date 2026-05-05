"""Unit tests for the ``tests:`` build-report matcher.

These tests construct fake ``build/tests/`` directory layouts in tmpdirs to
exercise :func:`tests.e2e.assertions.check_tests` without paying for a
full ``rbx build`` run.
"""

import pathlib

import pytest

from tests.e2e.assertions import AssertionContext, check_tests
from tests.e2e.spec import TestsMatcher


def _ctx(root: pathlib.Path) -> AssertionContext:
    return AssertionContext(package_root=root, stdout='', stderr='')


def _make_tests(root: pathlib.Path, layout: dict) -> None:
    """Materialize a fake ``build/tests/`` directory.

    ``layout`` maps group name -> list of input filenames (the ``.in``
    files). The function creates each file as an empty regular file plus
    the parent directory.
    """
    tests_root = root / 'build' / 'tests'
    tests_root.mkdir(parents=True, exist_ok=True)
    for group, names in layout.items():
        gdir = tests_root / group
        gdir.mkdir(parents=True, exist_ok=True)
        for name in names:
            (gdir / name).write_text('')


def test_count_pass(tmp_path):
    _make_tests(
        tmp_path,
        {'main': ['1-gen-000.in', '1-gen-001.in', '1-gen-002.in']},
    )
    check_tests(_ctx(tmp_path), TestsMatcher(count=3))


def test_count_mismatch_raises(tmp_path):
    _make_tests(tmp_path, {'main': ['a.in', 'b.in']})
    with pytest.raises(AssertionError, match=r'tests\.count: expected 3, got 2'):
        check_tests(_ctx(tmp_path), TestsMatcher(count=3))


def test_groups_pass(tmp_path):
    _make_tests(
        tmp_path,
        {
            'samples': ['s0.in', 's1.in', 's2.in'],
            'main': ['m0.in', 'm1.in'],
        },
    )
    check_tests(
        _ctx(tmp_path),
        TestsMatcher(groups={'samples': 3, 'main': 2}),
    )


def test_groups_wrong_count_raises(tmp_path):
    _make_tests(tmp_path, {'main': ['a.in', 'b.in']})
    with pytest.raises(AssertionError, match=r'tests\.groups\.main: expected 5, got 2'):
        check_tests(_ctx(tmp_path), TestsMatcher(groups={'main': 5}))


def test_groups_unknown_group_raises(tmp_path):
    _make_tests(tmp_path, {'main': ['a.in']})
    with pytest.raises(
        AssertionError,
        match=r'tests\.groups\.samples: group not found.*main',
    ):
        check_tests(_ctx(tmp_path), TestsMatcher(groups={'samples': 1}))


def test_exist_pass(tmp_path):
    _make_tests(tmp_path, {'main': ['1-gen-000.in']})
    check_tests(
        _ctx(tmp_path),
        TestsMatcher(exist=['main/1-gen-000.in']),
    )


def test_exist_missing_raises(tmp_path):
    _make_tests(tmp_path, {'main': ['1-gen-000.in']})
    with pytest.raises(
        AssertionError, match=r"tests\.exist: missing 'main/1-gen-999\.in'"
    ):
        check_tests(
            _ctx(tmp_path),
            TestsMatcher(exist=['main/1-gen-999.in']),
        )


def test_missing_build_tests_dir_raises(tmp_path):
    with pytest.raises(AssertionError, match=r'build/tests/ not found'):
        check_tests(_ctx(tmp_path), TestsMatcher(count=0))


def test_count_zero_pass_when_dir_exists(tmp_path):
    (tmp_path / 'build' / 'tests').mkdir(parents=True)
    check_tests(_ctx(tmp_path), TestsMatcher(count=0))


def test_all_valid_true_raises_not_implemented(tmp_path):
    _make_tests(tmp_path, {'main': ['a.in']})
    with pytest.raises(AssertionError, match=r'all_valid'):
        check_tests(_ctx(tmp_path), TestsMatcher(all_valid=True))


def test_all_valid_false_is_noop(tmp_path):
    _make_tests(tmp_path, {'main': ['a.in']})
    # Explicit False is also a no-op: not enforced either way.
    check_tests(_ctx(tmp_path), TestsMatcher(all_valid=False))


def test_only_in_files_counted(tmp_path):
    """``.out``/``.eval``/``.log`` siblings must not inflate counts."""
    _make_tests(tmp_path, {'main': ['a.in', 'b.in']})
    main = tmp_path / 'build' / 'tests' / 'main'
    (main / 'a.out').write_text('')
    (main / 'a.eval').write_text('')
    (main / 'a.log').write_text('')
    check_tests(_ctx(tmp_path), TestsMatcher(count=2, groups={'main': 2}))
