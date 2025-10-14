import pathlib
import sys
from unittest.mock import patch

import pytest

from rbx.grading import steps
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    CoordinatedRunParams,
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


class TestStepsRunCoordinated:
    """Test the steps.run_coordinated function."""

    async def test_run_coordinated_simple_communication(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test basic communication between interactor and solution."""
        # Setup input files
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        artifacts.outputs.extend(
            [
                GradingFileOutput(
                    src=pathlib.Path('interactor.stderr'),
                    dest=pathlib.Path('interactor.stderr'),
                ),
                GradingFileOutput(
                    src=pathlib.Path('solution.stderr'),
                    dest=pathlib.Path('solution.stderr'),
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        # Setup run parameters
        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(
                stderr_file=pathlib.Path('interactor.stderr'),
                timeout=5000,  # 5 seconds
            ),
            metadata=RunLogMetadata(language='python'),
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(
                stderr_file=pathlib.Path('solution.stderr'),
                timeout=5000,  # 5 seconds
            ),
            metadata=RunLogMetadata(language='python'),
        )

        # Run coordinated execution
        solution_log, interactor_log = await steps.run_coordinated(
            interactor_params, solution_params, artifacts, sandbox
        )

        # Verify results
        assert solution_log is not None
        assert interactor_log is not None
        assert solution_log.exitcode == 0
        assert interactor_log.exitcode == 0
        assert solution_log.time is not None
        assert interactor_log.time is not None
        assert solution_log.memory is not None
        assert interactor_log.memory is not None

        # Check that logs were captured
        assert artifacts.logs.run is not None
        assert artifacts.logs.interactor_run is not None
        assert artifacts.logs.run.exitcode == 0
        assert artifacts.logs.interactor_run.exitcode == 0

        # Check metadata was preserved
        assert solution_log.metadata is not None
        assert solution_log.metadata.language == 'python'
        assert interactor_log.metadata is not None
        assert interactor_log.metadata.language == 'python'

        # Check stderr files were created and verify content shows proper execution
        assert (cleandir / 'solution.stderr').exists()
        assert (cleandir / 'interactor.stderr').exists()

        # Read and verify stderr content to ensure programs executed correctly
        solution_stderr = (cleandir / 'solution.stderr').read_text()
        interactor_stderr = (cleandir / 'interactor.stderr').read_text()

        # Verify that the solution received responses (it logs these to stderr)
        assert 'Received: world' in solution_stderr
        assert 'Solution finished' in solution_stderr

        # Verify that the interactor also logged to stderr
        assert 'Interactor starting with 3 queries' in interactor_stderr
        assert 'Interactor finished' in interactor_stderr

    async def test_run_coordinated_with_timeout(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test run_coordinated with CPU timeout scenario."""
        interactor_file = testdata_path / 'steps_run_test' / 'busy_loop_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(timeout=100),  # 100ms CPU timeout
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(timeout=100),  # 100ms CPU timeout
        )

        solution_log, interactor_log = await steps.run_coordinated(
            interactor_params, solution_params, artifacts, sandbox
        )

        # Both logs should be present
        assert solution_log is not None
        assert interactor_log is not None

        # Check for timeout status - at least one should be affected by the busy loop
        timeout_statuses = [
            SandboxBase.EXIT_TIMEOUT,
        ]

        timeout_occurred = interactor_log.exitstatus in timeout_statuses

        assert timeout_occurred, (
            f'Expected CPU timeout to occur. '
            f'Solution: {solution_log.exitstatus}, Interactor: {interactor_log.exitstatus}'
        )
        assert interactor_log.exitindex < solution_log.exitindex

    async def test_run_coordinated_with_wall_timeout(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test run_coordinated with wall clock timeout scenario."""
        interactor_file = testdata_path / 'steps_run_test' / 'timeout_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(wallclock_timeout=2000),  # 2 second wall timeout
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(wallclock_timeout=2000),  # 2 second wall timeout
        )

        solution_log, interactor_log = await steps.run_coordinated(
            interactor_params, solution_params, artifacts, sandbox
        )

        # Both logs should be present
        assert solution_log is not None
        assert interactor_log is not None

        # Check for wall timeout status - at least one should be affected by the sleep
        wall_timeout_statuses = [
            SandboxBase.EXIT_TIMEOUT_WALL,
        ]

        wall_timeout_occurred = (
            interactor_log.exitstatus in wall_timeout_statuses
            or solution_log.exitstatus in wall_timeout_statuses
        )

        assert wall_timeout_occurred, (
            f'Expected wall timeout to occur. '
            f'Solution: {solution_log.exitstatus}, Interactor: {interactor_log.exitstatus}'
        )

    async def test_run_coordinated_solution_error(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test run_coordinated when solution crashes."""
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'error_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(timeout=5000),
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(timeout=5000),
        )

        solution_log, interactor_log = await steps.run_coordinated(
            interactor_params, solution_params, artifacts, sandbox
        )

        assert solution_log is not None
        assert interactor_log is not None

        # Solution should have non-zero exit code
        assert solution_log.exitcode != 0
        assert solution_log.exitstatus == SandboxBase.EXIT_NONZERO_RETURN
        assert solution_log.exitindex < interactor_log.exitindex

    async def test_run_coordinated_interactor_error(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test run_coordinated when interactor crashes."""
        interactor_file = testdata_path / 'steps_run_test' / 'error_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(timeout=5000),
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(timeout=5000),
        )

        solution_log, interactor_log = await steps.run_coordinated(
            interactor_params, solution_params, artifacts, sandbox
        )

        assert solution_log is not None
        assert interactor_log is not None

        # Interactor should have non-zero exit code
        assert interactor_log.exitcode != 0
        assert interactor_log.exitstatus == SandboxBase.EXIT_NONZERO_RETURN
        assert interactor_log.exitindex < solution_log.exitindex

    async def test_run_coordinated_java_memory_handling(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that Java commands have memory constraints removed."""
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        java_file = testdata_path / 'steps_run_test' / 'java_solution.java'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(
                    src=java_file, dest=pathlib.Path('java_solution.java')
                ),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(
                timeout=5000,
                address_space=512,  # 512MB limit
            ),
        )

        # Java solution with memory constraints that should be removed
        solution_params = CoordinatedRunParams(
            command='javac java_solution.java && java java_solution',
            params=SandboxParams(
                timeout=5000,
                address_space=256,  # This should be removed for Java
            ),
        )

        # Mock the sandbox.run_communication method to verify the parameters
        with patch.object(
            sandbox, 'run_communication', wraps=sandbox.run_communication
        ) as mock_run_communication:
            solution_log, interactor_log = await steps.run_coordinated(
                interactor_params, solution_params, artifacts, sandbox
            )

            # Verify that run_communication was called
            mock_run_communication.assert_called_once()

            # Get the actual call arguments
            call_args = mock_run_communication.call_args

            # Arguments should be: solution_cmd, solution_params, interactor_cmd, interactor_params, merged_capture
            (
                solution_cmd,
                solution_params_actual,
                interactor_cmd,
                interactor_params_actual,
                merged_capture,
            ) = call_args[0]

            # Verify that the Java solution's address_space was removed
            assert (
                solution_params_actual.address_space is None
            ), 'Java solution should have address_space removed'

            # Verify that the interactor still has its address_space constraint
            assert (
                interactor_params_actual.address_space == 512
            ), 'Interactor should keep its address_space constraint'

        # The key test is that the function doesn't fail due to memory constraints
        # and that both logs are returned (even if the execution has issues)
        assert solution_log is not None
        assert interactor_log is not None

    async def test_run_coordinated_with_merged_capture(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test run_coordinated with merged capture file."""
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('merged.log'), dest=pathlib.Path('merged.log')
            )
        )
        artifacts.logs = GradingLogsHolder()

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(timeout=5000),
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(timeout=5000),
        )

        solution_log, interactor_log = await steps.run_coordinated(
            interactor_params,
            solution_params,
            artifacts,
            sandbox,
            merged_capture=pathlib.Path('merged.log'),
        )

        assert solution_log is not None
        assert interactor_log is not None

        # Check that merged capture file was created and verify its exact content
        assert (cleandir / 'merged.log').exists()

        # Read merged capture content
        merged_content = (cleandir / 'merged.log').read_text()

        # With the updated scripts that write in alternating turns, the output is now deterministic:
        # - Initial tee markers: < and >
        # - Solution outputs number of queries: >3
        # - Turn-based communication: >hello <world >test <echo_test >goodbye <echo_goodbye
        expected_content = """<
>
>3
>hello
<world
>test
<echo_test
>goodbye
<echo_goodbye
"""

        assert merged_content == expected_content

    async def test_run_coordinated_output_artifacts_failure(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test run_coordinated when output artifact processing fails."""
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        # Add a required output that won't be created
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('nonexistent.txt'),
                dest=pathlib.Path('nonexistent.txt'),
                optional=False,
            )
        )
        artifacts.logs = GradingLogsHolder()

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(timeout=5000),
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(timeout=5000),
        )

        result = await steps.run_coordinated(
            interactor_params, solution_params, artifacts, sandbox
        )

        # Should return (None, None) when output processing fails
        assert result == (None, None)

    async def test_run_coordinated_command_expansion(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that commands are properly split and expanded."""
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        # Use command with arguments that need to be split
        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} -u interactor.py',  # -u for unbuffered output
            params=SandboxParams(timeout=5000),
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} -u solution.py',  # -u for unbuffered output
            params=SandboxParams(timeout=5000),
        )

        solution_log, interactor_log = await steps.run_coordinated(
            interactor_params, solution_params, artifacts, sandbox
        )

        assert solution_log is not None
        assert interactor_log is not None
        assert solution_log.exitcode == 0
        assert interactor_log.exitcode == 0

    async def test_run_coordinated_handles_program_error(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """ProgramError from run_communication should map to sandbox error RunLogs."""
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        artifacts.logs = GradingLogsHolder()

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(timeout=5000),
        )
        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py', params=SandboxParams(timeout=5000)
        )

        from rbx.grading.judge.program import ProgramError

        with patch.object(
            sandbox, 'run_communication', side_effect=ProgramError('boom')
        ):
            solution_log, interactor_log = await steps.run_coordinated(
                interactor_params, solution_params, artifacts, sandbox
            )

        assert solution_log is not None and interactor_log is not None
        assert solution_log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR
        assert interactor_log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR
        assert solution_log.exitcode == 1 and interactor_log.exitcode == 1

    async def test_run_coordinated_sandbox_reset_called(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test that sandbox.reset() is called at the beginning."""
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(timeout=5000),
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(timeout=5000),
        )

        # Use mock.patch to track reset calls
        with patch.object(sandbox, 'reset', wraps=sandbox.reset) as mock_reset:
            await steps.run_coordinated(
                interactor_params, solution_params, artifacts, sandbox
            )

            # Verify reset was called exactly once
            mock_reset.assert_called_once()

    async def test_run_coordinated_without_logs_holder(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Test run_coordinated without logs holder (should not crash)."""
        interactor_file = testdata_path / 'steps_run_test' / 'simple_interactor.py'
        solution_file = testdata_path / 'steps_run_test' / 'simple_solution.py'

        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.extend(
            [
                GradingFileInput(
                    src=interactor_file, dest=pathlib.Path('interactor.py')
                ),
                GradingFileInput(src=solution_file, dest=pathlib.Path('solution.py')),
            ]
        )
        # Note: No logs holder set

        interactor_params = CoordinatedRunParams(
            command=f'{sys.executable} interactor.py',
            params=SandboxParams(timeout=5000),
        )

        solution_params = CoordinatedRunParams(
            command=f'{sys.executable} solution.py',
            params=SandboxParams(timeout=5000),
        )

        solution_log, interactor_log = await steps.run_coordinated(
            interactor_params, solution_params, artifacts, sandbox
        )

        assert solution_log is not None
        assert interactor_log is not None
        assert solution_log.exitcode == 0
        assert interactor_log.exitcode == 0
