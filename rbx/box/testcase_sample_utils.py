import pathlib
from typing import List, Optional, Tuple

import typer
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import builder, checkers, package, testcase_extractors, validators
from rbx.box.environment import VerificationLevel, VerificationParam
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.schema import CodeItem
from rbx.box.testcase_utils import (
    Testcase,
    TestcaseInteraction,
    TestcaseInteractionEntry,
    TestcaseInteractionParsingError,
    get_best_interaction_file,
    merge_interaction_entries,
    parse_interaction,
)
from rbx.box.validators import (
    TestcaseValidationInfo,
    compile_output_validators_for_entries,
    compile_validators_for_entries,
)
from rbx.grading.steps import Outcome


class SampleInteractionChunk(TestcaseInteractionEntry):
    path: pathlib.Path


class SampleTestcaseInteraction(BaseModel):
    entries: List[TestcaseInteractionEntry]
    chunks: List[SampleInteractionChunk]


class StatementSample(BaseModel):
    entry: GenerationTestcaseEntry
    inputPath: pathlib.Path
    outputPath: pathlib.Path
    answerPath: Optional[pathlib.Path] = None
    explanationPath: Optional[pathlib.Path] = None
    explanationFromBlocks: bool = False
    hasOutput: bool = True
    checkOutput: bool = False
    validateStatementInput: bool = False
    validateStatementOutput: bool = False
    interaction: Optional[SampleTestcaseInteraction] = None


def _build_sample_interaction(
    entry: GenerationTestcaseEntry,
    interaction: TestcaseInteraction,
) -> SampleTestcaseInteraction:
    chunk_entries = merge_interaction_entries(interaction.entries)
    chunks: List[SampleInteractionChunk] = []
    chunks_folder = package.get_statement_chunks_folder()
    for i, chunk_entry in enumerate(chunk_entries):
        chunk_path = chunks_folder / str(entry.group_entry) / f'{i:03d}.txt'
        chunk_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_path.write_text(chunk_entry.data)
        chunks.append(
            SampleInteractionChunk(
                path=chunk_path.resolve(),
                data=chunk_entry.data,
                pipe=chunk_entry.pipe,
            )
        )
    return SampleTestcaseInteraction(entries=interaction.entries, chunks=chunks)


def _resolve_explanation_path(
    input_path: pathlib.Path, explanation_suffix: Optional[str]
) -> Tuple[Optional[pathlib.Path], bool]:
    """Resolve the explanation file for a sample input.

    Prefers a language-block ``.rbx<suffix>`` file over the plain ``<suffix>``
    file, returning whether the resolved file is a blocks file. Errors if both
    exist for the same sample.
    """
    if explanation_suffix is None:
        return None, False
    plain_path = input_path.with_suffix(explanation_suffix)
    blocks_path = input_path.with_suffix('.rbx' + explanation_suffix)
    plain_exists = plain_path.is_file()
    blocks_exists = blocks_path.is_file()
    if plain_exists and blocks_exists:
        console.console.print(
            f'[error]Both [item]{utils.abspath(blocks_path)}[/item] and '
            f'[item]{utils.abspath(plain_path)}[/item] exist for the same sample.[/error]'
        )
        console.console.print(
            f'[error]Use either the language-specific [item].rbx{explanation_suffix}[/item] '
            f'explanation or the language-agnostic [item]{explanation_suffix}[/item] '
            'explanation, but not both.[/error]'
        )
        raise typer.Exit(1)
    if blocks_exists:
        return blocks_path, True
    if plain_exists:
        return plain_path, False
    return None, False


