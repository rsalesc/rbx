import pathlib

from rbx.box.presets.fetch import PresetFetchInfo, get_preset_fetch_info


class TestPresetFetchInfo:
    """Tests for the PresetFetchInfo model."""

    def test_is_remote_with_fetch_uri(self):
        """Test that is_remote returns True when fetch_uri is set."""
        info = PresetFetchInfo(
            name='test',
            uri='https://github.com/user/repo',
            fetch_uri='https://github.com/user/repo',
        )
        assert info.is_remote() is True

    def test_is_remote_without_fetch_uri(self):
        """Test that is_remote returns False when fetch_uri is None."""
        info = PresetFetchInfo(name='test')
        assert info.is_remote() is False

    def test_is_local_dir_with_inner_dir_no_fetch_uri(self):
        """Test that is_local_dir returns True when inner_dir is set and no fetch_uri."""
        info = PresetFetchInfo(name='test', inner_dir='/local/path')
        assert info.is_local_dir() is True

    def test_is_local_dir_with_inner_dir_and_fetch_uri(self):
        """Test that is_local_dir returns False when both inner_dir and fetch_uri are set."""
        info = PresetFetchInfo(
            name='test',
            inner_dir='subdir',
            fetch_uri='https://github.com/user/repo',
        )
        assert info.is_local_dir() is False

    def test_is_local_dir_without_inner_dir(self):
        """Test that is_local_dir returns False when inner_dir is empty."""
        info = PresetFetchInfo(name='test')
        assert info.is_local_dir() is False


