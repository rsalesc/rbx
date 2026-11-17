import textwrap
from typing import Optional

import pytest

from rbx import testing_utils
from rbx.box import checkers, code, tasks
from rbx.box.environment import VerificationLevel
from rbx.box.schema import CodeItem, Testcase
from rbx.box.testing import testing_package
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.steps import Outcome

_ENV_WITH_MISSING_PY_INTERPRETER = textwrap.dedent("""\
    ---
    sandbox: "stupid"
    defaultCompilation:
      sandbox:
        maxProcesses: 1000
        timeLimit: 50000
        wallTimeLimit: 50000
        memoryLimit: 1024
    defaultExecution:
      sandbox:
        timeLimit: 50000
        wallTimeLimit: 50000
        memoryLimit: 1024
    languages:
      - name: "py"
        readableName: "Python3"
        extension: "py"
        execution:
          command: "rbx-not-a-real-interpreter {executable}"
        fileMapping:
          executable: "{compilable}"
""")


class TestRunSolutionOnTestcase:
    """Test suite for run_solution_on_testcase function."""

    async def test_run_solution_without_explicit_language(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that solutions without explicit language field work correctly.

        Regression test for the fix where solution.language was accessed directly
        instead of using find_language_name(), which can infer the language from
        the file extension when language is None.
        """
        # Create a simple Python program without specifying language
        py_file = testing_pkg.add_file(
            'solution.py', src='program_test/simple_hello.py'
        )
        # Create CodeItem WITHOUT setting language field - it should infer from extension
        solution = CodeItem(path=py_file)  # language not set, will be None

        # Verify language is actually None (this is the regression scenario)
        assert solution.language is None

        # Compile the solution
        compiled_digest = await code.compile_item(solution)

        # Create input and output files for testcase
        input_file = testing_pkg.add_file('test.in')
        input_file.write_text('')
        output_file = testing_pkg.path('test.ans')
        output_file.write_text('Hello, World!\n')

        testcase = Testcase(
            inputPath=input_file,
            outputPath=output_file,
        )

        # Create output directory
        output_dir = testing_pkg.path('outputs')
        output_dir.mkdir(exist_ok=True)

        # Run solution on testcase - this should work without crashing
        # The fix ensures find_language_name() is used instead of solution.language
        evaluation = await tasks.run_solution_on_testcase(
            solution=solution,
            compiled_digest=compiled_digest,
            checker_digest=None,
            testcase=testcase,
            output_dir=output_dir,
            verification=VerificationLevel.NONE,
            use_retries=False,
        )

        # Verify execution succeeded
        assert evaluation is not None
        assert evaluation.log is not None
        assert evaluation.log.exitcode == 0
        assert evaluation.log.exitstatus == SandboxBase.EXIT_OK

        # Verify output was generated
        output_path = output_dir / 'test.out'
        assert output_path.exists()
        assert output_path.read_text().strip() == 'Hello, World!'

    async def test_run_solution_without_explicit_language_cpp(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that C++ solutions without explicit language field work correctly."""
        # Create a simple C++ program without specifying language
        cpp_file = testing_pkg.add_file('solution.cpp', src='compile_test/simple.cpp')
        # Create CodeItem WITHOUT setting language field
        solution = CodeItem(path=cpp_file)  # language not set

        # Verify language is None
        assert solution.language is None

        # Compile the solution
        compiled_digest = await code.compile_item(solution)

        # Create input and output files for testcase
        input_file = testing_pkg.add_file('test.in')
        input_file.write_text('')
        output_file = testing_pkg.path('test.ans')
        output_file.write_text('')  # Simple.cpp output varies

        testcase = Testcase(
            inputPath=input_file,
            outputPath=output_file,
        )

        # Create output directory
        output_dir = testing_pkg.path('outputs')
        output_dir.mkdir(exist_ok=True)

        # Run solution on testcase
        evaluation = await tasks.run_solution_on_testcase(
            solution=solution,
            compiled_digest=compiled_digest,
            checker_digest=None,
            testcase=testcase,
            output_dir=output_dir,
            verification=VerificationLevel.NONE,
            use_retries=False,
        )

        # Verify execution succeeded
        assert evaluation is not None
        assert evaluation.log is not None
        assert evaluation.log.exitcode == 0
        assert evaluation.log.exitstatus == SandboxBase.EXIT_OK

        # Verify output was generated
        output_path = output_dir / 'test.out'
        assert output_path.exists()

    async def test_run_solution_with_explicit_language_still_works(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that solutions with explicit language field still work correctly.

        This ensures the fix doesn't break existing behavior.
        """
        # Create a Python program WITH explicit language
        py_file = testing_pkg.add_file(
            'solution.py', src='program_test/simple_hello.py'
        )
        solution = CodeItem(path=py_file, language='py')  # Explicit language

        # Verify language is set
        assert solution.language == 'py'

        # Compile the solution
        compiled_digest = await code.compile_item(solution)

        # Create input and output files for testcase
        input_file = testing_pkg.add_file('test.in')
        input_file.write_text('')
        output_file = testing_pkg.path('test.ans')
        output_file.write_text('Hello, World!\n')

        testcase = Testcase(
            inputPath=input_file,
            outputPath=output_file,
        )

        # Create output directory
        output_dir = testing_pkg.path('outputs')
        output_dir.mkdir(exist_ok=True)

        # Run solution on testcase
        evaluation = await tasks.run_solution_on_testcase(
            solution=solution,
            compiled_digest=compiled_digest,
            checker_digest=None,
            testcase=testcase,
            output_dir=output_dir,
            verification=VerificationLevel.NONE,
            use_retries=False,
        )

        # Verify execution succeeded
        assert evaluation is not None
        assert evaluation.log is not None
        assert evaluation.log.exitcode == 0
        assert evaluation.log.exitstatus == SandboxBase.EXIT_OK

    async def test_run_solution_with_missing_interpreter_reports_clear_error(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A solution whose execution command points at a non-existent binary
        should yield an informative INTERNAL_ERROR verdict instead of crashing
        with a cryptic FileNotFoundError (regression test for issue #454)."""
        # Point the python execution command at a non-existent interpreter.
        env_path = testing_pkg.preset.path('env.rbx.yml')
        env_path.write_text(_ENV_WITH_MISSING_PY_INTERPRETER)
        testing_utils.clear_all_functools_cache()

        py_file = testing_pkg.add_file(
            'solution.py', src='program_test/simple_hello.py'
        )
        solution = CodeItem(path=py_file, language='py')
        compiled_digest = await code.compile_item(solution)

        input_file = testing_pkg.add_file('test.in')
        input_file.write_text('')
        output_file = testing_pkg.path('test.ans')
        output_file.write_text('Hello, World!\n')
        testcase = Testcase(inputPath=input_file, outputPath=output_file)

        output_dir = testing_pkg.path('outputs')
        output_dir.mkdir(exist_ok=True)

        # Should not raise; the missing interpreter must be surfaced as a verdict.
        evaluation = await tasks.run_solution_on_testcase(
            solution=solution,
            compiled_digest=compiled_digest,
            checker_digest=None,
            testcase=testcase,
            output_dir=output_dir,
            verification=VerificationLevel.NONE,
            use_retries=False,
        )

        assert evaluation is not None
        assert evaluation.result.outcome == Outcome.INTERNAL_ERROR
        assert 'not found' in evaluation.result.message.lower()
        assert 'rbx-not-a-real-interpreter' in evaluation.result.message


class TestRunCommunicationSolutionOnTestcase:
    """Test suite for _run_communication_solution_on_testcase function."""

    async def test_communication_solution_without_explicit_language(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that communication solutions without explicit language work correctly.

        Regression test for the fix in _run_communication_solution_on_testcase
        where solution.language was accessed directly instead of using
        find_language_name().
        """
        # Create a simple Python program without specifying language
        py_file = testing_pkg.add_file(
            'solution.py', src='program_test/simple_hello.py'
        )
        solution = CodeItem(path=py_file)  # language not set

        # Verify language is None
        assert solution.language is None

        # Set task type to COMMUNICATION to allow interactor
        from rbx.box.schema import TaskType

        testing_pkg.set_type(TaskType.COMMUNICATION)

        # Create a simple interactor
        interactor_content = """
import sys

# Read input
input_data = open('interactor.in').read()

# Write output
with open('interactor.out', 'w') as f:
    f.write('0\\n')  # Score

sys.exit(0)
"""
        interactor_file = testing_pkg.add_file('interactor.py')
        interactor_file.write_text(interactor_content)

        # Set interactor in package
        testing_pkg.set_interactor('interactor.py', language='py')

        # Compile both
        compiled_digest = await code.compile_item(solution)
        interactor_digest = await code.compile_item(testing_pkg.yml.interactor)

        # Create testcase
        input_file = testing_pkg.add_file('test.in')
        input_file.write_text('')
        output_file = testing_pkg.path('test.ans')
        output_file.write_text('')

        testcase = Testcase(
            inputPath=input_file,
            outputPath=output_file,
        )

        # Create output directory
        output_dir = testing_pkg.path('outputs')
        output_dir.mkdir(exist_ok=True)

        # Run communication solution - this tests the fix in
        # _run_communication_solution_on_testcase
        evaluation = await tasks.run_solution_on_testcase(
            solution=solution,
            compiled_digest=compiled_digest,
            checker_digest=None,
            testcase=testcase,
            output_dir=output_dir,
            interactor_digest=interactor_digest,
            verification=VerificationLevel.NONE,
            use_retries=False,
            capture_pipes=False,
        )

        # Verify execution succeeded
        assert evaluation is not None
        assert evaluation.log is not None
        # Communication tasks may have different exit statuses
        assert evaluation.log.exitstatus in [
            SandboxBase.EXIT_OK,
            SandboxBase.EXIT_NONZERO_RETURN,
        ]


class TestGetLimitsForLanguage:
    """Test get_limits_for_language and how it populates configuredTime."""

    def test_enforced_and_configured_time_match_by_default(
        self, testing_pkg: testing_package.TestingPackage
    ):
        limits = tasks.get_limits_for_language(
            'cpp', VerificationLevel.NONE, timelimit_override=None
        )
        assert limits.time == 1000  # testing_pkg timeLimit
        assert limits.configuredTime == 1000

    def test_disabling_enforcement_keeps_configured_time(
        self, testing_pkg: testing_package.TestingPackage
    ):
        # use_timelimit=False nulls the enforced TL but must keep the declared
        # one so reporting can still show it without re-reading from disk.
        limits = tasks.get_limits_for_language(
            'cpp', VerificationLevel.NONE, timelimit_override=None, use_timelimit=False
        )
        assert limits.time is None
        assert limits.configuredTime == 1000
        assert limits.display_time() == 1000

    def test_timelimit_override_sets_enforced_time_but_keeps_declared(
        self, testing_pkg: testing_package.TestingPackage
    ):
        # The override only changes the *enforced* TL. configuredTime stays the
        # declared profile TL, so reporting shows the real limit (matching the
        # old re-resolve-from-disk behavior, which ignored the override).
        limits = tasks.get_limits_for_language(
            'cpp', VerificationLevel.NONE, timelimit_override=500
        )
        assert limits.time == 500
        assert limits.configuredTime == 1000

    def test_unlimited_override_does_not_leak_into_displayed_limit(
        self, testing_pkg: testing_package.TestingPackage
    ):
        # Regression for #351 adversarial review: time-limit estimation runs with
        # the timelimit_override=-1 "unlimited" sentinel. It must null the
        # enforced TL without leaking -1 into the displayed/declared limit (the
        # old disk-reload re-resolved the real profile TL).
        limits = tasks.get_limits_for_language(
            'cpp', VerificationLevel.NONE, timelimit_override=-1
        )
        assert limits.time is None
        assert limits.configuredTime == 1000
        assert limits.display_time() == 1000


class TestKeepCheckerStderr:
    """`run_solution_on_testcase(keep_checker_stderr=...)` and its artifact."""

    async def _run(
        self,
        testing_pkg: testing_package.TestingPackage,
        keep_checker_stderr: bool,
    ):
        testing_pkg.set_checker('checker.cpp', src='checkers/checker-verbose.cpp')
        checker_digest = await checkers.compile_checker()

        py_file = testing_pkg.add_file(
            'solution.py', src='program_test/simple_hello.py'
        )
        solution = CodeItem(path=py_file)
        compiled_digest = await code.compile_item(solution)

        input_file = testing_pkg.add_file('test.in')
        input_file.write_text('')
        output_file = testing_pkg.path('test.ans')
        output_file.write_text('Hello, World!\n')

        output_dir = testing_pkg.path('outputs')
        output_dir.mkdir(exist_ok=True)

        return await tasks.run_solution_on_testcase(
            solution=solution,
            compiled_digest=compiled_digest,
            checker_digest=checker_digest,
            testcase=Testcase(inputPath=input_file, outputPath=output_file),
            output_dir=output_dir,
            verification=VerificationLevel.NONE,
            use_retries=False,
            keep_checker_stderr=keep_checker_stderr,
        )

    async def test_writes_checker_err_artifact_when_asked(
        self, testing_pkg: testing_package.TestingPackage
    ):
        evaluation = await self._run(testing_pkg, keep_checker_stderr=True)

        checker_stderr_path = evaluation.log.checker_stderr_absolute_path
        assert checker_stderr_path is not None
        assert checker_stderr_path.name == 'test.checker.err'
        contents = checker_stderr_path.read_text()
        assert 'diagnostic line 1' in contents
        assert 'diagnostic line 2' in contents
        # The verdict message is unchanged -- still the last line only.
        assert evaluation.result.message == 'wrong answer verdict line'

    async def test_writes_nothing_by_default(
        self, testing_pkg: testing_package.TestingPackage
    ):
        evaluation = await self._run(testing_pkg, keep_checker_stderr=False)

        assert evaluation.log.checker_stderr_absolute_path is None
        assert not list(testing_pkg.path('outputs').glob('*.checker.err'))


# The naming contract of a fanout verdict: pure functions, tested directly.
name_processes = tasks._name_processes  # noqa: SLF001
name_failing_process = tasks._name_failing_process  # noqa: SLF001


def _process_log(exitstatus: str = SandboxBase.EXIT_OK, exitcode: int = 0):
    from rbx.grading.steps import RunLog

    return RunLog(exitstatus=exitstatus, exitcode=exitcode)


class TestNameProcesses:
    def test_one_process(self):
        assert name_processes([3]) == 'process 3'

    def test_a_short_run_is_listed(self):
        assert name_processes([2, 0]) == 'processes 0, 2'
        assert name_processes([4, 5]) == 'processes 4, 5'

    def test_a_long_run_is_a_range(self):
        assert name_processes(list(range(16))) == 'processes 0-15'
        assert name_processes([0, 1, 2, 7]) == 'processes 0-2, 7'

    def test_abbreviated_after_six_runs(self):
        # The even processes of 16: eight runs of one.
        assert name_processes(list(range(0, 16, 2))) == (
            'processes 0, 2, 4, 6, 8, 10, ... (8 in all)'
        )


class TestNameFailingProcess:
    def _result(self, outcome: Outcome, message: str = 'boom'):
        from rbx.grading.steps import CheckerResult

        return CheckerResult(outcome=outcome, message=message)

    def test_one_process_is_left_untouched(self):
        logs = [_process_log(SandboxBase.EXIT_NONZERO_RETURN, 1)]

        result = name_failing_process(self._result(Outcome.RUNTIME_ERROR), 0, logs)

        assert result.message == 'boom'

    def test_the_deciding_process_is_named(self):
        logs = [
            _process_log(),
            _process_log(),
            _process_log(SandboxBase.EXIT_NONZERO_RETURN, 1),
        ]

        result = name_failing_process(self._result(Outcome.RUNTIME_ERROR), 2, logs)

        assert result.message == 'process 2: boom'

    def test_no_message_is_just_the_name(self):
        logs = [_process_log(SandboxBase.EXIT_NONZERO_RETURN, 1), _process_log()]

        result = name_failing_process(
            self._result(Outcome.RUNTIME_ERROR, message=''), 0, logs
        )

        assert result.message == 'process 0'

    def test_every_process_that_failed_like_the_decider_is_named(self):
        logs = [
            _process_log(SandboxBase.EXIT_TIMEOUT_WALL),
            _process_log(),
            _process_log(SandboxBase.EXIT_TIMEOUT_WALL),
        ]

        result = name_failing_process(
            self._result(Outcome.TIME_LIMIT_EXCEEDED, message=''), 2, logs
        )

        assert result.message == 'processes 0, 2'

    def test_processes_the_group_kill_stopped_are_not_named_beside_a_crash(self):
        logs = [
            _process_log(SandboxBase.EXIT_SIGNAL, -6),
            _process_log(SandboxBase.EXIT_SIGNAL, -9),
            _process_log(SandboxBase.EXIT_SIGNAL, -6),
            _process_log(SandboxBase.EXIT_SIGNAL, -9),
        ]

        result = name_failing_process(
            self._result(Outcome.RUNTIME_ERROR, message=''), 0, logs
        )

        assert result.message == 'processes 0, 2'

    def test_a_tle_with_no_decider_is_the_processes_together(self):
        logs = [_process_log(), _process_log(), _process_log()]

        result = name_failing_process(
            self._result(Outcome.TIME_LIMIT_EXCEEDED, message=''), None, logs
        )

        assert result.message == 'the processes together'

    def test_a_summed_tle_is_not_blamed_on_the_processes_that_crashed(self):
        # The summed CPU time is over the limit, and the decider crashed rather
        # than timing out: naming the crashed processes would call a crash a
        # time limit.
        logs = [
            _process_log(SandboxBase.EXIT_SIGNAL, -6),
            _process_log(),
            _process_log(SandboxBase.EXIT_SIGNAL, -6),
        ]

        result = name_failing_process(
            self._result(Outcome.TIME_LIMIT_EXCEEDED, message=''), 0, logs
        )

        assert result.message == 'the processes together'

    @pytest.mark.parametrize('decider', [None, 1])
    def test_an_interactor_verdict_never_names_a_process(self, decider: Optional[int]):
        logs = [
            _process_log(SandboxBase.EXIT_SIGNAL, -9),
            _process_log(SandboxBase.EXIT_SIGNAL, -9),
        ]

        result = name_failing_process(self._result(Outcome.WRONG_ANSWER), decider, logs)

        assert result.message == 'boom'

    def test_a_non_tle_without_a_decider_is_left_untouched(self):
        logs = [_process_log(), _process_log()]

        result = name_failing_process(self._result(Outcome.RUNTIME_ERROR), None, logs)

        assert result.message == 'boom'
