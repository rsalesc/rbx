import pathlib
import tempfile
from typing import List, Optional, Set, Tuple, Union

from pydantic import BaseModel

from rbx import console, utils
from rbx.box import checkers, package, validators
from rbx.box.schema import (
    CheckerTest,
    CodeItem,
    ExpectedOutcome,
    Testcase,
    ValidatorOutcome,
    ValidatorTest,
)
from rbx.box.stressing import unit_parser
from rbx.grading.steps import Outcome
from rbx.utils import StatusProgress


class TestplanReference(BaseModel):
    path: pathlib.Path
    line: int

    def __str__(self) -> str:
        return f'{self.path}:{self.line}'


class UnitTestInput(BaseModel):
    text: Union[str, pathlib.Path]
    ref: Optional[TestplanReference] = None


class ValidatorTestEntry(BaseModel):
    input: UnitTestInput
    outcome: ValidatorOutcome
    basename: str
    validator: Optional[CodeItem]
    ref: Optional[TestplanReference] = None

    def display_string(self) -> str:
        if self.ref is not None and str(self.ref) != self.basename:
            return f'{self.basename} ({self.ref})'
        return self.basename

    def get_sort_key(self) -> Tuple[str, int]:
        return (self.basename, self.ref.line if self.ref is not None else 0)


class CheckerTestEntry(BaseModel):
    input: Optional[UnitTestInput] = None
    output: Optional[UnitTestInput] = None
    answer: Optional[UnitTestInput] = None
    basename: str
    outcome: ExpectedOutcome
    ref: Optional[TestplanReference] = None

    def running_tests_formatted_string(self) -> str:
        res = []
        if self.ref is not None:
            res_str = f'{self.basename}'
            if self.basename != str(self.ref):
                res_str += f' ({self.ref})'
            return res_str
        if self.input:
            res.append(f'{self.input.text}')
        if self.output:
            res.append(f'{self.output.text}')
        if self.answer:
            res.append(f'{self.answer.text}')
        return ', '.join(res)

    def get_sort_key(self) -> Tuple[str, int]:
        return (self.basename, self.ref.line if self.ref is not None else 0)


def _extract_validator_glob_test_entries(
    test: ValidatorTest,
) -> List[ValidatorTestEntry]:
    if test.outcome is None:
        return []
    res: List[ValidatorTestEntry] = []
    for input in sorted(pathlib.Path().glob(str(test.glob))):
        if not input.is_file():
            continue
        res.append(
            ValidatorTestEntry(
                input=UnitTestInput(text=input),
                outcome=test.outcome,
                basename=input.name,
                validator=test.validator,
            )
        )
    return sorted(res, key=lambda x: x.get_sort_key())


def _extract_validator_testplan_test_entries(
    test: ValidatorTest,
) -> List[ValidatorTestEntry]:
    if test.testplan is None:
        return []
    res: List[ValidatorTestEntry] = []
    results = unit_parser.parse_and_transform(
        test.testplan.read_text(),
        pathlib.Path(test.testplan),
        unit_parser.UnitTestMode.VALIDATOR,
    )
    for result in results:
        assert isinstance(result.expectation, ValidatorOutcome)
        ref = TestplanReference(path=test.testplan, line=result.line)
        res.append(
            ValidatorTestEntry(
                input=UnitTestInput(
                    text=result.input,
                    ref=ref,
                ),
                basename=result.name or str(ref),
                outcome=result.expectation,
                validator=test.validator,
                ref=ref,
            )
        )
    return res


def extract_validator_test_entries(
    tests: List[ValidatorTest],
) -> List[ValidatorTestEntry]:
    res: List[ValidatorTestEntry] = []
    for test in tests:
        if test.glob is not None:
            res.extend(_extract_validator_glob_test_entries(test))
        elif test.testplan is not None:
            res.extend(_extract_validator_testplan_test_entries(test))
        else:
            raise ValueError('No glob or testplan specified for validator test')
    return res


def _extract_checker_glob_test_entries(test: CheckerTest) -> List[CheckerTestEntry]:
    if test.outcome is None:
        return []
    res: List[CheckerTestEntry] = []
    seen: Set[pathlib.Path] = set()
    for file in sorted(pathlib.Path().glob(str(test.glob))):
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
                input=UnitTestInput(text=input) if input.is_file() else None,
                output=UnitTestInput(text=output) if output.is_file() else None,
                answer=UnitTestInput(text=answer) if answer.is_file() else None,
                basename=basefile.name,
                outcome=test.outcome,
            )
        )
    return sorted(res, key=lambda x: x.get_sort_key())


def _extract_checker_testplan_test_entries(test: CheckerTest) -> List[CheckerTestEntry]:
    res: List[CheckerTestEntry] = []
    if test.testplan is None:
        return []
    results = unit_parser.parse_and_transform(
        test.testplan.read_text(),
        pathlib.Path(test.testplan),
        unit_parser.UnitTestMode.CHECKER,
    )
    for result in results:
        assert isinstance(result.expectation, ExpectedOutcome)
        ref = TestplanReference(path=test.testplan, line=result.line)
        res.append(
            CheckerTestEntry(
                input=UnitTestInput(
                    text=result.input,
                    ref=ref,
                ),
                output=UnitTestInput(
                    text=result.output,
                    ref=ref,
                )
                if result.output is not None
                else None,
                answer=UnitTestInput(
                    text=result.answer,
                    ref=ref,
                )
                if result.answer is not None
                else None,
                basename=result.name or str(ref),
                outcome=result.expectation,
                ref=ref,
            )
        )
    return res


