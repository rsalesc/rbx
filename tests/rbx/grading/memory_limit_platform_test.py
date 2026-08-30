"""Memory-limit behaviour that cannot hold on Linux and macOS at once.

rbx enforces `memoryLimit` two different ways, and the difference is visible in
the verdict a memory-hungry program gets:

- On **Linux**, `RLIMIT_AS` caps the address space at exactly the limit, so the
  allocation fails *inside* the program. It dies of `MemoryError` /
  `std::bad_alloc` -- a runtime error -- and never reaches the watchdog. Memory
  that is reserved but never touched is charged.
- On **macOS**, no `RLIMIT_AS` is imposed. The RSS watchdog samples the program
  and kills it once it goes over, which is what produces an `MLE`. A reservation
  that is never touched never becomes resident, so it is not charged.

Every test here is gated on one platform. The parts of the memory limit that
behave the same everywhere -- that a limit is plumbed through at all, that a fat
parent does not push a trivial program over it -- stay in
`judge/test_program.py` and `steps_run_test.py`; what lands in *this* file is
exactly what diverges, so that when the two platforms drift again there is one
obvious place to look.
"""

import pathlib
import sys

import pytest

from rbx.grading import steps
from rbx.grading.judge.program import Program, ProgramCode, ProgramIO, ProgramParams
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    GradingLogsHolder,
)

linux_only = pytest.mark.skipif(
    sys.platform != 'linux', reason='RLIMIT_AS is imposed on Linux only'
)
darwin_only = pytest.mark.skipif(
    sys.platform != 'darwin', reason='the RSS watchdog is the only enforcement here'
)

# Comfortably above what an interpreter needs to start, so these tests exercise a
# failing *allocation* rather than a program that could never run at all.
LIMIT_MB = 256

# Reserves address space without touching a page of it: charged by RLIMIT_AS on
# Linux, invisible to an RSS sampler on macOS.
RESERVE_UNTOUCHED = (
    'import mmap; m = mmap.mmap(-1, 512 * 1024 * 1024); print("reserved")'
)

# Reports the address-space limit the child actually runs under.
PRINT_AS_LIMIT = 'import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0])'


def _run_python(code: str, tmp_path: pathlib.Path, **kwargs):
    """Run `code` in a child interpreter, capturing stdout."""
    output = tmp_path / 'out.txt'
    params = ProgramParams(io=ProgramIO(output=str(output)), **kwargs)
    result = Program([sys.executable, '-c', code], params).wait()
    return result, output.read_text().strip() if output.is_file() else ''


def _allocate(mb: int, tmp_path: pathlib.Path, **kwargs):
    """Run a child that allocates `mb` MiB and touches every page of it."""
    code = (
        'data = []\n'
        f'for _ in range({mb}):\n'
        '    chunk = bytearray(1024 * 1024)\n'
        '    for j in range(0, len(chunk), 4096):\n'
        '        chunk[j] = 1\n'
        '    data.append(chunk)\n'
        'print("allocated")\n'
    )
    return _run_python(code, tmp_path, **kwargs)


@linux_only
class TestLinuxAddressSpaceCap:
    def test_the_cap_is_visible_to_the_child(self, tmp_path):
        """The end-to-end check that `RLIMIT_AS` is actually imposed: ask the
        child itself what it is running under."""
        result, out = _run_python(PRINT_AS_LIMIT, tmp_path, memory_limit=LIMIT_MB)

        assert result.exitcode == 0
        assert int(out) == LIMIT_MB * 1024 * 1024

    def test_no_cap_is_imposed_without_a_memory_limit(self, tmp_path):
        import resource

        result, out = _run_python(PRINT_AS_LIMIT, tmp_path)

        assert result.exitcode == 0
        assert int(out) == resource.RLIM_INFINITY

    def test_an_over_limit_program_dies_from_the_failed_allocation(self, tmp_path):
        """The verdict divergence itself: over the limit is a *runtime* failure
        here, not an MLE -- the program never survives to be killed."""
        result, out = _allocate(512, tmp_path, memory_limit=LIMIT_MB)

        assert result.exitcode != 0
        assert 'allocated' not in out
        assert ProgramCode.ML not in result.program_codes

    def test_an_untouched_reservation_is_charged(self, tmp_path):
        """`RLIMIT_AS` limits virtual memory, so a reservation costs its full
        size even though not one page of it is ever resident."""
        result, out = _run_python(RESERVE_UNTOUCHED, tmp_path, memory_limit=LIMIT_MB)

        assert result.exitcode != 0
        assert 'reserved' not in out

    def test_a_real_offender_is_still_caught_under_a_fat_parent(self, tmp_path):
        """The guarantee `test_program.py` pins for the RSS sampler still holds
        here, just delivered by the kernel rather than by the watchdog."""
        ballast = bytearray(150 * 1024 * 1024)
        try:
            for i in range(0, len(ballast), 4096):
                ballast[i] = 1

            result, out = _allocate(512, tmp_path, memory_limit=LIMIT_MB)
        finally:
            del ballast

        assert result.exitcode != 0
        assert 'allocated' not in out

    async def test_run_reports_a_failed_allocation_rather_than_mle(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """The same divergence one layer up, where it becomes a verdict."""
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
            address_space=LIMIT_MB,
        )
        command = f'{sys.executable} script.py 512'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitstatus != SandboxBase.EXIT_OK
        assert result.exitstatus != SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED


@darwin_only
class TestDarwinRssWatchdog:
    def test_no_cap_is_imposed_on_the_child(self, tmp_path):
        """Whatever the child inherits, it is not the limit rbx was given."""
        result, out = _run_python(PRINT_AS_LIMIT, tmp_path, memory_limit=LIMIT_MB)

        assert result.exitcode == 0
        assert int(out) != LIMIT_MB * 1024 * 1024

    def test_an_over_limit_program_is_killed_by_the_watchdog(self, tmp_path):
        result, _ = _allocate(512, tmp_path, memory_limit=LIMIT_MB)

        assert ProgramCode.ML in result.program_codes

    def test_an_untouched_reservation_is_not_charged(self, tmp_path):
        """Nothing is resident, so the sampler never sees it and the program is
        left alone -- the mirror image of the Linux case."""
        result, out = _run_python(RESERVE_UNTOUCHED, tmp_path, memory_limit=LIMIT_MB)

        assert result.exitcode == 0
        assert out == 'reserved'
        assert ProgramCode.ML not in result.program_codes

    def test_a_real_offender_is_still_caught_under_a_fat_parent(self, tmp_path):
        """No false negatives in the band `ru_maxrss` cannot measure: the sampler
        has to catch the child before it exits."""
        ballast = bytearray(150 * 1024 * 1024)
        try:
            for i in range(0, len(ballast), 4096):
                ballast[i] = 1

            result, _ = _allocate(512, tmp_path, memory_limit=LIMIT_MB)
        finally:
            del ballast

        assert ProgramCode.ML in result.program_codes

    async def test_run_reports_mle(
        self, sandbox: SandboxBase, cleandir: pathlib.Path, testdata_path: pathlib.Path
    ):
        """Regression test for the memory limit detection bug (#720-era).

        `get_memory_usage` used to divide `ru_maxrss` by 1024 on macOS, where it
        is already in bytes, so the limit was never detected. `memory_heavy.py`
        allocates and exits quickly, leaning on the post-execution check rather
        than on the sampling thread.
        """
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
            address_space=50,
        )
        command = f'{sys.executable} script.py 100'

        result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitstatus == SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED
        assert result.memory is not None
        assert result.memory > 50 * 1024 * 1024
