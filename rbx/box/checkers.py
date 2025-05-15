import pathlib
import signal
from typing import List, Optional

import typer

from rbx import console
from rbx.box import package
from rbx.box.code import SanitizationLevel, compile_item, run_item
from rbx.box.schema import Testcase
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.steps import (
    CheckerResult,
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
    GradingFileInput,
    Outcome,
    RunLog,
)
from rbx.utils import StatusProgress


def compile_checker(progress: Optional[StatusProgress] = None) -> str:
    checker = package.get_checker()

    if progress:
        progress.update('Compiling checker...')

    try:
        digest = compile_item(checker, sanitized=SanitizationLevel.PREFER)
    except Exception as e:
        console.console.print('[error]Failed compiling checker.[/error]')
        raise typer.Exit(1) from e
    return digest


def compile_interactor(progress: Optional[StatusProgress] = None) -> str:
    interactor = package.get_interactor()

    if interactor is None:
        console.console.print('[error]No interactor found for this problem.[/error]')
        raise typer.Exit(1)

    if progress:
        progress.update('Compiling interactor...')

    try:
        digest = compile_item(interactor, sanitized=SanitizationLevel.PREFER)
    except Exception as e:
        console.console.print('[error]Failed compiling interactor.[/error]')
        raise typer.Exit(1) from e
    return digest


def _any_failed(logs: List[Optional[RunLog]]) -> bool:
    return any(
        log is None or log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR for log in logs
    )


def _check_pre_output(run_log: Optional[RunLog]) -> CheckerResult:
    is_sanitized = (
        run_log is not None
        and run_log.metadata is not None
        and run_log.metadata.is_sanitized
    )

    if run_log is None:
        return CheckerResult(outcome=Outcome.INTERNAL_ERROR)

    timelimit = (
        run_log.metadata.limits.get_expanded_tl()
        if run_log.metadata is not None
        else None
    )
    is_tl_unbounded = (
        run_log is not None
        and run_log.metadata is not None
        and run_log.metadata.timeLimit is None
    )

    if (
        run_log.time is not None
        and timelimit is not None
        and run_log.time * 1000 > timelimit
        and not is_sanitized
        and not is_tl_unbounded
    ):
        return CheckerResult(outcome=Outcome.TIME_LIMIT_EXCEEDED)

    if run_log.exitstatus in [SandboxBase.EXIT_SIGNAL, SandboxBase.EXIT_NONZERO_RETURN]:
        return CheckerResult(outcome=Outcome.RUNTIME_ERROR)
    if run_log.exitstatus == SandboxBase.EXIT_TIMEOUT:
        return CheckerResult(outcome=Outcome.TIME_LIMIT_EXCEEDED)
    if run_log.exitstatus == SandboxBase.EXIT_TIMEOUT_WALL:
        return CheckerResult(outcome=Outcome.IDLENESS_LIMIT_EXCEEDED)
    if run_log.exitstatus == SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED:
        return CheckerResult(outcome=Outcome.MEMORY_LIMIT_EXCEEDED)
    if run_log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR:
        return CheckerResult(outcome=Outcome.INTERNAL_ERROR)
    if run_log.exitstatus == SandboxBase.EXIT_OUTPUT_LIMIT_EXCEEDED:
        return CheckerResult(outcome=Outcome.OUTPUT_LIMIT_EXCEEDED)
    return CheckerResult(outcome=Outcome.ACCEPTED)


def _convert_tle(result: CheckerResult, run_log: Optional[RunLog]) -> CheckerResult:
    if result.outcome.is_slow():
        # This already is a TLE outcome.
        return result
    is_sanitized = (
        run_log is not None
        and run_log.metadata is not None
        and run_log.metadata.is_sanitized
    )
    timelimit = (
        run_log.metadata.limits.time
        if run_log is not None and run_log.metadata is not None
        else None
    )
    is_tl_unbounded = (
        run_log is not None
        and run_log.metadata is not None
        and run_log.metadata.timeLimit is None
    )
    if (
        run_log is not None
        and run_log.time is not None
        and timelimit is not None
        and run_log.time * 1000 >= timelimit
        and not is_sanitized
        and not is_tl_unbounded
    ):
        # Soft TLE.
        result.no_tle_outcome = result.outcome
        result.outcome = Outcome.TIME_LIMIT_EXCEEDED
    return result


