import os
from unittest import mock

import pytest

from rbx.box.schema import LimitModifiers, LimitsProfile


class TestLimitsProfile:
    """Test LimitsProfile methods."""

    def test_timelimit_for_language_no_modifiers(self):
        """Test timelimit_for_language without any language-specific modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
        )

        assert profile.timelimit_for_language() == 2000
        assert profile.timelimit_for_language('cpp') == 2000
        assert profile.timelimit_for_language('python') == 2000

    def test_timelimit_for_language_with_time_override(self):
        """Test timelimit_for_language with specific time override for a language."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(time=1500),
                'python': LimitModifiers(time=3000),
            },
        )

        # No language specified - use base time limit
        assert profile.timelimit_for_language() == 2000

        # Language with time override
        assert profile.timelimit_for_language('cpp') == 1500
        assert profile.timelimit_for_language('python') == 3000

        # Language without modifiers - use base time limit
        assert profile.timelimit_for_language('java') == 2000

    def test_timelimit_for_language_with_time_multiplier(self):
        """Test timelimit_for_language with time multiplier for a language."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'python': LimitModifiers(timeMultiplier=2.5),
                'java': LimitModifiers(timeMultiplier=1.5),
            },
        )

        # No language specified - use base time limit
        assert profile.timelimit_for_language() == 2000

        # Language with time multiplier
        assert profile.timelimit_for_language('python') == int(2000 * 2.5)  # 5000
        assert profile.timelimit_for_language('java') == int(2000 * 1.5)  # 3000

        # Language without modifiers - use base time limit
        assert profile.timelimit_for_language('cpp') == 2000

    def test_timelimit_for_language_time_override_takes_precedence(self):
        """Test that time override takes precedence over time multiplier."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(time=1200, timeMultiplier=3.0),
            },
        )

        # Time override should be used first, then multiplier applied to that
        expected = int(1200 * 3.0)  # 3600
        assert profile.timelimit_for_language('cpp') == expected

    @mock.patch.dict(os.environ, {'RBX_TIME_MULTIPLIER': '2.0'})
    def test_timelimit_for_language_with_env_multiplier(self):
        """Test timelimit_for_language with RBX_TIME_MULTIPLIER environment variable."""
        profile = LimitsProfile(
            timeLimit=1000,
            memoryLimit=256,
        )

        # Environment multiplier should be applied to final result
        assert profile.timelimit_for_language() == int(1000 * 2.0)  # 2000
        assert profile.timelimit_for_language('cpp') == int(1000 * 2.0)  # 2000

    @mock.patch.dict(os.environ, {'RBX_TIME_MULTIPLIER': '1.5'})
    def test_timelimit_for_language_env_multiplier_with_language_modifiers(self):
        """Test timelimit_for_language with both language modifiers and environment multiplier."""
        profile = LimitsProfile(
            timeLimit=1000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(time=800, timeMultiplier=2.0),
                'python': LimitModifiers(timeMultiplier=3.0),
            },
        )

        # For cpp: time override (800) * timeMultiplier (2.0) * env multiplier (1.5)
        expected_cpp = int(int(800 * 2.0) * 1.5)  # int(1600 * 1.5) = 2400
        assert profile.timelimit_for_language('cpp') == expected_cpp

        # For python: base time (1000) * timeMultiplier (3.0) * env multiplier (1.5)
        expected_python = int(int(1000 * 3.0) * 1.5)  # int(3000 * 1.5) = 4500
        assert profile.timelimit_for_language('python') == expected_python

        # For java (no modifiers): base time (1000) * env multiplier (1.5)
        expected_java = int(1000 * 1.5)  # 1500
        assert profile.timelimit_for_language('java') == expected_java

    def test_memorylimit_for_language_no_modifiers(self):
        """Test memorylimit_for_language without any language-specific modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
        )

        assert profile.memorylimit_for_language() == 256
        assert profile.memorylimit_for_language('cpp') == 256
        assert profile.memorylimit_for_language('python') == 256

    def test_memorylimit_for_language_with_memory_override(self):
        """Test memorylimit_for_language with specific memory override for a language."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(memory=128),
                'java': LimitModifiers(memory=512),
            },
        )

        # No language specified - use base memory limit
        assert profile.memorylimit_for_language() == 256

        # Language with memory override
        assert profile.memorylimit_for_language('cpp') == 128
        assert profile.memorylimit_for_language('java') == 512

        # Language without modifiers - use base memory limit
        assert profile.memorylimit_for_language('python') == 256

    def test_memorylimit_for_language_ignores_time_modifiers(self):
        """Test that memorylimit_for_language ignores time-related modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(time=1500, timeMultiplier=2.0),
                'python': LimitModifiers(timeMultiplier=3.0, memory=128),
            },
        )

        # cpp has time modifiers but no memory modifier
        assert profile.memorylimit_for_language('cpp') == 256

        # python has both time and memory modifiers - only memory should be used
        assert profile.memorylimit_for_language('python') == 128

    def test_memorylimit_for_language_none_language(self):
        """Test memorylimit_for_language with None language parameter."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(memory=128),
            },
        )

        # None language should return base memory limit
        assert profile.memorylimit_for_language(None) == 256

    def test_memorylimit_for_language_nonexistent_language(self):
        """Test memorylimit_for_language with a language that has no modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(memory=128),
            },
        )

        # Language not in modifiers should return base memory limit
        assert profile.memorylimit_for_language('nonexistent') == 256

    def test_timelimit_assertion_failure(self):
        """Test that timelimit_for_language raises assertion error when timeLimit is None."""
        profile = LimitsProfile(
            memoryLimit=256,
        )

        with pytest.raises(AssertionError):
            profile.timelimit_for_language()

    def test_memorylimit_assertion_failure(self):
        """Test that memorylimit_for_language raises assertion error when memoryLimit is None."""
        profile = LimitsProfile(
            timeLimit=2000,
        )

        with pytest.raises(AssertionError):
            profile.memorylimit_for_language()

    @mock.patch.dict(os.environ, {'RBX_TIME_MULTIPLIER': '0.5'})
    def test_timelimit_for_language_fractional_env_multiplier(self):
        """Test timelimit_for_language with fractional environment multiplier."""
        profile = LimitsProfile(
            timeLimit=1000,
            memoryLimit=256,
        )

        # Should handle fractional multipliers properly
        assert profile.timelimit_for_language() == int(1000 * 0.5)  # 500

    def test_complex_scenario_all_modifiers(self):
        """Test a complex scenario with multiple types of modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=512,
            modifiers={
                'cpp': LimitModifiers(time=1500, memory=256),
                'python': LimitModifiers(timeMultiplier=2.0, memory=1024),
                'java': LimitModifiers(timeMultiplier=1.5),
                'go': LimitModifiers(memory=128),
            },
        )

        # Test time limits
        assert profile.timelimit_for_language('cpp') == 1500  # time override
        assert profile.timelimit_for_language('python') == int(2000 * 2.0)  # 4000
        assert profile.timelimit_for_language('java') == int(2000 * 1.5)  # 3000
        assert profile.timelimit_for_language('go') == 2000  # no time modifier

        # Test memory limits
        assert profile.memorylimit_for_language('cpp') == 256  # memory override
        assert profile.memorylimit_for_language('python') == 1024  # memory override
        assert profile.memorylimit_for_language('java') == 512  # no memory modifier
        assert profile.memorylimit_for_language('go') == 128  # memory override
