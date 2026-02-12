import subprocess

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


class TestCheckSymlinks:
    def test_git_not_installed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(git_utils.utils, 'command_exists', lambda cmd: False)
        assert git_utils.check_symlinks(tmp_path) is True

    def test_not_a_repo(self, monkeypatch, tmp_path):
        monkeypatch.setattr(git_utils.utils, 'command_exists', lambda cmd: True)
        monkeypatch.setattr(git_utils, 'get_repo_or_nil', lambda path, **kwargs: None)
        assert git_utils.check_symlinks(tmp_path) is True

    def test_valid_symlinks(self, monkeypatch, tmp_path):
        monkeypatch.setattr(git_utils.utils, 'command_exists', lambda cmd: True)

        mock_repo = type('Repo', (), {'working_dir': str(tmp_path)})()
        monkeypatch.setattr(
            git_utils, 'get_repo_or_nil', lambda path, **kwargs: mock_repo
        )

        def fake_run(cmd, cwd, check, capture_output, text):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='120000 0000000000000000000000000000000000000000 0\tlink_to_file',
                stderr='',
            )

        monkeypatch.setattr(subprocess, 'run', fake_run)

        # Create the file and the symlink
        (tmp_path / 'target').touch()
        (tmp_path / 'link_to_file').symlink_to('target')

        assert git_utils.check_symlinks(tmp_path) is True

    def test_broken_symlinks_regular_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(git_utils.utils, 'command_exists', lambda cmd: True)

        mock_repo = type('Repo', (), {'working_dir': str(tmp_path)})()
        monkeypatch.setattr(
            git_utils, 'get_repo_or_nil', lambda path, **kwargs: mock_repo
        )

        def fake_run(cmd, cwd, check, capture_output, text):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='120000 0000000000000000000000000000000000000000 0\tshould_be_link',
                stderr='',
            )

        monkeypatch.setattr(subprocess, 'run', fake_run)

        # Create a regular file instead of a symlink
        (tmp_path / 'should_be_link').touch()

        assert git_utils.check_symlinks(tmp_path) is False

    def test_missing_symlink(self, monkeypatch, tmp_path):
        monkeypatch.setattr(git_utils.utils, 'command_exists', lambda cmd: True)

        mock_repo = type('Repo', (), {'working_dir': str(tmp_path)})()
        monkeypatch.setattr(
            git_utils, 'get_repo_or_nil', lambda path, **kwargs: mock_repo
        )

        def fake_run(cmd, cwd, check, capture_output, text):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='120000 0000000000000000000000000000000000000000 0\tmissing_link',
                stderr='',
            )

        monkeypatch.setattr(subprocess, 'run', fake_run)

        # Do not create the file

        assert git_utils.check_symlinks(tmp_path) is True
