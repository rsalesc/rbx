"""Unit tests for the generic e2e assertion helpers."""

import pathlib
import zipfile

import pytest

from tests.e2e.assertions import (
    AssertionContext,
    check_file_contains,
    check_files_absent,
    check_files_exist,
    check_stderr_contains,
    check_stdout_contains,
    check_stdout_matches,
    check_zip_contains,
    check_zip_not_contains,
)
from tests.e2e.spec import ZipMatcher


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


# ---------------------------------------------------------------------------
# zip_contains / zip_not_contains
# ---------------------------------------------------------------------------


def _build_zip(
    path: pathlib.Path, entries: list[str], contents: str = 'x'
) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as zf:
        for entry in entries:
            zf.writestr(entry, contents)
    return path


def test_zip_contains_literal_entries_pass(tmp_path):
    _build_zip(
        tmp_path / 'pkg.zip',
        ['description.xml', 'limits/cc', 'limits/py3'],
    )
    check_zip_contains(
        _ctx(tmp_path),
        ZipMatcher(path='pkg.zip', entries=['description.xml', 'limits/cc']),
    )


def test_zip_contains_glob_entries_pass(tmp_path):
    _build_zip(
        tmp_path / 'pkg.zip',
        ['description.xml', 'limits/cc', 'limits/py3', 'input/001'],
    )
    check_zip_contains(
        _ctx(tmp_path),
        ZipMatcher(path='pkg.zip', entries=['*.xml', 'limits/*']),
    )


def test_zip_contains_path_glob_pass(tmp_path):
    _build_zip(tmp_path / 'build' / 'boca' / 'pkg-name.zip', ['description.xml'])
    check_zip_contains(
        _ctx(tmp_path),
        ZipMatcher(path='build/boca/*.zip', entries=['description.xml']),
    )


def test_zip_contains_zip_not_found_raises(tmp_path):
    with pytest.raises(AssertionError, match='no zip matched'):
        check_zip_contains(
            _ctx(tmp_path),
            ZipMatcher(path='build/boca/*.zip', entries=['description.xml']),
        )


def test_zip_contains_missing_entry_raises(tmp_path):
    _build_zip(tmp_path / 'pkg.zip', ['description.xml'])
    with pytest.raises(AssertionError, match='missing entry'):
        check_zip_contains(
            _ctx(tmp_path),
            ZipMatcher(path='pkg.zip', entries=['description.xml', 'missing.txt']),
        )


def test_zip_contains_glob_no_match_raises(tmp_path):
    _build_zip(tmp_path / 'pkg.zip', ['description.xml'])
    with pytest.raises(AssertionError, match='missing entry'):
        check_zip_contains(
            _ctx(tmp_path),
            ZipMatcher(path='pkg.zip', entries=['limits/*']),
        )


def test_zip_not_contains_pass(tmp_path):
    _build_zip(tmp_path / 'pkg.zip', ['description.xml'])
    check_zip_not_contains(
        _ctx(tmp_path),
        ZipMatcher(path='pkg.zip', entries=['secrets/*', 'private.key']),
    )


def test_zip_not_contains_unexpected_entry_raises(tmp_path):
    _build_zip(tmp_path / 'pkg.zip', ['description.xml', 'secrets/api.key'])
    with pytest.raises(AssertionError, match='unexpected entry'):
        check_zip_not_contains(
            _ctx(tmp_path),
            ZipMatcher(path='pkg.zip', entries=['secrets/*']),
        )


def test_zip_not_contains_missing_zip_raises(tmp_path):
    # Decision: if the user wrote a path expecting a zip and it does not
    # exist, that's far more likely to be a typo than a deliberate
    # "nothing to assert against" — so we surface it as an error rather
    # than silently no-op.
    with pytest.raises(AssertionError, match='no zip matched'):
        check_zip_not_contains(
            _ctx(tmp_path),
            ZipMatcher(path='build/boca/*.zip', entries=['secrets/*']),
        )
