import pathlib
from unittest.mock import patch

import pytest
import typer

from rbx.grading import steps
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    GradingLogsHolder,
)


@pytest.fixture(autouse=True)
def clear_steps_cache():
    """Clear all cached functions in steps.py before each test."""
    # Clear all cached functions to ensure clean state between tests
    steps._complain_about_clang.cache_clear()  # noqa: SLF001
    steps._get_cxx_version_output.cache_clear()  # noqa: SLF001
    steps._maybe_complain_about_sanitization.cache_clear()  # noqa: SLF001
    steps._try_following_alias_for_exe.cache_clear()  # noqa: SLF001


class TestStepsCompile:
    """Test the steps.compile function."""

    def test_compile_empty_commands_returns_true(
        self, sandbox: SandboxBase, cleandir: pathlib.Path
    ):
        """Test that compile returns True when no commands are provided."""
        params = SandboxParams()
        artifacts = GradingArtifacts(root=cleandir)

        result = steps.compile([], params, sandbox, artifacts)

        assert result is True

    def test_compile_successful_cpp_compilation(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test successful C++ compilation."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'simple.cpp'
        output_file = cleandir / 'simple'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('simple.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('simple'),
                dest=pathlib.Path('simple'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -o simple simple.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is True
        assert output_file.exists()
        assert output_file.stat().st_mode & 0o111  # Check executable bit
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1
        assert artifacts.logs.preprocess[0].exitcode == 0

    def test_compile_successful_python_no_compilation(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that Python files don't need compilation."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'simple.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('simple.py'))
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = []  # Python doesn't need compilation

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is True
        assert artifacts.logs.preprocess is None or len(artifacts.logs.preprocess) == 0

    def test_compile_java_compilation_removes_memory_constraints(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that Java compilation removes memory constraints."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'simple.java'
        output_file = cleandir / 'Simple.class'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('Simple.java'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('Simple.class'),
                dest=pathlib.Path('Simple.class'),
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(address_space=1024)  # Set memory constraint
        commands = ['javac Simple.java']

        # Use mock to capture the params passed to sandbox.run
        with patch.object(sandbox, 'run', wraps=sandbox.run) as mock_run:
            result = steps.compile(commands, params, sandbox, artifacts)

            assert result is True
            assert output_file.exists()
            # Original params should not be modified
            assert params.address_space == 1024
            # But the params passed to sandbox.run should have address_space removed
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            captured_params = call_args[0][1]  # Second argument (params)
            assert captured_params.address_space is None

    def test_compile_compilation_error_returns_false(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that compilation errors return False."""
        # Setup input file with compilation error
        source_file = testdata_path / 'compile_test' / 'error.cpp'
        output_file = cleandir / 'error'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('error.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('error'),
                dest=pathlib.Path('error'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -o error error.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is False
        assert not output_file.exists()  # No output file should be created on error
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1
        assert artifacts.logs.preprocess[0].exitcode != 0

    def test_compile_detects_compilation_warnings(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that compilation warnings are detected."""
        # Setup input file with warnings
        source_file = testdata_path / 'compile_test' / 'warning.cpp'
        output_file = cleandir / 'warning'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('warning.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('warning'),
                dest=pathlib.Path('warning'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -Wall -o warning warning.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is True
        assert output_file.exists()
        assert output_file.stat().st_mode & 0o111  # Check executable bit
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1
        assert artifacts.logs.preprocess[0].exitcode == 0

        # Check that warnings are actually detected
        log = artifacts.logs.preprocess[0]
        assert log.warnings is True  # The warnings flag should be set
        assert 'warning' in log.log.lower()  # The log should contain warning text
        assert (
            'unused_variable' in log.log or 'unused' in log.log
        )  # Should mention the unused variable

    def test_compile_multiple_commands_stops_on_first_error(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that multiple commands stop on first error."""
        # Setup input files
        source_file1 = testdata_path / 'compile_test' / 'simple.cpp'
        source_file2 = testdata_path / 'compile_test' / 'error.cpp'
        output_file1 = cleandir / 'simple'
        output_file2 = cleandir / 'error'
        output_file3 = cleandir / 'third_output.txt'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(src=source_file1, dest=pathlib.Path('simple.cpp')),
                GradingFileInput(src=source_file2, dest=pathlib.Path('error.cpp')),
            ]
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('simple'),
                    dest=pathlib.Path('simple'),
                    executable=True,
                ),
                GradingFileOutput(
                    src=pathlib.Path('error'),
                    dest=pathlib.Path('error'),
                    executable=True,
                ),
                GradingFileOutput(
                    src=pathlib.Path('third_output.txt'),
                    dest=pathlib.Path('third_output.txt'),
                    optional=True,
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = [
            'g++ -o simple simple.cpp',  # This should succeed
            'g++ -o error error.cpp',  # This should fail
            "echo 'This should not run' > third_output.txt",  # This should not be executed
        ]

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is False
        # When compilation fails, no output artifacts are processed
        # So even though the first command succeeded, no files are copied out
        assert not output_file1.exists()  # No output artifacts processed on failure
        assert not output_file2.exists()  # Second command failed
        assert not output_file3.exists()  # Third command never ran
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 2  # Only first two commands executed
        assert artifacts.logs.preprocess[0].exitcode == 0  # First command succeeded
        assert artifacts.logs.preprocess[1].exitcode != 0  # Second command failed

    def test_compile_multiple_commands_all_succeed(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that multiple commands all succeed."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'multi_step.cpp'
        object_file = cleandir / 'multi_step.o'
        output_file = cleandir / 'multi_step'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('multi_step.cpp'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('multi_step.o'),
                    dest=pathlib.Path('multi_step.o'),
                ),
                GradingFileOutput(
                    src=pathlib.Path('multi_step'),
                    dest=pathlib.Path('multi_step'),
                    executable=True,
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = [
            'g++ -c multi_step.cpp',  # Compile to object file
            'g++ -o multi_step multi_step.o',  # Link to executable
        ]

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is True
        assert object_file.exists()
        assert output_file.exists()
        assert output_file.stat().st_mode & 0o111  # Check executable bit
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 2
        assert all(log.exitcode == 0 for log in artifacts.logs.preprocess)

    def test_compile_with_input_and_output_artifacts(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that input and output artifacts are handled correctly."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'simple.cpp'
        output_file = cleandir / 'simple'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('simple.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('simple'),
                dest=pathlib.Path('simple'),
                executable=True,
            )
        )

        params = SandboxParams()
        commands = ['g++ -o simple simple.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is True
        assert output_file.exists()
        assert output_file.stat().st_mode & 0o111  # Check executable bit

    def test_compile_output_artifact_processing_failure_returns_false(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that missing required output artifacts cause failure."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'simple.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('simple.cpp'))
        )
        # Expect a file that won't be created
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('nonexistent_file'),
                dest=pathlib.Path('nonexistent_file'),
                optional=False,  # This is required
            )
        )

        params = SandboxParams()
        commands = ['g++ -o simple simple.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is False

    def test_compile_optional_output_artifacts_dont_cause_failure(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that missing optional output artifacts don't cause failure."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'simple.cpp'
        output_file = cleandir / 'simple'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('simple.cpp'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('simple'),
                    dest=pathlib.Path('simple'),
                    executable=True,
                ),
                GradingFileOutput(
                    src=pathlib.Path('optional_file'),
                    dest=pathlib.Path('optional_file'),
                    optional=True,  # This is optional
                ),
            ]
        )

        params = SandboxParams()
        commands = ['g++ -o simple simple.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is True
        assert output_file.exists()

    def test_compile_creates_stdout_stderr_files_in_sandbox(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that stdout and stderr files are created in the sandbox."""
        # Setup input file with compilation error to generate stderr
        source_file = testdata_path / 'compile_test' / 'error.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('error.cpp'))
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -o error error.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is False
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1

        # Check that the log contains stderr output (compilation error)
        log = artifacts.logs.preprocess[0]
        assert log.log is not None
        assert len(log.log) > 0
        # Should contain error information
        assert 'error' in log.log.lower() or 'undeclared' in log.log.lower()

    def test_compile_with_sanitizer_command(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test compilation with sanitizer flags."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'sanitizer.cpp'
        output_file = cleandir / 'sanitizer'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('sanitizer.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('sanitizer'),
                dest=pathlib.Path('sanitizer'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        # Use a sanitizer flag that should work on most systems
        commands = ['g++ -fsanitize=address -o sanitizer sanitizer.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        # Note: This might fail on some systems without proper sanitizer support
        # but we're testing the function's behavior, not the compiler's capabilities
        if result:
            assert output_file.exists()
            assert output_file.stat().st_mode & 0o111  # Check executable bit

        # Regardless of success/failure, logs should be created
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1

    def test_compile_logs_contain_command_and_outputs(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that logs contain the command and its outputs."""
        # Setup input file
        source_file = testdata_path / 'compile_test' / 'simple.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('simple.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('simple'),
                dest=pathlib.Path('simple'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -o simple simple.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is True
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1
        log = artifacts.logs.preprocess[0]

        # Check that command is recorded
        assert isinstance(log.cmd, list)
        assert len(log.cmd) > 0
        # Command may be resolved to full path, so check the expected parts are present
        expected_parts = ['-o', 'simple', 'simple.cpp']
        assert all(part in log.cmd for part in expected_parts)
        assert any('g++' in part for part in log.cmd)  # g++ might be full path

        # Check that log contains output information
        assert isinstance(log.log, str)
        assert log.exitcode == 0
        assert log.time is not None
        assert log.memory is not None

    def test_compile_with_multiple_input_files(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test compilation with multiple input files."""
        # Setup multiple input files that can be compiled together
        header_file = testdata_path / 'compile_test' / 'math_utils.h'
        impl_file = testdata_path / 'compile_test' / 'math_utils.cpp'
        main_file = testdata_path / 'compile_test' / 'main_with_utils.cpp'
        output_file = cleandir / 'combined'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(src=header_file, dest=pathlib.Path('math_utils.h')),
                GradingFileInput(src=impl_file, dest=pathlib.Path('math_utils.cpp')),
                GradingFileInput(
                    src=main_file, dest=pathlib.Path('main_with_utils.cpp')
                ),
            ]
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('combined'),
                dest=pathlib.Path('combined'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        # Compile multiple files together
        commands = ['g++ -o combined main_with_utils.cpp math_utils.cpp']

        result = steps.compile(commands, params, sandbox, artifacts)

        assert result is True
        assert output_file.exists()
        assert output_file.stat().st_mode & 0o111  # Check executable bit
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1
        assert artifacts.logs.preprocess[0].exitcode == 0

    def test_sanitizer_command_detection(self):
        """Test that sanitizer commands are correctly detected."""
        # Test various sanitizer commands
        sanitizer_commands = [
            'g++ -fsanitize=address -o test test.cpp',
            'clang++ -fsanitize=thread -g -o test test.cpp',
            'g++ -fsanitize=undefined,address -O2 -o test test.cpp',
            '/usr/bin/g++ -fsanitize=memory -o test test.cpp',
        ]

        for command in sanitizer_commands:
            assert steps.is_cxx_sanitizer_command(
                command
            ), f'Failed to detect sanitizer in: {command}'

        # Test non-sanitizer commands
        non_sanitizer_commands = [
            'g++ -o test test.cpp',
            'clang++ -O2 -g -o test test.cpp',
            'javac Test.java',
            'python test.py',
        ]

        for command in non_sanitizer_commands:
            assert not steps.is_cxx_sanitizer_command(
                command
            ), f'False positive for: {command}'

    @patch('sys.platform', 'linux')
    @patch('rbx.grading.steps._get_cxx_version_output')
    def test_sanitizer_gcc_on_linux_no_warning(
        self,
        mock_version_output,
        sandbox: SandboxBase,
        cleandir: pathlib.Path,
        testdata_path: pathlib.Path,
    ):
        """Test that GCC with sanitizers on Linux doesn't produce warnings."""
        # Mock GCC version output
        mock_version_output.return_value = """Using built-in specs.
COLLECT_GCC=gcc
COLLECT_LTO_WRAPPER=/usr/lib/gcc/x86_64-linux-gnu/9/lto-wrapper
OFFLOAD_TARGET_NAMES=nvptx-none:hsa
OFFLOAD_TARGET_DEFAULT=1
Target: x86_64-linux-gnu
Configured with: ../src/configure --build=x86_64-linux-gnu
Thread model: posix
gcc version 9.4.0 (Ubuntu 9.4.0-1ubuntu1~20.04.2)"""

        # Setup test files
        source_file = testdata_path / 'compile_test' / 'sanitizer.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('sanitizer.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('sanitizer'),
                dest=pathlib.Path('sanitizer'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -fsanitize=address -o sanitizer sanitizer.cpp']

        # This should not raise an exception on Linux with GCC
        result = steps.compile(commands, params, sandbox, artifacts)

        # The compilation might fail due to missing sanitizer libraries,
        # but the function should not exit or complain about the platform
        assert isinstance(result, bool)
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1

    @patch('sys.platform', 'darwin')
    @patch('rbx.grading.steps._get_cxx_version_output')
    def test_sanitizer_gcc_on_macos_raises_error(
        self,
        mock_version_output,
        sandbox: SandboxBase,
        cleandir: pathlib.Path,
        testdata_path: pathlib.Path,
    ):
        """Test that GCC with sanitizers on macOS raises an error and exits."""
        # Mock GCC version output (macOS with GCC)
        mock_version_output.return_value = """Using built-in specs.
COLLECT_GCC=gcc
COLLECT_LTO_WRAPPER=/usr/local/libexec/gcc/x86_64-apple-darwin21/11.3.0/lto-wrapper
Target: x86_64-apple-darwin21
Configured with: ../configure --build=x86_64-apple-darwin21
Thread model: posix
gcc version 11.3.0 (Homebrew GCC 11.3.0)"""

        # Setup test files
        source_file = testdata_path / 'compile_test' / 'sanitizer.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('sanitizer.cpp'))
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -fsanitize=address -o sanitizer sanitizer.cpp']

        # This should raise a typer.Exit exception on macOS with GCC
        with pytest.raises(typer.Exit):
            steps.compile(commands, params, sandbox, artifacts)

    @patch('sys.platform', 'darwin')
    @patch('rbx.grading.steps._get_cxx_version_output')
    def test_sanitizer_clang_on_macos_works(
        self,
        mock_version_output,
        sandbox: SandboxBase,
        cleandir: pathlib.Path,
        testdata_path: pathlib.Path,
    ):
        """Test that Clang with sanitizers on macOS works without warnings."""
        # Mock Clang version output
        mock_version_output.return_value = """Apple clang version 14.0.0 (clang-1400.0.29.202)
Target: x86_64-apple-darwin21.6.0
Thread model: posix
InstalledDir: /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin"""

        # Setup test files
        source_file = testdata_path / 'compile_test' / 'sanitizer.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('sanitizer.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('sanitizer'),
                dest=pathlib.Path('sanitizer'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['clang++ -fsanitize=address -o sanitizer sanitizer.cpp']

        # This should not raise an exception on macOS with Clang
        result = steps.compile(commands, params, sandbox, artifacts)

        # The compilation might fail due to missing sanitizer libraries,
        # but the function should not exit or complain about the platform
        assert isinstance(result, bool)
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1

    @patch('rbx.grading.steps._get_cxx_version_output')
    def test_sanitizer_version_check_failure_handles_gracefully(
        self,
        mock_version_output,
        sandbox: SandboxBase,
        cleandir: pathlib.Path,
        testdata_path: pathlib.Path,
    ):
        """Test that compilation continues gracefully when version check fails."""
        # Mock failed version check
        mock_version_output.return_value = None

        # Setup test files
        source_file = testdata_path / 'compile_test' / 'sanitizer.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('sanitizer.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('sanitizer'),
                dest=pathlib.Path('sanitizer'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -fsanitize=address -o sanitizer sanitizer.cpp']

        # Should not crash when version check fails
        result = steps.compile(commands, params, sandbox, artifacts)

        assert isinstance(result, bool)
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1

    @patch('sys.platform', 'linux')
    @patch('rbx.grading.steps._get_cxx_version_output')
    def test_sanitizer_warning_detection_in_stderr(
        self,
        mock_version_output,
        sandbox: SandboxBase,
        cleandir: pathlib.Path,
        testdata_path: pathlib.Path,
    ):
        """Test that sanitizer warnings are detected in stderr output."""
        # Mock GCC version output
        mock_version_output.return_value = (
            """gcc version 9.4.0 (Ubuntu 9.4.0-1ubuntu1~20.04.2)"""
        )

        # Setup test files
        source_file = testdata_path / 'compile_test' / 'sanitizer.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('sanitizer.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('sanitizer'),
                dest=pathlib.Path('sanitizer'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -fsanitize=address -o sanitizer sanitizer.cpp']

        # Mock sandbox to simulate sanitizer warnings in stderr
        with patch.object(
            sandbox, 'get_file_to_string', wraps=sandbox.get_file_to_string
        ) as mock_get_file:

            def mock_get_file_to_string(path, maxlen=None):
                if 'stderr' in str(path):
                    return '==1234==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602000000110'
                return mock_get_file.return_value

            mock_get_file.side_effect = mock_get_file_to_string

            steps.compile(commands, params, sandbox, artifacts)

            # Check that logs were created
            assert artifacts.logs.preprocess is not None
            assert len(artifacts.logs.preprocess) == 1

            # The log should contain the sanitizer warning
            log = artifacts.logs.preprocess[0]
            assert 'AddressSanitizer' in log.log
            assert 'heap-buffer-overflow' in log.log

    def test_sanitizer_warning_line_detection(self):
        """Test the sanitizer warning detection logic."""
        # Test lines that should be detected as sanitizer warnings
        warning_lines = [
            '==1234==ERROR: AddressSanitizer: heap-buffer-overflow',
            '==5678==ERROR: ThreadSanitizer: data race',
            'runtime error: signed integer overflow',
            '==ERROR: LeakSanitizer: detected memory leaks',
            'RUNTIME ERROR: something bad happened',  # case insensitive
            'Some prefix ==ERROR something else',  # embedded in line
        ]

        for line in warning_lines:
            assert steps.check_for_sanitizer_warnings_in_line(
                line
            ), f'Failed to detect warning in: {line}'

        # Test lines that should NOT be detected as sanitizer warnings
        normal_lines = [
            'Compilation successful',
            "warning: unused variable 'x'",
            "error: undeclared identifier 'foo'",  # regular compilation error
            "In function 'main':",
            'note: candidate function not viable',
            'SUMMARY: AddressSanitizer: heap-buffer-overflow',  # summary lines are not detected
            'AddressSanitizer: heap-buffer-overflow',  # without ==ERROR prefix
        ]

        for line in normal_lines:
            assert not steps.check_for_sanitizer_warnings_in_line(
                line
            ), f'False positive for: {line}'

    @patch('sys.platform', 'darwin')
    @patch('rbx.grading.steps._get_cxx_version_output')
    def test_non_sanitizer_command_on_macos_no_check(
        self,
        mock_version_output,
        sandbox: SandboxBase,
        cleandir: pathlib.Path,
        testdata_path: pathlib.Path,
    ):
        """Test that non-sanitizer commands on macOS don't trigger version checks."""
        # Setup test files
        source_file = testdata_path / 'compile_test' / 'simple.cpp'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('simple.cpp'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('simple'),
                dest=pathlib.Path('simple'),
                executable=True,
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams()
        commands = ['g++ -o simple simple.cpp']  # No sanitizer flags

        # This should work fine without any version checks
        result = steps.compile(commands, params, sandbox, artifacts)

        # _get_cxx_version_output should not have been called for non-sanitizer commands
        mock_version_output.assert_not_called()

        assert isinstance(result, bool)
        assert artifacts.logs.preprocess is not None
        assert len(artifacts.logs.preprocess) == 1
