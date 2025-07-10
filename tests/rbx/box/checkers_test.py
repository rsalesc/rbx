import pathlib
from typing import Dict, Tuple
from unittest import mock

import pytest
import typer

from rbx.box import checkers
from rbx.box.checkers import compile_checker
from rbx.box.schema import CodeItem, Testcase
from rbx.box.testing import testing_package
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.limits import Limits
from rbx.grading.steps import DigestOrSource, Outcome, RunLog, RunLogMetadata

INTERESTING_CHECKERS = [
    'checkers/checker.cpp',
    'checkers/checker-fl.cpp',
    'checkers/checker-crash.cpp',
]


@pytest.fixture(scope='package')
def pkg_with_compiled_checker(tmp_path_factory, pkg_cder):
    pkg_dir = tmp_path_factory.mktemp('pkg')
    with pkg_cder(pkg_dir.absolute()):
        testing_pkg = testing_package.TestingPackage(pkg_dir.absolute())
        checkers = {}
        for checker in INTERESTING_CHECKERS:
            testing_pkg.set_checker('checker.cpp', src=checker)
            checkers[checker] = compile_checker()
        yield testing_pkg, checkers
        testing_pkg.cleanup()


@pytest.fixture
def checker_pkg(
    pkg_with_compiled_checker: Tuple[testing_package.TestingPackage, str],
    testing_pkg: testing_package.TestingPackage,
) -> testing_package.TestingPackage:
    pkg, _ = pkg_with_compiled_checker
    testing_pkg.copy_from(pkg)
    return testing_pkg


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
        CodeItem(
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
        CodeItem(
            path=pathlib.Path('checker.cpp'),
        ),
        DigestOrSource.create(checker_digest),
        stderr=mock.ANY,
        inputs=mock.ANY,
        extra_args=mock.ANY,
    )