def _get_statement_sample_from_entry(
    entry: GenerationTestcaseEntry, explanation_suffix: Optional[str] = None
) -> StatementSample:
    input_path: pathlib.Path = utils.get_empty_sentinel_path()
    output_path: pathlib.Path = utils.get_empty_sentinel_path()
    answer_path: Optional[pathlib.Path] = None
    explanation_path: Optional[pathlib.Path] = None
    explanation_from_blocks: bool = False
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
        nonlocal input_path, output_path, explanation_path
        nonlocal explanation_from_blocks, interaction
        explanation_path, explanation_from_blocks = _resolve_explanation_path(
            testcase.inputPath, explanation_suffix
        )

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

        # Applied after `process_additional_files` -- unlike `.out.statement`, which is
        # applied before it. An explicit `.in.statement` is the setter saying what the
        # statement should show, so it outranks a `.pin` captured from an interaction;
        # and resolving it last keeps the interaction lookup anchored to the real input.
        in_statement = entry.metadata.copied_from.inputPath.with_suffix('.in.statement')
        if in_statement.is_file():
            input_path = in_statement

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

    # Statement-only files are never checked, but the group can ask for them to be
    # validated -- see `validateStatementFiles` in the schema.
    validate_statement_input = (
        entry.validate_statement_files and input_path.name.endswith('.in.statement')
    )
    validate_statement_output = (
        entry.validate_statement_files and output_path.name.endswith('.out.statement')
    )

    return StatementSample(
        entry=entry,
        inputPath=input_path,
        outputPath=output_path,
        answerPath=answer_path,
        hasOutput=output_path is not None,
        checkOutput=should_check_output,
        validateStatementInput=validate_statement_input,
        validateStatementOutput=validate_statement_output,
        interaction=_build_sample_interaction(entry, interaction)
        if interaction is not None
        else None,
        explanationPath=explanation_path,
        explanationFromBlocks=explanation_from_blocks,
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


def _input_validators_for(entry: GenerationTestcaseEntry) -> List[CodeItem]:
    validators_for_entry: List[CodeItem] = []
    if entry.validator is not None:
        validators_for_entry.append(entry.validator)
    validators_for_entry.extend(entry.extra_validators)
    return validators_for_entry


async def _validate_samples(
    samples: List[StatementSample],
    output: bool,
    progress: Optional[utils.StatusProgress] = None,
) -> bool:
    """Run the samples' validators over their input or output files.

    With ``output=True`` this runs the entries' output validators over
    ``outputPath``; otherwise it runs the entries' validator and extra validators
    over ``inputPath``.
    """

    def step():
        if progress is not None:
            progress.step()

    entries = [sample.entry for sample in samples]
    if output:
        validator_to_compiled_digest = await compile_output_validators_for_entries(
            entries
        )
    else:
        validator_to_compiled_digest = await compile_validators_for_entries(entries)

    if not validator_to_compiled_digest:
        if progress is not None:
            progress.omit()
        return True

    validation_info: List[TestcaseValidationInfo] = []

    for sample in samples:
        entry = sample.entry
        path = sample.outputPath if output else sample.inputPath
        validators_for_entry = (
            entry.output_validators if output else _input_validators_for(entry)
        )
        for validator in validators_for_entry:
            compiled_digest = validator_to_compiled_digest[str(validator.path)]
            ok, message, _ = await validators.validate_file(
                path,
                validator,
                compiled_digest,
                group=entry.group_entry.group,
            )
            validation_info.append(
                TestcaseValidationInfo(
                    validator=validator,
                    testcase=entry.group_entry,
                    generation_metadata=entry.metadata,
                    path=path,
                    ok=ok,
                    hit_bounds={},
                    message=message,
                )
            )
            step()

    validators.print_validation_report(validation_info, output_validation=output)

    return all(info.ok for info in validation_info)


async def _validate_sample_outputs(
    samples: List[StatementSample],
    progress: Optional[utils.StatusProgress] = None,
) -> bool:
    return await _validate_samples(samples, output=True, progress=progress)


async def _validate_sample_inputs(
    samples: List[StatementSample],
    progress: Optional[utils.StatusProgress] = None,
) -> bool:
    return await _validate_samples(samples, output=False, progress=progress)


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

    # Validate manually specified statement-only inputs and outputs.
    samples = await get_statement_samples()
    # `.out` outputs are both validated and checked; `.out.statement` outputs are only
    # validated, and only when the group opts in through `validateStatementFiles`.
    samples_to_check = [sample for sample in samples if sample.checkOutput]
    inputs_to_validate = [sample for sample in samples if sample.validateStatementInput]
    outputs_to_validate = [
        sample
        for sample in samples
        if sample.checkOutput or sample.validateStatementOutput
    ]

    if not inputs_to_validate and not outputs_to_validate:
        return True

    if inputs_to_validate:
        with utils.StatusProgress(
            'Validating manual statement inputs for testcases...',
            'Validated [item]{processed}[/item] manual statement inputs...',
            keep=True,
        ) as s:
            ok = await _validate_sample_inputs(inputs_to_validate, s)

    if ok and outputs_to_validate:
        with utils.StatusProgress(
            'Validating manual statement outputs for testcases...',
            'Validated [item]{processed}[/item] manual statement outputs...',
            keep=True,
        ) as s:
            ok = await _validate_sample_outputs(outputs_to_validate, s)

    checked = False
    if ok and samples_to_check:
        checked = True
        with utils.StatusProgress(
            'Checking manual statement outputs for testcases...',
            'Checked [item]{processed}[/item] manual statement outputs...',
            keep=True,
        ) as s:
            checker_digest = await checkers.compile_checker()
            for sample in samples_to_check:
                if not await _check_sample(checker_digest, sample):
                    ok = False
                s.step()

    if not ok:
        console.console.print(
            '[error]Some manually provided sample files are not considered valid.[/error]'
        )
        if checked:
            console.console.print(
                '[error]If you think these files should not be checked, use the [item].out.statement[/item] file extension (not recommended).[/error]'
            )
        console.console.print(
            '[error]You can also use either the [item]-v0[/item] or the [item]--no-validate[/item] flag to disable sample validation temporarily.[/error]'
        )
    else:
        console.console.print(
            '[success]All manual statement files are considered valid.[/success]'
        )
    return ok
