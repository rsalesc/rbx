"""
Test suite for rbx.box.presets module.

This module tests preset management functionality including:
- Preset discovery and loading
- Asset tracking and globbing
- Package installation from presets
- Lock file generation and syncing
"""

from pathlib import Path
from typing import Iterator, Optional

import click
import pytest

from rbx.box import presets
from rbx.box.presets.lock_schema import LockedAsset, SymlinkInfo, TrackedAsset
from rbx.box.testing.testing_preset import TestingPreset

# ===================
# Reusable Fixtures
# ===================


@pytest.fixture
def simple_preset_testdata(testdata_path):
    """Fixture providing path to simple preset testdata."""
    return testdata_path / 'presets' / 'simple-preset'


@pytest.fixture
def problem_only_preset_testdata(testdata_path):
    """Fixture providing path to problem-only preset testdata."""
    return testdata_path / 'presets' / 'problem-only-preset'


@pytest.fixture
def symlink_preset_testdata(testdata_path):
    """Fixture providing path to symlink preset testdata."""
    return testdata_path / 'presets' / 'symlink-preset'


@pytest.fixture
def nested_preset_testdata(testdata_path):
    """Fixture providing path to nested preset testdata."""
    return testdata_path / 'presets' / 'nested-preset'


@pytest.fixture
def preset_with_problem_package(tmp_path) -> Iterator[TestingPreset]:
    """Create a preset with a problem package configuration."""
    preset_dir = tmp_path / 'preset'
    preset_dir.mkdir()
    with TestingPreset(preset_dir) as preset:
        preset.initialize()
        preset.set_name('test-preset')
        preset.set_uri('user/test-preset')
        preset.set_problem_path(Path('problem'))
        preset.create_problem_package()
        yield preset


@pytest.fixture
def preset_with_contest_package(tmp_path) -> Iterator[TestingPreset]:
    """Create a preset with a contest package configuration."""
    preset_dir = tmp_path / 'preset'
    preset_dir.mkdir()
    with TestingPreset(preset_dir) as preset:
        preset.initialize()
        preset.set_name('test-preset')
        preset.set_uri('user/test-preset')
        preset.set_contest_path(Path('contest'))
        preset.create_contest_package()
        yield preset


@pytest.fixture
def problem_package_with_preset(tmp_path, simple_preset_testdata) -> Path:
    """Create a problem package with an installed preset."""
    package_dir = tmp_path / 'package'
    package_dir.mkdir()

    # Create problem package
    problem_yml = package_dir / 'problem.rbx.yml'
    problem_yml.write_text("""---
name: "test-problem"
timeLimit: 1000
memoryLimit: 256
""")

    # Install preset
    presets.install_preset_from_dir(simple_preset_testdata, package_dir / '.local.rbx')

    return package_dir


@pytest.fixture
def contest_package_with_preset(tmp_path, simple_preset_testdata) -> Path:
    """Create a contest package with an installed preset."""
    package_dir = tmp_path / 'package'
    package_dir.mkdir()

    # Create contest package
    contest_yml = package_dir / 'contest.rbx.yml'
    contest_yml.write_text("""---
name: "Test Contest"
duration: 180
startTime: "2024-01-01T00:00:00Z"
problems:
  - name: "A"
    label: "Problem A"
""")

    # Install preset
    presets.install_preset_from_dir(simple_preset_testdata, package_dir / '.local.rbx')

    return package_dir


@pytest.fixture
def create_tracked_assets():
    """Factory fixture for creating TrackedAsset instances."""

    def _create(*paths: str, symlink: bool = False) -> list[TrackedAsset]:
        return [TrackedAsset(path=Path(p), symlink=symlink) for p in paths]

    return _create


@pytest.fixture
def create_locked_assets():
    """Factory fixture for creating LockedAsset instances."""

    def _create(
        *specs: tuple[str, Optional[str], Optional[SymlinkInfo]],
    ) -> list[LockedAsset]:
        return [
            LockedAsset(path=Path(path), hash=hash_val, symlink_info=symlink_info)
            for path, hash_val, symlink_info in specs
        ]

    return _create


