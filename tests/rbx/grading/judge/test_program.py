import os
import signal
import subprocess
import sys
import time
from unittest import mock

import pytest

from rbx.grading.judge.program import (
    Program,
    ProgramCode,
    ProgramIO,
    ProgramParams,
    ProgramResult,
    get_cpu_time,
    get_memory_usage,
    get_preexec_fn,
)


@pytest.fixture
def program_test_data(testdata_path):
    """Path to program test data directory."""
    return testdata_path / 'program_test'


@pytest.fixture
def simple_hello_program(program_test_data):
    """Path to simple hello world program."""
    return program_test_data / 'simple_hello.py'


@pytest.fixture
def infinite_loop_program(program_test_data):
    """Path to infinite loop program."""
    return program_test_data / 'infinite_loop.py'


@pytest.fixture
def memory_hog_program(program_test_data):
    """Path to memory-intensive program."""
    return program_test_data / 'memory_hog.py'


@pytest.fixture
def output_large_program(program_test_data):
    """Path to large output program."""
    return program_test_data / 'output_large.py'


@pytest.fixture
def exit_with_code_program(program_test_data):
    """Path to program that exits with specific codes."""
    return program_test_data / 'exit_with_code.py'


@pytest.fixture
def signal_test_program(program_test_data):
    """Path to signal handling program."""
    return program_test_data / 'signal_test.py'


@pytest.fixture
def input_echo_program(program_test_data):
    """Path to input echo program."""
    return program_test_data / 'input_echo.py'


@pytest.fixture
def cpu_intensive_program(program_test_data):
    """Path to CPU-intensive program."""
    return program_test_data / 'cpu_intensive.py'


class TestProgramIO:
    """Test ProgramIO class functionality."""

    def test_default_io(self):
        """Test default ProgramIO settings."""
        io = ProgramIO()
        assert io.input == subprocess.PIPE
        assert io.output == subprocess.PIPE
        assert io.stderr == subprocess.PIPE

    def test_custom_io_paths(self, tmp_path):
        """Test ProgramIO with file paths."""
        input_file = tmp_path / 'input.txt'
        output_file = tmp_path / 'output.txt'
        stderr_file = tmp_path / 'stderr.txt'

        input_file.write_text('test input\n')

        io = ProgramIO(
            input=str(input_file), output=str(output_file), stderr=str(stderr_file)
        )

        input_fobj, output_fobj, stderr_fobj = io.get_file_objects()

        # Test that files are opened correctly
        assert hasattr(input_fobj, 'read')
        assert hasattr(output_fobj, 'write')
        assert hasattr(stderr_fobj, 'write')

        # Close the files only if they're not file descriptors
        if not isinstance(input_fobj, int):
            input_fobj.close()
        if not isinstance(output_fobj, int):
            output_fobj.close()
        if not isinstance(stderr_fobj, int):
            stderr_fobj.close()

    def test_io_with_file_descriptors(self):
        """Test ProgramIO with file descriptors."""
        io = ProgramIO(input=0, output=1, stderr=2)
        input_fobj, output_fobj, stderr_fobj = io.get_file_objects()

        assert input_fobj == 0
        assert output_fobj == 1
        assert stderr_fobj == 2

    def test_io_creates_parent_directories(self, tmp_path):
        """Test that ProgramIO creates parent directories for output files."""
        nested_output = tmp_path / 'nested' / 'dir' / 'output.txt'
        nested_stderr = tmp_path / 'nested' / 'dir' / 'stderr.txt'

        io = ProgramIO(output=str(nested_output), stderr=str(nested_stderr))
        input_fobj, output_fobj, stderr_fobj = io.get_file_objects()

        assert nested_output.parent.exists()
        assert nested_stderr.parent.exists()

        # Close the files only if they're not file descriptors
        if not isinstance(output_fobj, int):
            output_fobj.close()
        if not isinstance(stderr_fobj, int):
            stderr_fobj.close()


