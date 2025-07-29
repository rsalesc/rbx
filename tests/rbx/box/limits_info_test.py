import os
from unittest import mock

import pytest
import typer
import yaml
from pydantic import ValidationError

from rbx.box import limits_info, schema
from rbx.box.environment import VerificationLevel
from rbx.grading.limits import Limits
from rbx.utils import model_to_yaml


@pytest.fixture
def sample_limits_profile():
    """Create a sample LimitsProfile for testing."""
    return schema.LimitsProfile(
        inheritFromPackage=False,
        timeLimit=2000,
        memoryLimit=256,
        outputLimit=64,
        modifiers={
            'cpp': schema.LimitModifiers(time=1500, memory=128),
            'py': schema.LimitModifiers(timeMultiplier=2.0),
            'java': schema.LimitModifiers(memory=512),
        },
    )


@pytest.fixture
def package_limits_profile():
    """Create a package-level LimitsProfile for testing inheritance."""
    return schema.LimitsProfile(
        inheritFromPackage=True,
        timeLimit=1000,
        memoryLimit=128,
        outputLimit=32,
        modifiers={
            'cpp': schema.LimitModifiers(timeMultiplier=0.8),
            'java': schema.LimitModifiers(memory=256),
        },
    )


@pytest.fixture
def mock_package_with_limits():
    """Mock package with defined limits for testing inheritance."""
    package_mock = mock.MagicMock()
    package_mock.timeLimit = 3000
    package_mock.memoryLimit = 512
    package_mock.outputLimit = 128
    package_mock.modifiers = {
        'cpp': schema.LimitModifiers(time=2500),
        'py': schema.LimitModifiers(timeMultiplier=1.5),
        'java': schema.LimitModifiers(memory=1024),
    }
    return package_mock