# ==========================
# Test Preset Discovery
# ==========================


class TestPresetDiscovery:
    """Test preset discovery and location functions."""

    def test_find_preset_in_current_directory(self, tmp_path):
        """Should find preset.rbx.yml in the specified directory."""
        preset_file = tmp_path / 'preset.rbx.yml'
        preset_file.touch()

        assert presets.find_preset_yaml(tmp_path) == preset_file

    def test_find_preset_not_found(self, tmp_path):
        """Should return None when preset.rbx.yml doesn't exist."""
        assert presets.find_preset_yaml(tmp_path) is None

    def test_find_local_preset_in_local_rbx(self, tmp_path):
        """Should find preset in .local.rbx directory."""
        local_rbx = tmp_path / '.local.rbx'
        local_rbx.mkdir()
        (local_rbx / 'preset.rbx.yml').touch()

        assert presets.find_local_preset(tmp_path) == local_rbx

    def test_find_nested_preset(self, tmp_path):
        """Should find preset in current directory when searching for nested preset."""
        (tmp_path / 'preset.rbx.yml').touch()

        assert presets.find_nested_preset(tmp_path) == tmp_path

    def test_is_installed_preset(self, tmp_path):
        """Should correctly identify installed presets in .local.rbx."""
        local_rbx = tmp_path / '.local.rbx'
        local_rbx.mkdir()
        (local_rbx / 'preset.rbx.yml').touch()

        assert presets._is_installed_preset(tmp_path) is True  # noqa: SLF001

        # Test with non-installed preset (in isolated directory)
        other_path = tmp_path.parent / 'other'
        other_path.mkdir(exist_ok=True)
        assert presets._is_installed_preset(other_path) is False  # noqa: SLF001


# ==========================
# Test Preset Loading
# ==========================


class TestPresetLoading:
    """Test preset configuration loading."""

    def test_load_preset_yaml_success(self, preset_with_problem_package):
        """Should successfully load preset configuration from YAML."""
        preset = presets.get_preset_yaml(preset_with_problem_package.root)

        assert preset.name == 'test-preset'
        assert preset.uri == 'user/test-preset'
        assert preset.problem == Path('problem')

    def test_load_preset_yaml_not_found(self, tmp_path):
        """Should raise Exit when preset.rbx.yml is not found."""
        with pytest.raises(click.exceptions.Exit):
            presets.get_preset_yaml(tmp_path)

    def test_get_active_preset_when_installed(self, problem_package_with_preset):
        """Should get active preset when one is installed."""
        preset = presets.get_active_preset(problem_package_with_preset)

        assert preset.name == 'simple-preset'
        assert preset.uri == 'test/simple-preset'

    def test_get_active_preset_none_active(self, tmp_path):
        """Should raise Exit when no preset is active."""
        with pytest.raises(click.exceptions.Exit):
            presets.get_active_preset(tmp_path)


# ==========================
# Test Asset Tracking
# ==========================


