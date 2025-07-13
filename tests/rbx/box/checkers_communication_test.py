import pathlib
import signal
from typing import Dict, Iterator, Tuple

import pytest

from rbx.box import checkers
from rbx.box.checkers import compile_checker
from rbx.box.schema import Testcase
from rbx.box.testing import testing_package
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.limits import Limits
from rbx.grading.steps import Outcome, RunLog, RunLogMetadata

INTERESTING_CHECKERS = [
    'checkers/checker.cpp',
    'checkers/checker-fl.cpp',
    'checkers/checker-crash.cpp',
]


@pytest.fixture(scope='module')
def pkg_with_compiled_checker(tmp_path_factory):
    pkg_dir = tmp_path_factory.mktemp('pkg')
    with testing_package.TestingPackage(pkg_dir.absolute()) as testing_pkg:
        checkers = {}
        for checker in INTERESTING_CHECKERS:
            testing_pkg.set_checker('checker.cpp', src=checker)
            checkers[checker] = compile_checker()
        yield testing_pkg, checkers


@pytest.fixture(autouse=True)
def checker_pkg(
    pkg_with_compiled_checker: Tuple[testing_package.TestingPackage, str],
    testing_pkg: testing_package.TestingPackage,
) -> Iterator[testing_package.TestingPackage]:
    pkg, _ = pkg_with_compiled_checker
    testing_pkg.copy_from(pkg)
    with testing_pkg:
        yield testing_pkg


@pytest.fixture
def checker_digest(
    pkg_with_compiled_checker: Tuple[testing_package.TestingPackage, Dict[str, str]],
) -> str:
    _, checkers = pkg_with_compiled_checker
    return checkers['checkers/checker.cpp']


@pytest.fixture
def checker_digest_dict(
    pkg_with_compiled_checker: Tuple[testing_package.TestingPackage, Dict[str, str]],
) -> Dict[str, str]:
    _, checkers = pkg_with_compiled_checker
    return checkers


@pytest.fixture
def testcase(tmp_path_factory) -> Testcase:
    testcase_dir = tmp_path_factory.mktemp('testcase')
    input_path = testcase_dir / 'input.txt'
    input_path.touch()
    output_path = testcase_dir / 'output.txt'
    output_path.touch()
    return Testcase(
        inputPath=input_path,
        outputPath=output_path,
    )


@pytest.fixture
def program_output(tmp_path_factory) -> pathlib.Path:
    output_dir = tmp_path_factory.mktemp('output')
    output_path = output_dir / 'output.txt'
    output_path.touch()
    return output_path


@pytest.fixture
def interactor_stderr(tmp_path_factory) -> pathlib.Path:
    stderr_dir = tmp_path_factory.mktemp('stderr')
    stderr_path = stderr_dir / 'stderr.txt'
    stderr_path.touch()
    return stderr_path


@pytest.fixture
def testlib_eof_stderr(interactor_stderr: pathlib.Path) -> pathlib.Path:
    interactor_stderr.write_text('wrong output format Unexpected end of file')
    return interactor_stderr


@pytest.fixture
def run_log() -> RunLog:
    return RunLog(
        exitcode=0,
        exitstatus=SandboxBase.EXIT_OK,
        metadata=RunLogMetadata(
            limits=Limits(time=1000, memory=1024, output=1024, isDoubleTL=True),
            timeLimit=1000,
            memoryLimit=1024,
            retryIndex=0,
        ),
        exitindex=0,
    )


@pytest.fixture
def interactor_run_log() -> RunLog:
    return RunLog(
        exitcode=0,
        exitstatus=SandboxBase.EXIT_OK,
        metadata=RunLogMetadata(
            limits=Limits(time=1000, memory=1024, output=1024, isDoubleTL=True),
            timeLimit=1000,
            memoryLimit=1024,
            retryIndex=0,
        ),
        exitindex=1,
    )


@pytest.fixture
def interactor_exit_first(run_log: RunLog, interactor_run_log: RunLog):
    interactor_run_log.exitindex = 0
    run_log.exitindex = 1


