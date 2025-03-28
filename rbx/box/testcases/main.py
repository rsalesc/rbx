import pathlib
from typing import Annotated, List, Optional

import typer

from rbx import annotations, config
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


def _generate_input_for_editing(entry: GenerationTestcaseEntry) -> pathlib.Path:
    if _should_generate_output(entry) or entry.metadata.copied_from is None:
        generate_standalone(
            entry.metadata,
            validate=False,
            group_entry=entry.group_entry,
        )
    if entry.metadata.copied_from is not None:
        return entry.metadata.copied_from.inputPath
    return entry.metadata.copied_to.inputPath


def _generate_output_for_editing(
    entry: GenerationTestcaseEntry,
) -> Optional[pathlib.Path]:
    if (
        entry.metadata.copied_from is not None
        and entry.metadata.copied_from.outputPath is not None
    ):
        return entry.metadata.copied_from.outputPath
    if not _should_generate_output(entry):
        return None
    generate_outputs_for_testcases()
    return entry.metadata.copied_to.outputPath


def _generate_for_editing(entry: GenerationTestcaseEntry) -> List[pathlib.Path]:
    res = [_generate_input_for_editing(entry)]
    output = _generate_output_for_editing(entry)
    if output is not None:
        res.append(output)
    return res


@app.command('view, v')
def view(
    tc: Annotated[
        str,
        typer.Argument(help='Testcase to view. Format: [group]/[index].'),
    ],
):
    entry = TestcaseEntry.parse(tc)
    testcase = _find_testcase(entry)

    items = _generate_for_editing(testcase)
    config.edit_multiple(items)
