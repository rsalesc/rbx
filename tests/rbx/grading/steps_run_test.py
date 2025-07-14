import pathlib
import sys
from unittest.mock import patch

import pytest

from rbx.grading import steps
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    GradingLogsHolder,
    RunLogMetadata,
)


@pytest.fixture(autouse=True)
def clear_steps_cache():
    """Clear all cached functions in steps.py before each test."""
    # Clear all cached functions to ensure clean state between tests
    steps._complain_about_clang.cache_clear()  # noqa: SLF001
    steps._get_cxx_version_output.cache_clear()  # noqa: SLF001
    steps._maybe_complain_about_sanitization.cache_clear()  # noqa: SLF001
    steps._try_following_alias_for_exe.cache_clear()  # noqa: SLF001


class TestStepsRun:
    """Test the steps.run function."""

    async def test_run_simple_python_command(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a simple Python command that outputs to stdout."""
        # Setup input file
        source_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert result.time is not None
        assert result.memory is not None
        assert (cleandir / 'output.txt').exists()
        assert (cleandir / 'output.txt').read_text().strip() == 'Hello from Python!'
        assert artifacts.logs.run is not None
        assert artifacts.logs.run.exitcode == 0

    async def test_run_with_input_file(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with input file redirection."""
        # Setup input files
        script_file = testdata_path / 'steps_run_test' / 'simple_input.py'
        input_file = testdata_path / 'steps_run_test' / 'input.txt'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(src=script_file, dest=pathlib.Path('script.py')),
                GradingFileInput(src=input_file, dest=pathlib.Path('input.txt')),
            ]
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(
            stdin_file=pathlib.Path('input.txt'), stdout_file=pathlib.Path('output.txt')
        )
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'output.txt').exists()
        assert 'Received: test input line' in (cleandir / 'output.txt').read_text()

    async def test_run_creates_output_file(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command that creates an output file."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'create_file.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('created.txt'), dest=pathlib.Path('created.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('stdout.txt'), dest=pathlib.Path('stdout.txt')
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('stdout.txt'))
        command = f'{sys.executable} script.py created.txt "test content"'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'created.txt').exists()
        assert (cleandir / 'created.txt').read_text() == 'test content'
        assert (cleandir / 'stdout.txt').exists()
        assert (
            'Created file created.txt with content: test content'
            in (cleandir / 'stdout.txt').read_text()
        )

    async def test_run_with_error_returns_error_exitcode(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that run returns exitcode with error when command fails."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'error_program.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py 42'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None  # run returns RunLog even on error
        assert result.exitcode == 42
        assert artifacts.logs.run is not None
        assert artifacts.logs.run.exitcode == 42

    async def test_run_with_timeout(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with CPU timeout."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'busy_loop.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(
            stdout_file=pathlib.Path('output.txt'),
            timeout=500,  # 500ms timeout
        )
        command = f'{sys.executable} script.py 2.0'  # Busy loop for 2 seconds

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        # Should timeout due to CPU time limit
        assert result.exitstatus == SandboxBase.EXIT_TIMEOUT
        assert result.exitcode != 0

    async def test_run_with_wall_timeout(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with wall timeout."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'slow_program.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(
            stdout_file=pathlib.Path('output.txt'),
            wallclock_timeout=500,  # 500ms wall timeout
        )
        command = f'{sys.executable} script.py 2.0'  # Sleep for 2 seconds

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        # Should timeout due to wall time limit
        assert result.exitstatus == SandboxBase.EXIT_TIMEOUT_WALL
        assert result.exitcode != 0

    async def test_run_with_memory_limit(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with memory limit."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'memory_heavy_gradual.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(
            stdout_file=pathlib.Path('output.txt'),
            address_space=50,  # 50MB memory limit
        )
        command = f'{sys.executable} script.py 100'  # Try to allocate 100MB

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        # Should hit memory limit and be killed
        assert result.exitstatus == SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED
        assert result.exitcode != 0

    async def test_run_with_memory_limit_regression_test(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Regression test for memory limit detection bug.

        This test ensures that the get_memory_usage function correctly reports
        memory usage in bytes on all platforms. Previously, on macOS, the function
        incorrectly divided ru.ru_maxrss by 1024, causing memory limits to not
        be properly detected.

        The original memory_heavy.py script allocates memory quickly and exits,
        relying on the post-execution memory check (ru.ru_maxrss) rather than
        the runtime monitoring thread to detect memory limit violations.
        """
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'memory_heavy.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(
            stdout_file=pathlib.Path('output.txt'),
            address_space=50,  # 50MB memory limit
        )
        command = f'{sys.executable} script.py 100'  # Try to allocate 100MB

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        # Should hit memory limit and be flagged (may complete successfully but exceed limit)
        assert result.exitstatus == SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED
        # Memory usage should exceed the limit
        assert result.memory is not None
        assert result.memory > 50 * 1024 * 1024  # Should use more than 50MB

    async def test_run_with_metadata(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with metadata."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        metadata = RunLogMetadata(
            language='python', is_sanitized=False, timeLimit=1000, memoryLimit=512
        )
        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts, metadata)

        assert result is not None
        assert result.exitcode == 0
        assert result.metadata is not None
        assert result.metadata.language == 'python'
        assert result.metadata.timeLimit == 1000
        assert result.metadata.memoryLimit == 512
        assert not result.metadata.is_sanitized
        assert artifacts.logs.run is not None
        assert artifacts.logs.run.metadata is not None
        assert artifacts.logs.run.metadata.language == 'python'

    async def test_run_java_removes_memory_constraints(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that Java commands have memory constraints removed."""
        # Setup input file
        source_file = testdata_path / 'steps_run_test' / 'simple.java'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('Simple.java'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(
            stdout_file=pathlib.Path('output.txt'),
            address_space=1024,  # Set memory constraint
        )
        command = 'java Simple'

        # Use mock to capture the params passed to sandbox.run
        with patch.object(sandbox, 'run', wraps=sandbox.run) as mock_run:
            result = await steps.run(command, params, sandbox, artifacts)

            assert result is not None
            # Original params should not be modified
            assert params.address_space == 1024
            # But the params passed to sandbox.run should have address_space removed
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            captured_params = call_args[0][1]  # Second argument (params)
            assert captured_params.address_space is None

    async def test_run_with_optional_output_file(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with optional output file that doesn't exist."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('optional.txt'),
                    dest=pathlib.Path('optional.txt'),
                    optional=True,
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'output.txt').exists()
        assert not (
            cleandir / 'optional.txt'
        ).exists()  # Optional file doesn't exist, but that's OK

    async def test_run_with_executable_output(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command that produces an executable output."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'create_file.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('executable'),
                    dest=pathlib.Path('executable'),
                    executable=True,
                ),
                GradingFileOutput(
                    src=pathlib.Path('stdout.txt'), dest=pathlib.Path('stdout.txt')
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('stdout.txt'))
        command = f'{sys.executable} script.py executable "#!/bin/bash\\necho test"'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'executable').exists()
        # Check that the file has executable permissions
        assert (cleandir / 'executable').stat().st_mode & 0o111

    async def test_run_missing_required_output_returns_none(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that run returns None when required output file is missing."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('missing.txt'),
                    dest=pathlib.Path('missing.txt'),
                    optional=False,  # Required file
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is None  # Should return None due to missing required output

    async def test_run_with_maxlen_output(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with output size limit."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'create_file.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('large.txt'),
                    dest=pathlib.Path('large.txt'),
                    maxlen=10,  # Limit to 10 bytes
                ),
                GradingFileOutput(
                    src=pathlib.Path('stdout.txt'), dest=pathlib.Path('stdout.txt')
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('stdout.txt'))
        # Create a file with more than 10 bytes
        large_content = 'x' * 100
        command = f'{sys.executable} script.py large.txt "{large_content}"'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'large.txt').exists()
        # The file should be truncated to maxlen
        assert len((cleandir / 'large.txt').read_text()) <= 10

    async def test_run_with_touch_output(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with touch output file."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('touched.txt'),
                    dest=pathlib.Path('touched.txt'),
                    touch=True,
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'output.txt').exists()
        assert (cleandir / 'touched.txt').exists()
        # The touched file should be empty (touched before command runs)
        assert (cleandir / 'touched.txt').read_text() == ''

    async def test_run_processes_input_artifacts(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that run processes input artifacts correctly."""
        # Setup multiple input files
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        input_file = testdata_path / 'steps_run_test' / 'input.txt'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(src=script_file, dest=pathlib.Path('script.py')),
                GradingFileInput(src=input_file, dest=pathlib.Path('data.txt')),
            ]
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'output.txt').exists()
        # Both input files should have been processed into the sandbox

    async def test_run_sanitizer_warnings_detection(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that sanitizer warnings are detected when metadata indicates sanitization."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('stderr.txt'), dest=pathlib.Path('stderr.txt')
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        metadata = RunLogMetadata(language='cpp', is_sanitized=True)
        params = SandboxParams(
            stdout_file=pathlib.Path('output.txt'),
            stderr_file=pathlib.Path('stderr.txt'),
        )
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts, metadata)

        assert result is not None
        assert result.exitcode == 0
        assert result.metadata is not None
        assert result.metadata.is_sanitized
        # The warnings flag should be set based on stderr content
        # (In this case, no actual sanitizer warnings, so should be False)
        assert not result.warnings

    async def test_run_logs_are_captured(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that run logs are properly captured in artifacts."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert artifacts.logs is not None
        assert artifacts.logs.run is not None
        assert artifacts.logs.run.exitcode == 0
        assert artifacts.logs.run.time is not None
        assert artifacts.logs.run.memory is not None
        assert artifacts.logs.run.sandbox is not None
        assert artifacts.logs.run.exitstatus is not None

    async def test_run_without_logs_holder(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that run works without a logs holder."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        # No logs holder set

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'output.txt').exists()
        # artifacts.logs should remain None
        assert artifacts.logs is None

    async def test_run_with_actual_sanitizer_warnings(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that actual sanitizer warnings are detected."""
        # Setup input file that simulates sanitizer warnings
        script_file = testdata_path / 'steps_run_test' / 'sanitizer_warning.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('stderr.txt'), dest=pathlib.Path('stderr.txt')
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        metadata = RunLogMetadata(language='cpp', is_sanitized=True)
        params = SandboxParams(
            stdout_file=pathlib.Path('output.txt'),
            stderr_file=pathlib.Path('stderr.txt'),
        )
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts, metadata)

        assert result is not None
        assert result.exitcode == 0
        assert result.metadata is not None
        assert result.metadata.is_sanitized
        # The warnings flag should be set based on stderr content
        assert result.warnings  # Should detect sanitizer warnings

    async def test_run_with_intermediate_output(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with intermediate output files."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'create_file.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('intermediate.txt'),
                    dest=pathlib.Path('intermediate.txt'),
                    intermediate=True,  # Intermediate file
                ),
                GradingFileOutput(
                    src=pathlib.Path('stdout.txt'), dest=pathlib.Path('stdout.txt')
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('stdout.txt'))
        command = f'{sys.executable} script.py intermediate.txt "intermediate content"'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'intermediate.txt').exists()
        assert (cleandir / 'intermediate.txt').read_text() == 'intermediate content'
        assert (cleandir / 'stdout.txt').exists()

    async def test_run_with_no_hash_tracking(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test running a command with hash tracking disabled."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(
                src=script_file, dest=pathlib.Path('script.py'), hash=False
            )
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'),
                dest=pathlib.Path('output.txt'),
                hash=False,  # Disable hash tracking
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'))
        command = f'{sys.executable} script.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'output.txt').exists()
        assert (cleandir / 'output.txt').read_text().strip() == 'Hello from Python!'

    async def test_run_with_glob_expansion(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that @glob: command expansion works correctly."""
        # Setup input files - script and files to be matched by glob
        script_file = testdata_path / 'steps_run_test' / 'glob_test.py'
        test1_file = testdata_path / 'steps_run_test' / 'test1.py'
        test2_file = testdata_path / 'steps_run_test' / 'test2.py'
        other_file = testdata_path / 'steps_run_test' / 'other.txt'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(src=script_file, dest=pathlib.Path('glob_test.py')),
                GradingFileInput(src=test1_file, dest=pathlib.Path('test1.py')),
                GradingFileInput(src=test2_file, dest=pathlib.Path('test2.py')),
                GradingFileInput(src=other_file, dest=pathlib.Path('other.txt')),
            ]
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('stdout.txt'), dest=pathlib.Path('stdout.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('glob_output.txt'),
                    dest=pathlib.Path('glob_output.txt'),
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('stdout.txt'))
        # Use @glob: to expand *.py files
        command = f'{sys.executable} glob_test.py @glob:*.py'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'stdout.txt').exists()
        assert (cleandir / 'glob_output.txt').exists()

        # Check that glob expansion worked - should find test1.py and test2.py
        stdout_content = (cleandir / 'stdout.txt').read_text()
        glob_output_content = (cleandir / 'glob_output.txt').read_text()

        # Should have found 3 Python files (glob_test.py, test1.py, test2.py)
        assert 'Number of arguments: 3' in stdout_content

        # All Python files should be in the arguments
        assert 'glob_test.py' in glob_output_content
        assert 'test1.py' in glob_output_content
        assert 'test2.py' in glob_output_content

        # The .txt file should not be included
        assert 'other.txt' not in glob_output_content

        # Verify the arguments are properly quoted (shlex.quote behavior)
        # The order may vary, so just check that all files are present
        assert 'Count: 3' in glob_output_content

    async def test_run_with_glob_no_matches(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that @glob: works correctly when no files match the pattern."""
        # Setup input file
        script_file = testdata_path / 'steps_run_test' / 'glob_test.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('glob_test.py'))
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('stdout.txt'), dest=pathlib.Path('stdout.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('glob_output.txt'),
                    dest=pathlib.Path('glob_output.txt'),
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('stdout.txt'))
        # Use @glob: with a pattern that won't match any files
        command = f'{sys.executable} glob_test.py @glob:*.nonexistent'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'stdout.txt').exists()
        assert (cleandir / 'glob_output.txt').exists()

        # Should have found 0 files
        stdout_content = (cleandir / 'stdout.txt').read_text()
        glob_output_content = (cleandir / 'glob_output.txt').read_text()

        assert 'Number of arguments: 0' in stdout_content
        assert 'Count: 0' in glob_output_content
        assert 'Arguments: ' in glob_output_content  # Empty arguments

    async def test_run_with_mixed_glob_and_normal_args(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that @glob: works correctly mixed with normal arguments."""
        # Setup input files
        script_file = testdata_path / 'steps_run_test' / 'glob_test.py'
        test1_file = testdata_path / 'steps_run_test' / 'test1.py'
        test2_file = testdata_path / 'steps_run_test' / 'test2.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(src=script_file, dest=pathlib.Path('glob_test.py')),
                GradingFileInput(src=test1_file, dest=pathlib.Path('test1.py')),
                GradingFileInput(src=test2_file, dest=pathlib.Path('test2.py')),
            ]
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('stdout.txt'), dest=pathlib.Path('stdout.txt')
                ),
                GradingFileOutput(
                    src=pathlib.Path('glob_output.txt'),
                    dest=pathlib.Path('glob_output.txt'),
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('stdout.txt'))
        # Mix normal arguments with @glob: expansion
        command = f'{sys.executable} glob_test.py --flag @glob:*.py --end'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert (cleandir / 'stdout.txt').exists()
        assert (cleandir / 'glob_output.txt').exists()

        # Should have found 5 arguments: --flag, glob_test.py, test1.py, test2.py, --end
        stdout_content = (cleandir / 'stdout.txt').read_text()
        glob_output_content = (cleandir / 'glob_output.txt').read_text()

        assert 'Number of arguments: 5' in stdout_content

        # All arguments should be present
        assert '--flag' in glob_output_content
        assert '--end' in glob_output_content
        assert 'glob_test.py' in glob_output_content
        assert 'test1.py' in glob_output_content
        assert 'test2.py' in glob_output_content
