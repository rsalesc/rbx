import json
import subprocess
import sys
import time

import pytest

from rbx.box import git_utils


class TestLsRemoteTags:
    def test_parses_git_ls_remote_output(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd == ['git']:
                return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
            assert cmd[:3] == ['git', 'ls-remote', '--tags']
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='aaaaaaaa\trefs/tags/1.0.0\n'
                'bbbbbbbb\trefs/tags/1.0.1\n'
                'cccccccc\trefs/tags/2.0.0^{}\n',
                stderr='',
            )

        monkeypatch.setattr(subprocess, 'run', fake_run)

        tags = git_utils.ls_remote_tags('https://example.com/repo.git')
        assert tags == ['1.0.0', '1.0.1', '2.0.0']


class TestSemverFilteringAndLatest:
    def test_ls_version_remote_tags_filters_invalid(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd == ['git']:
                return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='x\trefs/tags/1.0.0\n'
                'y\trefs/tags/not-a-version\n'
                'z\trefs/tags/2.0.0\n',
                stderr='',
            )

        monkeypatch.setattr(subprocess, 'run', fake_run)

        tags = git_utils.ls_version_remote_tags('any')
        assert tags == ['1.0.0', '2.0.0']

    def test_latest_remote_tag_basic_and_ranges(self, monkeypatch):
        monkeypatch.setattr(
            git_utils,
            'ls_version_remote_tags',
            lambda _uri: ['1.0.0', '1.2.0', '2.0.0'],
        )

        assert git_utils.latest_remote_tag('x') == '2.0.0'
        assert git_utils.latest_remote_tag('x', before='1.2.0') == '1.2.0'
        assert git_utils.latest_remote_tag('x', after='1.1.0') == '2.0.0'
        assert (
            git_utils.latest_remote_tag('x', before='1.2.0', after='1.0.0') == '1.2.0'
        )

    def test_latest_remote_tag_no_valid_tags_raises(self, monkeypatch):
        monkeypatch.setattr(git_utils, 'ls_version_remote_tags', lambda _uri: [])
        with pytest.raises(ValueError):
            git_utils.latest_remote_tag('x')


class TestHasRemoteTag:
    def test_true_and_false(self, monkeypatch):
        monkeypatch.setattr(
            git_utils, 'ls_remote_tags', lambda _uri: ['1.0.0', '1.1.0']
        )
        assert git_utils.has_remote_tag('x', '1.1.0') is True
        assert git_utils.has_remote_tag('x', '2.0.0') is False


def _make_repo(monkeypatch, tmp_path, *tracked_symlinks: str):
    """Turn `tmp_path` into a repo root whose listing yields `tracked_symlinks`."""
    (tmp_path / '.git').mkdir()
    monkeypatch.setattr(git_utils.utils, 'command_exists', lambda cmd: True)

    stdout = ''.join(f'120000 {"0" * 40} 0\t{path}\n' for path in tracked_symlinks)

    def fake_run(cmd, cwd, check, capture_output, text):
        assert cmd == ['git', 'ls-files', '-s']
        assert cwd == tmp_path
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr='')

    monkeypatch.setattr(subprocess, 'run', fake_run)


