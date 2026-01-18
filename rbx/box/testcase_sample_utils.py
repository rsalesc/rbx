import pathlib
from typing import List, Optional

import typer
from pydantic import BaseModel

from rbx import console, utils
from rbx.box import testcase_extractors
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.testcase_utils import (
    Testcase,
    TestcaseInteraction,
    TestcaseInteractionParsingError,
    get_best_interaction_file,
    parse_interaction,
)


class StatementSample(BaseModel):
    inputPath: pathlib.Path
    outputPath: pathlib.Path
    answerPath: Optional[pathlib.Path] = None
    explanationPath: Optional[pathlib.Path] = None
    hasOutput: bool = True
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

    return StatementSample(
        inputPath=input_path,
        outputPath=output_path,
        answerPath=answer_path,
        hasOutput=output_path is not None,
        interaction=interaction,
        explanationPath=explanation_path,
    )


async def get_statement_samples(
    explanation_suffix: Optional[str] = None,
) -> List[StatementSample]:
    """Get the statement samples from the testcase extractors.

    This function assumes that the samples group is already built."""
    entries = await testcase_extractors.extract_generation_testcases_from_groups(
        set(['samples'])
    )

    return [
        _get_statement_sample_from_entry(entry, explanation_suffix) for entry in entries
    ]
