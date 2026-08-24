from typing import List, Optional, Set

from rbx import console, utils
from rbx.box import environment, package
from rbx.box.environment import VerificationLevel
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.solutions import (
    is_fast,
    print_run_report,
    run_solutions,
)
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.box.testset_manifest import write_manifest_or_warn
from rbx.box.validators import (
    TestcaseValidationInfo,
    check_output_from_entries,
    has_validation_errors,
    print_validation_report,
    validate_outputs_from_entries,
    validate_testcases,
)
from rbx.box.visualizers import run_visualizers_for_entries


async def build(
    verification: environment.VerificationParam,
    groups: Optional[Set[str]] = None,
    output: Optional[bool] = True,
    validate: bool = True,
    visualize: bool = False,
    is_run: bool = False,
    is_statement: bool = False,
) -> bool:
    no_main_solution_report = False
    # None, not [], when the build did not validate: the manifest omits its
    # `validation` key entirely rather than publishing an empty coverage table
    # that would read as "nothing is covered".
    input_validation_infos: Optional[List[TestcaseValidationInfo]] = None
    if output is None:
        output = package.get_main_solution() is not None
        no_main_solution_report = not output

    with utils.StatusProgress(
        'Building testcases...',
        'Built [item]{processed}[/item] testcases...',
        keep=True,
    ) as s:
        await generate_testcases(
            s, groups=groups, verification=VerificationLevel(verification)
        )

    if verification > 0 and validate:
        with utils.StatusProgress(
            'Validating testcases...',
            'Validated [item]{processed}[/item] testcases...',
            keep=True,
        ) as s:
            infos = await validate_testcases(
                s,
                groups=groups,
            )
            input_validation_infos = infos
            print_validation_report(infos)

        if has_validation_errors(infos):
            console.console.print(
                '[error]Validation failed, check the report above.[/error]'
            )
            if is_run:
                console.console.print(
                    '[error]You can use the [item]--no-validate[/item] flag to skip validation.[/error]'
                )
            else:
                console.console.print(
                    '[error]You can use the [item]-v0[/item] flag to skip validation.[/error]'
                )
            return False

    entries = await extract_generation_testcases_from_groups(groups)
    with utils.StatusProgress(
        'Building outputs for testcases...',
        'Built [item]{processed}[/item] outputs...',
        keep=True,
    ) as s:
        if output:
            await generate_outputs_for_testcases(
                [entry.group_entry for entry in entries], s
            )

    if verification > 0 and validate:
        with utils.StatusProgress(
            'Validating outputs for testcases...',
            'Validated [item]{processed}[/item] outputs...',
            keep=True,
        ) as s:
            if output:
                validation_info = await validate_outputs_from_entries(entries, s)
                print_validation_report(validation_info, output_validation=True)

    if verification > 0 and validate:
        with utils.StatusProgress(
            'Checking manual answers for testcases...',
            'Checked [item]{processed}[/item] manual answers...',
            keep=True,
        ) as s:
            if output:
                validation_info = await check_output_from_entries(entries, s)
                print_validation_report(validation_info, output_validation=True)

    if visualize:
        with utils.StatusProgress(
            'Building visualizations for testcases...',
            'Built [item]{processed}[/item] visualizations...',
            keep=True,
        ) as s:
            await run_visualizers_for_entries(entries, s)

    console.console.print(
        '[success]Problem built.[/success] '
        '[warning]Check the output for verification errors![/warning]'
    )

    if no_main_solution_report:
        console.console.print(
            '[warning]No main solution found, skipping generating samples for the statement.[/warning]'
        )

    # Last, on purpose: a reader that sees the manifest may assume everything it
    # names -- inputs, outputs, visualizations -- has already landed, which is
    # what lets its watcher be a single glob instead of a settling heuristic.
    write_manifest_or_warn(entries, input_validation_infos)

    return True


async def verify(
    verification: environment.VerificationParam, groups: Optional[Set[str]] = None
) -> bool:
    if not await build(verification=verification, groups=groups):
        return False

    if verification < VerificationLevel.FAST_SOLUTIONS.value:
        return True

    tracked_solutions = None
    if verification < VerificationLevel.ALL_SOLUTIONS.value:
        tracked_solutions = {
            str(solution.path)
            for solution in package.get_solutions()
            if is_fast(solution)
        }

    with utils.StatusProgress('Running solutions...') as s:
        solution_result = await run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            verification=VerificationLevel(verification),
        )

    console.console.print()
    console.console.rule('[status]Run report[/status]', style='status')
    try:
        return await print_run_report(
            solution_result,
            console.console,
            VerificationLevel(verification),
        )
    finally:
        # After the report, because the report is what *consumes* the deferreds:
        # closing before it would tear down work whose results are still about to
        # be read. In the `finally` because the interesting case is the report
        # ending early -- a failure, or Ctrl-C -- which is exactly when a backend
        # that dispatched ahead still has jobs nobody will ever ask about.
        # A no-op on the local sandbox, which is all this call site uses today.
        await solution_result.close()
