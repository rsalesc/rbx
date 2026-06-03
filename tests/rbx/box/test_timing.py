"""
Comprehensive tests for the rbx.box.timing module.
"""

import pathlib
from unittest import mock

import pytest
import yaml

from rbx.box import schema, timing
from rbx.box.deferred import Deferred
from rbx.box.environment import LanguageGroupFallback
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.box.solutions import EvaluationItem, RunSolutionResult
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testing import testing_package


class TestTimingProfile:
    """Test suite for TimingProfile model."""

    def test_timing_profile_creation(self):
        """Test creating a TimingProfile with basic parameters."""
        profile = timing.TimingProfile(
            timeLimit=1000,
            formula='slowest * 2',
            timeLimitPerLanguage={'cpp': 500, 'py': 2000},
        )

        assert profile.timeLimit == 1000
        assert profile.formula == 'slowest * 2'
        assert profile.timeLimitPerLanguage == {'cpp': 500, 'py': 2000}

    def test_timing_profile_defaults(self):
        """Test TimingProfile with default values."""
        profile = timing.TimingProfile(timeLimit=1000)

        assert profile.timeLimit == 1000
        assert profile.formula is None
        assert profile.timeLimitPerLanguage == {}

    def test_to_limits_conversion(self):
        """Test converting TimingProfile to schema.Limits."""
        profile = timing.TimingProfile(
            timeLimit=1000,
            formula='slowest * 2',
            timeLimitPerLanguage={'cpp': 500, 'py': 2000},
        )

        limits = profile.to_limits()

        assert isinstance(limits, schema.LimitsProfile)
        assert limits.timeLimit == 1000
        assert limits.formula == 'slowest * 2'
        assert 'cpp' in limits.modifiers
        assert 'py' in limits.modifiers
        assert limits.modifiers['cpp'].time == 500
        assert limits.modifiers['py'].time == 2000

    def test_to_limits_empty_modifiers(self):
        """Test converting TimingProfile to schema.Limits with no language-specific limits."""
        profile = timing.TimingProfile(timeLimit=1000)

        limits = profile.to_limits()

        assert limits.timeLimit == 1000
        assert limits.modifiers == {}


class TestStepFunctions:
    """Test suite for step_up and step_down helper functions."""

    def test_step_down_exact_multiple(self):
        """Test step_down with exact multiples."""
        assert timing.step_down(100, 10) == 100
        assert timing.step_down(1000, 50) == 1000

    def test_step_down_non_multiple(self):
        """Test step_down with non-multiples."""
        assert timing.step_down(123, 10) == 120
        assert timing.step_down(987, 50) == 950
        assert timing.step_down(1, 10) == 0

    def test_step_up_exact_multiple(self):
        """Test step_up with exact multiples."""
        assert timing.step_up(100, 10) == 100
        assert timing.step_up(1000, 50) == 1000

    def test_step_up_non_multiple(self):
        """Test step_up with non-multiples."""
        assert timing.step_up(123, 10) == 130
        assert timing.step_up(987, 50) == 1000
        assert timing.step_up(1, 10) == 10

    def test_step_functions_with_string_input(self):
        """Test step functions convert string inputs to integers."""
        assert timing.step_down('123', 10) == 120
        assert timing.step_up('123', 10) == 130