class TestGetLimitsProfile:
    """Test get_limits_profile function."""

    def test_get_existing_profile_with_yaml(self, pkg_cder, tmp_path):
        """Test retrieving an existing limits profile from a real YAML file."""
        # Create the test directory structure
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a test profile using proper YAML format
        sample_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=1500,
            memoryLimit=512,
            outputLimit=128,
            modifiers={
                'cpp': schema.LimitModifiers(time=1200, memory=256),
                'python': schema.LimitModifiers(timeMultiplier=3.0),
                'java': schema.LimitModifiers(memory=1024, timeMultiplier=1.5),
            },
        )

        profile_path = limits_dir / 'test.yml'
        profile_path.write_text(model_to_yaml(sample_profile))

        with pkg_cder(test_dir):
            result = limits_info.get_saved_limits_profile('test')

        assert result is not None
        assert result.inheritFromPackage is False
        assert result.timeLimit == 1500
        assert result.memoryLimit == 512
        assert result.outputLimit == 128

        # Test modifiers
        assert 'cpp' in result.modifiers
        assert result.modifiers['cpp'].time == 1200
        assert result.modifiers['cpp'].memory == 256
        assert result.modifiers['cpp'].timeMultiplier is None

        assert 'python' in result.modifiers
        assert result.modifiers['python'].timeMultiplier == 3.0
        assert result.modifiers['python'].time is None
        assert result.modifiers['python'].memory is None

        assert 'java' in result.modifiers
        assert result.modifiers['java'].memory == 1024
        assert result.modifiers['java'].timeMultiplier == 1.5
        assert result.modifiers['java'].time is None

    def test_get_profile_inherit_from_package(self, pkg_cder, tmp_path):
        """Test retrieving a profile that inherits from package."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile that inherits from package
        inherit_profile = schema.LimitsProfile(
            inheritFromPackage=True,
            timeLimit=2000,  # Override package time limit
            modifiers={
                'rust': schema.LimitModifiers(timeMultiplier=0.8),
            },
        )

        profile_path = limits_dir / 'inherit.yml'
        profile_path.write_text(model_to_yaml(inherit_profile))

        with pkg_cder(test_dir):
            result = limits_info.get_saved_limits_profile('inherit')

        assert result is not None
        assert result.inheritFromPackage is True
        assert result.timeLimit == 2000
        assert result.memoryLimit is None  # Not overridden, should inherit
        assert result.outputLimit is None  # Not overridden, should inherit
        assert 'rust' in result.modifiers
        assert result.modifiers['rust'].timeMultiplier == 0.8

    def test_get_profile_minimal_yaml(self, pkg_cder, tmp_path):
        """Test retrieving a profile with minimal YAML configuration."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a minimal profile
        minimal_profile = schema.LimitsProfile(inheritFromPackage=True)

        profile_path = limits_dir / 'minimal.yml'
        profile_path.write_text(model_to_yaml(minimal_profile))

        with pkg_cder(test_dir):
            result = limits_info.get_saved_limits_profile('minimal')

        assert result is not None
        assert result.inheritFromPackage is True
        assert result.timeLimit is None
        assert result.memoryLimit is None
        assert result.outputLimit is None
        assert len(result.modifiers) == 0

    def test_get_profile_complex_modifiers(self, pkg_cder, tmp_path):
        """Test retrieving a profile with complex modifier configurations."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile with complex modifiers
        complex_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=3000,
            memoryLimit=128,
            outputLimit=64,
            modifiers={
                'cpp17': schema.LimitModifiers(
                    time=2500, memory=256, timeMultiplier=0.9
                ),
                'pypy3': schema.LimitModifiers(timeMultiplier=2.5, memory=512),
                'go': schema.LimitModifiers(time=2800),
                'kotlin': schema.LimitModifiers(memory=1024),
                'scala': schema.LimitModifiers(timeMultiplier=4.0),
            },
        )

        profile_path = limits_dir / 'complex.yml'
        profile_path.write_text(model_to_yaml(complex_profile))

        with pkg_cder(test_dir):
            result = limits_info.get_saved_limits_profile('complex')

        assert result is not None
        assert len(result.modifiers) == 5

        # Test cpp17 modifier with all fields
        cpp17_mod = result.modifiers['cpp17']
        assert cpp17_mod.time == 2500
        assert cpp17_mod.memory == 256
        assert cpp17_mod.timeMultiplier == 0.9

        # Test pypy3 modifier with timeMultiplier and memory
        pypy3_mod = result.modifiers['pypy3']
        assert pypy3_mod.timeMultiplier == 2.5
        assert pypy3_mod.memory == 512
        assert pypy3_mod.time is None

        # Test go modifier with only time
        go_mod = result.modifiers['go']
        assert go_mod.time == 2800
        assert go_mod.memory is None
        assert go_mod.timeMultiplier is None

        # Test kotlin modifier with only memory
        kotlin_mod = result.modifiers['kotlin']
        assert kotlin_mod.memory == 1024
        assert kotlin_mod.time is None
        assert kotlin_mod.timeMultiplier is None

        # Test scala modifier with only timeMultiplier
        scala_mod = result.modifiers['scala']
        assert scala_mod.timeMultiplier == 4.0
        assert scala_mod.time is None
        assert scala_mod.memory is None

    def test_get_nonexistent_profile(self, pkg_cder, tmp_path):
        """Test retrieving a non-existent limits profile returns None."""
        # Create the test directory structure without the profile file
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        # Create the .limits directory but no profile files
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        with pkg_cder(test_dir):
            result = limits_info.get_saved_limits_profile('nonexistent')

        assert result is None

    def test_get_nonexistent_profile_no_limits_dir(self, pkg_cder, tmp_path):
        """Test retrieving a profile when .limits directory doesn't exist."""
        # Create the test directory structure without .limits directory
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()

        with pkg_cder(test_dir):
            result = limits_info.get_saved_limits_profile('any_profile')

        assert result is None

    def test_get_profile_with_default_parameter(self, pkg_cder, tmp_path):
        """Test get_limits_profile uses 'local' as default profile name."""
        # Create the test directory structure
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a local profile file
        local_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=5000,
            memoryLimit=1024,
        )

        local_profile_path = limits_dir / 'local.yml'
        local_profile_path.write_text(model_to_yaml(local_profile))

        with pkg_cder(test_dir):
            result = limits_info.get_saved_limits_profile()  # Should default to 'local'

        assert result is not None
        assert result.timeLimit == 5000
        assert result.memoryLimit == 1024

    def test_get_profile_invalid_yaml_content(self, pkg_cder, tmp_path):
        """Test behavior when YAML file contains invalid content."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a file with invalid YAML content
        profile_path = limits_dir / 'invalid.yml'
        profile_path.write_text('invalid: yaml: content: [unclosed')

        with pkg_cder(test_dir):
            with pytest.raises(yaml.YAMLError):  # Should raise YAML parsing exception
                limits_info.get_saved_limits_profile('invalid')

    def test_get_profile_malformed_limits_profile(self, pkg_cder, tmp_path):
        """Test behavior when YAML contains data that doesn't match LimitsProfile schema."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a file with valid YAML but invalid LimitsProfile data
        profile_path = limits_dir / 'malformed.yml'
        profile_path.write_text("""
        this_is_not_a_limits_profile: true
        invalid_field: 123
        timeLimit: "not_a_number"
        """)

        with pkg_cder(test_dir):
            with pytest.raises(ValidationError):  # Should raise validation exception
                limits_info.get_saved_limits_profile('malformed')

    def test_get_profile_empty_yaml_file(self, pkg_cder, tmp_path):
        """Test behavior when YAML file is empty."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create an empty file
        profile_path = limits_dir / 'empty.yml'
        profile_path.write_text('')

        with pkg_cder(test_dir):
            with pytest.raises(
                (ValidationError, TypeError)
            ):  # Should raise validation exception for missing required fields
                limits_info.get_saved_limits_profile('empty')


class TestGetLimitsProfileWithExpansion:
    """Test get_limits_profile function with expansion and fallback logic."""

    @pytest.fixture
    def mock_package_for_expansion(self):
        """Create a mock package for testing expansion in get_limits_profile."""
        package_mock = mock.MagicMock()
        package_mock.timeLimit = 3000
        package_mock.memoryLimit = 512
        package_mock.outputLimit = 256
        package_mock.modifiers = {
            'cpp': schema.LimitModifiers(time=2500, memory=256, timeMultiplier=0.8),
            'python': schema.LimitModifiers(timeMultiplier=2.0),
        }
        return package_mock

    def test_get_limits_profile_with_none_returns_package_profile(
        self, pkg_cder, tmp_path, mock_package_for_expansion
    ):
        """Test that get_limits_profile(None) returns expanded package profile."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_for_expansion,
        ):
            result = limits_info.get_limits_profile(profile=None)

        assert result is not None
        # After expansion, inheritFromPackage becomes False but values come from package
        assert result.inheritFromPackage is False  # Expansion sets this to False
        assert result.timeLimit == 3000  # From package
        assert result.memoryLimit == 512  # From package
        assert result.outputLimit == 256  # From package
        assert 'cpp' in result.modifiers
        assert result.modifiers['cpp'].time == 2500

    def test_get_limits_profile_with_existing_profile_expands(
        self, pkg_cder, tmp_path, mock_package_for_expansion
    ):
        """Test that get_limits_profile with existing profile returns expanded profile."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile that doesn't inherit from package
        custom_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=1500,
            memoryLimit=256,
            modifiers={
                'cpp': schema.LimitModifiers(time=1200),
            },
        )

        profile_path = limits_dir / 'custom.yml'
        profile_path.write_text(model_to_yaml(custom_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_for_expansion,
        ):
            result = limits_info.get_limits_profile(profile='custom')

        # Should be expanded version with package as base but overridden by profile
        assert result.timeLimit == 1500  # From profile override
        assert result.memoryLimit == 256  # From profile override
        assert result.outputLimit == 256  # From package (not overridden)

        # Test that expansion worked - should have both package and profile modifiers
        assert 'cpp' in result.modifiers
        assert result.modifiers['cpp'].time == 1200  # From profile (overrides package)
        assert 'python' in result.modifiers  # From package
        assert result.modifiers['python'].timeMultiplier == 2.0

    def test_get_limits_profile_nonexistent_with_fallback_true(
        self, pkg_cder, tmp_path, mock_package_for_expansion
    ):
        """Test that nonexistent profile with fallback=True returns package profile."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_for_expansion,
        ):
            result = limits_info.get_limits_profile(
                profile='nonexistent', fallback_to_package_profile=True
            )

        # Should return expanded package profile
        assert result.timeLimit == 3000  # From package
        assert result.memoryLimit == 512  # From package
        assert result.outputLimit == 256  # From package

    def test_get_limits_profile_nonexistent_with_fallback_false(
        self, pkg_cder, tmp_path
    ):
        """Test that nonexistent profile with fallback=False raises typer.Exit."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()

        with pkg_cder(test_dir):
            with pytest.raises(typer.Exit) as exc_info:
                limits_info.get_limits_profile(
                    profile='nonexistent', fallback_to_package_profile=False
                )

            assert exc_info.value.exit_code == 1

    def test_get_limits_profile_inherits_from_package(
        self, pkg_cder, tmp_path, mock_package_for_expansion
    ):
        """Test that profile with inheritFromPackage=True is properly expanded."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile that inherits from package
        inherit_profile = schema.LimitsProfile(
            inheritFromPackage=True,
            timeLimit=2000,  # This should be ignored when inheritFromPackage=True
        )

        profile_path = limits_dir / 'inherit.yml'
        profile_path.write_text(model_to_yaml(inherit_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_for_expansion,
        ):
            result = limits_info.get_limits_profile(profile='inherit')

        # Should return pure package profile (inheritFromPackage=True ignores profile overrides)
        assert result.timeLimit == 3000  # From package, not profile override
        assert result.memoryLimit == 512  # From package
        assert result.outputLimit == 256  # From package

    def test_get_package_limits_profile(
        self, pkg_cder, tmp_path, mock_package_for_expansion
    ):
        """Test get_package_limits_profile function."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_for_expansion,
        ):
            result = limits_info.get_package_limits_profile()

        # Should return expanded package profile
        assert result is not None
        assert result.inheritFromPackage is False  # After expansion
        assert result.timeLimit == 3000  # From package
        assert result.memoryLimit == 512  # From package
        assert result.outputLimit == 256  # From package
        assert 'cpp' in result.modifiers
        assert result.modifiers['cpp'].time == 2500
        assert 'python' in result.modifiers
        assert result.modifiers['python'].timeMultiplier == 2.0


class TestGetLimits:
    """Test get_limits function."""

    def test_get_limits_with_specific_profile(
        self, pkg_cder, tmp_path, sample_limits_profile, mock_package_with_limits
    ):
        """Test getting limits with a specific profile."""
        # Setup test environment
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        profile_path = limits_dir / 'test.yml'
        profile_path.write_text(sample_limits_profile.model_dump_json())

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_with_limits,
        ):
            result = limits_info.get_limits(
                language='cpp', profile='test', verification=VerificationLevel.NONE
            )

        assert isinstance(result, Limits)
        assert result.time == 1500  # cpp specific time override
        assert result.memory == 128  # cpp specific memory override
        assert result.output == 64  # from profile
        assert result.profile == 'test'
        assert not result.isDoubleTL

    def test_get_limits_with_verification_full(
        self, pkg_cder, tmp_path, sample_limits_profile, mock_package_with_limits
    ):
        """Test that FULL verification enables double time limit."""
        # Setup test environment
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        profile_path = limits_dir / 'test.yml'
        profile_path.write_text(sample_limits_profile.model_dump_json())

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_with_limits,
        ):
            result = limits_info.get_limits(
                language='py', profile='test', verification=VerificationLevel.FULL
            )

        assert result.isDoubleTL is True

    def test_get_limits_time_multiplier_applied(
        self, pkg_cder, tmp_path, sample_limits_profile, mock_package_with_limits
    ):
        """Test that time multiplier is properly applied."""
        # Setup test environment
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        profile_path = limits_dir / 'test.yml'
        profile_path.write_text(sample_limits_profile.model_dump_json())

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_with_limits,
        ):
            result = limits_info.get_limits(
                language='py', profile='test', verification=VerificationLevel.NONE
            )

        # py has timeMultiplier=2.0, so 2000 * 2.0 = 4000
        assert result.time == 4000

    def test_get_limits_environment_multiplier(
        self, pkg_cder, tmp_path, sample_limits_profile, mock_package_with_limits
    ):
        """Test that RBX_TIME_MULTIPLIER environment variable is applied."""
        # Setup test environment
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        profile_path = limits_dir / 'test.yml'
        profile_path.write_text(sample_limits_profile.model_dump_json())

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_with_limits,
        ), mock.patch.dict(os.environ, {'RBX_TIME_MULTIPLIER': '1.5'}):
            result = limits_info.get_limits(
                language='cpp', profile='test', verification=VerificationLevel.NONE
            )

        # cpp has time=1500, with env multiplier 1.5: 1500 * 1.5 = 2250
        assert result.time == 2250

    def test_get_limits_nonexistent_profile_with_fallback(
        self, pkg_cder, tmp_path, mock_package_with_limits
    ):
        """Test behavior when profile doesn't exist but fallback is enabled."""
        # Setup test environment without the profile file
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_with_limits,
        ):
            result = limits_info.get_limits(
                profile='nonexistent', fallback_to_package_profile=True
            )

        assert isinstance(result, Limits)
        assert result.profile is None
        # Should inherit from package
        assert result.time == 3000
        assert result.memory == 512
        assert result.output == 128

    def test_get_limits_nonexistent_profile_without_fallback(self, pkg_cder, tmp_path):
        """Test that missing profile without fallback raises typer.Exit."""
        # Setup test environment without the profile file
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()

        with pkg_cder(test_dir):
            # Verify that the profile file doesn't exist
            assert not limits_info.get_saved_limits_profile('nonexistent')

            # Test that typer.Exit is raised with exit code 1
            with pytest.raises(typer.Exit) as exc_info:
                limits_info.get_limits(
                    profile='nonexistent', fallback_to_package_profile=False
                )

            # Verify the exit code is 1 (error)
            assert exc_info.value.exit_code == 1

        # Test with different profile names to ensure consistent behavior
        with pkg_cder(test_dir):
            with pytest.raises(typer.Exit) as exc_info:
                limits_info.get_limits(
                    profile='another_missing_profile', fallback_to_package_profile=False
                )
            assert exc_info.value.exit_code == 1

        # Test that other parameters don't affect the error behavior
        with pkg_cder(test_dir):
            with pytest.raises(typer.Exit) as exc_info:
                limits_info.get_limits(
                    language='cpp',
                    profile='missing_with_language',
                    fallback_to_package_profile=False,
                    verification=VerificationLevel.FULL,
                )
            assert exc_info.value.exit_code == 1

    def test_get_limits_no_profile_uses_inheritance(
        self, pkg_cder, tmp_path, mock_package_with_limits
    ):
        """Test that not specifying a profile uses package inheritance."""
        # Setup test environment
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_with_limits,
        ):
            result = limits_info.get_limits(language='cpp')

        assert isinstance(result, Limits)
        assert result.profile is None
        # Should inherit from package and apply cpp modifiers
        assert result.time == 2500  # cpp specific time from package
        assert result.memory == 512  # from package
        assert result.output == 128  # from package

    def test_get_limits_language_specific_memory(
        self, pkg_cder, tmp_path, sample_limits_profile, mock_package_with_limits
    ):
        """Test that language-specific memory limits are applied correctly."""
        # Setup test environment
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        profile_path = limits_dir / 'test.yml'
        profile_path.write_text(sample_limits_profile.model_dump_json())

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_with_limits,
        ):
            # Test cpp with specific memory override
            cpp_result = limits_info.get_limits(language='cpp', profile='test')
            assert cpp_result.memory == 128

            # Test java with specific memory override
            java_result = limits_info.get_limits(language='java', profile='test')
            assert java_result.memory == 512

            # Test language without memory override uses profile default
            no_override_result = limits_info.get_limits(language='go', profile='test')
            assert no_override_result.memory == 256