class TestCheckCommunicationInternalError:
    async def test_check_communication_sol_run_log_is_none(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        result = await checkers.check_communication(
            checker_digest,
            None,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.INTERNAL_ERROR

    async def test_check_communication_interactor_run_log_is_none(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        result = await checkers.check_communication(
            checker_digest,
            run_log,
            None,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.INTERNAL_ERROR

    async def test_check_communication_sol_run_log_has_sandbox_error(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitstatus = SandboxBase.EXIT_SANDBOX_ERROR
        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.INTERNAL_ERROR

    async def test_check_communication_interactor_run_log_has_sandbox_error(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        interactor_run_log.exitstatus = SandboxBase.EXIT_SANDBOX_ERROR
        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.INTERNAL_ERROR


@pytest.mark.usefixtures('interactor_exit_first')
class TestCheckCommunicationInteractorExitedFirst:
    async def test_check_communication_wa(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN
        interactor_run_log.exitcode = 1
        interactor_run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.WRONG_ANSWER

    async def test_check_communication_sol_terminated_and_fl(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitstatus = SandboxBase.EXIT_TERMINATED
        interactor_run_log.exitcode = 3
        interactor_run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.JUDGE_FAILED

    async def test_check_communication_sol_terminated_and_interactor_rte(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitstatus = SandboxBase.EXIT_TERMINATED
        interactor_run_log.exitcode = 42
        interactor_run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.JUDGE_FAILED

    async def test_check_communication_sol_terminated_and_interactor_tle(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitstatus = SandboxBase.EXIT_TERMINATED
        interactor_run_log.exitstatus = SandboxBase.EXIT_TIMEOUT

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED

    async def test_check_communication_sol_terminated_and_interactor_internal_error(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitstatus = SandboxBase.EXIT_TERMINATED
        interactor_run_log.exitstatus = SandboxBase.EXIT_SANDBOX_ERROR

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.INTERNAL_ERROR

    async def test_check_communication_sol_sigpipe_and_wa(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitcode = -signal.SIGPIPE
        interactor_run_log.exitcode = 1
        interactor_run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.WRONG_ANSWER

    async def test_check_communication_sol_sigpipe_as_rte_and_wa(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitcode = 2
        run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN
        interactor_run_log.exitcode = 1
        interactor_run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.WRONG_ANSWER


class TestCheckCommunicatedSolutionCrashedFirst:
    async def test_check_communication_sol_rte(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        testlib_eof_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitcode = 2
        run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            testlib_eof_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.RUNTIME_ERROR

    async def test_check_communication_sol_mle(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        testlib_eof_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitstatus = SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            testlib_eof_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.MEMORY_LIMIT_EXCEEDED

    async def test_check_communication_sol_tle(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        testlib_eof_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        run_log.exitstatus = SandboxBase.EXIT_TIMEOUT

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            testlib_eof_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED


class TestCheckCommunicatedSolutionExitedOkFirst:
    async def test_check_communication_sol_ok_interactor_wa(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        interactor_run_log.exitcode = 1
        interactor_run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.WRONG_ANSWER

    async def test_check_communication_sol_ok_interactor_fl(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        interactor_run_log.exitcode = 3
        interactor_run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.JUDGE_FAILED

    async def test_check_communication_sol_ok_interactor_rte(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        interactor_run_log.exitcode = 42
        interactor_run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.JUDGE_FAILED

    async def test_check_communication_sol_ok_interactor_tle(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        interactor_run_log.exitstatus = SandboxBase.EXIT_TIMEOUT

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED


class TestCheckCommunicationLegacyChecker:
    async def test_check_communication_checker_ac(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        assert testcase.outputPath is not None
        testcase.outputPath.write_text('123\n')
        program_output.write_text('123\n')

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.ACCEPTED

    async def test_check_communication_checker_wa(
        self,
        checker_digest: str,
        testcase: Testcase,
        program_output: pathlib.Path,
        interactor_stderr: pathlib.Path,
        run_log: RunLog,
        interactor_run_log: RunLog,
    ) -> None:
        assert testcase.outputPath is not None
        testcase.outputPath.write_text('123\n')
        program_output.write_text('456\n')

        result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_stderr,
            testcase,
            program_output,
        )

        assert result.outcome == Outcome.WRONG_ANSWER
