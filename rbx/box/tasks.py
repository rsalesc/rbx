import pathlib
from typing import Optional

from rbx.box import checkers, package, state
from rbx.box.code import CommunicationItem, run_communication, run_item
from rbx.box.environment import EnvironmentSandbox, ExecutionConfig, VerificationLevel
from rbx.box.retries import Retrier
from rbx.box.schema import Limits, Solution, Testcase
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.steps import (
    DigestOrDest,
    DigestOrSource,
    Evaluation,
    GradingFileInput,
    GradingFileOutput,
    TestcaseIO,
    TestcaseLog,
)
from rbx.utils import model_to_yaml


def get_limits_for_language(
    lang: Optional[str],
    verification: VerificationLevel,
    timelimit_override: Optional[int],
    use_timelimit: bool = True,
) -> Limits:
    pkg = package.find_problem_package_or_die()
    time = timelimit_override or pkg.timelimit_for_language(lang)
    isDoubleTL = verification.value >= VerificationLevel.FULL.value
    memory = pkg.memorylimit_for_language(lang)
    return Limits(
        time=time if use_timelimit else None,
        memory=memory,
        output=pkg.outputLimit,
        isDoubleTL=isDoubleTL,
    )


async def run_solution_on_testcase(
    solution: Solution,
    compiled_digest: str,
    checker_digest: Optional[str],
    testcase: Testcase,
    output_dir: Optional[pathlib.Path] = None,
    interactor_digest: Optional[str] = None,
    testcase_index: int = 0,
    verification: VerificationLevel = VerificationLevel.NONE,
    timelimit_override: Optional[int] = None,
    use_retries: bool = True,
    use_timelimit: bool = True,
    capture_pipes: bool = False,
) -> Evaluation:
    if interactor_digest is not None:
        return await _run_communication_solution_on_testcase(
            solution,
            compiled_digest,
            interactor_digest,
            checker_digest,
            testcase,
            output_dir,
            testcase_index=testcase_index,
            verification=verification,
            timelimit_override=timelimit_override,
            use_retries=use_retries,
            use_timelimit=use_timelimit,
            capture_pipes=capture_pipes,
        )

    async def run_fn(retry_index: int) -> Evaluation:
        actual_sandbox = package.get_singleton_sandbox()

        limits = get_limits_for_language(
            solution.language,
            verification,
            timelimit_override,
            use_timelimit=use_timelimit,
        )
        extra_config = _get_execution_config(limits, actual_sandbox)

        if output_dir is None:
            assert testcase.outputPath is not None
            output_path = testcase.outputPath
        else:
            output_path = output_dir / testcase.inputPath.with_suffix('.out').name
        error_path = output_path.with_suffix('.err')
        log_path = output_path.with_suffix('.log')
        output_path.parent.mkdir(parents=True, exist_ok=True)

        run_log = await run_item(
            solution,
            DigestOrSource.create(compiled_digest),
            stdin=DigestOrSource.create(testcase.inputPath),
            stdout=DigestOrDest.create(output_path),
            stderr=DigestOrDest.create(error_path),
            extra_config=extra_config,
            retry_index=retry_index,
        )

        if checker_digest is not None:
            checker_result = await checkers.check(
                checker_digest,
                run_log,
                testcase,
                program_output=output_path,
            )
        else:
            checker_result = checkers.check_with_no_output(run_log)

        eval = Evaluation(
            result=checker_result,
            testcase=TestcaseIO(
                index=testcase_index,
                input=testcase.inputPath,
                output=testcase.outputPath,
            ),
            log=TestcaseLog(
                **(run_log.model_dump() if run_log is not None else {}),
                stdout_absolute_path=output_path.absolute(),
                stderr_absolute_path=error_path.absolute(),
                log_absolute_path=log_path.absolute(),
            ),
        )

        log_path.write_text(model_to_yaml(eval))
        return eval

    if not use_retries:
        return await run_fn(0)

    retrier = Retrier()
    return await retrier.repeat(run_fn)


def _get_execution_config(
    limits: Limits,
    actual_sandbox: SandboxBase,
) -> ExecutionConfig:
    sandbox = EnvironmentSandbox()
    sandbox.timeLimit = limits.time
    if limits.isDoubleTL and sandbox.timeLimit is not None:
        # Double TL.
        sandbox.timeLimit = sandbox.timeLimit * 2
    sandbox.wallTimeLimit = sandbox.timeLimit
    if sandbox.timeLimit is not None and actual_sandbox.use_soft_timeout():
        sandbox.wallTimeLimit = sandbox.timeLimit * 2
    sandbox.memoryLimit = limits.memory
    sandbox.fileSizeLimit = limits.output
    return ExecutionConfig(sandbox=sandbox)