class TestAssetTracking:
    """Test asset tracking and globbing functionality."""

    def test_process_globbing_simple_files(
        self, simple_preset_testdata, create_tracked_assets
    ):
        """Should resolve simple file paths without globbing."""
        assets = create_tracked_assets('template.cpp', '.gitignore')
        result = presets.process_globbing(assets, simple_preset_testdata / 'problem')

        assert len(result) == 2
        assert all('*' not in str(asset.path) for asset in result)

    def test_process_globbing_with_wildcards(
        self, problem_only_preset_testdata, create_tracked_assets
    ):
        """Should expand wildcard patterns to match multiple files."""
        assets = create_tracked_assets('lib/*')
        result = presets.process_globbing(
            assets, problem_only_preset_testdata / 'problem'
        )

        # Should find utils.hpp and math.hpp
        assert len(result) == 2
        assert all(asset.path.parent == Path('lib') for asset in result)
        assert {asset.path.name for asset in result} == {'utils.hpp', 'math.hpp'}

    def test_process_globbing_recursive_pattern(
        self, nested_preset_testdata, create_tracked_assets
    ):
        """Should handle recursive glob patterns."""
        assets = create_tracked_assets('src/**/*.cpp')
        result = presets.process_globbing(assets, nested_preset_testdata / 'problem')

        # Should find all .cpp files in src directory tree
        assert all(asset.path.suffix == '.cpp' for asset in result)
        assert any('utils' in str(asset.path) for asset in result)

    def test_dedup_tracked_assets(self, create_tracked_assets):
        """Should remove duplicate paths from tracked assets."""
        assets = create_tracked_assets(
            'file1.cpp', 'file1.cpp', 'file2.cpp', 'file1.cpp'
        )
        result = presets.dedup_tracked_assets(assets)

        assert len(result) == 2
        assert {asset.path.name for asset in result} == {'file1.cpp', 'file2.cpp'}

    def test_get_preset_tracked_assets_problem(self, problem_package_with_preset):
        """Should get tracked assets for problem package."""
        assets = presets.get_preset_tracked_assets(
            problem_package_with_preset, is_contest=False
        )

        # Should include template.cpp and other tracked files
        assert any(asset.path.name == 'template.cpp' for asset in assets)

    def test_get_preset_tracked_assets_with_symlinks(
        self, tmp_path, symlink_preset_testdata
    ):
        """Should include symlinks when requested."""
        # Install preset
        package_dir = tmp_path / 'package'
        package_dir.mkdir()
        (package_dir / 'problem.rbx.yml').touch()
        presets.install_preset_from_dir(
            symlink_preset_testdata, package_dir / '.local.rbx'
        )

        assets = presets.get_preset_tracked_assets(
            package_dir, is_contest=False, add_symlinks=True
        )

        symlink_assets = [a for a in assets if a.symlink]
        assert len(symlink_assets) >= 2  # template.cpp and lib/common.hpp


# ==========================
# Test Symlink Handling
# ==========================


class TestSymlinkHandling:
    """Test symlink detection and information extraction."""

    def test_symlink_info_for_regular_file(self, tmp_path, create_tracked_assets):
        """Should return None for regular files."""
        regular_file = tmp_path / 'regular.txt'
        regular_file.write_text('content')

        asset = create_tracked_assets('regular.txt')[0]
        assert presets.get_symlink_info(asset, tmp_path) is None

    def test_symlink_info_for_valid_symlink(self, tmp_path, create_tracked_assets):
        """Should extract correct symlink information."""
        target = tmp_path / 'target.txt'
        target.write_text('content')
        symlink = tmp_path / 'link.txt'
        symlink.symlink_to('target.txt')

        asset = create_tracked_assets('link.txt')[0]
        info = presets.get_symlink_info(asset, tmp_path)

        assert info is not None
        assert info.target == Path('target.txt')
        assert info.is_broken is False
        assert info.is_outside is False

    def test_symlink_info_for_broken_symlink(self, tmp_path, create_tracked_assets):
        """Should detect broken symlinks."""
        symlink = tmp_path / 'broken.txt'
        symlink.symlink_to('nonexistent.txt')

        asset = create_tracked_assets('broken.txt')[0]
        info = presets.get_symlink_info(asset, tmp_path)

        assert info is not None
        assert info.is_broken is True

    def test_symlink_info_for_outside_symlink(self, tmp_path, create_tracked_assets):
        """Should detect symlinks pointing outside the root directory."""
        outside_target = tmp_path.parent / 'outside.txt'
        outside_target.write_text('content')
        symlink = tmp_path / 'outside_link.txt'
        symlink.symlink_to(outside_target)

        asset = create_tracked_assets('outside_link.txt')[0]
        info = presets.get_symlink_info(asset, tmp_path)

        assert info is not None
        assert info.is_outside is True


