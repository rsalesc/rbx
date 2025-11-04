import asyncio

from rbx.box import code, tasks
from rbx.box.environment import VerificationLevel
from rbx.box.schema import CodeItem, Testcase
from rbx.box.testing import testing_package
from rbx.grading.judge.sandbox import SandboxBase


class TestRunSolutionOnTestcase:
    """Test suite for run_solution_on_testcase function."""

    def test_run_solution_without_explicit_language(
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
        compiled_digest = code.compile_item(solution)

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
        evaluation = asyncio.run(
            tasks.run_solution_on_testcase(
                solution=solution,
                compiled_digest=compiled_digest,
                checker_digest=None,
                testcase=testcase,
                output_dir=output_dir,
                verification=VerificationLevel.NONE,
                use_retries=False,
            )
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

    def test_run_solution_without_explicit_language_cpp(
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
        compiled_digest = code.compile_item(solution)

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
        evaluation = asyncio.run(
            tasks.run_solution_on_testcase(
                solution=solution,
                compiled_digest=compiled_digest,
                checker_digest=None,
                testcase=testcase,
                output_dir=output_dir,
                verification=VerificationLevel.NONE,
                use_retries=False,
            )
        )

        # Verify execution succeeded
        assert evaluation is not None
        assert evaluation.log is not None
        assert evaluation.log.exitcode == 0
        assert evaluation.log.exitstatus == SandboxBase.EXIT_OK

        # Verify output was generated
        output_path = output_dir / 'test.out'
        assert output_path.exists()

    def test_run_solution_with_explicit_language_still_works(
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
        compiled_digest = code.compile_item(solution)

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
        evaluation = asyncio.run(
            tasks.run_solution_on_testcase(
                solution=solution,
                compiled_digest=compiled_digest,
                checker_digest=None,
                testcase=testcase,
                output_dir=output_dir,
                verification=VerificationLevel.NONE,
                use_retries=False,
            )
        )

        # Verify execution succeeded
        assert evaluation is not None
        assert evaluation.log is not None
        assert evaluation.log.exitcode == 0
        assert evaluation.log.exitstatus == SandboxBase.EXIT_OK


class TestRunCommunicationSolutionOnTestcase:
    """Test suite for _run_communication_solution_on_testcase function."""

    def test_communication_solution_without_explicit_language(
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
        compiled_digest = code.compile_item(solution)
        interactor_digest = code.compile_item(testing_pkg.yml.interactor)

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
        evaluation = asyncio.run(
            tasks.run_solution_on_testcase(
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
        )

        # Verify execution succeeded
        assert evaluation is not None
        assert evaluation.log is not None
        # Communication tasks may have different exit statuses
        assert evaluation.log.exitstatus in [
            SandboxBase.EXIT_OK,
            SandboxBase.EXIT_NONZERO_RETURN,
        ]
