import pathlib
from typing import Dict, Iterator, Tuple
from unittest import mock

import pytest
import typer

from rbx.box import checkers
from rbx.box.checkers import compile_checker, compile_interactor
from rbx.box.schema import Checker, CodeItem, Testcase
from rbx.box.testing import testing_package
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.limits import Limits
from rbx.grading.steps import DigestOrSource, Outcome, RunLog, RunLogMetadata
from rbx.utils import StatusProgress

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
def testcase_no_output(tmp_path_factory) -> Testcase:
    testcase_dir = tmp_path_factory.mktemp('testcase')
    input_path = testcase_dir / 'input.txt'
    input_path.touch()
    return Testcase(
        inputPath=input_path,
        outputPath=None,
    )


@pytest.fixture
def program_output(tmp_path_factory) -> pathlib.Path:
    output_dir = tmp_path_factory.mktemp('output')
    output_path = output_dir / 'output.txt'
    output_path.touch()
    return output_path


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
    )


@pytest.fixture
def run_log_with_warnings(run_log: RunLog) -> RunLog:
    run_log.warnings = True
    return run_log


# Compilation tests
@mock.patch('rbx.box.code.compile_item')
@mock.patch('rbx.box.package.get_checker')
def test_compile_checker_success(
    mock_get_checker: mock.Mock,
    mock_compile_item: mock.Mock,
) -> None:
    mock_get_checker.return_value = CodeItem(path=pathlib.Path('checker.cpp'))
    mock_compile_item.return_value = 'test_digest'

    result = compile_checker()

    assert result == 'test_digest'
    mock_get_checker.assert_called_once()
    mock_compile_item.assert_called_once()


@mock.patch('rbx.box.code.compile_item')
@mock.patch('rbx.box.package.get_checker')
def test_compile_checker_with_progress(
    mock_get_checker: mock.Mock,
    mock_compile_item: mock.Mock,
) -> None:
    mock_get_checker.return_value = CodeItem(path=pathlib.Path('checker.cpp'))
    mock_compile_item.return_value = 'test_digest'
    progress = mock.Mock(spec=StatusProgress)

    result = compile_checker(progress)

    assert result == 'test_digest'
    progress.update.assert_called_once_with(
        'Compiling checker [item]checker.cpp[/item]...'
    )


@mock.patch('rbx.box.code.compile_item')
@mock.patch('rbx.box.package.get_checker')
def test_compile_checker_failure(
    mock_get_checker: mock.Mock,
    mock_compile_item: mock.Mock,
) -> None:
    mock_get_checker.return_value = CodeItem(path=pathlib.Path('checker.cpp'))
    mock_compile_item.side_effect = Exception('Compilation failed')

    with pytest.raises(typer.Exit):
        compile_checker()


@mock.patch('rbx.box.code.compile_item')
@mock.patch('rbx.box.package.get_interactor')
def test_compile_interactor_success(
    mock_get_interactor: mock.Mock,
    mock_compile_item: mock.Mock,
) -> None:
    mock_get_interactor.return_value = CodeItem(path=pathlib.Path('interactor.cpp'))
    mock_compile_item.return_value = 'test_digest'

    result = compile_interactor()

    assert result == 'test_digest'
    mock_get_interactor.assert_called_once()
    mock_compile_item.assert_called_once()


@mock.patch('rbx.box.code.compile_item')
@mock.patch('rbx.box.package.get_interactor')
def test_compile_interactor_with_progress(
    mock_get_interactor: mock.Mock,
    mock_compile_item: mock.Mock,
) -> None:
    mock_get_interactor.return_value = CodeItem(path=pathlib.Path('interactor.cpp'))
    mock_compile_item.return_value = 'test_digest'
    progress = mock.Mock(spec=StatusProgress)

    result = compile_interactor(progress)

    assert result == 'test_digest'
    progress.update.assert_called_once_with('Compiling interactor...')


@mock.patch('rbx.box.package.get_interactor')
def test_compile_interactor_not_found(
    mock_get_interactor: mock.Mock,
) -> None:
    mock_get_interactor.return_value = None

    with pytest.raises(typer.Exit):
        compile_interactor()


@mock.patch('rbx.box.code.compile_item')
@mock.patch('rbx.box.package.get_interactor')
def test_compile_interactor_failure(
    mock_get_interactor: mock.Mock,
    mock_compile_item: mock.Mock,
) -> None:
    mock_get_interactor.return_value = CodeItem(path=pathlib.Path('interactor.cpp'))
    mock_compile_item.side_effect = Exception('Compilation failed')

    with pytest.raises(typer.Exit):
        compile_interactor()