async def _run_communication_solution_on_testcase(
    solution: Solution,
    compiled_digest: str,
    interactor_digest: str,
    checker_digest: Optional[str],
    testcase: Testcase,
    output_dir: Optional[pathlib.Path] = None,
    testcase_index: int = 0,
    verification: VerificationLevel = VerificationLevel.NONE,
    timelimit_override: Optional[int] = None,
    use_retries: bool = True,
    use_timelimit: bool = True,
    capture_pipes: bool = False,
) -> Evaluation:
    capture_pipes = capture_pipes or state.STATE.debug_logs

    async def run_fn(retry_index: int) -> Evaluation:
        actual_sandbox = package.get_singleton_sandbox()
        interactor_sandbox = package.get_singleton_interactor_sandbox()

        limits = get_limits_for_language(
            solution.language,
            verification,
            timelimit_override,
            use_timelimit=use_timelimit,
        )

        extra_config = _get_execution_config(limits, actual_sandbox)
        interactor_extra_config = _get_execution_config(limits, interactor_sandbox)
        if (
            interactor_extra_config.sandbox is not None
            and interactor_extra_config.sandbox.wallTimeLimit is not None
            and extra_config.sandbox is not None
            and extra_config.sandbox.wallTimeLimit is not None
        ):
            interactor_extra_config.sandbox.wallTimeLimit += (
                extra_config.sandbox.wallTimeLimit
            )
        # TODO: maybe combine wall time limits?

        if output_dir is None:
            assert testcase.outputPath is not None
            output_path = testcase.outputPath
        else:
            output_path = output_dir / testcase.inputPath.with_suffix('.out').name
        solution_error_path = output_path.with_suffix('.sol.err')
        interactor_error_path = output_path.with_suffix('.int.err')
        log_path = output_path.with_suffix('.log')
        output_path.parent.mkdir(parents=True, exist_ok=True)

        interactor_capture_path = (
            output_path.with_suffix('.pin') if capture_pipes else None
        )
        interactor_item = CommunicationItem(
            code=package.get_interactor(),
            executable=DigestOrSource.create(interactor_digest),
            stderr=DigestOrDest.create(interactor_error_path),
            extra_config=interactor_extra_config,
            extra_args='interactor.in interactor.out',
            inputs=[
                GradingFileInput(
                    src=testcase.inputPath,
                    dest=pathlib.PosixPath('interactor.in'),
                )
            ],
            outputs=[
                GradingFileOutput(
                    src=pathlib.PosixPath('interactor.out'),
                    dest=output_path,
                    touch=True,
                )
            ],
            capture=DigestOrDest.create(interactor_capture_path)
            if interactor_capture_path
            else None,
        )
        solution_capture_path = (
            output_path.with_suffix('.pout') if capture_pipes else None
        )
        solution_item = CommunicationItem(
            code=solution,
            executable=DigestOrSource.create(compiled_digest),
            stderr=DigestOrDest.create(solution_error_path),
            extra_config=extra_config,
            capture=DigestOrDest.create(solution_capture_path)
            if solution_capture_path
            else None,
        )

        merged_capture_path = output_path.with_suffix('.pio') if capture_pipes else None
        interactor_run_log, run_log = await run_communication(
            interactor=interactor_item,
            solution=solution_item,
            retry_index=retry_index,
            merged_capture=merged_capture_path,
        )

        checker_result = await checkers.check_communication(
            checker_digest,
            run_log,
            interactor_run_log,
            interactor_error_path,
            testcase,
            output_path,
        )

        eval = Evaluation(
            result=checker_result,
            testcase=TestcaseIO(
                index=testcase_index,
                input=testcase.inputPath,
                output=testcase.outputPath,
            ),
            log=TestcaseLog(
                **(run_log.model_dump() if run_log is not None else {}),
                stdout_absolute_path=output_path.absolute(),
                stderr_absolute_path=solution_error_path.absolute(),
                log_absolute_path=log_path.absolute(),
            ),
        )

        log_path.write_text(model_to_yaml(eval))

        interactor_log_path = output_path.with_suffix('.int.log')
        interactor_log_path.unlink(missing_ok=True)
        if interactor_run_log is not None:
            interactor_log_path.write_text(model_to_yaml(interactor_run_log))
        solution_log_path = output_path.with_suffix('.sol.log')
        solution_log_path.unlink(missing_ok=True)
        if run_log is not None:
            solution_log_path.write_text(model_to_yaml(run_log))
        return eval

    if not use_retries:
        return await run_fn(0)

    retrier = Retrier()
    return await retrier.repeat(run_fn)
