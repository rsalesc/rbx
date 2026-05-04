"""Unit tests for the generic e2e assertion helpers."""

import pathlib

import pytest

from tests.e2e.assertions import (
    AssertionContext,
    check_file_contains,
    check_files_absent,
    check_files_exist,
    check_stderr_contains,
    check_stdout_contains,
    check_stdout_matches,
)


def _ctx(
    tmp_path: pathlib.Path, stdout: str = '', stderr: str = ''
) -> AssertionContext:
    return AssertionContext(package_root=tmp_path, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# stdout_contains
# ---------------------------------------------------------------------------


def test_stdout_contains_single_string_pass(tmp_path):
    check_stdout_contains(_ctx(tmp_path, stdout='hello world'), 'hello')


def test_stdout_contains_single_string_fail(tmp_path):
    with pytest.raises(AssertionError, match='missing'):
        check_stdout_contains(_ctx(tmp_path, stdout='hello world'), 'goodbye')


def test_stdout_contains_list_pass(tmp_path):
    check_stdout_contains(_ctx(tmp_path, stdout='alpha beta gamma'), ['alpha', 'gamma'])


def test_stdout_contains_list_fail_reports_missing_needle(tmp_path):
    with pytest.raises(AssertionError, match="'delta'"):
        check_stdout_contains(
            _ctx(tmp_path, stdout='alpha beta gamma'), ['alpha', 'delta']
        )


# ---------------------------------------------------------------------------
# stderr_contains
# ---------------------------------------------------------------------------


def test_stderr_contains_single_pass(tmp_path):
    check_stderr_contains(_ctx(tmp_path, stderr='warning: oops'), 'warning')


def test_stderr_contains_list_fail(tmp_path):
    with pytest.raises(AssertionError, match='stderr missing'):
        check_stderr_contains(_ctx(tmp_path, stderr='only this'), ['only', 'missing'])


# ---------------------------------------------------------------------------
# stdout_matches
# ---------------------------------------------------------------------------


def test_stdout_matches_regex_pass(tmp_path):
    check_stdout_matches(_ctx(tmp_path, stdout='build OK in 2.5s'), r'build OK in \d')


def test_stdout_matches_regex_fail(tmp_path):
    with pytest.raises(AssertionError, match='did not match'):
        check_stdout_matches(_ctx(tmp_path, stdout='nope'), r'build OK in \d')


# ---------------------------------------------------------------------------
# files_exist
# ---------------------------------------------------------------------------


def test_files_exist_literal_pass(tmp_path):
    (tmp_path / 'foo.txt').write_text('x')
    check_files_exist(_ctx(tmp_path), ['foo.txt'])


def test_files_exist_glob_pass(tmp_path):
    sub = tmp_path / 'build' / 'tests'
    sub.mkdir(parents=True)
    (sub / '001.in').write_text('1')
    (sub / '002.in').write_text('2')
    check_files_exist(_ctx(tmp_path), ['build/tests/*.in'])


def test_files_exist_no_match_raises(tmp_path):
    with pytest.raises(AssertionError, match='no file matched'):
        check_files_exist(_ctx(tmp_path), ['build/missing/*.in'])


def test_files_exist_literal_missing_raises(tmp_path):
    with pytest.raises(AssertionError, match="'absent.txt'"):
        check_files_exist(_ctx(tmp_path), ['absent.txt'])


# ---------------------------------------------------------------------------
# files_absent
# ---------------------------------------------------------------------------


def test_files_absent_pass(tmp_path):
    check_files_absent(_ctx(tmp_path), ['nope/*.txt', 'absent.bin'])


def test_files_absent_fail_when_match_exists(tmp_path):
    (tmp_path / 'leak.txt').write_text('oops')
    with pytest.raises(AssertionError, match='unexpected file matched'):
        check_files_absent(_ctx(tmp_path), ['leak.txt'])


def test_files_absent_fail_with_glob(tmp_path):
    d = tmp_path / 'build'
    d.mkdir()
    (d / 'a.in').write_text('1')
    with pytest.raises(AssertionError, match="'build/\\*.in'"):
        check_files_absent(_ctx(tmp_path), ['build/*.in'])


# ---------------------------------------------------------------------------
# file_contains
# ---------------------------------------------------------------------------


def test_file_contains_substring_pass(tmp_path):
    (tmp_path / 'a.txt').write_text('hello world\n')
    check_file_contains(_ctx(tmp_path), {'a.txt': 'hello'})


def test_file_contains_substring_fail(tmp_path):
    (tmp_path / 'a.txt').write_text('hello world\n')
    with pytest.raises(AssertionError, match='missing'):
        check_file_contains(_ctx(tmp_path), {'a.txt': 'goodbye'})


def test_file_contains_regex_pass(tmp_path):
    (tmp_path / 'b.txt').write_text('build OK in 1.234s\n')
    check_file_contains(_ctx(tmp_path), {'b.txt': r'/build OK in \d+\.\d+s/'})


def test_file_contains_regex_fail(tmp_path):
    (tmp_path / 'b.txt').write_text('nope\n')
    with pytest.raises(AssertionError, match='no match'):
        check_file_contains(_ctx(tmp_path), {'b.txt': r'/build OK in \d+/'})


def test_file_contains_double_slash_is_literal_not_empty_regex(tmp_path):
    # ``//`` has length 2 and so must be treated as a literal substring,
    # not as an empty regex (which would silently match anything).
    (tmp_path / 'a.txt').write_text('no slashes here\n')
    with pytest.raises(AssertionError, match='missing'):
        check_file_contains(_ctx(tmp_path), {'a.txt': '//'})

    (tmp_path / 'b.txt').write_text('a // b\n')
    check_file_contains(_ctx(tmp_path), {'b.txt': '//'})


def test_file_contains_regex_precedence_over_literal(tmp_path):
    # ``/x.+y/`` is interpreted as the regex ``x.+y``; ``x123y`` matches
    # the regex but not the literal value (which contains slashes).
    (tmp_path / 'c.txt').write_text('prefix x123y suffix\n')
    check_file_contains(_ctx(tmp_path), {'c.txt': '/x.+y/'})


# ---------------------------------------------------------------------------
# _glob magic-character detection
# ---------------------------------------------------------------------------


def test_files_exist_literal_with_unmatched_bracket_does_not_glob(tmp_path):
    # A stray ``[`` with no matching ``]`` must be treated as a literal
    # path component, not handed to ``Path.glob`` (which would either
    # raise or silently match nothing).
    (tmp_path / 'foo[bar').write_text('x')
    check_files_exist(_ctx(tmp_path), ['foo[bar'])


def test_files_exist_bracket_charclass_globs(tmp_path):
    (tmp_path / 'a1.txt').write_text('x')
    (tmp_path / 'a2.txt').write_text('y')
    check_files_exist(_ctx(tmp_path), ['a[12].txt'])


def test_files_absent_literal_with_unmatched_bracket(tmp_path):
    # No file present; literal lookup must return empty without raising.
    check_files_absent(_ctx(tmp_path), ['ghost[name'])
