import pathlib
from typing import Annotated, List, Optional

import typer

from rbx import annotations, config, utils
from rbx.box import package
from rbx.box.generators import (
    GenerationTestcaseEntry,
    extract_generation_testcases,
    generate_outputs_for_testcases,
    generate_standalone,
)
from rbx.box.testcase_utils import TestcaseEntry
from rbx.console import console

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


def _find_testcase(entry: TestcaseEntry) -> GenerationTestcaseEntry:
    extracted = extract_generation_testcases([entry])
    if not extracted:
        console.print(f'[error]Testcase [item]{entry}[/item] not found.[/error]')
        raise typer.Exit(1)
    return extracted[0]


def _should_generate_output(entry: GenerationTestcaseEntry) -> bool:
    return (
        entry.metadata.copied_from is None
        or entry.metadata.copied_from.outputPath is None
    ) and package.get_main_solution() is not None


def _generate_input_for_editing(
    entry: GenerationTestcaseEntry,
    output: bool = True,
    progress: Optional[utils.StatusProgress] = None,
) -> pathlib.Path:
    if (
        output and _should_generate_output(entry)
    ) or entry.metadata.copied_from is None:
        generate_standalone(
            entry.metadata,
            validate=False,
            group_entry=entry.group_entry,
            progress=progress,
        )
    if entry.metadata.copied_from is not None:
        return entry.metadata.copied_from.inputPath
    return entry.metadata.copied_to.inputPath


def _generate_output_for_editing(
    entry: GenerationTestcaseEntry,
    progress: Optional[utils.StatusProgress] = None,
) -> Optional[pathlib.Path]:
    if (
        entry.metadata.copied_from is not None
        and entry.metadata.copied_from.outputPath is not None
    ):
        return entry.metadata.copied_from.outputPath
    if not _should_generate_output(entry):
        return None
    generate_outputs_for_testcases([entry.group_entry], progress=progress)
    return entry.metadata.copied_to.outputPath


def _generate_for_editing(
    entry: GenerationTestcaseEntry,
    input: bool,
    output: bool,
    progress: Optional[utils.StatusProgress] = None,
) -> List[pathlib.Path]:
    res = []
    input_path = _generate_input_for_editing(entry, output=output, progress=progress)
    if input:
        res.append(input_path)
    if output:
        output_path = _generate_output_for_editing(entry, progress=progress)
        if output_path is not None:
            res.append(output_path)
    return res


@app.command('view, v')
def view(
    tc: Annotated[
        str,
        typer.Argument(help='Testcase to view. Format: [group]/[index].'),
    ],
    input_only: bool = typer.Option(
        False,
        '--input',
        '-i',
        help='Whether to open only the input file in the editor.',
    ),
    output_only: bool = typer.Option(
        False,
        '--output',
        '-o',
        help='Whether to open only the output file in the editor.',
    ),
):
    if input_only and output_only:
        console.print(
            '[error]Flags --input and --output cannot be used together.[/error]'
        )
        raise typer.Exit(1)

    entry = TestcaseEntry.parse(tc)
    testcase = _find_testcase(entry)

    with utils.StatusProgress('Preparing testcase...') as s:
        items = _generate_for_editing(
            testcase, input=not output_only, output=not input_only, progress=s
        )
    config.edit_multiple(items)