class TestEstimateTimeLimit:
    """Test suite for estimate_time_limit function."""

    @pytest.fixture
    def mock_console(self):
        """Mock console for testing output."""
        return mock.Mock()

    @pytest.fixture
    def sample_solution_result(self, testing_pkg: testing_package.TestingPackage):
        """Create a sample RunSolutionResult for testing."""
        # Create mock solutions
        sol1 = Solution(
            path=testing_pkg.path('sol1.cpp'),
            language='cpp',
            outcome=ExpectedOutcome.ACCEPTED,
        )
        sol2 = Solution(
            path=testing_pkg.path('sol2.py'),
            language='py',
            outcome=ExpectedOutcome.ACCEPTED,
        )

        # Create a mock skeleton instead of a full one
        skeleton = mock.Mock()
        skeleton.solutions = [sol1, sol2]

        # Create mock evaluation items with timing data
        async def mock_eval1():
            mock_log = mock.Mock()
            mock_log.time = 0.5  # 500ms
            return mock.Mock(log=mock_log, result=mock.Mock(outcome='ACCEPTED'))

        async def mock_eval2():
            mock_log = mock.Mock()
            mock_log.time = 1.2  # 1200ms
            return mock.Mock(log=mock_log, result=mock.Mock(outcome='ACCEPTED'))

        # Create proper EvaluationItem instances
        items = [
            EvaluationItem(
                solution=sol1,
                testcase_entry=TestcaseEntry(group='test', index=0),
                eval=Deferred(mock_eval1),
            ),
            EvaluationItem(
                solution=sol2,
                testcase_entry=TestcaseEntry(group='test', index=0),
                eval=Deferred(mock_eval2),
            ),
        ]

        return RunSolutionResult(skeleton=skeleton, items=items)

    @mock.patch('rbx.box.timing.consume_and_key_evaluation_items')
    @mock.patch('rbx.box.timing.find_language_name')
    @mock.patch('rbx.box.environment.get_environment')
    async def test_estimate_time_limit_basic(
        self,
        mock_env,
        mock_find_lang,
        mock_consume,
        mock_console,
        sample_solution_result,
    ):
        """Test basic time limit estimation."""
        from types import SimpleNamespace

        # Mock the structured evaluations
        mock_consume.return_value = {
            str(sample_solution_result.skeleton.solutions[0].path): {
                'group1': [sample_solution_result.items[0].eval]
            },
            str(sample_solution_result.skeleton.solutions[1].path): {
                'group1': [sample_solution_result.items[1].eval]
            },
        }

        # Mock find_language_name to avoid language lookup issues
        mock_find_lang.side_effect = lambda sol: sol.language

        # Mock environment so the grouping code works
        mock_env.return_value.timing.formula = 'slowest * 2'
        mock_env.return_value.timing.groups = []
        mock_env.return_value.languages = [
            SimpleNamespace(name='cpp'),
            SimpleNamespace(name='py'),
        ]

        # auto=True skips the interactive repartition prompt
        result = await timing.estimate_time_limit(
            mock_console, sample_solution_result, formula='slowest * 2', auto=True
        )

        assert result is not None
        assert isinstance(result, timing.TimingProfile)
        assert result.timeLimit == 2400  # slowest (1200) * 2
        assert result.formula == 'slowest * 2'

    @mock.patch('rbx.box.timing.consume_and_key_evaluation_items')
    @mock.patch('rbx.box.timing.find_language_name')
    async def test_estimate_time_limit_no_timings(
        self, mock_find_lang, mock_consume, mock_console, testing_pkg
    ):
        """Test time limit estimation with solutions that have no timing data."""
        sol = Solution(
            path=testing_pkg.path('sol.cpp'),
            language='cpp',
            outcome=ExpectedOutcome.ACCEPTED,
        )
        skeleton = mock.Mock()
        skeleton.solutions = [sol]

        # Create evaluation with no timing data
        async def mock_eval_no_time():
            mock_log = mock.Mock()
            mock_log.time = None
            return mock.Mock(log=mock_log, result=mock.Mock(outcome='ACCEPTED'))

        items = [
            EvaluationItem(
                solution=sol,
                testcase_entry=TestcaseEntry(group='test', index=0),
                eval=Deferred(mock_eval_no_time),
            )
        ]
        result = RunSolutionResult(skeleton=skeleton, items=items)

        mock_consume.return_value = {
            str(sol.path): {'group1': [Deferred(mock_eval_no_time)]}
        }

        # Mock find_language_name to avoid language lookup issues
        mock_find_lang.side_effect = lambda sol: sol.language

        # No timing data: estimation cannot proceed, so it returns None gracefully
        # (previously this raised ValueError due to min() on an empty sequence).
        estimate = await timing.estimate_time_limit(mock_console, result)
        assert estimate is None
        mock_console.print.assert_any_call(
            '[error]No timings collected from solutions.[/error]'
        )

    async def test_estimate_time_limit_no_solutions(self, mock_console):
        """Test time limit estimation with no solutions."""
        empty_skeleton = mock.Mock()
        empty_skeleton.solutions = []
        empty_result = RunSolutionResult(skeleton=empty_skeleton, items=[])

        result = await timing.estimate_time_limit(mock_console, empty_result)

        assert result is None
        mock_console.print.assert_called_with(
            '[error]No solutions to estimate time limit from.[/error]'
        )


