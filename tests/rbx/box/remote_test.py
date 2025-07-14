import pathlib
from unittest import mock

import pytest
import typer

from rbx.box import package, remote
from rbx.box.schema import ExpectedOutcome
from rbx.box.testing import testing_package


class TestExpander:
    """Test the base Expander class."""

    def test_get_remote_path(self, testing_pkg: testing_package.TestingPackage):
        """Test get_remote_path returns correct path under remote directory."""
        expander = remote.MainExpander()
        test_path = pathlib.Path('test/path')

        result = expander.get_remote_path(test_path)

        # Should be under the problem remote directory
        assert result.parent.parent.name == '.remote'
        assert result.name == 'path'

    def test_cacheable_paths_default_empty(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test cacheable_paths returns empty list by default."""
        expander = remote.MainExpander()

        result = expander.cacheable_paths(pathlib.Path('test'))

        assert result == []

    def test_cacheable_globs_default_empty(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test cacheable_globs returns empty list by default."""
        expander = remote.MainExpander()

        result = expander.cacheable_globs(pathlib.Path('test'))

        assert result == []


class TestMainExpander:
    """Test the MainExpander class."""

    def test_expand_with_main_path(self, testing_pkg: testing_package.TestingPackage):
        """Test expand returns main solution path when given @main."""
        # Set up main solution
        testing_pkg.add_solution('sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED)

        expander = remote.MainExpander()

        result = expander.expand(pathlib.Path('@main'))

        assert result == pathlib.Path('sols/main.cpp')

    def test_expand_with_non_main_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand returns None when path is not @main."""
        expander = remote.MainExpander()

        result = expander.expand(pathlib.Path('@other'))

        assert result is None

    def test_expand_with_no_main_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand returns None when no main solution exists."""
        # Add a non-accepted solution
        testing_pkg.add_solution('sols/wa.cpp', outcome=ExpectedOutcome.WRONG_ANSWER)

        expander = remote.MainExpander()

        result = expander.expand(pathlib.Path('@main'))

        assert result is None


class TestBocaExpander:
    """Test the BocaExpander class."""

    def test_get_match_valid_run_with_site(self):
        """Test get_match parses valid BOCA run with site number."""
        expander = remote.BocaExpander()

        result = expander.get_match('@boca/123-2')

        assert result == (123, 2)

    def test_get_match_valid_run_without_site(self):
        """Test get_match parses valid BOCA run without site number (defaults to 1)."""
        expander = remote.BocaExpander()

        result = expander.get_match('@boca/456')

        assert result == (456, 1)

    def test_get_match_invalid_format(self):
        """Test get_match returns None for invalid format."""
        expander = remote.BocaExpander()

        result = expander.get_match('@invalid/format')

        assert result is None

    def test_get_match_non_boca_path(self):
        """Test get_match returns None for non-BOCA path."""
        expander = remote.BocaExpander()

        result = expander.get_match('@main')

        assert result is None

    def test_get_boca_path(self, testing_pkg: testing_package.TestingPackage):
        """Test get_boca_path returns correct path for run and site."""
        expander = remote.BocaExpander()

        result = expander.get_boca_path(123, 2)

        assert result.name == '123-2'
        assert result.parent.name == 'boca'

    def test_cacheable_globs_valid_boca_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test cacheable_globs returns correct glob pattern for valid BOCA path."""
        expander = remote.BocaExpander()

        result = expander.cacheable_globs(pathlib.Path('@boca/123-2'))

        assert len(result) == 1
        assert result[0].endswith('123-2.*')
        assert 'boca' in result[0]

    def test_cacheable_globs_invalid_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test cacheable_globs returns empty list for invalid path."""
        expander = remote.BocaExpander()

        result = expander.cacheable_globs(pathlib.Path('@main'))

        assert result == []

    @mock.patch('rbx.box.tooling.boca.scraper.get_boca_scraper')
    def test_expand_valid_boca_path(
        self, mock_get_scraper, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand downloads and returns path for valid BOCA run."""
        # Mock the BOCA scraper
        mock_scraper = mock.MagicMock()
        mock_get_scraper.return_value = mock_scraper

        # Create a temporary file to simulate downloaded solution
        boca_folder = package.get_problem_remote_dir() / 'boca'
        boca_folder.mkdir(parents=True, exist_ok=True)
        downloaded_file = boca_folder / '123-2.cpp'

        mock_scraper.download_run.return_value = downloaded_file

        expander = remote.BocaExpander()

        result = expander.expand(pathlib.Path('@boca/123-2'))

        # Verify scraper was called correctly
        mock_scraper.login.assert_called_once()
        mock_scraper.download_run.assert_called_once_with(
            123, 2, expander.get_boca_folder()
        )

        assert result == downloaded_file

    def test_expand_invalid_boca_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand returns None for invalid BOCA path."""
        expander = remote.BocaExpander()

        result = expander.expand(pathlib.Path('@main'))

        assert result is None


class TestExpandFiles:
    """Test the expand_files function."""

    def test_expand_files_normal_paths(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files passes through normal paths unchanged."""
        files = ['normal.cpp', 'another.cpp']

        result = remote.expand_files(files)

        assert result == [pathlib.Path('normal.cpp'), pathlib.Path('another.cpp')]

    def test_expand_files_with_main_expansion(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files expands @main to main solution."""
        # Set up main solution
        testing_pkg.add_solution('sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED)

        files = ['normal.cpp', '@main']

        result = remote.expand_files(files)

        assert result == [pathlib.Path('normal.cpp'), pathlib.Path('sols/main.cpp')]

    def test_expand_files_with_unexpandable_paths(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test expand_files skips unexpandable paths and prints warning."""
        files = ['normal.cpp', '@unknown']

        result = remote.expand_files(files)

        # Should skip the unexpandable path
        assert result == [pathlib.Path('normal.cpp')]

        # Should print a warning
        captured = capsys.readouterr()
        assert 'could not be expanded' in captured.out

    def test_expand_files_with_cached_file(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files uses cached file when available."""
        # Create a cached file for BOCA expansion
        remote_dir = package.get_problem_remote_dir()
        boca_folder = remote_dir / 'boca'
        boca_folder.mkdir(parents=True, exist_ok=True)
        cached_file = boca_folder / '123-2.cpp'
        cached_file.write_text('cached content')

        files = ['@boca/123-2']

        result = remote.expand_files(files)

        # Should return the cached file path relative to package
        assert result == [testing_pkg.relpath(cached_file)]
        assert cached_file.read_text() == 'cached content'

    def test_expand_files_mixed_paths(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files handles mixed normal and remote paths."""
        # Set up main solution
        testing_pkg.add_solution('sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED)

        files = ['normal1.cpp', '@main', 'normal2.cpp']

        result = remote.expand_files(files)

        assert result == [
            pathlib.Path('normal1.cpp'),
            pathlib.Path('sols/main.cpp'),
            pathlib.Path('normal2.cpp'),
        ]

    @mock.patch('rbx.box.cd.is_problem_package')
    def test_expand_files_not_in_package(
        self, mock_is_problem_package, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_files exits when not in a problem package."""
        mock_is_problem_package.return_value = False

        with pytest.raises(typer.Exit):
            remote.expand_files(['@main'])


class TestExpandFile:
    """Test the expand_file function."""

    def test_expand_file_single_result(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_file returns single expanded file."""
        # Set up main solution
        testing_pkg.add_solution('sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED)

        result = remote.expand_file('@main')

        assert result == pathlib.Path('sols/main.cpp')

    def test_expand_file_no_expansion(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_file exits when expansion fails."""
        with pytest.raises(typer.Exit):
            remote.expand_file('@unknown')

    def test_expand_file_multiple_results(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test expand_file exits when multiple results returned (shouldn't happen in practice)."""
        # This is a bit artificial since expand_files normally returns one result per input
        # but we test the error handling
        with mock.patch.object(remote, 'expand_files') as mock_expand:
            mock_expand.return_value = [
                pathlib.Path('file1.cpp'),
                pathlib.Path('file2.cpp'),
            ]

            with pytest.raises(typer.Exit):
                remote.expand_file('@test')


class TestIsPathRemote:
    """Test the is_path_remote function."""

    def test_is_path_remote_true(self, testing_pkg: testing_package.TestingPackage):
        """Test is_path_remote returns True for paths under remote directory."""
        remote_dir = package.get_problem_remote_dir()
        remote_file = remote_dir / 'test.cpp'
        remote_file.parent.mkdir(parents=True, exist_ok=True)
        remote_file.write_text('test content')

        result = remote.is_path_remote(remote_file)

        assert result is True

    def test_is_path_remote_false(self, testing_pkg: testing_package.TestingPackage):
        """Test is_path_remote returns False for paths outside remote directory."""
        local_file = testing_pkg.path('local.cpp')
        local_file.write_text('local content')

        result = remote.is_path_remote(local_file)

        assert result is False

    def test_is_path_remote_relative_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test is_path_remote works with relative paths."""
        # Create a file in the remote directory
        remote_dir = package.get_problem_remote_dir()
        remote_file = remote_dir / 'test.cpp'
        remote_file.parent.mkdir(parents=True, exist_ok=True)
        remote_file.write_text('test content')

        # Test with the actual relative path to the remote file
        result = remote.is_path_remote(remote_file)

        assert result is True


class TestBocaRegex:
    """Test the BOCA_REGEX pattern."""

    def test_boca_regex_with_site(self):
        """Test BOCA_REGEX matches pattern with site number."""
        match = remote.BocaExpander.BOCA_REGEX.match('@boca/123-2')

        assert match is not None
        assert match.group(1) == '123'
        assert match.group(2) == '2'

    def test_boca_regex_without_site(self):
        """Test BOCA_REGEX matches pattern without site number."""
        match = remote.BocaExpander.BOCA_REGEX.match('@boca/456')

        assert match is not None
        assert match.group(1) == '456'
        assert match.group(2) is None

    def test_boca_regex_invalid_format(self):
        """Test BOCA_REGEX doesn't match invalid format."""
        match = remote.BocaExpander.BOCA_REGEX.match('@boca/invalid')

        assert match is None

    def test_boca_regex_non_boca_path(self):
        """Test BOCA_REGEX doesn't match non-BOCA paths."""
        match = remote.BocaExpander.BOCA_REGEX.match('@main')

        assert match is None
