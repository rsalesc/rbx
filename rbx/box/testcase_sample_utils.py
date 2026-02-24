import pathlib
from typing import List, Optional

import typer
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import builder, checkers, testcase_extractors, validators
from rbx.box.environment import VerificationLevel, VerificationParam
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.testcase_utils import (
    Testcase,
    TestcaseInteraction,
    TestcaseInteractionParsingError,
    get_best_interaction_file,
    parse_interaction,
)
from rbx.box.validators import (
    TestcaseValidationInfo,
    compile_output_validators_for_entries,
)
from rbx.grading.steps import Outcome


class StatementSample(BaseModel):
    entry: GenerationTestcaseEntry
    inputPath: pathlib.Path
    outputPath: pathlib.Path
    answerPath: Optional[pathlib.Path] = None
    explanationPath: Optional[pathlib.Path] = None
    hasOutput: bool = True
    checkOutput: bool = False
    interaction: Optional[TestcaseInteraction] = None


def _get_statement_sample_from_entry(
    entry: GenerationTestcaseEntry, explanation_suffix: Optional[str] = None
) -> StatementSample:
    input_path: pathlib.Path = utils.get_empty_sentinel_path()
    output_path: pathlib.Path = utils.get_empty_sentinel_path()
    answer_path: Optional[pathlib.Path] = None
    explanation_path: Optional[pathlib.Path] = None
    interaction: Optional[TestcaseInteraction] = None

    # Process manually provided files.
    if entry.metadata.copied_from is not None:
        input_path = entry.metadata.copied_from.inputPath
        if (
            entry.metadata.copied_from.outputPath is not None
            and entry.metadata.copied_from.outputPath.is_file()
        ):
            output_path = entry.metadata.copied_from.outputPath
            answer_path = entry.metadata.copied_from.outputPath

    # Process generated files.
    testcase = entry.metadata.copied_to
    input_path = testcase.inputPath

    if testcase.outputPath is not None and testcase.outputPath.is_file():
        output_path = testcase.outputPath
        answer_path = testcase.outputPath

    def process_additional_files(testcase: Testcase):
        nonlocal input_path, output_path, explanation_path, interaction
        if explanation_suffix is not None:
            explanation_path = testcase.inputPath.with_suffix(explanation_suffix)
            if explanation_path.is_file():
                explanation_path = explanation_path

        pin_path = testcase.inputPath.with_suffix('.pin')
        pout_path = testcase.inputPath.with_suffix('.pout')

        if pin_path.is_file():
            input_path = pin_path
        if pout_path.is_file():
            output_path = pout_path

        interaction_path = get_best_interaction_file(input_path)
        if interaction_path is not None:
            try:
                interaction = parse_interaction(interaction_path)
            except TestcaseInteractionParsingError as e:
                console.console.print(
                    f'Error parsing interactive sample: [error]{e}[/error]'
                )
                raise typer.Exit(1) from e

    process_additional_files(testcase)

    # Process statement-specific manual files
    if entry.metadata.copied_from is not None:
        out_path = entry.metadata.copied_from.inputPath.with_suffix('.out')
        if out_path.is_file():
            output_path = out_path
        out_statement = entry.metadata.copied_from.inputPath.with_suffix(
            '.out.statement'
        )
        if out_statement.is_file():
            output_path = out_statement

        process_additional_files(entry.metadata.copied_from)

    # Make all paths absolute.
    input_path = utils.abspath(input_path)
    output_path = utils.abspath(output_path)
    answer_path = utils.abspath(answer_path) if answer_path is not None else None
    explanation_path = (
        utils.abspath(explanation_path) if explanation_path is not None else None
    )

    # Whether the custom specified output should be checked.
    should_check_output = False
    if (
        answer_path is not None
        and output_path.suffix == '.out'
        and answer_path != output_path
        and output_path.is_file()
    ):
        should_check_output = True

    return StatementSample(
        entry=entry,
        inputPath=input_path,
        outputPath=output_path,
        answerPath=answer_path,
        hasOutput=output_path is not None,
        checkOutput=should_check_output,
        interaction=interaction,
        explanationPath=explanation_path,
    )


