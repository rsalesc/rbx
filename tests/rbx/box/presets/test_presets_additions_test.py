from pathlib import Path
from types import SimpleNamespace

import click
import pytest

from rbx.box import presets


class TestGetPresetFetchInfoWithFallback:
    def test_none_uri_uses_default_when_no_active_preset(self, monkeypatch):
        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): None
        )
        # Stub default preset fetch info
        dummy = SimpleNamespace(name='default', fetch_uri='https://example/repo.git')
        monkeypatch.setattr(presets, 'get_preset_fetch_info', lambda name: dummy)

        res = presets.get_preset_fetch_info_with_fallback(None)
        assert res is dummy

    def test_none_uri_returns_none_when_active_preset_exists(self, monkeypatch):
        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): SimpleNamespace()
        )

        assert presets.get_preset_fetch_info_with_fallback(None) is None

    def test_missing_default_preset_errors(self, monkeypatch):
        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): None
        )
        monkeypatch.setattr(presets, 'get_preset_fetch_info', lambda name: None)

        with pytest.raises(click.exceptions.Exit):
            presets.get_preset_fetch_info_with_fallback(None)


class TestGetPresetEnvironmentPath:
    def test_returns_env_path_when_present(self, tmp_path, monkeypatch):
        # Prepare active preset pointing to env file
        env_file = tmp_path / 'env.rbx.yml'
        env_file.write_text('env')

        preset = SimpleNamespace(name='p', env=Path('env.rbx.yml'))
        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): preset
        )
        monkeypatch.setattr(
            presets, 'get_active_preset_path', lambda root=Path(): tmp_path
        )

        p = presets.get_preset_environment_path(Path('.'))
        assert p == env_file

    def test_none_when_no_active_or_no_env(self, monkeypatch):
        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): None
        )
        assert presets.get_preset_environment_path(Path('.')) is None

        preset = SimpleNamespace(name='p', env=None)
        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): preset
        )
        assert presets.get_preset_environment_path(Path('.')) is None

    def test_errors_when_env_missing(self, tmp_path, monkeypatch):
        preset = SimpleNamespace(name='p', env=Path('missing.yml'))
        monkeypatch.setattr(
            presets, 'get_active_preset_or_null', lambda root=Path(): preset
        )
        monkeypatch.setattr(
            presets, 'get_active_preset_path', lambda root=Path(): tmp_path
        )

        with pytest.raises(click.exceptions.Exit):
            presets.get_preset_environment_path(Path('.'))


class TestCopyTreeNormalizingGitdir:
    def test_copies_gitdir_from_repo_file_pointer(self, tmp_path, monkeypatch):
        # Simulate a source whose .git is a file pointing to real git dir
        src = tmp_path / 'src'
        dst = tmp_path / 'dst'
        gitdir_real = tmp_path / 'real_gitdir'
        (gitdir_real / 'config').mkdir(parents=True)
        src.mkdir()
        # Create .git file to trigger normalization path
        (src / '.git').write_text('gitdir: /IGNORED')

        class _Repo:
            def __init__(self, git_dir):
                self.git_dir = str(git_dir)

        # Return a fake repo for src; None for others
        monkeypatch.setattr(
            presets.git_utils,
            'get_repo_or_nil',
            lambda path, search_parent_directories=False: (
                _Repo(gitdir_real) if path == src else None
            ),
        )

        presets.copy_tree_normalizing_gitdir(src, dst)

        # .git should be materialized as a directory copied from gitdir_real
        assert (dst / '.git').is_dir()
        assert (dst / '.git' / 'config').is_dir()


class TestCopyLocalPreset:
    def test_adds_submodule_when_remote_and_user_accepts(self, tmp_path, monkeypatch):
        preset_repo_path = tmp_path / 'preset'
        preset_repo_path.mkdir()
        (preset_repo_path / 'preset.rbx.yml').write_text('name: x')

        current_repo_root = tmp_path / 'proj'
        current_repo_root.mkdir()

        class _Repo:
            def __init__(self):
                self.remotes = []

            @property
            def git(self):
                class _Git:
                    def submodule(self, *args):
                        # emulate call like: git submodule add <uri> <path>
                        return None

                return _Git()

        # Pretend we are inside current_repo_root
        monkeypatch.chdir(current_repo_root)

        # Repo detection for both
        monkeypatch.setattr(
            presets.git_utils,
            'get_repo_or_nil',
            lambda path, search_parent_directories=False: _Repo(),
        )

        # get_preset_fetch_info returns remote fetch info
        monkeypatch.setattr(
            presets,
            'get_preset_fetch_info',
            lambda uri: (
                SimpleNamespace(fetch_uri='https://example/repo.git')
                if uri is None
                else SimpleNamespace(fetch_uri='https://example/repo.git')
            ),
        )

        # get_any_remote returns a remote-like with url
        class _Remote:
            url = 'https://example/repo.git'

        monkeypatch.setattr(presets.git_utils, 'get_any_remote', lambda repo: _Remote())

        # User accepts adding submodule
        monkeypatch.setattr(
            presets.questionary,
            'confirm',
            lambda *a, **k: SimpleNamespace(ask=lambda: True),
        )

        presets.copy_local_preset(preset_repo_path, current_repo_root)

        # Verify content copied
        assert (current_repo_root / '.local.rbx' / 'preset.rbx.yml').exists()