class TestCheckSymlinks:
    def test_git_not_installed(self, monkeypatch, tmp_path):
        (tmp_path / '.git').mkdir()
        monkeypatch.setattr(git_utils.utils, 'command_exists', lambda cmd: False)
        assert git_utils.check_symlinks(tmp_path) is True

    def test_not_a_repo(self, monkeypatch, tmp_path):
        monkeypatch.setattr(git_utils.utils, 'command_exists', lambda cmd: True)
        assert git_utils.check_symlinks(tmp_path) is True

    def test_valid_symlinks(self, monkeypatch, tmp_path):
        _make_repo(monkeypatch, tmp_path, 'link_to_file')

        # Create the file and the symlink
        (tmp_path / 'target').touch()
        (tmp_path / 'link_to_file').symlink_to('target')

        assert git_utils.check_symlinks(tmp_path) is True

    def test_broken_symlinks_regular_file(self, monkeypatch, tmp_path):
        _make_repo(monkeypatch, tmp_path, 'should_be_link')

        # Create a regular file instead of a symlink
        (tmp_path / 'should_be_link').touch()

        assert git_utils.check_symlinks(tmp_path) is False

    def test_missing_symlink(self, monkeypatch, tmp_path):
        _make_repo(monkeypatch, tmp_path, 'missing_link')

        # Do not create the file

        assert git_utils.check_symlinks(tmp_path) is True

    def test_finds_repo_root_from_a_subdirectory(self, monkeypatch, tmp_path):
        _make_repo(monkeypatch, tmp_path, 'should_be_link')
        (tmp_path / 'should_be_link').touch()
        nested = tmp_path / 'a' / 'b'
        nested.mkdir(parents=True)

        assert git_utils.check_symlinks(nested) is False

    def test_does_not_import_gitpython(self):
        # GitPython costs ~80ms to import and this check runs before every
        # command dispatch, so it must not pull the library in.
        output = subprocess.check_output(
            [
                sys.executable,
                '-c',
                'import pathlib, sys; from rbx.box import git_utils; '
                'git_utils.check_symlinks(pathlib.Path()); '
                "print('git' in sys.modules)",
            ],
            text=True,
        )
        assert output.strip() == 'False'


class TestCheckSymlinksCached:
    def test_caches_good_verdict(self, monkeypatch, tmp_path):
        (tmp_path / '.git').mkdir()
        monkeypatch.setattr(
            git_utils, '_symlink_check_cache_path', lambda: tmp_path / 'cache.json'
        )

        calls = []
        monkeypatch.setattr(
            git_utils, 'check_symlinks', lambda root: calls.append(root) or True
        )

        assert git_utils.check_symlinks_cached(tmp_path) is True
        assert git_utils.check_symlinks_cached(tmp_path) is True
        assert calls == [tmp_path]

    def test_expired_entry_is_rechecked(self, monkeypatch, tmp_path):
        (tmp_path / '.git').mkdir()
        cache_path = tmp_path / 'cache.json'
        monkeypatch.setattr(git_utils, '_symlink_check_cache_path', lambda: cache_path)
        cache_path.write_text(
            json.dumps(
                {str(tmp_path): time.time() - git_utils.SYMLINK_CHECK_TTL_SECONDS - 1}
            )
        )

        calls = []
        monkeypatch.setattr(
            git_utils, 'check_symlinks', lambda root: calls.append(root) or True
        )

        assert git_utils.check_symlinks_cached(tmp_path) is True
        assert calls == [tmp_path]

    def test_bad_verdict_is_not_cached(self, monkeypatch, tmp_path):
        (tmp_path / '.git').mkdir()
        monkeypatch.setattr(
            git_utils, '_symlink_check_cache_path', lambda: tmp_path / 'cache.json'
        )

        calls = []
        monkeypatch.setattr(
            git_utils, 'check_symlinks', lambda root: calls.append(root) or False
        )

        assert git_utils.check_symlinks_cached(tmp_path) is False
        assert git_utils.check_symlinks_cached(tmp_path) is False
        assert calls == [tmp_path, tmp_path]

    def test_not_a_repo_skips_the_check_entirely(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            git_utils, '_symlink_check_cache_path', lambda: tmp_path / 'cache.json'
        )

        def _boom(root):
            raise AssertionError('should not be called outside a repo')

        monkeypatch.setattr(git_utils, 'check_symlinks', _boom)

        assert git_utils.check_symlinks_cached(tmp_path) is True

    def test_corrupt_cache_is_ignored(self, monkeypatch, tmp_path):
        (tmp_path / '.git').mkdir()
        cache_path = tmp_path / 'cache.json'
        monkeypatch.setattr(git_utils, '_symlink_check_cache_path', lambda: cache_path)
        cache_path.write_text('not json')

        monkeypatch.setattr(git_utils, 'check_symlinks', lambda root: True)

        assert git_utils.check_symlinks_cached(tmp_path) is True
        assert str(tmp_path) in json.loads(cache_path.read_text())
