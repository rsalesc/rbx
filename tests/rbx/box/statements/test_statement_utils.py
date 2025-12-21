import os
import pathlib

import pytest
import typer

from rbx.box.statements.statement_utils import get_relative_assets


class TestGetRelativeAssets:
    """Test get_relative_assets function."""

    def test_basic_asset_resolution(self, chdir_tmp_path):
        """Test basic asset file resolution."""
        # Create test files in the working directory
        asset_file = chdir_tmp_path / 'test.png'
        asset_file.write_text('fake image content')

        assets = get_relative_assets(chdir_tmp_path, ['test.png'])

        assert len(assets) == 1
        abs_path, rel_path = assets[0]
        assert abs_path.name == 'test.png'
        assert rel_path == pathlib.Path('test.png')

    def test_glob_pattern_asset_resolution(self, chdir_tmp_path):
        """Test asset resolution with glob patterns."""
        # Create multiple test files
        for i in range(3):
            (chdir_tmp_path / f'image{i}.png').write_text(f'content {i}')

        # Use real glob implementation with actual files
        assets = get_relative_assets(chdir_tmp_path, ['*.png'])

        assert len(assets) == 3
        png_files = [rel_path.name for _, rel_path in assets]
        assert 'image0.png' in png_files
        assert 'image1.png' in png_files
        assert 'image2.png' in png_files

    def test_nonexistent_asset_raises_exit(self, chdir_tmp_path):
        """Test that non-existent asset without glob raises typer.Exit."""
        with pytest.raises(typer.Exit):
            get_relative_assets(chdir_tmp_path, ['nonexistent.png'])

    def test_asset_outside_relative_path_raises_exit(self, tmp_path):
        """Test that asset outside relative path raises typer.Exit."""
        # Create asset outside the base directory
        outside_dir = tmp_path.parent / 'outside'
        outside_dir.mkdir()
        outside_asset = outside_dir / 'outside.txt'
        outside_asset.write_text('outside content')

        base_dir = tmp_path / 'base'
        base_dir.mkdir()

        # Change to base directory for this test
        original_cwd = os.getcwd()
        try:
            os.chdir(base_dir)
            with pytest.raises(typer.Exit):
                get_relative_assets(base_dir, [str(outside_asset)])
        finally:
            os.chdir(original_cwd)

    def test_root_parameter_resolution(self, tmp_path):
        """Test asset resolution using the root parameter."""
        # Structure:
        # tmp_path/
        #   project/  <- relative_to
        #     assets/
        #       image.png
        #       data1.txt
        #       data2.txt
        #   other/    <- CWD

        project_dir = tmp_path / 'project'
        project_dir.mkdir()
        assets_dir = project_dir / 'assets'
        assets_dir.mkdir()

        (assets_dir / 'image.png').write_text('image')
        (assets_dir / 'data1.txt').write_text('data1')
        (assets_dir / 'data2.txt').write_text('data2')

        other_dir = tmp_path / 'other'
        other_dir.mkdir()

        original_cwd = os.getcwd()
        try:
            os.chdir(other_dir)

            # Case 1: strict file match via root
            # We request 'assets/image.png'.
            # specific file check in CWD fails.
            # root.glob('assets/image.png') finds it in project_dir.
            assets = get_relative_assets(
                relative_to=project_dir,
                assets=['assets/image.png'],
                root=project_dir,
            )

            assert len(assets) == 1
            assert assets[0][0].name == 'image.png'
            # Expected relative path matches what was requested if it was relative to relative_to
            assert assets[0][1] == pathlib.Path('assets/image.png')

            # Case 2: Glob match via root
            assets_glob = get_relative_assets(
                relative_to=project_dir,
                assets=['assets/*.txt'],
                root=project_dir,
            )
            assert len(assets_glob) == 2
            names = sorted([p[0].name for p in assets_glob])
            assert names == ['data1.txt', 'data2.txt']

            # Case 3: Not found in root raises Exit
            with pytest.raises(typer.Exit):
                get_relative_assets(
                    relative_to=project_dir,
                    assets=['nonexistent.png'],
                    root=project_dir,
                )

        finally:
            # Always clean up cwd
            os.chdir(original_cwd)


@pytest.fixture
def chdir_tmp_path(tmp_path):
    """Fixture to change to tmp_path directory and restore original directory after test."""
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        yield tmp_path
    finally:
        os.chdir(original_cwd)