# Test check_with_no_output function
def test_check_with_no_output_none() -> None:
    result = checkers.check_with_no_output(None)
    assert result.outcome == Outcome.INTERNAL_ERROR


def test_check_with_no_output_accepted(run_log: RunLog) -> None:
    result = checkers.check_with_no_output(run_log)
    assert result.outcome == Outcome.ACCEPTED


def test_check_with_no_output_tle(run_log: RunLog) -> None:
    run_log.exitstatus = SandboxBase.EXIT_TIMEOUT
    result = checkers.check_with_no_output(run_log)
    assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED


def test_check_with_no_output_soft_tle(run_log: RunLog) -> None:
    run_log.time = 1.5  # Greater than TL but less than 2*TL
    result = checkers.check_with_no_output(run_log)
    assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    assert result.no_tle_outcome == Outcome.ACCEPTED


# Test with testcase that has no output file
async def test_check_with_testcase_no_output(
    checker_digest: str,
    testcase_no_output: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    # When there's no expected output, program output should also be empty
    program_output.write_text('')
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase_no_output,
        program_output,
    )
    assert result.outcome == Outcome.ACCEPTED


# Test sanitizer warnings
async def test_check_sets_sanitizer_warnings(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log_with_warnings: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    result = await checkers.check(
        checker_digest,
        run_log_with_warnings,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.ACCEPTED
    assert result.sanitizer_warnings is True


async def test_check_no_sanitizer_warnings(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.ACCEPTED
    assert result.sanitizer_warnings is False


# Test output size calculation edge cases
async def test_program_output_exactly_at_limit(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    # Write exactly 1024 KB (1024 * 1024 bytes)
    content = 'a' * (1024 * 1024)
    testcase.outputPath.write_text(content)
    program_output.write_text(content)

    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.ACCEPTED


async def test_program_output_just_over_limit(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    # Write just over 1024 KB (1024 * 1024 + 1 bytes)
    program_output.write_text('a' * (1024 * 1024 + 1))

    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.OUTPUT_LIMIT_EXCEEDED


# Test checker with different exit status combinations
@mock.patch('rbx.box.code.run_item')
async def test_checker_with_timeout_exit_status(
    mock_run_item: mock.AsyncMock,
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    mock_run_item.return_value = RunLog(
        exitcode=0,
        exitstatus=SandboxBase.EXIT_TIMEOUT,
    )

    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.JUDGE_FAILED
    assert 'checker failed with exit status' in result.message


@mock.patch('rbx.box.code.run_item')
async def test_checker_with_signal_exit_status(
    mock_run_item: mock.AsyncMock,
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    mock_run_item.return_value = RunLog(
        exitcode=0,
        exitstatus=SandboxBase.EXIT_SIGNAL,
    )

    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.JUDGE_FAILED
    assert 'checker failed with exit status' in result.message


async def test_check_fails_with_no_run_log(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')
    result = await checkers.check(
        checker_digest,
        None,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.INTERNAL_ERROR


async def test_wcmp_checker_works_with_skipped_no_run_log(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')
    result = await checkers.check(
        checker_digest,
        None,
        testcase,
        program_output,
        skip_run_log=True,
    )
    assert result.outcome == Outcome.ACCEPTED


async def test_wcmp_checker_works_with_skipped_bad_run_log(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
        skip_run_log=True,
    )
    assert result.outcome == Outcome.ACCEPTED


async def test_wcmp_checker_works(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.ACCEPTED


async def test_wcmp_checker_wa(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('456\n')
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.WRONG_ANSWER


async def test_run_log_has_sandbox_tle(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.exitstatus = SandboxBase.EXIT_TIMEOUT
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED


async def test_run_log_has_sandbox_idleness(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.exitstatus = SandboxBase.EXIT_TIMEOUT_WALL
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.IDLENESS_LIMIT_EXCEEDED


async def test_run_log_has_sandbox_mle(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.exitstatus = SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.MEMORY_LIMIT_EXCEEDED


async def test_run_log_has_sandbox_rte(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.RUNTIME_ERROR


async def test_run_log_has_sandbox_signal(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.exitstatus = SandboxBase.EXIT_SIGNAL
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.RUNTIME_ERROR


async def test_run_log_has_sandbox_output_limit(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.exitstatus = SandboxBase.EXIT_OUTPUT_LIMIT_EXCEEDED
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.OUTPUT_LIMIT_EXCEEDED


async def test_run_log_has_sandbox_internal_error(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.exitstatus = SandboxBase.EXIT_SANDBOX_ERROR
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.INTERNAL_ERROR


async def test_run_log_has_time_based_2tle(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.time = 2.5  # Greater than 2*TL = 2s
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED


async def test_run_log_has_unbounded_tl(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.time = 2.5  # Greater than 2*TL = 2s
    assert run_log.metadata is not None
    run_log.metadata.timeLimit = None  # TL is unbounded
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.ACCEPTED


async def test_run_log_has_unbounded_tl_because_sanitized(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.time = 2.5  # Greater than 2*TL = 2s
    assert run_log.metadata is not None
    run_log.metadata.is_sanitized = True
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.ACCEPTED


async def test_run_log_has_soft_tle(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.time = 1.5  # Less than 2*TL = 2s
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    assert result.no_tle_outcome == Outcome.ACCEPTED


async def test_run_log_has_soft_tle_but_wa(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('456\n')

    run_log.time = 1.5  # Less than 2*TL = 2s
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    assert result.no_tle_outcome == Outcome.WRONG_ANSWER


async def test_run_log_has_soft_tle_but_rte(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    run_log.time = 1.5  # Less than 2*TL = 2s
    run_log.exitstatus = SandboxBase.EXIT_NONZERO_RETURN
    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.TIME_LIMIT_EXCEEDED
    assert result.no_tle_outcome == Outcome.RUNTIME_ERROR


async def test_program_output_is_too_large(
    checker_digest: str,
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    assert testcase.outputPath
    program_output.write_text('123\n' * 10**6)

    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.OUTPUT_LIMIT_EXCEEDED


async def test_checker_item_run_log_has_fl_exitcode(
    checker_digest_dict: Dict[str, str],
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    checker_digest = checker_digest_dict['checkers/checker-fl.cpp']
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.JUDGE_FAILED


async def test_checker_item_run_log_has_invalid_exitcode(
    checker_digest_dict: Dict[str, str],
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    checker_digest = checker_digest_dict['checkers/checker-crash.cpp']
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    result = await checkers.check(
        checker_digest,
        run_log,
        testcase,
        program_output,
    )
    assert result.outcome == Outcome.JUDGE_FAILED
    assert 'checker failed with unknown exit code 42' in result.message


@mock.patch('rbx.box.code.run_item')
async def test_checker_item_run_log_is_none(
    mock_run_item: mock.AsyncMock,
    checker_digest_dict: Dict[str, str],
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    checker_digest = checker_digest_dict['checkers/checker.cpp']
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    mock_run_item.return_value = None

    with pytest.raises(typer.Exit):  # noqa: F821
        await checkers.check(
            checker_digest,
            run_log,
            testcase,
            program_output,
        )

    mock_run_item.assert_awaited_with(
        Checker(
            path=pathlib.Path('checker.cpp'),
        ),
        DigestOrSource.create(checker_digest),
        stderr=mock.ANY,
        inputs=mock.ANY,
        extra_args=mock.ANY,
    )


@mock.patch('rbx.box.code.run_item')
async def test_checker_item_has_sandbox_error(
    mock_run_item: mock.AsyncMock,
    checker_digest_dict: Dict[str, str],
    testcase: Testcase,
    program_output: pathlib.Path,
    run_log: RunLog,
) -> None:
    checker_digest = checker_digest_dict['checkers/checker.cpp']
    assert testcase.outputPath
    testcase.outputPath.write_text('123\n')
    program_output.write_text('123\n')

    mock_run_item.return_value = RunLog(
        exitcode=0,
        exitstatus=SandboxBase.EXIT_SANDBOX_ERROR,
    )

    with pytest.raises(typer.Exit):  # noqa: F821
        await checkers.check(
            checker_digest,
            run_log,
            testcase,
            program_output,
        )

    mock_run_item.assert_awaited_with(
        Checker(
            path=pathlib.Path('checker.cpp'),
        ),
        DigestOrSource.create(checker_digest),
        stderr=mock.ANY,
        inputs=mock.ANY,
        extra_args=mock.ANY,
    )


# Test that process_checker_run_log uses last line of message
def test_process_checker_run_log_uses_last_line() -> None:
    """Test that process_checker_run_log extracts the last line from multi-line messages."""
    checker_run_log = RunLog(
        exitcode=1,
        exitstatus=SandboxBase.EXIT_NONZERO_RETURN,
    )
    multi_line_message = 'Debug info\nMore debug\nActual error message'

    result = checkers.process_checker_run_log(checker_run_log, multi_line_message)

    assert result.outcome == Outcome.WRONG_ANSWER
    assert result.message == 'Actual error message'