class TestComputeTimeLimits:
    """Test suite for compute_time_limits function."""

    async def test_compute_time_limits_no_main_solution(self):
        """Test compute_time_limits when no main solution exists."""
        with mock.patch('rbx.box.package.get_main_solution', return_value=None):
            result = await timing.compute_time_limits(check=True, detailed=False)

        assert result is None

    @mock.patch('rbx.box.package.get_main_solution')
    @mock.patch('rbx.box.timing.get_exact_matching_solutions')
    @mock.patch('rbx.box.timing.run_solutions')
    @mock.patch('rbx.box.timing.print_run_report')
    @mock.patch('rbx.box.timing.estimate_time_limit')
    async def test_compute_time_limits_success(
        self,
        mock_estimate_time_limit,
        mock_print_run_report,
        mock_run_solutions,
        mock_get_exact_matching_solutions,
        mock_get_main_solution,
        testing_pkg: testing_package.TestingPackage,
    ):
        """Test successful time limit computation."""
        # Mock main solution exists
        mock_get_main_solution.return_value = mock.Mock()

        # Mock get_exact_matching_solutions
        mock_solution = mock.Mock()
        mock_solution.path = testing_pkg.path('sol.cpp')
        mock_get_exact_matching_solutions.return_value = [mock_solution]

        # Mock run_solutions
        mock_result = mock.Mock()
        mock_result.skeleton.solutions = [mock_solution]
        mock_run_solutions.return_value = mock_result

        # Mock print_run_report
        mock_print_run_report.return_value = True

        # Mock estimate_time_limit
        mock_profile = timing.TimingProfile(timeLimit=1000)
        mock_estimate_time_limit.return_value = mock_profile

        result = await timing.compute_time_limits(
            check=True, detailed=False, runs=0, profile='local'
        )

        limits_path = testing_pkg.path('.limits/local.yml')
        assert result is not None
        assert result.timeLimit == 1000
        assert limits_path.exists()

    @mock.patch('rbx.box.package.get_main_solution')
    @mock.patch('rbx.box.timing.get_exact_matching_solutions')
    @mock.patch('rbx.box.timing.run_solutions')
    @mock.patch('rbx.box.timing.print_run_report')
    async def test_compute_time_limits_failed_run_report(
        self,
        mock_print_run_report,
        mock_run_solutions,
        mock_get_exact_matching_solutions,
        mock_get_main_solution,
    ):
        """Test compute_time_limits when run report fails."""
        mock_get_main_solution.return_value = mock.Mock()

        mock_solution = mock.Mock()
        mock_solution.path = pathlib.Path('sol.cpp')
        mock_get_exact_matching_solutions.return_value = [mock_solution]

        mock_result = mock.Mock()
        mock_run_solutions.return_value = mock_result

        # Mock print_run_report to return False (failure)
        mock_print_run_report.return_value = False

        result = await timing.compute_time_limits(check=True, detailed=False)

        assert result is None


class TestInheritTimeLimits:
    """Test suite for inherit_time_limits function."""

    def test_inherit_time_limits(self, testing_pkg: testing_package.TestingPackage):
        """Test inheriting time limits from package."""
        limits_path = testing_pkg.path('.limits/test-profile.yml')
        limits_path.parent.mkdir(parents=True, exist_ok=True)

        timing.inherit_time_limits(profile='test-profile')

        assert limits_path.exists()

        # Verify the content
        limits_data = yaml.safe_load(limits_path.read_text())
        assert limits_data['inheritFromPackage'] is True


class TestSetTimeLimit:
    """Test suite for set_time_limit function."""

    def test_set_time_limit(self, testing_pkg: testing_package.TestingPackage):
        """Test setting a custom time limit."""
        limits_path = testing_pkg.path('.limits/custom-profile.yml')
        limits_path.parent.mkdir(parents=True, exist_ok=True)

        timing.set_time_limit(timelimit=2000, profile='custom-profile')

        assert limits_path.exists()

        # Verify the content
        limits_data = yaml.safe_load(limits_path.read_text())
        assert limits_data['timeLimit'] == 2000