class TestGetPresetFetchInfo:
    """Tests for the get_preset_fetch_info function."""

    def test_none_input(self):
        """Test that None input returns None."""
        result = get_preset_fetch_info(None)
        assert result is None

    def test_github_full_url_without_subdirectory(self):
        """Test GitHub URL parsing without subdirectory."""
        uri = 'https://github.com/user/repo'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(
            name='user/repo',
            uri=uri,
            fetch_uri='https://github.com/user/repo',
            inner_dir='',
        )
        assert result == expected

    def test_github_full_url_with_subdirectory(self):
        """Test GitHub URL parsing with subdirectory."""
        uri = 'https://github.com/user/repo/subdir/path'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(
            name='user/repo',
            uri=uri,
            fetch_uri='https://github.com/user/repo',
            inner_dir='subdir/path',
        )
        assert result == expected

    def test_github_full_url_with_git_extension(self):
        """Test GitHub URL parsing with .git extension."""
        uri = 'https://github.com/user/repo.git'
        result = get_preset_fetch_info(uri)

        # Note: .git is included in the repo name by the regex
        expected = PresetFetchInfo(
            name='user/repo.git',
            uri=uri,
            fetch_uri='https://github.com/user/repo.git',
            inner_dir='',
        )
        assert result == expected

    def test_github_full_url_with_git_extension_and_subdirectory(self):
        """Test GitHub URL parsing with .git extension and subdirectory."""
        uri = 'https://github.com/user/repo.git/subdir'
        result = get_preset_fetch_info(uri)

        # Note: .git is included in the repo name by the regex
        expected = PresetFetchInfo(
            name='user/repo.git',
            uri=uri,
            fetch_uri='https://github.com/user/repo.git',
            inner_dir='subdir',
        )
        assert result == expected

    def test_github_subdomain_url(self):
        """Test GitHub subdomain URL parsing."""
        uri = 'https://subdomain.github.com/user/repo'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(
            name='user/repo',
            uri=uri,
            fetch_uri='https://subdomain.github.com/user/repo',
            inner_dir='',
        )
        assert result == expected

    def test_short_github_format(self):
        """Test short GitHub format (user/repo)."""
        uri = 'user/repo'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(
            name='user/repo',
            uri=uri,
            fetch_uri='https://github.com/user/repo',
            inner_dir='',
        )
        assert result == expected

    def test_short_github_format_with_at_gh_prefix(self):
        """Test short GitHub format with @gh/ prefix."""
        uri = '@gh/user/repo'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(
            name='user/repo',
            uri=uri,
            fetch_uri='https://github.com/user/repo',
            inner_dir='',
        )
        assert result == expected

    def test_short_github_format_with_subdirectory(self):
        """Test short GitHub format with subdirectory."""
        uri = 'user/repo/subdir/path'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(
            name='user/repo',
            uri=uri,
            fetch_uri='https://github.com/user/repo',
            inner_dir='subdir/path',
        )
        assert result == expected

    def test_github_with_dots_in_repo_name(self):
        """Test GitHub URL with dots in repository name."""
        uri = 'https://github.com/user/repo.name.with.dots'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(
            name='user/repo.name.with.dots',
            uri=uri,
            fetch_uri='https://github.com/user/repo.name.with.dots',
            inner_dir='',
        )
        assert result == expected

    def test_github_with_hyphens_in_names(self):
        """Test GitHub URL with hyphens in user and repo names."""
        uri = 'https://github.com/user-name/repo-name'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(
            name='user-name/repo-name',
            uri=uri,
            fetch_uri='https://github.com/user-name/repo-name',
            inner_dir='',
        )
        assert result == expected

    def test_local_directory_existing_path(self, tmp_path):
        """Test local directory parsing with existing path."""
        test_dir = tmp_path / 'test_preset'
        test_dir.mkdir()

        result = get_preset_fetch_info(str(test_dir))

        expected = PresetFetchInfo(
            name='test_preset',
            inner_dir=str(test_dir),
        )
        assert result == expected

    def test_local_directory_nonexistent_path(self, tmp_path):
        """Test that nonexistent local directories return None."""
        nonexistent_path = tmp_path / 'nonexistent'

        result = get_preset_fetch_info(str(nonexistent_path))

        # Nonexistent paths return None from local_dir_fetch_info
        assert result is None

    def test_local_directory_with_relative_path(self, tmp_path, monkeypatch):
        """Test local directory with relative path."""
        test_dir = tmp_path / 'test_preset'
        test_dir.mkdir()

        # Change to parent directory and use relative path
        monkeypatch.chdir(tmp_path)

        result = get_preset_fetch_info('test_preset')

        expected = PresetFetchInfo(
            name='test_preset',
            inner_dir='test_preset',
        )
        assert result == expected

    def test_local_preset_name_simple(self):
        """Test simple local preset name."""
        uri = 'simple-preset'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(name='simple-preset')
        assert result == expected

    def test_local_preset_name_with_underscores(self):
        """Test local preset name with underscores."""
        uri = 'my_preset_name'
        result = get_preset_fetch_info(uri)

        expected = PresetFetchInfo(name='my_preset_name')
        assert result == expected

    def test_invalid_github_url_no_user_repo(self):
        """Test invalid GitHub URL without user/repo structure falls back to local preset."""
        uri = 'https://github.com/'
        result = get_preset_fetch_info(uri)

        # Falls back to local preset name extractor
        expected = PresetFetchInfo(name='https://github.com/')
        assert result == expected

    def test_invalid_url_format(self):
        """Test completely invalid URL format falls back to local preset."""
        uri = 'not-a-valid-format://example'
        result = get_preset_fetch_info(uri)

        # Falls back to local preset name extractor (partial match)
        expected = PresetFetchInfo(name='not-a-valid-format://example')
        assert result == expected

    def test_empty_string(self):
        """Test empty string input."""
        result = get_preset_fetch_info('')

        # Empty string exists as current directory, so treated as local dir
        expected = PresetFetchInfo(name='', inner_dir='.')
        assert result == expected

    def test_github_url_priority_over_short_format(self):
        """Test that full GitHub URLs take priority over short format interpretation."""
        uri = 'https://github.com/user/repo'
        result = get_preset_fetch_info(uri)

        # Should be parsed as full GitHub URL, not as short format
        expected = PresetFetchInfo(
            name='user/repo',
            uri=uri,
            fetch_uri='https://github.com/user/repo',
            inner_dir='',
        )
        assert result == expected

    def test_local_directory_priority_over_preset_name(self, tmp_path, monkeypatch):
        """Test that existing local directories take priority over preset names."""
        test_dir = tmp_path / 'preset'
        test_dir.mkdir()

        monkeypatch.chdir(tmp_path)

        result = get_preset_fetch_info('preset')

        # Should be parsed as local directory, not as preset name
        expected = PresetFetchInfo(
            name='preset',
            inner_dir='preset',
        )
        assert result == expected

    def test_local_preset_name_partial_match_with_special_characters(self):
        """Test that strings with special characters partially match as preset names."""
        uri = 'preset@special#chars'
        result = get_preset_fetch_info(uri)

        # Regex matches the beginning but not the full string, still returns result
        expected = PresetFetchInfo(name='preset@special#chars')
        assert result == expected

    def test_path_with_exception_handling(self, monkeypatch):
        """Test that path exceptions are handled gracefully."""
        # Mock pathlib.Path to raise an exception
        original_path = pathlib.Path

        def mock_path_constructor(path_str):
            if path_str == 'some-path':
                raise OSError('Simulated path error')
            return original_path(path_str)

        monkeypatch.setattr(pathlib, 'Path', mock_path_constructor)

        result = get_preset_fetch_info('some-path')

        # Should fall back to local preset name due to exception
        expected = PresetFetchInfo(name='some-path')
        assert result == expected