async def get_sample_entries() -> List[GenerationTestcaseEntry]:
    return await testcase_extractors.extract_generation_testcases_from_groups(
        set(['samples'])
    )


async def get_statement_samples(
    explanation_suffix: Optional[str] = None,
) -> List[StatementSample]:
    """Get the statement samples from the testcase extractors.

    This function assumes that the samples group is already built."""
    entries = await get_sample_entries()

    return [
        _get_statement_sample_from_entry(entry, explanation_suffix) for entry in entries
    ]


async def _check_sample(checker_digest: str, sample: StatementSample) -> bool:
    answer_path = sample.answerPath or utils.get_empty_sentinel_path()

    result = await checkers.check(
        checker_digest,
        run_log=None,
        testcase=Testcase(
            inputPath=sample.inputPath,
            outputPath=answer_path,
        ),
        program_output=sample.outputPath,
        skip_run_log=True,
    )

    if result.outcome != Outcome.ACCEPTED:
        output_relpath = utils.relcwd(sample.outputPath)
        console.console.print(
            f'[error]Custom output for test [item]{sample.entry}[/item] failed checker.[/error]'
        )
        console.console.print(f'[error]Path: [item]{output_relpath}[/item][/error]')
        console.console.print(f'[error]Message:[/error] {result.message}')
        console.console.print()
        return False

    return True


async def _validate_sample_outputs(
    samples: List[StatementSample],
    progress: Optional[utils.StatusProgress] = None,
) -> bool:
    def step():
        if progress is not None:
            progress.step()

    validator_to_compiled_digest = compile_output_validators_for_entries(
        [sample.entry for sample in samples]
    )

    if not validator_to_compiled_digest:
        if progress is not None:
            progress.omit()
        return True

    validation_info: List[TestcaseValidationInfo] = []

    for sample in samples:
        entry = sample.entry
        for output_validator in entry.output_validators:
            compiled_digest = validator_to_compiled_digest[str(output_validator.path)]
            ok, message, _ = await validators.validate_file(
                sample.outputPath,
                output_validator,
                compiled_digest,
                group=entry.group_entry.group,
            )
            validation_info.append(
                TestcaseValidationInfo(
                    validator=output_validator,
                    testcase=entry.group_entry,
                    generation_metadata=entry.metadata,
                    path=sample.outputPath,
                    ok=ok,
                    hit_bounds={},
                    message=message,
                )
            )
            step()

    validators.print_validation_report(validation_info, output_validation=True)

    return all(info.ok for info in validation_info)


async def build_samples(
    verification: VerificationParam,
    validate: bool,
    check_outputs_only: bool = False,
) -> bool:
    ok = True
    if not check_outputs_only:
        ok = await builder.build(
            verification=verification,
            groups=set(['samples']),
            output=None,
            validate=validate,
        )
    if not ok:
        return False
    if not validate or verification < VerificationLevel.VALIDATE.value:
        return True

    # Validate manually specified statement-only outputs.
    samples = await get_statement_samples()
    samples_to_check = [sample for sample in samples if sample.checkOutput]

    if not samples_to_check:
        return True

    with utils.StatusProgress(
        'Validating manual statement outputs for testcases...',
        'Validated [item]{processed}[/item] manual statement outputs...',
        keep=True,
    ) as s:
        ok = await _validate_sample_outputs(samples_to_check, s)

    if ok:
        with utils.StatusProgress(
            'Checking manual statement outputs for testcases...',
            'Checked [item]{processed}[/item] manual statement outputs...',
            keep=True,
        ) as s:
            checker_digest = checkers.compile_checker()
            for sample in samples_to_check:
                if not await _check_sample(checker_digest, sample):
                    ok = False
                s.step()

    if not ok:
        console.console.print(
            '[error]Some manually provided sample outputs are not considered valid answers.[/error]'
        )
        console.console.print(
            '[error]If you think these files should not be checked, use the [item].out.statement[/item] file extension (not recommended).[/error]'
        )
        console.console.print(
            '[error]You can also use either the [item]-v0[/item] or the [item]--no-validate[/item] flag to disable sample validation temporarily.[/error]'
        )
    else:
        console.console.print(
            '[success]All manual statement outputs are considered valid.[/success]'
        )
    return ok
