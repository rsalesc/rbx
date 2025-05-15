import pathlib
from typing import List, Optional, Set

import syncer
from pydantic import BaseModel

from rbx import console
from rbx.box import checkers, package, validators
from rbx.box.schema import (
    CheckerTest,
    CodeItem,
    ExpectedOutcome,
    Testcase,
    ValidatorOutcome,
    ValidatorTest,
)
from rbx.grading.steps import Outcome
from rbx.utils import StatusProgress


class ValidatorTestEntry(BaseModel):
    input: pathlib.Path
    outcome: ValidatorOutcome
    validator: Optional[CodeItem]


class CheckerTestEntry(BaseModel):
    input: Optional[pathlib.Path] = None
    output: Optional[pathlib.Path] = None
    answer: Optional[pathlib.Path] = None
    outcome: ExpectedOutcome

    def running_tests_formatted_string(self) -> str:
        res = []
        if self.input:
            res.append(f'[item]{self.input}[/item]')
        if self.output:
            res.append(f'[item]{self.output}[/item]')
        if self.answer:
            res.append(f'[item]{self.answer}[/item]')
        return ', '.join(res)


def _extract_validator_test_entries(
    tests: List[ValidatorTest],
) -> List[ValidatorTestEntry]:
    res: List[ValidatorTestEntry] = []
    for test in tests:
        for input in pathlib.Path().glob(str(test.glob)):
            if not input.is_file():
                continue
            res.append(
                ValidatorTestEntry(
                    input=input, outcome=test.outcome, validator=test.validator
                )
            )
    return sorted(res, key=lambda x: x.input.name)


def _extract_checker_test_entries(tests: List[CheckerTest]) -> List[CheckerTestEntry]:
    res: List[CheckerTestEntry] = []
    seen: Set[pathlib.Path] = set()
    for test in tests:
        for file in pathlib.Path().glob(str(test.glob)):
            if not file.is_file():
                continue
            if file.suffix not in ['.in', '.out', '.ans']:
                continue
            basefile = file.with_suffix('')
            if basefile in seen:
                continue
            seen.add(basefile)
            input = basefile.with_suffix('.in')
            output = basefile.with_suffix('.out')
            answer = basefile.with_suffix('.ans')
            res.append(
                CheckerTestEntry(
                    input=input if input.is_file() else None,
                    output=output if output.is_file() else None,
                    answer=answer if answer.is_file() else None,
                    outcome=test.outcome,
                )
            )
    return res


def _get_validator_for_test(test: ValidatorTestEntry) -> Optional[CodeItem]:
    pkg = package.find_problem_package_or_die()
    if test.validator is not None:
        return test.validator
    return pkg.validator


async def run_validator_unit_tests(progress: StatusProgress):
    pkg = package.find_problem_package_or_die()

    entries = _extract_validator_test_entries(pkg.unitTests.validator)

    vals: List[CodeItem] = []
    for test in entries:
        val = _get_validator_for_test(test)
        if val is not None:
            vals.append(val)

    console.console.rule('Validator tests', style='info')
    if not entries:
        console.console.print('No validator unit tests found.')
        return

    compiled_validators = validators.compile_validators(vals, progress=progress)

    if progress:
        progress.update('Running validator unit tests...')

    for i, test in enumerate(entries):
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
                console.console.print('  [status]Actual[/status] INVALID')

        if info.message:
            console.console.print(f'  [status]Message[/status] {info.message}')


async def run_checker_unit_tests(progress: StatusProgress):
    pkg = package.find_problem_package_or_die()

    if not package.get_checker():
        console.console.print(
            '[warning]No checker found, skipping checker unit tests.[/warning]'
        )
        return

    console.console.rule('Checker tests', style='info')

    entries = _extract_checker_test_entries(pkg.unitTests.checker)
    if not entries:
        console.console.print('No checker unit tests found.')
        return

    compiled_digest = checkers.compile_checker(progress=progress)

    if progress:
        progress.update('Running checker unit tests...')

    empty_file = package.get_empty_sentinel_path()

    for i, test in enumerate(entries):
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

        if test.answer is not None:
            ans_result = await checkers.check(
                compiled_digest,
                run_log=None,
                testcase=Testcase(
                    inputPath=test.input or empty_file,
                    outputPath=test.answer,
                ),
                program_output=test.answer,
                skip_run_log=True,
            )

            if ans_result.outcome != Outcome.ACCEPTED:
                console.console.print(
                    f'[error]FAIL[/error] Unit test [item]#{i + 1}[/item] ({test.running_tests_formatted_string()})'
                )
                console.console.print(
                    '[error]Error validating the [item].ans[/item] file.'
                )
                console.console.print(
                    '[error]While checking your [item].ans[/item] against itself, the checker returned the following error:[/error]'
                )
                console.console.print(
                    f'  [status]Verdict[/status] {ans_result.outcome.name}'
                )
                console.console.print(
                    f'  [status]Message[/status] {ans_result.message}'
                )
                console.console.print(
                    '[error]Please fix your [item].ans[/item] file and try again, or double-check that your checker is correct.[/error]'
                )
                continue

        markup = (
            '[success]OK[/success]'
            if test.outcome.match(result.outcome)
            else '[error]FAIL[/error]'
        )

        console.console.print(
            f'{markup} Unit test [item]#{i + 1}[/item] ({test.running_tests_formatted_string()})'
        )
        console.console.print(f'  [status]Expected[/status] {test.outcome.name}')

        if not test.outcome.match(result.outcome):
            console.console.print(f'  [status]Actual[/status] {result.outcome.name}')
        if result.message:
            console.console.print(f'  [status]Message[/status] {result.message}')


@syncer.sync
async def run_unit_tests(progress: StatusProgress):
    await run_validator_unit_tests(progress)
    await run_checker_unit_tests(progress)