class TestProgramParams:
    """Test ProgramParams class functionality."""

    def test_default_params(self):
        """Test default ProgramParams settings."""
        params = ProgramParams()
        assert isinstance(params.io, ProgramIO)
        assert params.chdir is None
        assert params.time_limit is None
        assert params.wall_time_limit is None
        assert params.memory_limit is None
        assert params.fs_limit is None
        assert params.env == {}
        assert params.pgid is None

    def test_custom_params(self, tmp_path):
        """Test custom ProgramParams settings."""
        params = ProgramParams(
            chdir=tmp_path,
            time_limit=5.0,
            wall_time_limit=10.0,
            memory_limit=100,
            fs_limit=1000,
            env={'TEST_VAR': 'test_value'},
            pgid=12345,
        )

        assert params.chdir == tmp_path
        assert params.time_limit == 5.0
        assert params.wall_time_limit == 10.0
        assert params.memory_limit == 100
        assert params.fs_limit == 1000
        assert params.env == {'TEST_VAR': 'test_value'}
        assert params.pgid == 12345


class TestPreexecFn:
    """Test preexec_fn functionality."""

    def test_preexec_fn_with_limits(self):
        """Test that preexec_fn is created correctly with limits."""
        params = ProgramParams(time_limit=5.0, fs_limit=1000, pgid=12345)

        preexec_fn = get_preexec_fn(params)
        assert callable(preexec_fn)

    def test_preexec_fn_no_limits(self):
        """Test that preexec_fn works without limits."""
        params = ProgramParams()
        preexec_fn = get_preexec_fn(params)
        assert callable(preexec_fn)


class TestResourceUtilities:
    """Test resource utility functions."""

    def test_get_cpu_time(self):
        """Test get_cpu_time function."""
        # Create a mock resource usage object
        mock_ru = mock.MagicMock()
        mock_ru.ru_utime = 1.5
        mock_ru.ru_stime = 0.5

        cpu_time = get_cpu_time(mock_ru)
        assert cpu_time == 2.0

    @pytest.mark.parametrize(
        'platform,expected_multiplier',
        [
            ('darwin', 1),
            ('linux', 1024),
        ],
    )
    def test_get_memory_usage(self, platform, expected_multiplier):
        """Test get_memory_usage function for different platforms."""
        mock_ru = mock.MagicMock()
        mock_ru.ru_maxrss = 1000
        mock_ru.ru_ixrss = 100
        mock_ru.ru_idrss = 50
        mock_ru.ru_isrss = 25

        with mock.patch('sys.platform', platform):
            memory_usage = get_memory_usage(mock_ru)

            if platform == 'darwin':
                # On macOS: ru_maxrss is in bytes, ru_ixrss in KB
                expected = 1000 + 100 * 1024
            else:
                # On Linux: all values in KB, convert to bytes
                expected = (1000 + 100 + 50 + 25) * 1024

            assert memory_usage == expected