def _is_checker_exitcode(exitcode: int) -> bool:
    return exitcode in [0, 1, 2, 3]


def process_checker_run_log(
    checker_run_log: Optional[RunLog], message: str
) -> CheckerResult:
    if (
        checker_run_log is not None
        and checker_run_log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR
    ):
        # When the sandbox fails, it means the checker failed to run.
        # We don't know what happened.
        return CheckerResult(
            outcome=Outcome.INTERNAL_ERROR,
            message='sandbox failed to run checker',
        )

    if checker_run_log is None:
        return CheckerResult(outcome=Outcome.INTERNAL_ERROR)
    if not _is_checker_exitcode(checker_run_log.exitcode):
        return CheckerResult(
            outcome=Outcome.JUDGE_FAILED,
            message=f'checker failed with unknown exit code {checker_run_log.exitcode}: {message}',
        )

    result = CheckerResult(outcome=Outcome.ACCEPTED, message=message)

    if checker_run_log.exitcode in [1, 2]:
        result = CheckerResult(outcome=Outcome.WRONG_ANSWER, message=message)
    if checker_run_log.exitcode == 3:
        result = CheckerResult(outcome=Outcome.JUDGE_FAILED, message=message)
    return result


def check_with_no_output(run_log: Optional[RunLog]) -> CheckerResult:
    result = _check_pre_output(run_log)
    return _convert_tle(result, run_log)


async def _check(
    checker_digest: str,
    run_log: Optional[RunLog],
    testcase: Testcase,
    program_output: pathlib.Path,
    skip_run_log: bool = False,
) -> CheckerResult:
    if not skip_run_log:
        result = _check_pre_output(run_log)
        if result.outcome != Outcome.ACCEPTED:
            return _convert_tle(result, run_log)

    pkg = package.find_problem_package_or_die()
    output_size = program_output.stat().st_size
    if output_size > pkg.outputLimit * 1024:
        return CheckerResult(
            outcome=Outcome.OUTPUT_LIMIT_EXCEEDED,
            message=f'Output size {pkg.outputLimit}kb, limit is {output_size // 1024}kb.',
        )

    error = DigestHolder()
    inputs = [
        GradingFileInput(
            src=testcase.inputPath,
            dest=pathlib.PosixPath('input.txt'),
        ),
        GradingFileInput(
            src=testcase.outputPath or package.get_empty_sentinel_path(),
            dest=pathlib.PosixPath('expected.txt'),
        ),
        GradingFileInput(
            src=program_output,
            dest=pathlib.PosixPath('output.txt'),
        ),
    ]
    checker_run_log = await run_item(
        package.get_checker(),
        DigestOrSource.create(checker_digest),
        stderr=DigestOrDest.create(error),
        inputs=inputs,
        extra_args='input.txt output.txt expected.txt',
    )
    message = package.get_digest_as_string(error.value or '') or ''

    processed_checker_result = process_checker_run_log(checker_run_log, message)
    if processed_checker_result.outcome == Outcome.INTERNAL_ERROR:
        console.console.print(
            f'[error]Checker [item]{package.get_checker().path}[/item] failed unexpectedly.[/error]'
        )
        if checker_run_log is not None:
            console.console.print(
                f'[error]Summary:[/error] {checker_run_log.get_summary()}'
            )
        console.console.print(
            f'[error]Testcase input:[/error] [item]{testcase.inputPath}[/item]'
        )
        console.console.print(
            f'[error]Testcase output:[/error] [item]{testcase.outputPath}[/item]'
        )
        console.console.print(
            f'[error]Program output:[/error] [item]{program_output}[/item]'
        )
        raise typer.Exit(1)

    result = processed_checker_result

    if skip_run_log:
        return result
    return _convert_tle(result, run_log)


def _check_sanitizer_warnings(run_log: Optional[RunLog]) -> bool:
    if run_log is None:
        return False
    return run_log.warnings


def _is_testlib_eof(stderr: str) -> bool:
    return 'wrong output format Unexpected end of file' in stderr