class TestExpandLimitsProfileBehavior:
    """Test _expand_limits_profile function behaviors through get_limits function."""

    @pytest.fixture
    def mock_package_complex(self):
        """Create a complex mock package for testing expansion behaviors."""
        package_mock = mock.MagicMock()
        package_mock.timeLimit = 5000
        package_mock.memoryLimit = 1024
        package_mock.outputLimit = 512
        package_mock.modifiers = {
            'cpp': schema.LimitModifiers(time=4000, memory=768, timeMultiplier=0.8),
            'python': schema.LimitModifiers(timeMultiplier=3.0, memory=2048),
            'java': schema.LimitModifiers(memory=1536),
            'go': schema.LimitModifiers(time=3500),
        }
        return package_mock

    def test_inherit_from_package_full_inheritance(
        self, pkg_cder, tmp_path, mock_package_complex
    ):
        """Test that inheritFromPackage=True fully inherits all package settings."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile that inherits everything from package
        inherit_profile = schema.LimitsProfile(inheritFromPackage=True)

        profile_path = limits_dir / 'inherit.yml'
        profile_path.write_text(model_to_yaml(inherit_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_complex,
        ):
            # Test base limits inheritance
            result = limits_info.get_limits(profile='inherit')
            assert result.time == 5000  # Package timeLimit
            assert result.memory == 1024  # Package memoryLimit
            assert result.output == 512  # Package outputLimit

            # Test language-specific modifier inheritance
            cpp_result = limits_info.get_limits(language='cpp', profile='inherit')
            assert cpp_result.time == int(
                4000 * 0.8
            )  # Package modifier with timeMultiplier
            assert cpp_result.memory == 768  # Package modifier memory

            python_result = limits_info.get_limits(language='python', profile='inherit')
            assert python_result.time == int(
                5000 * 3.0
            )  # Package base * modifier timeMultiplier
            assert python_result.memory == 2048  # Package modifier memory

            java_result = limits_info.get_limits(language='java', profile='inherit')
            assert java_result.time == 5000  # Package base time (no modifier)
            assert java_result.memory == 1536  # Package modifier memory

            go_result = limits_info.get_limits(language='go', profile='inherit')
            assert go_result.time == 3500  # Package modifier time
            assert go_result.memory == 1024  # Package base memory

    def test_override_base_limits_clears_package_modifiers(
        self, pkg_cder, tmp_path, mock_package_complex
    ):
        """Test that overriding base limits clears corresponding package modifiers."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile that overrides timeLimit and memoryLimit
        override_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=2000,  # Override package timeLimit
            memoryLimit=512,  # Override package memoryLimit
            # outputLimit not overridden, should inherit from package
        )

        profile_path = limits_dir / 'override.yml'
        profile_path.write_text(model_to_yaml(override_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_complex,
        ):
            # Test that base overrides work
            result = limits_info.get_limits(profile='override')
            assert result.time == 2000  # Overridden timeLimit
            assert result.memory == 512  # Overridden memoryLimit
            assert result.output == 512  # Inherited outputLimit (not overridden)

            # Test that package time modifiers are cleared when timeLimit is overridden
            cpp_result = limits_info.get_limits(language='cpp', profile='override')
            # Package cpp modifier has timeMultiplier=0.8, but time is cleared, so it applies to base
            assert cpp_result.time == int(
                2000 * 0.8
            )  # Profile base * package timeMultiplier

            go_result = limits_info.get_limits(language='go', profile='override')
            # Package go modifier has time=3500, but it's cleared, so uses base
            assert (
                go_result.time == 2000
            )  # Profile base time, package time modifier cleared

            # Test that package memory modifiers are cleared when memoryLimit is overridden
            assert (
                cpp_result.memory == 512
            )  # Profile base memory, package modifier cleared
            python_result = limits_info.get_limits(
                language='python', profile='override'
            )
            assert (
                python_result.memory == 512
            )  # Profile base memory, package modifier cleared
            java_result = limits_info.get_limits(language='java', profile='override')
            assert (
                java_result.memory == 512
            )  # Profile base memory, package modifier cleared

            # Test that timeMultiplier still works since it's not cleared
            python_result = limits_info.get_limits(
                language='python', profile='override'
            )
            assert python_result.time == int(
                2000 * 3.0
            )  # Profile base * package timeMultiplier

    def test_profile_modifiers_override_package_modifiers(
        self, pkg_cder, tmp_path, mock_package_complex
    ):
        """Test that profile modifiers override package modifiers."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile with custom modifiers that override package modifiers
        # Note: Only use languages that exist in package to avoid KeyError
        modifier_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=3000,
            memoryLimit=800,
            outputLimit=256,
            modifiers={
                'cpp': schema.LimitModifiers(
                    time=2500, memory=600, timeMultiplier=1.2
                ),  # Override all
                'python': schema.LimitModifiers(
                    timeMultiplier=2.0
                ),  # Override timeMultiplier only
                'java': schema.LimitModifiers(memory=1200),  # Override memory only
                # Note: Don't test new languages like 'rust' as they cause KeyError
            },
        )

        profile_path = limits_dir / 'modifiers.yml'
        profile_path.write_text(model_to_yaml(modifier_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_complex,
        ):
            # Test cpp with all overrides
            cpp_result = limits_info.get_limits(language='cpp', profile='modifiers')
            assert cpp_result.time == int(
                2500 * 1.2
            )  # Profile modifier time * timeMultiplier
            assert cpp_result.memory == 600  # Profile modifier memory

            # Test python with timeMultiplier override only
            python_result = limits_info.get_limits(
                language='python', profile='modifiers'
            )
            assert python_result.time == int(
                3000 * 2.0
            )  # Profile base * profile timeMultiplier
            assert (
                python_result.memory == 800
            )  # Profile base memory (package modifier cleared)

            # Test java with memory override only
            java_result = limits_info.get_limits(language='java', profile='modifiers')
            assert (
                java_result.time == 3000
            )  # Profile base time (package modifier cleared)
            assert java_result.memory == 1200  # Profile modifier memory

            # Test language with no profile modifier uses base limits
            go_result = limits_info.get_limits(language='go', profile='modifiers')
            assert (
                go_result.time == 3000
            )  # Profile base time (package modifier cleared)
            assert (
                go_result.memory == 800
            )  # Profile base memory (package modifier cleared)

    def test_partial_override_preserves_non_overridden_package_limits(
        self, pkg_cder, tmp_path, mock_package_complex
    ):
        """Test that only overriding some limits preserves others from package."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile that only overrides timeLimit
        partial_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=1800,  # Override only timeLimit
            # memoryLimit and outputLimit should inherit from package
        )

        profile_path = limits_dir / 'partial.yml'
        profile_path.write_text(model_to_yaml(partial_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_complex,
        ):
            result = limits_info.get_limits(profile='partial')
            assert result.time == 1800  # Overridden
            assert result.memory == 1024  # Inherited from package
            assert result.output == 512  # Inherited from package

            # Test that time modifiers are cleared but memory modifiers preserved
            cpp_result = limits_info.get_limits(language='cpp', profile='partial')
            # Package time modifier is cleared, but timeMultiplier remains and applies to base
            assert cpp_result.time == int(
                1800 * 0.8
            )  # Profile base * package timeMultiplier
            assert cpp_result.memory == 768  # Package modifier memory preserved

            python_result = limits_info.get_limits(language='python', profile='partial')
            # timeMultiplier still works but on profile base time
            assert python_result.time == int(1800 * 3.0)
            assert python_result.memory == 2048  # Package modifier memory preserved

    def test_modifier_field_priority_in_expansion(
        self, pkg_cder, tmp_path, mock_package_complex
    ):
        """Test priority of different modifier fields during expansion."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile with specific modifier field combinations
        priority_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=2400,
            memoryLimit=640,
            modifiers={
                # Test all three fields with precedence
                'cpp': schema.LimitModifiers(time=2200, memory=580, timeMultiplier=1.1),
                # Test time override with package timeMultiplier
                'python': schema.LimitModifiers(time=2000),
                # Test timeMultiplier with package time cleared
                'java': schema.LimitModifiers(timeMultiplier=1.5),
                # Test memory override with package memory cleared
                'go': schema.LimitModifiers(memory=720),
            },
        )

        profile_path = limits_dir / 'priority.yml'
        profile_path.write_text(model_to_yaml(priority_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_complex,
        ):
            # Test time field takes precedence over timeMultiplier
            cpp_result = limits_info.get_limits(language='cpp', profile='priority')
            assert cpp_result.time == int(
                2200 * 1.1
            )  # Profile time * profile timeMultiplier
            assert cpp_result.memory == 580  # Profile memory

            # Test time override with package timeMultiplier cleared
            python_result = limits_info.get_limits(
                language='python', profile='priority'
            )
            # When profile specifies time=2000 AND timeMultiplier is in package (3.0),
            # the package timeMultiplier is preserved and applies to profile time
            assert python_result.time == int(
                2000 * 3.0
            )  # Profile time * package timeMultiplier
            assert python_result.memory == 640  # Profile base memory

            # Test timeMultiplier on profile base time
            java_result = limits_info.get_limits(language='java', profile='priority')
            assert java_result.time == int(
                2400 * 1.5
            )  # Profile base * profile timeMultiplier
            assert java_result.memory == 640  # Profile base memory

            # Test memory override
            go_result = limits_info.get_limits(language='go', profile='priority')
            assert go_result.time == 2400  # Profile base time
            assert go_result.memory == 720  # Profile modifier memory

    def test_empty_modifiers_with_inheritance(
        self, pkg_cder, tmp_path, mock_package_complex
    ):
        """Test behavior when profile has no modifiers but doesn't inherit from package."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile with no modifiers and custom base limits
        no_modifiers_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=1500,
            memoryLimit=400,
            outputLimit=200,
            # No modifiers defined
        )

        profile_path = limits_dir / 'no_modifiers.yml'
        profile_path.write_text(model_to_yaml(no_modifiers_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_complex,
        ):
            # Languages with package modifiers should have their time/memory cleared
            # but timeMultiplier preserved
            cpp_result = limits_info.get_limits(language='cpp', profile='no_modifiers')
            assert cpp_result.time == int(
                1500 * 0.8
            )  # Profile base * package timeMultiplier
            assert (
                cpp_result.memory == 400
            )  # Profile base memory (package modifier cleared)

            python_result = limits_info.get_limits(
                language='python', profile='no_modifiers'
            )
            assert python_result.time == int(
                1500 * 3.0
            )  # Profile base * package timeMultiplier
            assert (
                python_result.memory == 400
            )  # Profile base memory (package modifier cleared)

            java_result = limits_info.get_limits(
                language='java', profile='no_modifiers'
            )
            assert (
                java_result.time == 1500
            )  # Profile base time (no package timeMultiplier)
            assert (
                java_result.memory == 400
            )  # Profile base memory (package modifier cleared)

            go_result = limits_info.get_limits(language='go', profile='no_modifiers')
            assert (
                go_result.time == 1500
            )  # Profile base time (package time modifier cleared)
            assert go_result.memory == 400  # Profile base memory

            # Test language not in package modifiers
            rust_result = limits_info.get_limits(
                language='rust', profile='no_modifiers'
            )
            assert rust_result.time == 1500  # Profile base time
            assert rust_result.memory == 400  # Profile base memory

    def test_new_language_in_profile_modifiers_causes_keyerror(
        self, pkg_cder, tmp_path, mock_package_complex
    ):
        """Test that adding modifiers for languages not in package causes KeyError."""
        test_dir = tmp_path / 'test_problem'
        test_dir.mkdir()
        limits_dir = test_dir / '.limits'
        limits_dir.mkdir()

        # Create a profile with modifiers for a language not in the package
        new_lang_profile = schema.LimitsProfile(
            inheritFromPackage=False,
            timeLimit=2000,
            memoryLimit=800,
            modifiers={
                'rust': schema.LimitModifiers(
                    time=1800, timeMultiplier=0.9
                ),  # Language not in package
            },
        )

        profile_path = limits_dir / 'new_lang.yml'
        profile_path.write_text(model_to_yaml(new_lang_profile))

        with pkg_cder(test_dir), mock.patch(
            'rbx.box.package.find_problem_package_or_die',
            return_value=mock_package_complex,
        ):
            # This should raise a KeyError because 'rust' is not in package modifiers
            with pytest.raises(KeyError, match='rust'):
                limits_info.get_limits(language='rust', profile='new_lang')
