import pathlib
from typing import Annotated, Dict, List, Optional

import syncer
import typer

from rbx import annotations, config, utils
from rbx.box import package, promotion
from rbx.box.generators import (
    GenerationTestcaseEntry,
    generate_outputs_for_testcases,
    generate_standalone,
)
from rbx.box.schema import TestcaseGroup
from rbx.box.testcase_extractors import (
    extract_generation_testcases,
    extract_generation_testcases_from_groups,
    extract_generation_testcases_from_patterns,
)
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testcase_utils import TestcasePattern
from rbx.console import console

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


async def _find_testcase(entry: TestcaseEntry) -> GenerationTestcaseEntry:
    extracted = await extract_generation_testcases([entry])
    if not extracted:
        console.print(f'[error]Testcase [item]{entry}[/item] not found.[/error]')
        raise typer.Exit(1)
    return extracted[0]


def _should_generate_output(entry: GenerationTestcaseEntry) -> bool:
    return (
        entry.metadata.copied_from is None
        or entry.metadata.copied_from.outputPath is None
    ) and package.get_main_solution() is not None


async def _generate_input_for_editing(
    entry: GenerationTestcaseEntry,
    output: bool = True,
    progress: Optional[utils.StatusProgress] = None,
) -> pathlib.Path:
    if (
        output and _should_generate_output(entry)
    ) or entry.metadata.copied_from is None:
        await generate_standalone(
            entry.metadata,
            validate=False,
            group_entry=entry.group_entry,
            progress=progress,
        )
    if entry.metadata.copied_from is not None:
        return entry.metadata.copied_from.inputPath
    return entry.metadata.copied_to.inputPath


