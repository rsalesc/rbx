from typing import Optional, Set

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
from rbx.box.validators import (
    has_validation_errors,
    print_validation_report,
    validate_testcases,
)


async def build(
    verification: environment.VerificationParam,
    groups: Optional[Set[str]] = None,
    output: Optional[bool] = True,
) -> bool:
    no_main_solution_report = False
    if output is None:
        output = package.get_main_solution() is not None
        no_main_solution_report = not output

    with utils.StatusProgress(
        'Building testcases...',
        'Built [item]{processed}[/item] testcases...',
        keep=True,
    ) as s:
        await generate_testcases(s, groups=groups)

    if verification > 0:
        validator = package.get_validator_or_nil()
        if validator is None:
            console.console.print(
                '[warning]No validator found, skipping validation.[/warning]'
            )

        if validator is not None:
            with utils.StatusProgress(
                'Validating testcases...',
                'Validated [item]{processed}[/item] testcases...',
                keep=True,
            ) as s:
                infos = await validate_testcases(
                    s,
                    groups=groups,
                )
                print_validation_report(infos)

            if has_validation_errors(infos):
                console.console.print(
                    '[error]Validation failed, check the report above.[/error]'
                )
                return False

    with utils.StatusProgress(
        'Building outputs for testcases...',
        'Built [item]{processed}[/item] outputs...',
        keep=True,
    ) as s:
        if output:
            entries = [
                entry.group_entry
                for entry in await extract_generation_testcases_from_groups(groups)
            ]
            await generate_outputs_for_testcases(entries, s)

    console.console.print(
        '[success]Problem built.[/success] '
        '[warning]Check the output for verification errors![/warning]'
    )

    if no_main_solution_report:
        console.console.print(
            '[warning]No main solution found, skipping generating samples for the statement.[/warning]'
        )

    return True


async def verify(verification: environment.VerificationParam) -> bool:
    if not await build(verification=verification):
        return False

    if verification < VerificationLevel.FAST_SOLUTIONS.value:
        return True

    tracked_solutions = None
    if verification < VerificationLevel.ALL_SOLUTIONS.value:
        pkg = package.find_problem_package_or_die()

        tracked_solutions = {
            str(solution.path) for solution in pkg.solutions if is_fast(solution)
        }

    with utils.StatusProgress('Running solutions...') as s:
        solution_result = run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            verification=VerificationLevel(verification),
        )

    console.console.print()
    console.console.rule('[status]Run report[/status]', style='status')
    return await print_run_report(
        solution_result,
        console.console,
        VerificationLevel(verification),
    )