# ==========================
# Test File Operations
# ==========================


class TestFileOperations:
    """Test file copying and manipulation operations."""

    def test_copy_preset_file_regular(self, tmp_path):
        """Should copy regular files preserving content."""
        src = tmp_path / 'src' / 'file.txt'
        dst = tmp_path / 'dst' / 'file.txt'
        src.parent.mkdir()
        src.write_text('content')

        presets.copy_preset_file(src, dst, src.parent, tmp_path)

        assert dst.exists()
        assert dst.read_text() == 'content'
        assert not dst.is_symlink()

    def test_copy_preset_file_creates_parent_dirs(self, tmp_path):
        """Should create parent directories as needed."""
        src = tmp_path / 'file.txt'
        dst = tmp_path / 'deep' / 'nested' / 'dir' / 'file.txt'
        src.write_text('content')

        presets.copy_preset_file(src, dst, tmp_path, tmp_path)

        assert dst.exists()
        assert dst.parent.exists()

    def test_copy_preset_file_preserves_symlinks(self, tmp_path):
        """Should preserve symlinks when copying."""
        preset_pkg = tmp_path / 'preset' / 'pkg'
        preset_pkg.mkdir(parents=True)
        target = preset_pkg / 'target.txt'
        target.write_text('content')
        src = preset_pkg / 'link.txt'
        src.symlink_to('target.txt')
        dst = tmp_path / 'dst' / 'link.txt'

        presets.copy_preset_file(src, dst, preset_pkg, tmp_path / 'preset')

        assert dst.is_symlink()
        assert dst.readlink() == Path('target.txt')

    def test_copy_preset_file_overwrites_existing(self, tmp_path):
        """Should overwrite existing files."""
        src = tmp_path / 'new.txt'
        dst = tmp_path / 'existing.txt'
        src.write_text('new content')
        dst.write_text('old content')

        presets.copy_preset_file(src, dst, tmp_path, tmp_path)

        assert dst.read_text() == 'new content'


# ==========================
# Test Installation
# ==========================


class TestPresetInstallation:
    """Test preset installation functionality."""

    def test_install_preset_from_dir(self, tmp_path, simple_preset_testdata):
        """Should install preset from directory correctly."""
        dst = tmp_path / 'installed'

        presets.install_preset_from_dir(simple_preset_testdata, dst)

        # Verify preset structure
        assert (dst / 'preset.rbx.yml').exists()
        assert (dst / 'env.rbx.yml').exists()
        assert (dst / 'problem' / 'template.cpp').exists()
        assert (dst / 'contest' / 'contest.rbx.yml').exists()

    def test_install_preset_cleans_build_dirs(self, tmp_path, simple_preset_testdata):
        """Should clean build and cache directories during installation."""
        dst = tmp_path / 'installed'
        dst.mkdir()  # Create the destination directory first

        # Create directories that should be cleaned
        (dst / 'build').mkdir(parents=True)
        (dst / '.local.rbx').mkdir(parents=True)
        (dst / 'problem' / '.box').mkdir(parents=True)

        presets.install_preset_from_dir(simple_preset_testdata, dst, update=True)  # noqa: SLF001

        # Verify cleanup
        assert not (dst / 'build').exists()
        assert not (dst / '.local.rbx').exists()
        assert not (dst / 'problem' / '.box').exists()

    def test_install_problem_package(self, tmp_path, simple_preset_testdata):
        """Should install problem package files correctly."""
        package_dir = tmp_path / 'package'
        package_dir.mkdir()
        (package_dir / 'problem.rbx.yml').touch()

        # Install preset first
        presets.install_preset_from_dir(
            simple_preset_testdata, package_dir / '.local.rbx'
        )

        # Install problem package
        presets.install_problem(package_dir)

        # Verify files were copied
        assert (package_dir / 'template.cpp').exists()

    def test_install_contest_package(self, tmp_path, simple_preset_testdata):
        """Should install contest package files correctly."""
        package_dir = tmp_path / 'package'
        package_dir.mkdir()
        (package_dir / 'contest.rbx.yml').write_text("""---
name: "Test Contest"
duration: 180
""")

        # Install preset first
        presets.install_preset_from_dir(
            simple_preset_testdata, package_dir / '.local.rbx'
        )

        # Install contest package
        presets.install_contest(package_dir)

        # Verify installation
        assert (package_dir / 'contest.rbx.yml').exists()


