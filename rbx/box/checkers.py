import pathlib
from typing import Optional

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


def compile_checker() -> str:
    checker = package.get_checker()

    try:
        digest = compile_item(checker, sanitized=SanitizationLevel.PREFER)
    except Exception as e:
        console.console.print('[error]Failed compiling checker.[/error]')
        raise typer.Exit(1) from e
    return digest


def _check_pre_output(run_log: Optional[RunLog]) -> CheckerResult:
    pkg = package.find_problem_package_or_die()

    is_sanitized = (
        run_log is not None
        and run_log.metadata is not None
        and run_log.metadata.is_sanitized
    )

    if run_log is None:
        return CheckerResult(outcome=Outcome.INTERNAL_ERROR)

    timelimit = pkg.timelimit_for_language(run_log.get_run_language())
    if (
        run_log.time is not None
        and run_log.time * 1000 > timelimit * 2
        and not is_sanitized
    ):
        return CheckerResult(outcome=Outcome.TIME_LIMIT_EXCEEDED)

    if run_log.exitstatus in [SandboxBase.EXIT_SIGNAL, SandboxBase.EXIT_NONZERO_RETURN]:
        return CheckerResult(outcome=Outcome.RUNTIME_ERROR)
    if run_log.exitstatus in [SandboxBase.EXIT_TIMEOUT, SandboxBase.EXIT_TIMEOUT_WALL]:
        return CheckerResult(outcome=Outcome.TIME_LIMIT_EXCEEDED)
    if run_log.exitstatus == SandboxBase.EXIT_MEMORY_LIMIT_EXCEEDED:
        return CheckerResult(outcome=Outcome.MEMORY_LIMIT_EXCEEDED)
    if run_log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR:
        return CheckerResult(outcome=Outcome.INTERNAL_ERROR)
    if run_log.exitstatus == SandboxBase.EXIT_OUTPUT_LIMIT_EXCEEDED:
        return CheckerResult(outcome=Outcome.OUTPUT_LIMIT_EXCEEDED)
    return CheckerResult(outcome=Outcome.ACCEPTED)


def _convert_tle(result: CheckerResult, run_log: Optional[RunLog]) -> CheckerResult:
    if result.outcome == Outcome.TIME_LIMIT_EXCEEDED:
        # This already is a TLE outcome.
        return result
    pkg = package.find_problem_package_or_die()
    is_sanitized = (
        run_log is not None
        and run_log.metadata is not None
        and run_log.metadata.is_sanitized
    )
    if (
        run_log is not None
        and run_log.time is not None
        and run_log.time * 1000
        >= pkg.timelimit_for_language(run_log.get_run_language())
        and not is_sanitized
    ):
        # Soft TLE.
        result.no_tle_outcome = result.outcome
        result.outcome = Outcome.TIME_LIMIT_EXCEEDED
    return result


def check_with_no_output(run_log: Optional[RunLog]) -> CheckerResult:
    result = _check_pre_output(run_log)
    return _convert_tle(result, run_log)


def _check(
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
            src=testcase.outputPath,
            dest=pathlib.PosixPath('expected.txt'),
        ),
        GradingFileInput(
            src=program_output,
            dest=pathlib.PosixPath('output.txt'),
        ),
    ]
    checker_run_log = run_item(
        package.get_checker(),
        DigestOrSource.create(checker_digest),
        stderr=DigestOrDest.create(error),
        inputs=inputs,
        extra_args='input.txt output.txt expected.txt',
    )
    message = package.get_digest_as_string(error.value or '') or ''

    if (
        checker_run_log is not None
        and checker_run_log.exitcode != 0
        and (
            checker_run_log.exitstatus != SandboxBase.EXIT_NONZERO_RETURN
            or checker_run_log.exitcode not in [0, 1, 2, 3]
        )
    ):
        console.console.print(
            f'[error]Checker [item]{package.get_checker().path}[/item] failed unexpectedly.[/error]'
        )
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

    if checker_run_log is None or checker_run_log.exitcode not in [0, 1, 2, 3]:
        return CheckerResult(outcome=Outcome.INTERNAL_ERROR)

    result = CheckerResult(outcome=Outcome.ACCEPTED, message=message)

    if checker_run_log.exitcode in [1, 2]:
        result = CheckerResult(outcome=Outcome.WRONG_ANSWER, message=message)
    if checker_run_log.exitcode == 3:
        result = CheckerResult(outcome=Outcome.JUDGE_FAILED, message=message)

    if skip_run_log:
        return result
    return _convert_tle(result, run_log)


def _check_sanitizer_warnings(run_log: Optional[RunLog]) -> bool:
    if run_log is None:
        return False
    return run_log.warnings


def check(
    checker_digest: str,
    run_log: Optional[RunLog],
    testcase: Testcase,
    program_output: pathlib.Path,
    skip_run_log: bool = False,
) -> CheckerResult:
    result = _check(checker_digest, run_log, testcase, program_output, skip_run_log)
    result.sanitizer_warnings = _check_sanitizer_warnings(run_log)
    return result