async def _generate_output_for_editing(
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
    await generate_outputs_for_testcases([entry.group_entry], progress=progress)
    return entry.metadata.copied_to.outputPath


async def _generate_for_editing(
    entry: GenerationTestcaseEntry,
    input: bool,
    output: bool,
    progress: Optional[utils.StatusProgress] = None,
) -> List[pathlib.Path]:
    res = []
    input_path = await _generate_input_for_editing(
        entry, output=output, progress=progress
    )
    if input:
        res.append(input_path)
    if output:
        output_path = await _generate_output_for_editing(entry, progress=progress)
        if output_path is not None:
            res.append(output_path)
    return res


@app.command('view, v', help='View a testcase in your default editor.')
@package.within_problem
@syncer.sync
async def view(
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
    testcase = await _find_testcase(entry)

    with utils.StatusProgress('Preparing testcase...') as s:
        items = await _generate_for_editing(
            testcase, input=not output_only, output=not input_only, progress=s
        )
    config.edit_multiple(items, readonly=True)


@app.command('info, i', help='Show information about testcases.')
@package.within_problem
@syncer.sync
async def info(
    pattern: Annotated[
        Optional[str],
        typer.Argument(
            help='Testcases to detail, as a pattern. Might be a group, or a specific test in the format [group]/[index].'
        ),
    ] = None,
):
    tc_pattern = TestcasePattern.parse(pattern or '*')
    testcases = await extract_generation_testcases_from_patterns([tc_pattern])
    if not testcases:
        console.print(
            f'[error]No testcases found matching pattern [item]{pattern}[/item].[/error]'
        )
        raise typer.Exit(1)

    for testcase in testcases:
        console.print(f'[status]Identifier:[/status] {testcase.group_entry}')
        if testcase.metadata.generator_call is not None:
            console.print(
                f'[status]Generator call:[/status] {testcase.metadata.generator_call}'
            )
        if testcase.metadata.copied_from is not None:
            console.print(
                f'[status]Input file:[/status] {testcase.metadata.copied_from.inputPath}'
            )
            if testcase.metadata.copied_from.outputPath is not None:
                console.print(
                    f'[status]Output file:[/status] {testcase.metadata.copied_from.outputPath}'
                )

        if testcase.metadata.generator_script is not None:
            console.print(
                f'[status]Generator script:[/status] {testcase.metadata.generator_script.path}, line {testcase.metadata.generator_script.line}'
            )
        console.print()


async def _pick_manual_group(
    manual_groups: Dict[str, TestcaseGroup],
) -> Optional[TestcaseGroup]:
    """Interactively pick (or create) a manual group to promote tests into.

    Offers the existing ``manual_groups`` plus a ``(create new manual group)``
    option and a ``(skip)`` option. Returns the chosen ``TestcaseGroup`` object,
    or ``None`` when the user skips/aborts.
    """
    import questionary

    choice = await questionary.select(
        'Choose the manual group to promote into:',
        choices=list(manual_groups) + ['(create new manual group)', '(skip)'],
    ).ask_async()

    if choice is None or choice == '(skip)':
        return None

    if choice == '(create new manual group)':
        new_name = await questionary.text(
            'Enter the name of the new manual group:'
        ).ask_async()
        glob = await questionary.text(
            'Enter the testcase glob for the new group (e.g. tests/manual/corner/*.in):'
        ).ask_async()
        if not new_name or not glob:
            return None
        return promotion.create_manual_group(new_name, glob)

    return manual_groups[choice]


async def _promote_interactive(
    manual_groups: Dict[str, TestcaseGroup],
    group: Optional[str] = None,
    progress: Optional[utils.StatusProgress] = None,
) -> None:
    """Interactively select tests and promote them into a manual group."""
    import questionary

    all_entries = await extract_generation_testcases_from_groups()
    if not all_entries:
        console.print('[error]No tests available to promote.[/error]')
        return

    selected = await questionary.checkbox(
        'Select tests to promote to manual tests:',
        choices=[str(entry.group_entry) for entry in all_entries],
    ).ask_async()
    if not selected:
        return

    selected_set = set(selected)
    chosen_entries = [
        entry for entry in all_entries if str(entry.group_entry) in selected_set
    ]

    if group is not None:
        target = manual_groups[group]
    else:
        target = await _pick_manual_group(manual_groups)
        if target is None:
            return

    with utils.StatusProgress('Promoting tests...') as s:
        for entry in chosen_entries:
            default = promotion.next_testcase_name(promotion.manual_group_dir(target))
            name = await questionary.text(
                f'Filename stem for {entry.group_entry}:',
                default=default,
            ).ask_async()
            input_path = await _generate_input_for_editing(
                entry, output=False, progress=s
            )
            written = promotion.promote_input_to_group(
                input_path, target, name=name or None
            )
            console.print(
                f'[success]Promoted [item]{entry.group_entry}[/item] to '
                f'[item]{written}[/item].[/success]'
            )


@app.command('promote', help='Promote generated tests into a manual test group.')
@package.within_problem
@syncer.sync
async def promote(
    selectors: Annotated[
        Optional[List[str]],
        typer.Argument(
            help='Tests to promote, as [group]/[index] selectors. '
            'If omitted, tests are selected interactively.'
        ),
    ] = None,
    group: Annotated[
        Optional[str],
        typer.Option(
            '--group',
            '-G',
            help='Destination manual test group.',
        ),
    ] = None,
    name: Annotated[
        Optional[str],
        typer.Option(
            '--name',
            '-n',
            help='Filename stem for the promoted test. '
            'Only meaningful when promoting exactly one test.',
        ),
    ] = None,
):
    manual_groups = promotion.get_manual_groups_by_name()

    if not selectors:
        if group is not None and group not in manual_groups:
            console.print(
                f'[error]Manual group [item]{group}[/item] does not exist.[/error]'
            )
            raise typer.Exit(1)
        await _promote_interactive(manual_groups, group=group)
        return

    if group is None:
        target = await _pick_manual_group(manual_groups)
        if target is None:
            return
    else:
        if group not in manual_groups:
            console.print(
                f'[error]Manual group [item]{group}[/item] does not exist.[/error]'
            )
            console.print(
                '[error]Create it first by running [item]rbx testcases promote[/item] '
                'interactively (without a [item]--group[/item]).[/error]'
            )
            raise typer.Exit(1)
        target = manual_groups[group]

    patterns = [TestcasePattern.parse(selector) for selector in selectors]
    with utils.StatusProgress('Promoting tests...') as s:
        entries = await extract_generation_testcases_from_patterns(patterns)
        if not entries:
            console.print('[error]No tests matched the provided selectors.[/error]')
            raise typer.Exit(1)

        single = len(entries) == 1
        for entry in entries:
            input_path = await _generate_input_for_editing(
                entry, output=False, progress=s
            )
            written = promotion.promote_input_to_group(
                input_path,
                target,
                name=name if single else None,
            )
            console.print(
                f'[success]Promoted [item]{entry.group_entry}[/item] to '
                f'[item]{written}[/item].[/success]'
            )