# ==========================
# Test Lock Generation
# ==========================


class TestLockGeneration:
    """Test lock file generation and management."""

    def test_build_package_locked_assets(self, tmp_path, create_tracked_assets):
        """Should build locked assets with file hashes."""
        (tmp_path / 'file1.txt').write_text('content1')
        (tmp_path / 'file2.txt').write_text('content2')

        tracked = create_tracked_assets('file1.txt', 'file2.txt')
        locked = presets.build_package_locked_assets(tracked, tmp_path)

        assert len(locked) == 2
        assert all(asset.hash is not None for asset in locked)
        assert locked[0].path == Path('file1.txt')
        assert locked[1].path == Path('file2.txt')

    def test_build_package_locked_assets_with_symlinks(
        self, tmp_path, create_tracked_assets
    ):
        """Should include symlink information in locked assets."""
        target = tmp_path / 'target.txt'
        target.write_text('content')
        symlink = tmp_path / 'link.txt'
        symlink.symlink_to('target.txt')

        tracked = create_tracked_assets('link.txt')
        locked = presets.build_package_locked_assets(tracked, tmp_path)

        assert len(locked) == 1
        assert locked[0].symlink_info is not None
        assert locked[0].symlink_info.target == Path('target.txt')

    def test_find_non_modified_assets(self, create_locked_assets):
        """Should identify assets that haven't been modified."""
        reference = create_locked_assets(
            ('unchanged.txt', 'hash1', None),
            ('modified.txt', 'hash2_old', None),
            ('removed.txt', 'hash3', None),
        )

        current = create_locked_assets(
            ('unchanged.txt', 'hash1', None),
            ('modified.txt', 'hash2_new', None),
            ('new.txt', 'hash4', None),
        )

        non_modified = presets.find_non_modified_assets(reference, current)

        # Only unchanged.txt should be non-modified
        assert len(non_modified) == 1
        assert non_modified[0].path == Path('unchanged.txt')

    def test_find_modified_assets(self, create_locked_assets):
        """Should identify assets that have been modified."""
        reference = create_locked_assets(
            ('unchanged.txt', 'hash1', None),
            ('modified.txt', 'hash2_old', None),
            ('removed.txt', 'hash3', None),
        )

        current = create_locked_assets(
            ('unchanged.txt', 'hash1', None),
            ('modified.txt', 'hash2_new', None),
        )

        modified = presets.find_modified_assets(reference, current, set())

        # Should find modified.txt and removed.txt
        assert len(modified) == 2
        paths = {asset.path.name for asset in modified}
        assert paths == {'modified.txt', 'removed.txt'}

    def test_generate_lock_creates_file(self, problem_package_with_preset):
        """Should create .preset-lock.yml file with correct content."""
        presets.generate_lock(problem_package_with_preset)

        lock_file = problem_package_with_preset / '.preset-lock.yml'
        assert lock_file.exists()

        # Verify lock content
        lock = presets.get_preset_lock(problem_package_with_preset)
        assert lock is not None
        assert lock.name == 'simple-preset'
        assert isinstance(lock.assets, list)


# ==========================
# Test Package Detection
# ==========================