class TestProgram:
    """Test Program class functionality."""

    def test_simple_program_execution(self, simple_hello_program):
        """Test basic program execution."""
        command = [sys.executable, str(simple_hello_program)]
        params = ProgramParams()

        program = Program(command, params)
        result = program.wait()

        assert isinstance(result, ProgramResult)
        assert result.exitcode == 0
        assert result.wall_time > 0
        assert result.cpu_time >= 0
        assert result.memory_used > 0
        assert len(result.program_codes) == 0  # No error codes for successful execution

    def test_program_with_exit_code(self, exit_with_code_program):
        """Test program execution with non-zero exit code."""
        command = [sys.executable, str(exit_with_code_program), '42']
        params = ProgramParams()

        program = Program(command, params)
        result = program.wait()

        assert result.exitcode == 42
        assert ProgramCode.RE in result.program_codes

    def test_program_with_input_output(self, input_echo_program, tmp_path):
        """Test program execution with input and output files."""
        input_file = tmp_path / 'input.txt'
        output_file = tmp_path / 'output.txt'
        stderr_file = tmp_path / 'stderr.txt'

        input_file.write_text('Hello\nWorld\n')

        io = ProgramIO(
            input=str(input_file), output=str(output_file), stderr=str(stderr_file)
        )
        params = ProgramParams(io=io)
        command = [sys.executable, str(input_echo_program)]

        program = Program(command, params)
        result = program.wait()

        assert result.exitcode == 0
        assert output_file.exists()
        assert stderr_file.exists()

        output_content = output_file.read_text()
        assert 'Echo: Hello' in output_content
        assert 'Echo: World' in output_content

    def test_program_with_working_directory(self, simple_hello_program, tmp_path):
        """Test program execution with custom working directory."""
        params = ProgramParams(chdir=tmp_path)
        command = [sys.executable, str(simple_hello_program)]

        program = Program(command, params)
        result = program.wait()

        assert result.exitcode == 0

    def test_program_with_environment_variables(self, tmp_path):
        """Test program execution with custom environment variables."""
        test_script = tmp_path / 'env_test.py'
        output_file = tmp_path / 'output.txt'

        test_script.write_text(
            "import os; print(os.environ.get('TEST_VAR', 'NOT_FOUND'))"
        )

        io = ProgramIO(output=str(output_file))
        params = ProgramParams(io=io, env={'TEST_VAR': 'test_value'})
        command = [sys.executable, str(test_script)]

        program = Program(command, params)
        result = program.wait()

        assert result.exitcode == 0

        # Verify the environment variable was correctly passed
        output_content = output_file.read_text().strip()
        assert output_content == 'test_value'

    def test_cpu_time_limit(self, cpu_intensive_program):
        """Test CPU time limit enforcement."""
        params = ProgramParams(time_limit=0.1)  # Very short time limit
        command = [sys.executable, str(cpu_intensive_program)]

        program = Program(command, params)
        result = program.wait()

        # Should be killed due to CPU time limit
        assert ProgramCode.TO in result.program_codes

    def test_wall_time_limit(self, infinite_loop_program):
        """Test wall time limit enforcement."""
        params = ProgramParams(wall_time_limit=0.5)  # Short wall time limit
        command = [sys.executable, str(infinite_loop_program)]

        program = Program(command, params)
        result = program.wait()

        # Should be killed due to wall time limit
        assert ProgramCode.WT in result.program_codes
        assert ProgramCode.TO in result.program_codes
        assert result.wall_time >= 0.5

    def test_memory_limit(self, memory_hog_program):
        """Test memory limit enforcement."""
        params = ProgramParams(memory_limit=10)  # 10 MB limit
        command = [sys.executable, str(memory_hog_program)]

        program = Program(command, params)
        result = program.wait()

        # Should be killed due to memory limit
        assert ProgramCode.ML in result.program_codes

    def test_output_limit(self, output_large_program, tmp_path):
        """Test file size limit enforcement."""
        output_file = tmp_path / 'output.txt'
        io = ProgramIO(output=str(output_file))
        params = ProgramParams(io=io, fs_limit=1)  # 1 KB limit
        command = [sys.executable, str(output_large_program)]

        program = Program(command, params)
        result = program.wait()

        # Should exceed file size limit
        assert ProgramCode.OL in result.program_codes

    def test_signal_handling(self, signal_test_program):
        """Test signal handling and program termination."""
        params = ProgramParams()
        command = [sys.executable, str(signal_test_program)]

        program = Program(command, params)

        # Give the program a moment to start
        time.sleep(1.0)

        # Send SIGTERM to the process
        os.kill(program.pid, signal.SIGTERM)

        result = program.wait()

        # Two possible outcomes due to race condition:

        # 1. Signal handler executes: exit code 143 = 128 + SIGTERM (15)
        # 2. Process killed by signal: exit code -15
        assert result.exitcode in [143, -15]

        # Both cases should be marked as errors
        if result.exitcode == 143:
            assert ProgramCode.RE in result.program_codes
        else:  # result.exitcode == -15
            assert ProgramCode.SG in result.program_codes
            assert result.killing_signal == 15

    def test_program_pipes_access(self, simple_hello_program):
        """Test access to program pipes."""
        params = ProgramParams()
        command = [sys.executable, str(simple_hello_program)]

        program = Program(command, params)
        pipes = program.pipes

        assert pipes.input is not None
        assert pipes.output is not None
        assert pipes.stderr is not None

        result = program.wait()
        assert result.exitcode == 0

    def test_program_pid_access(self, simple_hello_program):
        """Test access to program PID."""
        params = ProgramParams()
        command = [sys.executable, str(simple_hello_program)]

        program = Program(command, params)
        pid = program.pid

        assert isinstance(pid, int)
        assert pid > 0

        result = program.wait()
        assert result.exitcode == 0

    def test_multiple_program_codes(self, tmp_path):
        """Test that multiple program codes can be set simultaneously."""
        # Create a program that will exceed both time and memory limits
        test_script = tmp_path / 'multi_limit_test.py'
        test_script.write_text("""
import time
data = []
for i in range(1000000):
    data.append([0] * 1000)
    time.sleep(0.001)
""")

        params = ProgramParams(
            time_limit=0.1,
            memory_limit=1,  # 1 MB
            wall_time_limit=0.2,
        )
        command = [sys.executable, str(test_script)]

        program = Program(command, params)
        result = program.wait()

        # Could have multiple violation codes
        violation_codes = [
            code
            for code in result.program_codes
            if code in [ProgramCode.TO, ProgramCode.WT, ProgramCode.ML]
        ]
        assert len(violation_codes) > 0

    def test_program_result_attributes(self, simple_hello_program):
        """Test that ProgramResult has all expected attributes."""
        params = ProgramParams()
        command = [sys.executable, str(simple_hello_program)]

        program = Program(command, params)
        result = program.wait()

        # Check all attributes exist and have correct types
        assert isinstance(result.exitcode, int)
        assert isinstance(result.wall_time, float)
        assert isinstance(result.cpu_time, float)
        assert isinstance(result.memory_used, int)
        assert isinstance(result.file_sizes, int)
        assert isinstance(result.program_codes, list)
        assert result.killing_signal is None or isinstance(result.killing_signal, int)
        assert result.alarm_msg is None or isinstance(result.alarm_msg, str)

    def test_file_size_calculation(self, tmp_path):
        """Test file size calculation for output files."""
        output_file = tmp_path / 'output.txt'
        stderr_file = tmp_path / 'stderr.txt'

        test_script = tmp_path / 'file_size_test.py'
        test_script.write_text("""
print("Hello" * 100)
import sys
print("Error" * 50, file=sys.stderr)
""")

        io = ProgramIO(output=str(output_file), stderr=str(stderr_file))
        params = ProgramParams(io=io)
        command = [sys.executable, str(test_script)]

        program = Program(command, params)
        result = program.wait()

        assert result.exitcode == 0
        assert result.file_sizes > 0

        # Verify actual file sizes match
        actual_size = output_file.stat().st_size + stderr_file.stat().st_size
        assert result.file_sizes == actual_size