class TestTimingIntegration:
    """Integration tests for timing functionality."""

    @pytest.mark.test_pkg('problems/box1')
    @mock.patch('rbx.box.package.get_main_solution')
    @mock.patch('rbx.box.timing.get_exact_matching_solutions')
    @mock.patch('rbx.box.timing.run_solutions')
    @mock.patch('rbx.box.timing.print_run_report')
    @mock.patch('rbx.box.timing.estimate_time_limit')
    async def test_timing_with_real_problem(
        self,
        mock_estimate_time_limit,
        mock_print_run_report,
        mock_run_solutions,
        mock_get_exact_matching_solutions,
        mock_get_main_solution,
        pkg_from_testdata: pathlib.Path,
    ):
        """Test timing functionality with a real problem package."""
        # This test primarily verifies that the timing functions can be called
        # without crashing when provided with proper mocked data

        # Mock all external dependencies to avoid environment issues
        mock_get_main_solution.return_value = mock.Mock()

        # Simple mock solution
        mock_solution = mock.Mock()
        mock_solution.path = pathlib.Path('sol.cpp')
        mock_solution.language = 'cpp'
        mock_get_exact_matching_solutions.return_value = [mock_solution]

        # Mock the result structure
        mock_result = mock.Mock()
        mock_result.skeleton.solutions = [mock_solution]
        mock_result.items = []
        mock_run_solutions.return_value = mock_result

        mock_print_run_report.return_value = True

        # Mock a successful timing profile
        mock_profile = timing.TimingProfile(timeLimit=1000)
        mock_estimate_time_limit.return_value = mock_profile

        mock_limits_path = pkg_from_testdata / '.limits' / 'test.yml'
        mock_limits_path.parent.mkdir(parents=True, exist_ok=True)

        result = await timing.compute_time_limits(
            check=False, detailed=False, runs=0, profile='test'
        )

        # Verify we got a result
        assert result is not None
        assert isinstance(result, timing.TimingProfile)
        assert result.timeLimit == 1000


class TestForcedRelativeIntegration:
    """Integration tests for the forced-relative override through the public
    build_timing_profile path."""

    def test_forced_relative_overrides_group_with_own_timings(self):
        """The headline behavior: a forced relative spec overrides a group's OWN
        measured timings, not just an empty group.

        Setup (formula='slowest', so _eval(fastest, slowest) == slowest):
          - repartition puts cpp in bucket 1, python in bucket 2.
          - Both groups HAVE their own measured solutions:
              cpp:    a.cpp = 100ms  -> estimated limit = slowest(100) = 100
              python: b.py  = 900ms  -> estimated limit would be 900
          - python's bucket (group key 'g2') carries a forced relative spec
            relativeTo='cpp', multiplier=2.0, increment=50.

        Expected python limit = multiplier * cpp_estimate + increment
                              = 2.0 * 100 + 50 = 250
        and explicitly NOT python's own 900ms estimate -- proving the forced
        relative wins over the group's own measured timings.
        """
        profile = timing.build_timing_profile(
            timing_per_solution_per_language={
                'cpp': {'a.cpp': 100},
                'python': {'b.py': 900},
            },
            formula='slowest',
            env_groups=[],
            all_languages=['cpp', 'python'],
            repartition={'cpp': 1, 'python': 2},
            relatives={
                'g2': LanguageGroupFallback(
                    relativeTo='cpp', multiplier=2.0, increment=50
                )
            },
        )

        # python's resolved limit is the forced relative value, not its own 900.
        assert profile.timeLimitPerLanguage['python'] == 250
        assert profile.timeLimitPerLanguage['python'] != 900
        # cpp is still estimated from its own (only) measurement.
        assert profile.timeLimitPerLanguage['cpp'] == 100

        # The overridden group report keeps the measured solution count for
        # display and is flagged as MULTIPLIER origin.
        python_group = next(
            report for report in profile.groups if 'python' in report.languages
        )
        assert python_group.origin == schema.TimingGroupOrigin.MULTIPLIER
        assert python_group.solutionCount == 1
        assert python_group.relativeToLanguage == 'cpp'
        assert python_group.timeLimit == 250