class TestPackageDetection:
    """Test package type detection functions."""

    def test_is_contest_detection(self, tmp_path):
        """Should correctly detect contest packages."""
        # Test positive case
        (tmp_path / 'contest.rbx.yml').touch()
        assert presets.is_contest(tmp_path) is True

        # Test negative case
        (tmp_path / 'contest.rbx.yml').unlink()
        (tmp_path / 'problem.rbx.yml').touch()
        assert presets.is_contest(tmp_path) is False

    def test_is_problem_detection(self, tmp_path):
        """Should correctly detect problem packages."""
        # Test positive case
        (tmp_path / 'problem.rbx.yml').touch()
        assert presets.is_problem(tmp_path) is True

        # Test negative case
        (tmp_path / 'problem.rbx.yml').unlink()
        (tmp_path / 'contest.rbx.yml').touch()
        assert presets.is_problem(tmp_path) is False

    def test_check_valid_package(self, tmp_path):
        """Should validate package directories correctly."""
        # Invalid package
        with pytest.raises(click.exceptions.Exit):
            presets.check_is_valid_package(tmp_path)

        # Valid problem package
        (tmp_path / 'problem.rbx.yml').touch()
        presets.check_is_valid_package(tmp_path)  # Should not raise

        # Valid contest package
        (tmp_path / 'problem.rbx.yml').unlink()
        (tmp_path / 'contest.rbx.yml').touch()
        presets.check_is_valid_package(tmp_path)  # Should not raise


# ==========================
# Test Cleanup Functions
# ==========================


class TestCleanupFunctions:
    """Test directory cleanup functionality."""

    def test_clean_copied_package_dir(self, tmp_path):
        """Should remove .box directories and lock files."""
        # Create files to be cleaned
        (tmp_path / '.box').mkdir()
        (tmp_path / 'nested' / '.box').mkdir(parents=True)
        (tmp_path / '.preset-lock.yml').touch()
        (tmp_path / 'nested' / '.preset-lock.yml').touch()

        # Create files that should remain
        (tmp_path / 'keep.txt').touch()

        presets.clean_copied_package_dir(tmp_path)

        # Verify cleanup
        assert not (tmp_path / '.box').exists()
        assert not (tmp_path / 'nested' / '.box').exists()
        assert not (tmp_path / '.preset-lock.yml').exists()
        assert not (tmp_path / 'nested' / '.preset-lock.yml').exists()
        assert (tmp_path / 'keep.txt').exists()

    def test_clean_copied_contest_dir(self, tmp_path):
        """Should clean contest-specific directories."""
        # Create directories
        (tmp_path / 'build').mkdir()
        (tmp_path / '.local.rbx').mkdir()
        (tmp_path / '.box').mkdir()
        (tmp_path / 'contest.rbx.yml').touch()

        presets.clean_copied_contest_dir(tmp_path)

        # Verify cleanup
        assert not (tmp_path / 'build').exists()
        assert not (tmp_path / '.local.rbx').exists()
        assert not (tmp_path / '.box').exists()
        assert (tmp_path / 'contest.rbx.yml').exists()

    def test_clean_copied_problem_dir(self, tmp_path):
        """Should clean problem-specific directories."""
        # Create directories
        (tmp_path / 'build').mkdir()
        (tmp_path / '.box').mkdir()
        (tmp_path / 'main.cpp').touch()

        presets.clean_copied_problem_dir(tmp_path)

        # Verify cleanup
        assert not (tmp_path / 'build').exists()
        assert not (tmp_path / '.box').exists()
        assert (tmp_path / 'main.cpp').exists()


# ==========================
# Test Integration Scenarios
# ==========================