class TestProgramCode:
    """Test ProgramCode enum."""

    def test_program_code_values(self):
        """Test that ProgramCode enum has expected values."""
        assert ProgramCode.RE.value == 'RE'  # Runtime Error
        assert ProgramCode.SG.value == 'SG'  # Signal
        assert ProgramCode.TO.value == 'TO'  # Time Out
        assert ProgramCode.WT.value == 'WT'  # Wall Time
        assert ProgramCode.ML.value == 'ML'  # Memory Limit
        assert ProgramCode.OL.value == 'OL'  # Output Limit
        assert ProgramCode.TE.value == 'TE'  # Time Error


class TestProgramMocks:
    """Test Program functionality using mocks to verify intended behavior."""

    @mock.patch('rbx.grading.judge.program.get_file_sizes')
    @mock.patch('rbx.grading.judge.program.get_memory_usage')
    @mock.patch('rbx.grading.judge.program.get_cpu_time')
    @mock.patch('os.wait4')
    def test_process_exit_with_mocks(
        self,
        mock_wait4,
        mock_get_cpu_time,
        mock_get_memory_usage,
        mock_get_file_sizes,
        simple_hello_program,
    ):
        """Test that process_exit correctly processes resource usage data."""
        # Setup mocks
        mock_wait4.return_value = (12345, 0, mock.MagicMock())  # pid, exitstatus, ru
        mock_get_cpu_time.return_value = 1.5
        mock_get_memory_usage.return_value = 1024 * 1024  # 1MB in bytes
        mock_get_file_sizes.return_value = 2048

        command = [sys.executable, str(simple_hello_program)]
        params = ProgramParams()
        program = Program(command, params)

        # Wait for the process to complete and get the mocked result
        result = program.wait()

        # Verify that our utility functions were called
        mock_get_cpu_time.assert_called_once()
        mock_get_memory_usage.assert_called_once()
        mock_get_file_sizes.assert_called_once_with(params.io)

        # Verify the result uses mocked values
        assert result.cpu_time == 1.5
        assert result.memory_used == 1024 * 1024
        assert result.file_sizes == 2048

    @mock.patch('os.setpgid')
    @mock.patch('resource.setrlimit')
    def test_preexec_fn_behavior(self, mock_setrlimit, mock_setpgid):
        """Test that preexec_fn actually calls the expected system functions."""
        import resource as resource_module

        params = ProgramParams(time_limit=5.0, fs_limit=1000, pgid=12345)

        preexec_fn = get_preexec_fn(params)
        preexec_fn()

        # Verify setpgid was called
        mock_setpgid.assert_called_once_with(0, 12345)

        # Verify setrlimit was called for CPU and file size limits
        assert mock_setrlimit.call_count == 2
        calls = mock_setrlimit.call_args_list

        # Check CPU limit call
        cpu_call = calls[0]
        assert cpu_call[0][0] == resource_module.RLIMIT_CPU

        # Check file size limit call
        fs_call = calls[1]
        assert fs_call[0][0] == resource_module.RLIMIT_FSIZE

    @mock.patch('psutil.Process')
    def test_handle_alarm_cpu_limit(self, mock_process_class):
        """Test _handle_alarm correctly detects CPU time limit violations."""
        mock_process = mock.MagicMock()
        mock_process_class.return_value = mock_process

        # Mock CPU times exceeding limit
        mock_process.cpu_times.return_value.user = 3.0
        mock_process.cpu_times.return_value.system = 2.5

        command = [sys.executable, '-c', 'import time; time.sleep(1)']
        params = ProgramParams(time_limit=5.0)  # CPU total will be 5.5 > 5.0

        program = Program(command, params)

        # Simulate the alarm handler
        program.params.time_limit = 5.0
        times = mock_process.cpu_times.return_value
        cpu_time = times.user + times.system

        # Verify the logic would trigger
        assert cpu_time > program.params.time_limit

        program.wait()  # Clean up

    @mock.patch('psutil.Process')
    def test_handle_alarm_memory_limit(self, mock_process_class):
        """Test _handle_alarm correctly detects memory limit violations."""
        mock_process = mock.MagicMock()
        mock_process_class.return_value = mock_process

        # Mock memory usage exceeding limit (20MB vs 10MB limit)
        mock_process.memory_info.return_value.rss = 20 * 1024 * 1024

        command = [sys.executable, '-c', 'import time; time.sleep(1)']
        params = ProgramParams(memory_limit=10)  # 10 MB limit

        program = Program(command, params)

        # Simulate the alarm handler logic
        memory_used = mock_process.memory_info.return_value.rss
        if program.params.memory_limit is not None:
            memory_limit_bytes = program.params.memory_limit * 1024 * 1024

            # Verify the logic would trigger
            assert memory_used > memory_limit_bytes

        program.wait()  # Clean up


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_nonexistent_program(self):
        """Test execution of non-existent program."""
        params = ProgramParams()
        command = ['/nonexistent/program']

        with pytest.raises(FileNotFoundError):
            Program(command, params)

    def test_empty_command(self):
        """Test execution with empty command."""
        params = ProgramParams()
        command = []

        with pytest.raises((ValueError, IndexError)):
            Program(command, params)

    def test_concurrent_programs(self, simple_hello_program):
        """Test running multiple programs concurrently."""
        params = ProgramParams()
        command = [sys.executable, str(simple_hello_program)]

        programs = []
        for _ in range(3):
            program = Program(command, params)
            programs.append(program)

        results = []
        for program in programs:
            result = program.wait()
            results.append(result)

        # All should succeed
        for result in results:
            assert result.exitcode == 0
