from typing import List, Optional

import syncer

from rbx import console
from rbx.box import checkers, package, validators
from rbx.box.schema import CodeItem, Testcase, ValidatorOutcome, ValidatorTest
from rbx.utils import StatusProgress


def _get_validator_for_test(test: ValidatorTest) -> Optional[CodeItem]:
    pkg = package.find_problem_package_or_die()
    if test.validator is not None:
        return test.validator
    return pkg.validator


async def run_validator_unit_tests(progress: StatusProgress):
    pkg = package.find_problem_package_or_die()

    vals: List[CodeItem] = []
    for test in pkg.unitTests.validator:
        val = _get_validator_for_test(test)
        if val is not None:
            vals.append(val)

    compiled_validators = validators.compile_validators(vals, progress=progress)

    if progress:
        progress.update('Running validator unit tests...')

    console.console.rule('Validator tests', style='info')

    for i, test in enumerate(pkg.unitTests.validator):
        val = _get_validator_for_test(test)
        if val is None:
            console.console.print(
                f'[warning]No validator found for test [item]#{i + 1}[/item], skipping.[/warning]'
            )
            continue

        compiled_digest = compiled_validators[str(val.path)]
        info = await validators.validate_one_off(
            test.input,
            val,
            compiled_digest,
        )

        is_valid = test.outcome == ValidatorOutcome.VALID

        markup = (
            '[success]OK[/success]' if info.ok == is_valid else '[error]FAIL[/error]'
        )

        console.console.print(
            f'{markup} Unit test [item]#{i + 1}[/item] for [item]{test.input}[/item]'
        )
        console.console.print(f'  [status]Expected[/status] {test.outcome.value}')
        if info.ok != is_valid:
            if info.ok:
                console.console.print('  [status]Actual[/status] VALID')
            else:
                console.console.print(f'  [status]Actual[/status] {info.message}')


async def run_checker_unit_tests(progress: StatusProgress):
    pkg = package.find_problem_package_or_die()
    if not pkg.unitTests.checker:
        return

    if not package.get_checker():
        console.console.print(
            '[warning]No checker found, skipping checker unit tests.[/warning]'
        )
        return

    compiled_digest = checkers.compile_checker(progress=progress)

    if progress:
        progress.update('Running checker unit tests...')

    console.console.rule('Checker tests', style='info')

    empty_file = package.get_empty_sentinel_path()

    for i, test in enumerate(pkg.unitTests.checker):
        result = await checkers.check(
            compiled_digest,
            run_log=None,
            testcase=Testcase(
                inputPath=test.input or empty_file,
                outputPath=test.answer or empty_file,
            ),
            program_output=test.output or empty_file,
            skip_run_log=True,
        )

        markup = (
            '[success]OK[/success]'
            if test.outcome.match(result.outcome)
            else '[error]FAIL[/error]'
        )

        console.console.print(f'{markup} Unit test [item]#{i + 1}[/item]')
        console.console.print(f'  [status]Expected[/status] {test.outcome.name}')

        if not test.outcome.match(result.outcome):
            console.console.print(f'  [status]Actual[/status] {result.outcome.name}')
            if result.message:
                console.console.print(f'  [status]Message[/status] {result.message}')


@syncer.sync
async def run_unit_tests(progress: StatusProgress):
    await run_validator_unit_tests(progress)
    await run_checker_unit_tests(progress)