class TestIntegrationScenarios:
    """Test complete workflows combining multiple features."""

    def test_complete_preset_workflow(self, tmp_path, simple_preset_testdata):
        """Test installation → package creation → lock generation workflow."""
        package_dir = tmp_path / 'package'
        package_dir.mkdir()

        # Create problem package
        (package_dir / 'problem.rbx.yml').write_text("""---
name: "test-problem"
timeLimit: 1000
memoryLimit: 256
""")

        # Install preset
        presets.install_preset_from_dir(
            simple_preset_testdata, package_dir / '.local.rbx'
        )

        # Install problem files
        presets.install_problem(package_dir)

        # Generate lock
        presets.generate_lock(package_dir)

        # Verify complete workflow
        assert (package_dir / 'template.cpp').exists()
        assert (package_dir / '.preset-lock.yml').exists()

        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        assert lock.name == 'simple-preset'

    def test_symlink_preservation_workflow(self, tmp_path, symlink_preset_testdata):
        """Test that symlinks are preserved throughout the workflow."""
        package_dir = tmp_path / 'package'
        package_dir.mkdir()

        # Create problem package
        (package_dir / 'problem.rbx.yml').write_text("""---
name: "symlink-test"
timeLimit: 1000
memoryLimit: 256
""")

        # Install preset
        presets.install_preset_from_dir(
            symlink_preset_testdata, package_dir / '.local.rbx'
        )

        # Install problem with symlinks
        presets.install_problem(package_dir)

        # Verify symlinks are preserved
        assert (package_dir / 'template.cpp').is_symlink()
        assert (package_dir / 'lib' / 'common.hpp').is_symlink()
        assert not (package_dir / 'regular.cpp').is_symlink()

        # Generate lock and verify it tracks symlinks
        presets.generate_lock(package_dir)
        lock = presets.get_preset_lock(package_dir)

        # Find symlink assets in lock
        assert lock is not None
        symlink_assets = [a for a in lock.assets if a.symlink_info is not None]
        assert len(symlink_assets) >= 2

    def test_nested_files_workflow(self, tmp_path, nested_preset_testdata):
        """Test handling of nested directory structures."""
        package_dir = tmp_path / 'package'
        package_dir.mkdir()

        # Create problem package
        (package_dir / 'problem.rbx.yml').write_text("""---
name: "nested-test"
timeLimit: 1000
memoryLimit: 256
""")

        # Install preset
        presets.install_preset_from_dir(
            nested_preset_testdata, package_dir / '.local.rbx'
        )

        # Install problem with nested files
        presets.install_problem(package_dir)

        # Verify nested structure is preserved
        assert (package_dir / 'src' / 'main.cpp').exists()
        assert (package_dir / 'src' / 'utils' / 'helper.hpp').exists()
        assert (package_dir / 'src' / 'utils' / 'math.cpp').exists()
        assert (package_dir / 'config.json').exists()

        # Verify config.json content
        import json

        config = json.loads((package_dir / 'config.json').read_text())
        assert config['version'] == '1.0'
        assert config['settings']['debug'] is True


# ==========================
# Test Error Handling
# ==========================


class TestErrorHandling:
    """Test error conditions and edge cases."""

    def test_install_preset_without_problem_definition(self, tmp_path):
        """Should fail when preset doesn't have required package type."""
        preset_dir = tmp_path / 'preset'
        preset_dir.mkdir()

        # Create preset with only contest definition
        with TestingPreset(preset_dir) as preset:
            preset.initialize()
            preset.set_contest_path(Path('contest'))
            preset.create_contest_package()

        package_dir = tmp_path / 'package'
        package_dir.mkdir()
        (package_dir / 'problem.rbx.yml').touch()

        # Install preset
        presets.install_preset_from_dir(preset_dir, package_dir / '.local.rbx')

        # Should fail when trying to install problem package
        with pytest.raises(click.exceptions.Exit):
            presets.install_problem(package_dir)

    def test_copy_file_with_missing_source(self, tmp_path):
        """Should handle missing source files gracefully."""
        src = tmp_path / 'missing.txt'
        dst = tmp_path / 'dst.txt'

        # Should not raise exception
        presets.copy_preset_file(src, dst, tmp_path, tmp_path)

        # Destination should not exist
        assert not dst.exists()