def extract_checker_test_entries(tests: List[CheckerTest]) -> List[CheckerTestEntry]:
    res: List[CheckerTestEntry] = []
    for test in tests:
        if test.glob is not None:
            res.extend(_extract_checker_glob_test_entries(test))
        elif test.testplan is not None:
            res.extend(_extract_checker_testplan_test_entries(test))
        else:
            raise ValueError('No glob or testplan specified for checker test')
    return res


def _get_validators_for_test(test: ValidatorTestEntry) -> List[CodeItem]:
    if test.validator is not None:
        return [test.validator]
    return package.get_all_validators()


async def run_validator_unit_tests(progress: StatusProgress, tmpd: pathlib.Path):
    pkg = package.find_problem_package_or_die()

    entries = extract_validator_test_entries(pkg.unitTests.validator)

    vals: List[CodeItem] = []
    for test in entries:
        vals.extend(_get_validators_for_test(test))

    console.console.rule('Validator tests', style='info')
    if not entries:
        console.console.print('No validator unit tests found.')
        return

    compiled_validators = validators.compile_validators(vals, progress=progress)

    if progress:
        progress.update('Running validator unit tests...')

    tmpp = tmpd / 'validator.in'

    for i, test in enumerate(entries):
        vals_for_test = _get_validators_for_test(test)
        if not vals_for_test:
            console.console.print(
                f'[warning]No validators found for test [item]#{i + 1}[/item], skipping.[/warning]'
            )
            console.console.print()
            continue

        if isinstance(test.input.text, str):
            tmpp.write_text(test.input.text)

        infos = await validators.validate_one_off(
            test.input.text if isinstance(test.input.text, pathlib.Path) else tmpp,
            vals_for_test,
            compiled_validators,
        )

        is_valid = test.outcome == ValidatorOutcome.VALID
        markup = (
            '[success]OK[/success]'
            if all(info.ok for info in infos) == is_valid
            else '[error]FAIL[/error]'
        )
        console.console.print(
            f'{markup} Unit test [item]#{i + 1}[/item] for [item]{test.display_string()}[/item]'
        )
        for info in infos:
            if len(infos) > 1:
                console.console.print(
                    f'  [status]Validator[/status] {info.validator.href()}'
                )

            console.console.print(f'  [status]Expected[/status] {test.outcome.value}')
            if info.ok != is_valid:
                if info.ok:
                    console.console.print('  [status]Actual[/status] VALID')
                else:
                    console.console.print('  [status]Actual[/status] INVALID')

            if info.message:
                console.console.print(
                    f'  [status]Message[/status] {utils.escape_markup(info.message.strip())}'
                )
            console.console.print()


async def run_checker_unit_tests(progress: StatusProgress, tmpd: pathlib.Path):
    pkg = package.find_problem_package_or_die()

    if not package.get_checker():
        console.console.print(
            '[warning]No checker found, skipping checker unit tests.[/warning]'
        )
        return

    console.console.rule('Checker tests', style='info')

    entries = extract_checker_test_entries(pkg.unitTests.checker)
    if not entries:
        console.console.print('No checker unit tests found.')
        return

    compiled_digest = checkers.compile_checker(progress=progress)

    if progress:
        progress.update('Running checker unit tests...')

    empty_file = package.get_empty_sentinel_path()
    tmpi = tmpd / 'checker.in'
    tmpo = tmpd / 'checker.out'
    tmpa = tmpd / 'checker.ans'

    for i, test in enumerate(entries):
        if test.input is not None and isinstance(test.input.text, str):
            tmpi.write_text(test.input.text)
        if test.output is not None and isinstance(test.output.text, str):
            tmpo.write_text(test.output.text)
        if test.answer is not None and isinstance(test.answer.text, str):
            tmpa.write_text(test.answer.text)

        def _get_file(
            input: Optional[UnitTestInput], bkp: pathlib.Path
        ) -> pathlib.Path:
            if input is None:
                return empty_file
            if isinstance(input.text, pathlib.Path):
                return input.text
            return bkp

        result = await checkers.check(
            compiled_digest,
            run_log=None,
            testcase=Testcase(
                inputPath=_get_file(test.input, tmpi),
                outputPath=(_get_file(test.answer, tmpa)),
            ),
            program_output=_get_file(test.output, tmpo),
            skip_run_log=True,
        )

        if test.answer is not None:
            ans_result = await checkers.check(
                compiled_digest,
                run_log=None,
                testcase=Testcase(
                    inputPath=_get_file(test.input, tmpi),
                    outputPath=_get_file(test.answer, tmpa),
                ),
                program_output=_get_file(test.answer, tmpa),
                skip_run_log=True,
            )

            if ans_result.outcome != Outcome.ACCEPTED:
                console.console.print(
                    f'[error]FAIL[/error] Unit test [item]#{i + 1}[/item] for [item]{test.running_tests_formatted_string()}[/item]'
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
            f'{markup} Unit test [item]#{i + 1}[/item] for [item]{test.running_tests_formatted_string()}[/item]'
        )
        console.console.print(f'  [status]Expected[/status] {test.outcome.name}')

        if not test.outcome.match(result.outcome):
            console.console.print(f'  [status]Actual[/status] {result.outcome.name}')
        if result.message:
            console.console.print(
                f'  [status]Message[/status] {utils.escape_markup(result.message.strip())}'
            )


async def run_unit_tests(progress: StatusProgress):
    with tempfile.TemporaryDirectory() as tmpd:
        await run_validator_unit_tests(progress, pathlib.Path(tmpd))
        await run_checker_unit_tests(progress, pathlib.Path(tmpd))
