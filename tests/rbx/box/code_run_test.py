import asyncio
import pathlib
import resource
from unittest import mock

import pytest
import typer

from rbx.box import code, state
from rbx.box.environment import EnvironmentSandbox, ExecutionConfig
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.steps import (
    DigestOrDest,
    DigestOrSource,
    GradingFileInput,
    GradingFileOutput,
    RunLog,
)


class TestRunItem:
    """Test suite for run_item function."""

    def test_run_simple_python_program(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test basic execution of a simple Python program."""
        # Create a simple Python program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program (Python doesn't need compilation but creates digest)
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run the program
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0
        assert run_log.exitstatus == SandboxBase.EXIT_OK
        assert run_log.time is not None
        assert run_log.time >= 0
        assert run_log.memory is not None
        assert run_log.memory >= 0

        # Verify output was captured
        assert output_path.exists()
        assert output_path.read_text().strip() == 'Hello, World!'

        # Verify metadata
        assert run_log.metadata is not None
        assert run_log.metadata.language == 'py'
        assert run_log.metadata.is_sanitized is False

    def test_run_with_stdin_input(self, testing_pkg: testing_package.TestingPackage):
        """Test execution with stdin input."""
        # Create echo program
        py_file = testing_pkg.add_file('echo.py', src='program_test/input_echo.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create input file
        input_path = testing_pkg.path('input.txt')
        input_path.write_text('Hello\nWorld\n')
        stdin_source = DigestOrSource.create(input_path)

        # Create output destinations
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)
        error_path = testing_pkg.path('error.txt')
        stderr_dest = DigestOrDest.create(error_path)

        # Run the program
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdin=stdin_source,
                stdout=stdout_dest,
                stderr=stderr_dest,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0
        assert run_log.exitstatus == SandboxBase.EXIT_OK

        # Verify stdout output
        assert output_path.exists()
        stdout_content = output_path.read_text()
        assert 'Echo: Hello' in stdout_content
        assert 'Echo: World' in stdout_content

        # Verify stderr output
        assert error_path.exists()
        stderr_content = error_path.read_text()
        assert 'Read line: Hello' in stderr_content
        assert 'Read line: World' in stderr_content

    def test_run_with_extra_args(self, testing_pkg: testing_package.TestingPackage):
        """Test execution with extra command line arguments."""
        # Create program that accepts arguments
        py_file = testing_pkg.add_file(
            'exit_code.py', src='program_test/exit_with_code.py'
        )
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run with extra arguments
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
                extra_args='42',
            )
        )

        # Verify execution with expected exit code
        assert run_log is not None
        assert run_log.exitcode == 42
        assert run_log.exitstatus == SandboxBase.EXIT_NONZERO_RETURN

        # Verify output
        assert output_path.exists()
        assert 'Exiting with code 42' in output_path.read_text()

    def test_run_with_additional_input_files(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test execution with additional input files."""
        # Create a program that reads from a file
        py_content = """
import pathlib
content = pathlib.Path('data.txt').read_text()
print(f'File content: {content.strip()}')
"""
        py_file = testing_pkg.add_file('reader.py')
        py_file.write_text(py_content)
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create additional input file
        data_file = testing_pkg.add_file('data.txt')
        data_file.write_text('Hello from file!')

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run with additional input files
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
                inputs=[
                    GradingFileInput(
                        src=data_file,
                        dest=pathlib.Path('data.txt'),
                    )
                ],
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0
        assert run_log.exitstatus == SandboxBase.EXIT_OK

        # Verify output
        assert output_path.exists()
        assert 'File content: Hello from file!' in output_path.read_text()

    def test_run_with_additional_output_files(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test execution with additional output files."""
        # Create a program that writes to a file
        py_content = """
import pathlib
pathlib.Path('result.txt').write_text('Generated output')
print('Done')
"""
        py_file = testing_pkg.add_file('writer.py')
        py_file.write_text(py_content)
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create output destinations
        stdout_path = testing_pkg.path('stdout.txt')
        stdout_dest = DigestOrDest.create(stdout_path)
        result_path = testing_pkg.path('result.txt')

        # Run with additional output files
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
                outputs=[
                    GradingFileOutput(
                        src=pathlib.Path('result.txt'),
                        dest=result_path,
                    )
                ],
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0
        assert run_log.exitstatus == SandboxBase.EXIT_OK

        # Verify stdout
        assert stdout_path.exists()
        assert 'Done' in stdout_path.read_text()

        # Verify additional output file was captured
        assert result_path.exists()
        assert 'Generated output' in result_path.read_text()

    def test_run_with_custom_execution_config(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test execution with custom execution configuration."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create custom execution config with stricter limits
        custom_config = ExecutionConfig(
            sandbox=EnvironmentSandbox(
                timeLimit=1000, memoryLimit=512
            )  # 1 second, 512MB
        )

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run with custom config
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
                extra_config=custom_config,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0
        assert run_log.exitstatus == SandboxBase.EXIT_OK

        # Verify metadata includes custom limits
        assert run_log.metadata is not None
        assert run_log.metadata.timeLimit == 1000
        assert (
            run_log.metadata.memoryLimit == 512
        )  # Memory limit is stored as MiB, not bytes

    def test_run_with_retry_index(self, testing_pkg: testing_package.TestingPackage):
        """Test execution with retry index."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run with retry index
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
                retry_index=2,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0

        # Verify retry index is set in metadata
        assert run_log.metadata is not None
        assert run_log.metadata.retryIndex == 2

    def test_run_sanitized_executable_removes_limits(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that sanitized executables have memory and time limits removed."""
        # Create a C++ program (Python programs don't get sanitizer flags)
        cpp_file = testing_pkg.add_file('hello.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Compile with sanitization
        executable_digest = code.compile_item(
            code_item, sanitized=code.SanitizationLevel.FORCE
        )
        executable = DigestOrSource.create(executable_digest)

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run the sanitized executable
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0

        # Verify metadata indicates sanitization
        assert run_log.metadata is not None
        assert run_log.metadata.is_sanitized is True
        # Sanitized executables should have no memory/time limits
        assert run_log.metadata.timeLimit is None
        assert run_log.metadata.memoryLimit is None

    def test_run_sanitized_executable_captures_stderr(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that sanitized executables automatically capture stderr."""
        # Create a C++ program that writes to stderr
        cpp_content = """
#include <iostream>
int main() {
    std::cout << "Hello stdout" << std::endl;
    std::cerr << "Hello stderr" << std::endl;
    return 0;
}
"""
        cpp_file = testing_pkg.add_file('stderr_writer.cpp')
        cpp_file.write_text(cpp_content)
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Compile with sanitization
        executable_digest = code.compile_item(
            code_item, sanitized=code.SanitizationLevel.FORCE
        )
        executable = DigestOrSource.create(executable_digest)

        # Create output destination (only stdout, stderr should be auto-captured)
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run the sanitized executable
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0

        # Verify stdout was captured
        assert output_path.exists()
        assert 'Hello stdout' in output_path.read_text()

        # Verify metadata indicates sanitization
        assert run_log.metadata is not None
        assert run_log.metadata.is_sanitized is True

    def test_run_memory_limit_exceeded(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test execution that exceeds memory limits."""
        # Create memory-intensive program
        py_file = testing_pkg.add_file(
            'memory_hog.py', src='program_test/memory_hog.py'
        )
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create custom config with very low memory limit
        custom_config = ExecutionConfig(
            sandbox=EnvironmentSandbox(memoryLimit=1)  # 1MB - very restrictive
        )

        # Create output destinations
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)
        error_path = testing_pkg.path('error.txt')
        stderr_dest = DigestOrDest.create(error_path)

        # Run with restrictive memory limit
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
                stderr=stderr_dest,
                extra_config=custom_config,
            )
        )

        # Verify execution failed due to memory limit
        assert run_log is not None
        assert run_log.exitcode != 0
        # Should be either memory limit exceeded or killed by sandbox
        assert run_log.exitstatus in [
            SandboxBase.EXIT_SANDBOX_ERROR,
            SandboxBase.EXIT_SIGNAL,
            SandboxBase.EXIT_TIMEOUT,
            SandboxBase.EXIT_TIMEOUT_WALL,
            SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED,
        ]

    def test_run_timeout_exceeded(self, testing_pkg: testing_package.TestingPackage):
        """Test execution that exceeds time limits."""
        # Create infinite loop program
        py_file = testing_pkg.add_file(
            'infinite.py', src='program_test/cpu_intensive.py'
        )
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create custom config with very short timeout
        custom_config = ExecutionConfig(
            sandbox=EnvironmentSandbox(timeLimit=100)  # 100 ms timeout
        )

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run with short timeout
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
                extra_config=custom_config,
            )
        )

        # Verify execution was terminated due to timeout
        assert run_log is not None
        assert run_log.exitcode != 0
        assert run_log.exitstatus == SandboxBase.EXIT_TIMEOUT
        # Should have hit the timeout limit
        assert run_log.time is not None
        assert run_log.time >= 0.1

    def test_run_nonexistent_executable_fails(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that running with nonexistent executable fails gracefully."""
        # Create a code item but don't compile it
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Create fake executable digest
        executable = DigestOrSource.create('nonexistent_digest')

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run should fail with KeyError which gets converted to None
        with pytest.raises(KeyError):
            asyncio.run(
                code.run_item(
                    code_item,
                    executable,
                    stdout=stdout_dest,
                )
            )

    @mock.patch('rbx.box.code._check_stack_limit')
    def test_run_checks_stack_limit(
        self, mock_check_stack_limit, testing_pkg: testing_package.TestingPackage
    ):
        """Test that run_item checks stack limits."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Run the program
        asyncio.run(
            code.run_item(
                code_item,
                executable,
            )
        )

        # Verify stack limit was checked (may be called multiple times)
        assert mock_check_stack_limit.call_count >= 1

    def test_stack_limit_check_disabled_by_config(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test that stack limit checking can be disabled by configuration."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Mock the setter config to disable stack checking
        with mock.patch('rbx.box.code.setter_config.get_setter_config') as mock_config:
            mock_judging_config = mock.Mock()
            mock_judging_config.check_stack = False
            mock_config_obj = mock.Mock()
            mock_config_obj.judging = mock_judging_config
            mock_config_obj.substitute_command = mock.Mock(
                side_effect=lambda cmd, sanitized=False: cmd
            )
            mock_config.return_value = mock_config_obj

            # Enable CLI mode to allow stack checking
            original_cli_state = state.STATE.run_through_cli
            state.STATE.run_through_cli = True

            try:
                # Mock resource.getrlimit to return low stack limit
                with mock.patch('rbx.box.code.resource.getrlimit') as mock_getrlimit:
                    mock_getrlimit.return_value = (
                        8 * 1024 * 1024,
                        256 * 1024 * 1024,
                    )  # 8MB soft, 256MB hard

                    # Compile the program
                    executable_digest = code.compile_item(code_item)
                    executable = DigestOrSource.create(executable_digest)

                    # Run the program
                    run_log = asyncio.run(
                        code.run_item(
                            code_item,
                            executable,
                        )
                    )

                    # Verify execution succeeded
                    assert run_log is not None
                    assert run_log.exitcode == 0

                    # Verify no stack limit warning was printed
                    captured = capsys.readouterr()
                    assert 'Stack limit is too low' not in captured.out
                    assert 'Stack limit is too low' not in captured.err

            finally:
                state.STATE.run_through_cli = original_cli_state

    def test_stack_limit_check_disabled_by_cli_state(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test that stack limit checking is disabled when not run through CLI."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Mock the setter config to enable stack checking
        with mock.patch('rbx.box.code.setter_config.get_setter_config') as mock_config:
            mock_judging_config = mock.Mock()
            mock_judging_config.check_stack = True
            mock_config_obj = mock.Mock()
            mock_config_obj.judging = mock_judging_config
            mock_config_obj.substitute_command = mock.Mock(
                side_effect=lambda cmd, sanitized=False: cmd
            )
            mock_config.return_value = mock_config_obj

            # Ensure CLI mode is disabled
            original_cli_state = state.STATE.run_through_cli
            state.STATE.run_through_cli = False

            try:
                # Mock resource.getrlimit to return low stack limit
                with mock.patch('rbx.box.code.resource.getrlimit') as mock_getrlimit:
                    mock_getrlimit.return_value = (
                        8 * 1024 * 1024,
                        256 * 1024 * 1024,
                    )  # 8MB soft, 256MB hard

                    # Compile the program
                    executable_digest = code.compile_item(code_item)
                    executable = DigestOrSource.create(executable_digest)

                    # Run the program
                    run_log = asyncio.run(
                        code.run_item(
                            code_item,
                            executable,
                        )
                    )

                    # Verify execution succeeded
                    assert run_log is not None
                    assert run_log.exitcode == 0

                    # Verify no stack limit warning was printed
                    captured = capsys.readouterr()
                    assert 'Stack limit is too low' not in captured.out
                    assert 'Stack limit is too low' not in captured.err

            finally:
                state.STATE.run_through_cli = original_cli_state

    def test_stack_limit_check_warns_on_low_stack_limit(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test that stack limit checking warns when stack limit is too low."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Mock the setter config to enable stack checking
        with mock.patch('rbx.box.code.setter_config.get_setter_config') as mock_config:
            mock_judging_config = mock.Mock()
            mock_judging_config.check_stack = True
            mock_config_obj = mock.Mock()
            mock_config_obj.judging = mock_judging_config
            mock_config_obj.substitute_command = mock.Mock(
                side_effect=lambda cmd, sanitized=False: cmd
            )
            mock_config.return_value = mock_config_obj

            # Enable CLI mode to allow stack checking
            original_cli_state = state.STATE.run_through_cli
            state.STATE.run_through_cli = True

            try:
                # Mock resource.getrlimit to return low stack limit
                with mock.patch('rbx.box.code.resource.getrlimit') as mock_getrlimit:
                    mock_getrlimit.return_value = (
                        8 * 1024 * 1024,
                        256 * 1024 * 1024,
                    )  # 8MB soft, 256MB hard

                    # Compile should fail with typer.Exit due to low stack limit
                    with pytest.raises(typer.Exit):
                        code.compile_item(code_item)

                    # Verify stack limit warning was printed
                    captured = capsys.readouterr()
                    assert 'Stack limit is too low' in captured.out
                    assert '8' in captured.out and 'MiB' in captured.out  # soft limit
                    assert '256' in captured.out and 'MiB' in captured.out  # hard limit
                    assert 'ulimit -s' in captured.out
                    assert 'rbx' in captured.out

            finally:
                state.STATE.run_through_cli = original_cli_state

    def test_stack_limit_check_no_warning_on_sufficient_stack_limit(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test that stack limit checking doesn't warn when stack limit is sufficient."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Mock the setter config to enable stack checking
        with mock.patch('rbx.box.code.setter_config.get_setter_config') as mock_config:
            mock_judging_config = mock.Mock()
            mock_judging_config.check_stack = True
            mock_config_obj = mock.Mock()
            mock_config_obj.judging = mock_judging_config
            mock_config_obj.substitute_command = mock.Mock(
                side_effect=lambda cmd, sanitized=False: cmd
            )
            mock_config.return_value = mock_config_obj

            # Enable CLI mode to allow stack checking
            original_cli_state = state.STATE.run_through_cli
            state.STATE.run_through_cli = True

            try:
                # Mock resource.getrlimit to return sufficient stack limit
                with mock.patch('rbx.box.code.resource.getrlimit') as mock_getrlimit:
                    mock_getrlimit.return_value = (
                        512 * 1024 * 1024,
                        512 * 1024 * 1024,
                    )  # 512MB soft and hard

                    # Compile the program
                    executable_digest = code.compile_item(code_item)
                    executable = DigestOrSource.create(executable_digest)

                    # Run the program
                    run_log = asyncio.run(
                        code.run_item(
                            code_item,
                            executable,
                        )
                    )

                    # Verify execution succeeded
                    assert run_log is not None
                    assert run_log.exitcode == 0

                    # Verify no stack limit warning was printed
                    captured = capsys.readouterr()
                    assert 'Stack limit is too low' not in captured.out
                    assert 'Stack limit is too low' not in captured.err

            finally:
                state.STATE.run_through_cli = original_cli_state

    def test_stack_limit_check_no_warning_on_unlimited_stack(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test that stack limit checking doesn't warn when stack limit is unlimited."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Mock the setter config to enable stack checking
        with mock.patch('rbx.box.code.setter_config.get_setter_config') as mock_config:
            mock_judging_config = mock.Mock()
            mock_judging_config.check_stack = True
            mock_config_obj = mock.Mock()
            mock_config_obj.judging = mock_judging_config
            mock_config_obj.substitute_command = mock.Mock(
                side_effect=lambda cmd, sanitized=False: cmd
            )
            mock_config.return_value = mock_config_obj

            # Enable CLI mode to allow stack checking
            original_cli_state = state.STATE.run_through_cli
            state.STATE.run_through_cli = True

            try:
                # Mock resource.getrlimit to return unlimited stack limit
                with mock.patch('rbx.box.code.resource.getrlimit') as mock_getrlimit:
                    mock_getrlimit.return_value = (
                        resource.RLIM_INFINITY,
                        resource.RLIM_INFINITY,
                    )

                    # Compile the program
                    executable_digest = code.compile_item(code_item)
                    executable = DigestOrSource.create(executable_digest)

                    # Run the program
                    run_log = asyncio.run(
                        code.run_item(
                            code_item,
                            executable,
                        )
                    )

                    # Verify execution succeeded
                    assert run_log is not None
                    assert run_log.exitcode == 0

                    # Verify no stack limit warning was printed
                    captured = capsys.readouterr()
                    assert 'Stack limit is too low' not in captured.out
                    assert 'Stack limit is too low' not in captured.err

            finally:
                state.STATE.run_through_cli = original_cli_state

    def test_stack_limit_check_formats_memory_correctly(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test that stack limit checking formats memory limits correctly."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Mock the setter config to enable stack checking
        with mock.patch('rbx.box.code.setter_config.get_setter_config') as mock_config:
            mock_judging_config = mock.Mock()
            mock_judging_config.check_stack = True
            mock_config_obj = mock.Mock()
            mock_config_obj.judging = mock_judging_config
            mock_config_obj.substitute_command = mock.Mock(
                side_effect=lambda cmd, sanitized=False: cmd
            )
            mock_config.return_value = mock_config_obj

            # Enable CLI mode to allow stack checking
            original_cli_state = state.STATE.run_through_cli
            state.STATE.run_through_cli = True

            try:
                # Mock resource.getrlimit to return small stack limit in bytes
                with mock.patch('rbx.box.code.resource.getrlimit') as mock_getrlimit:
                    mock_getrlimit.return_value = (
                        1024 * 1024,
                        2 * 1024 * 1024,
                    )  # 1MB soft, 2MB hard

                    # Compile should fail with typer.Exit due to low stack limit
                    with pytest.raises(typer.Exit):
                        code.compile_item(code_item)

                    # Verify stack limit warning was printed with correct formatting
                    captured = capsys.readouterr()
                    assert 'Stack limit is too low' in captured.out
                    assert '1' in captured.out and 'MiB' in captured.out  # soft limit
                    assert '2' in captured.out and 'MiB' in captured.out  # hard limit

            finally:
                state.STATE.run_through_cli = original_cli_state

    def test_stack_limit_check_handles_getrlimit_exception(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test that stack limit checking handles getrlimit exceptions gracefully."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Mock the setter config to enable stack checking
        with mock.patch('rbx.box.code.setter_config.get_setter_config') as mock_config:
            mock_judging_config = mock.Mock()
            mock_judging_config.check_stack = True
            mock_config_obj = mock.Mock()
            mock_config_obj.judging = mock_judging_config
            mock_config_obj.substitute_command = mock.Mock(
                side_effect=lambda cmd, sanitized=False: cmd
            )
            mock_config.return_value = mock_config_obj

            # Enable CLI mode to allow stack checking
            original_cli_state = state.STATE.run_through_cli
            state.STATE.run_through_cli = True

            try:
                # Mock resource.getrlimit to raise an exception
                with mock.patch('rbx.box.code.resource.getrlimit') as mock_getrlimit:
                    mock_getrlimit.side_effect = OSError('getrlimit failed')

                    # Compile the program (should succeed despite exception)
                    executable_digest = code.compile_item(code_item)
                    executable = DigestOrSource.create(executable_digest)

                    # Run the program
                    run_log = asyncio.run(
                        code.run_item(
                            code_item,
                            executable,
                        )
                    )

                    # Verify execution succeeded
                    assert run_log is not None
                    assert run_log.exitcode == 0

                    # Verify no stack limit warning was printed (exception handled)
                    captured = capsys.readouterr()
                    assert 'Stack limit is too low' not in captured.out
                    assert 'Stack limit is too low' not in captured.err

            finally:
                state.STATE.run_through_cli = original_cli_state

    def test_stack_limit_check_calculates_target_correctly_with_hard_limit(
        self, testing_pkg: testing_package.TestingPackage, capsys
    ):
        """Test that stack limit checking calculates target correctly when hard limit is lower than 256MB."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Mock the setter config to enable stack checking
        with mock.patch('rbx.box.code.setter_config.get_setter_config') as mock_config:
            mock_judging_config = mock.Mock()
            mock_judging_config.check_stack = True
            mock_config_obj = mock.Mock()
            mock_config_obj.judging = mock_judging_config
            mock_config_obj.substitute_command = mock.Mock(
                side_effect=lambda cmd, sanitized=False: cmd
            )
            mock_config.return_value = mock_config_obj

            # Enable CLI mode to allow stack checking
            original_cli_state = state.STATE.run_through_cli
            state.STATE.run_through_cli = True

            try:
                # Mock resource.getrlimit to return low hard limit
                with mock.patch('rbx.box.code.resource.getrlimit') as mock_getrlimit:
                    mock_getrlimit.return_value = (
                        8 * 1024 * 1024,
                        64 * 1024 * 1024,
                    )  # 8MB soft, 64MB hard

                    # Compile should fail with typer.Exit due to low stack limit
                    with pytest.raises(typer.Exit):
                        code.compile_item(code_item)

                    # Verify stack limit warning was printed with correct ulimit value
                    captured = capsys.readouterr()
                    assert 'Stack limit is too low' in captured.out
                    assert 'ulimit -s 65536' in captured.out  # 64MB / 1024 = 65536 KB

            finally:
                state.STATE.run_through_cli = original_cli_state

    def test_run_with_warnings_detection(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that run_item detects warnings in sanitized executables."""
        # Create a C++ program that will definitely trigger sanitizer warnings
        cpp_content = """
#include <iostream>
int main() {
    int* ptr = new int[10];
    std::cout << "Value: " << ptr[0] << std::endl;
    // Intentionally access out-of-bounds to trigger AddressSanitizer
    std::cout << "Out of bounds: " << ptr[15] << std::endl;  // heap-buffer-overflow
    return 0;
}
"""
        cpp_file = testing_pkg.add_file('warning_test.cpp')
        cpp_file.write_text(cpp_content)
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Compile with sanitization
        executable_digest = code.compile_item(
            code_item, sanitized=code.SanitizationLevel.FORCE
        )
        executable = DigestOrSource.create(executable_digest)

        # Create output destinations
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)
        error_path = testing_pkg.path('error.txt')
        stderr_dest = DigestOrDest.create(error_path)

        # Mock warning stack to test warning detection
        with mock.patch(
            'rbx.box.code.warning_stack.get_warning_stack'
        ) as mock_warning_stack:
            mock_stack = mock.Mock()
            mock_warning_stack.return_value = mock_stack

            # Run the program
            run_log = asyncio.run(
                code.run_item(
                    code_item,
                    executable,
                    stdout=stdout_dest,
                    stderr=stderr_dest,
                )
            )

            # Verify execution succeeded
            assert run_log is not None
            assert run_log.exitcode == -6

            # If there were warnings, the warning stack should be called
            assert run_log.warnings
            mock_stack.add_sanitizer_warning.assert_called_once()

    def test_run_python_program_not_sanitized(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that Python programs are never marked as sanitized."""
        # Create a simple Python program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile with sanitization (but Python programs don't get sanitizer flags)
        executable_digest = code.compile_item(
            code_item, sanitized=code.SanitizationLevel.FORCE
        )
        executable = DigestOrSource.create(executable_digest)

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run the executable
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0

        # Verify metadata indicates no sanitization (Python programs don't get sanitized)
        assert run_log.metadata is not None
        assert run_log.metadata.is_sanitized is False
        # Should still have normal limits
        assert run_log.metadata.timeLimit is not None
        assert run_log.metadata.memoryLimit is not None

    def test_run_cpp_program(self, testing_pkg: testing_package.TestingPackage):
        """Test execution of a C++ program."""
        # Create a simple C++ program
        cpp_file = testing_pkg.add_file('hello.cpp', src='compile_test/simple.cpp')
        code_item = CodeItem(path=cpp_file, language='cpp')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run the program
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0
        assert run_log.exitstatus == SandboxBase.EXIT_OK

        # Verify output was captured
        assert output_path.exists()
        # The simple.cpp program should produce some output
        assert len(output_path.read_text()) > 0

        # Verify metadata
        assert run_log.metadata is not None
        assert run_log.metadata.language == 'cpp'

    def test_run_java_program(self, testing_pkg: testing_package.TestingPackage):
        """Test execution of a Java program."""
        # Create a simple Java program
        java_file = testing_pkg.add_file(
            'Solution.java', src='compile_test/simple.java'
        )
        code_item = CodeItem(path=java_file, language='java')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create output destination
        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        # Run the program
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                stdout=stdout_dest,
            )
        )

        # Verify execution succeeded
        assert run_log is not None
        assert run_log.exitcode == 0
        assert run_log.exitstatus == SandboxBase.EXIT_OK

        # Verify output was captured
        assert output_path.exists()
        # The simple.java program should produce some output
        assert len(output_path.read_text()) > 0

        # Verify metadata
        assert run_log.metadata is not None
        assert run_log.metadata.language == 'java'

    def test_run_returns_none_on_sandbox_failure(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that run_item returns None when sandbox fails completely."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Mock steps_with_caching.run to return None (complete failure)
        with mock.patch('rbx.box.code.steps_with_caching.run') as mock_run:
            mock_run.return_value = None

            # Run the program
            run_log = asyncio.run(
                code.run_item(
                    code_item,
                    executable,
                )
            )

            # Verify None is returned on complete failure
            assert run_log is None

    def test_run_metadata_contains_correct_information(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that RunLogMetadata contains all expected information."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create custom config
        custom_config = ExecutionConfig(
            sandbox=EnvironmentSandbox(
                timeLimit=10000, memoryLimit=128
            )  # 10 seconds, 128MB
        )

        # Run with custom config and retry index
        run_log = asyncio.run(
            code.run_item(
                code_item,
                executable,
                extra_config=custom_config,
                retry_index=3,
            )
        )

        # Verify metadata is complete
        assert run_log is not None
        assert run_log.metadata is not None

        metadata = run_log.metadata
        assert metadata.language == 'py'
        assert metadata.is_sanitized is False
        assert metadata.timeLimit == 10000
        assert metadata.memoryLimit == 128  # Memory limit is stored as MiB, not bytes
        assert metadata.retryIndex == 3
        assert metadata.limits is not None

    def test_run_artifacts_setup_correctly(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that artifacts are set up correctly for execution."""
        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Create input/output files
        input_path = testing_pkg.path('input.txt')
        input_path.write_text('test input')
        stdin_source = DigestOrSource.create(input_path)

        output_path = testing_pkg.path('output.txt')
        stdout_dest = DigestOrDest.create(output_path)

        error_path = testing_pkg.path('error.txt')
        stderr_dest = DigestOrDest.create(error_path)

        # Mock steps_with_caching.run to inspect artifacts
        with mock.patch('rbx.box.code.steps_with_caching.run') as mock_run:
            mock_run.return_value = RunLog(
                exitcode=0,
                exitstatus=SandboxBase.EXIT_OK,
                time=0.1,
                memory=1024,
                sandbox='test',
            )

            # Run the program
            asyncio.run(
                code.run_item(
                    code_item,
                    executable,
                    stdin=stdin_source,
                    stdout=stdout_dest,
                    stderr=stderr_dest,
                )
            )

            # Verify artifacts were set up correctly
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs
            artifacts = call_kwargs['artifacts']

            # Should have executable input
            executable_inputs = [inp for inp in artifacts.inputs if inp.executable]
            assert len(executable_inputs) == 1

            # Should have stdin input
            stdin_inputs = [
                inp
                for inp in artifacts.inputs
                if not inp.executable and inp.src == input_path
            ]
            assert len(stdin_inputs) == 1

            # Should have stdout and stderr outputs
            outputs = artifacts.outputs
            assert len(outputs) == 2

            # Verify output destinations
            output_dests = [out.dest for out in outputs]
            assert any('output' in str(dest) for dest in output_dests)
            assert any('error' in str(dest) for dest in output_dests)

    @mock.patch('rbx.box.code.is_path_remote')
    def test_run_remote_path_disables_caching(
        self, mock_is_remote, testing_pkg: testing_package.TestingPackage
    ):
        """Test that remote paths disable caching during execution."""
        # Make the path appear remote
        mock_is_remote.return_value = True

        # Create a simple program
        py_file = testing_pkg.add_file('hello.py', src='program_test/simple_hello.py')
        code_item = CodeItem(path=py_file, language='py')

        # Compile the program
        executable_digest = code.compile_item(code_item)
        executable = DigestOrSource.create(executable_digest)

        # Mock grading_context.cache_level to verify it's called
        with mock.patch('rbx.box.code.grading_context.cache_level') as mock_cache_level:
            mock_cache_level.return_value.__enter__ = mock.Mock()
            mock_cache_level.return_value.__exit__ = mock.Mock()

            # Run the program
            asyncio.run(
                code.run_item(
                    code_item,
                    executable,
                )
            )

            # Verify caching was disabled for remote path (may be called multiple times)
            assert mock_cache_level.call_count >= 1
            # Verify at least one call was for NO_CACHE with a when condition
            calls = mock_cache_level.call_args_list
            no_cache_calls = [call for call in calls if 'when' in call.kwargs]
            assert len(no_cache_calls) >= 1
            # Verify the when condition returns True for remote path
            when_func = no_cache_calls[0].kwargs['when']
            assert when_func() is True