async def check(
    checker_digest: str,
    run_log: Optional[RunLog],
    testcase: Testcase,
    program_output: pathlib.Path,
    skip_run_log: bool = False,
) -> CheckerResult:
    result = await _check(
        checker_digest, run_log, testcase, program_output, skip_run_log
    )
    result.sanitizer_warnings = _check_sanitizer_warnings(run_log)
    return result


async def check_communication(
    checker_digest: Optional[str],
    run_log: Optional[RunLog],
    interactor_run_log: Optional[RunLog],
    interactor_stderr: pathlib.Path,
    testcase: Testcase,
    program_output: pathlib.Path,
    skip_run_log: bool = False,
) -> CheckerResult:
    def _extra_check_and_sanitize(result: CheckerResult) -> CheckerResult:
        result.sanitizer_warnings = _check_sanitizer_warnings(run_log)
        return result

    def _check_interactor(reinterpret_rte: bool = True) -> Optional[CheckerResult]:
        result = process_checker_run_log(
            interactor_run_log, interactor_stderr.read_text()
        )
        if result.outcome in [Outcome.JUDGE_FAILED, Outcome.WRONG_ANSWER]:
            # Only return testlib errors (exit code 2 and 3), skip other types of RTEs and verdicts.
            if (
                interactor_run_log is not None
                and _is_checker_exitcode(interactor_run_log.exitcode)
                and interactor_run_log.exitstatus == SandboxBase.EXIT_NONZERO_RETURN
            ):
                return _extra_check_and_sanitize(result)
            else:
                # Check for other verdicts, but potentially reinterpret RTEs as JUDGE_FAILED.
                result = check_with_no_output(interactor_run_log)
                if result.outcome == Outcome.RUNTIME_ERROR and reinterpret_rte:
                    result.outcome = Outcome.JUDGE_FAILED
                if result.outcome != Outcome.ACCEPTED:
                    return _extra_check_and_sanitize(result)
        else:
            # Return any other checker/interactor errors, such as INTERNAL_ERRORs.
            return _extra_check_and_sanitize(result)

        # No relevant error was found.
        return None

    # 0. If any of the sandboxes failed, we should return an error.
    if _any_failed([run_log, interactor_run_log]):
        return CheckerResult(outcome=Outcome.INTERNAL_ERROR)

    # 1. If the solution received SIGPIPE or was terminated, it means the
    # interactor exited before it. Thus, check the interactor, as it might have
    # returned a checker verdict.
    #
    # Also, treat the case where the solution has a non-zero exit code similarly.
    # This is aligned with what Polygon/Codeforces does: for some languages, we don't
    # get a SIGPIPE. Instead, we get a non-zero exit code which we can't distinguish
    # from a normal RTE. Thus, we decide that we should prioritize the interactor verdict
    # over the solution's exit code in these cases.
    if (
        interactor_run_log is not None
        and run_log is not None
        and (
            run_log.exitcode == -signal.SIGPIPE
            or run_log.exitstatus == SandboxBase.EXIT_TERMINATED
            or (
                run_log.exitstatus == SandboxBase.EXIT_NONZERO_RETURN
                and not _is_testlib_eof(interactor_stderr.read_text())
            )
        )
    ):
        result = _check_interactor()
        if result is not None and result.outcome != Outcome.ACCEPTED:
            return _extra_check_and_sanitize(result)

    # 2. Check if the solution failed without looking at its output (TLE, MLE, RTE, etc).
    result = check_with_no_output(run_log)
    if result.outcome != Outcome.ACCEPTED:
        return _extra_check_and_sanitize(result)

    # 3. Now check interactor return code regardless of what happened to the
    # solution.
    result = _check_interactor()
    if result is not None and result.outcome != Outcome.ACCEPTED:
        return _extra_check_and_sanitize(result)

    # Just a defensive pattern to ensure result is not None, should never happen.
    result = check_with_no_output(interactor_run_log)
    if result.outcome != Outcome.ACCEPTED:
        if result.outcome == Outcome.RUNTIME_ERROR:
            result.outcome = Outcome.JUDGE_FAILED
        return _extra_check_and_sanitize(result)

    # 4. Now actually check the output with a checker.
    if checker_digest is not None:
        result = await check(
            checker_digest, run_log, testcase, program_output, skip_run_log
        )

    return _extra_check_and_sanitize(result)
