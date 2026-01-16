import pathlib
from typing import List, Optional

from rich.panel import Panel
from rich.table import Table

from rbx import console
from rbx.box import cd, testcase_extractors
from rbx.box.contest.schema import Contest
from rbx.box.formatting import get_formatted_memory, get_formatted_time
from rbx.box.schema import ExpectedOutcome, Package, Solution, TaskType


async def _count_testcases_details(package: Package) -> tuple[int, int]:
    try:
        entries = await testcase_extractors.extract_generation_testcases_from_groups()
    except Exception:
        # Fallback or strict error?
        # If extraction fails (e.g. generator script error), we might want to return 0/0 or raise.
        # Given this is a summary, maybe returning 0 with a warning log is better,
        # but let's assume it works or propagation of error is acceptable.
        raise

    samples = 0
    hidden = 0
    for entry in entries:
        if entry.group_entry.group == 'samples':
            samples += 1
        else:
            hidden += 1
    return samples, hidden


async def _count_testcases_str(package: Package) -> str:
    samples, hidden = await _count_testcases_details(package)
    return f'{samples} samples, {hidden} hidden tests'


def _get_outcome_bucket(outcome: ExpectedOutcome) -> ExpectedOutcome:
    if outcome in (ExpectedOutcome.ACCEPTED, ExpectedOutcome.ACCEPTED_OR_TLE):
        return ExpectedOutcome.ACCEPTED
    if outcome in (ExpectedOutcome.WRONG_ANSWER, ExpectedOutcome.INCORRECT):
        return ExpectedOutcome.WRONG_ANSWER
    if outcome in (ExpectedOutcome.TIME_LIMIT_EXCEEDED, ExpectedOutcome.TLE_OR_RTE):
        return ExpectedOutcome.TIME_LIMIT_EXCEEDED
    if outcome in (
        ExpectedOutcome.RUNTIME_ERROR,
        ExpectedOutcome.MEMORY_LIMIT_EXCEEDED,
        ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED,
        ExpectedOutcome.JUDGE_FAILED,
        ExpectedOutcome.COMPILATION_ERROR,
    ):
        return ExpectedOutcome.RUNTIME_ERROR
    return ExpectedOutcome.WRONG_ANSWER  # Default fallback (e.g. ANY)


def _get_solution_counts(
    solutions: List[Solution], bucketize: bool = False
) -> dict[ExpectedOutcome, int]:
    if bucketize:
        counts = {
            ExpectedOutcome.ACCEPTED: 0,
            ExpectedOutcome.WRONG_ANSWER: 0,
            ExpectedOutcome.TIME_LIMIT_EXCEEDED: 0,
            ExpectedOutcome.RUNTIME_ERROR: 0,
        }
    else:
        counts = {outcome: 0 for outcome in ExpectedOutcome}

    for sol in solutions:
        if bucketize:
            bucket = _get_outcome_bucket(sol.outcome)
            counts[bucket] += 1
        elif sol.outcome in counts:
            counts[sol.outcome] += 1
    return counts


def _get_flags(package: Package) -> List[str]:
    flags = []
    if package.type == TaskType.COMMUNICATION:
        flags.append('[bold magenta]Interactive[/bold magenta]')
    if package.validator:
        flags.append('[green]Validator[/green]')
    if package.checker:
        flags.append('[blue]Custom Checker[/blue]')
    return flags


def _get_flags_short(package: Package) -> str:
    parts = []
    if package.type == TaskType.COMMUNICATION:
        parts.append('[bold magenta]I[/bold magenta]')
    else:
        parts.append('[dim]I[/dim]')

    if package.validator:
        parts.append('[green]V[/green]')
    else:
        parts.append('[dim]V[/dim]')

    if package.checker:
        parts.append('[blue]C[/blue]')
    else:
        parts.append('[dim]C[/dim]')

    return ' '.join(parts)


async def print_problem_summary(package: Package, short_name: Optional[str] = None):
    title = f'[bold]{package.name}[/bold]'
    if short_name:
        title = f'[bold]{short_name}. {package.name}[/bold]'

    # General Info Table
    info_table = Table(show_header=False, box=None, padding=(0, 1))
    info_table.add_column('Property', style='cyan')
    info_table.add_column('Value')

    info_table.add_row('Time Limit', get_formatted_time(package.timeLimit))
    info_table.add_row(
        'Memory Limit', get_formatted_memory(package.memoryLimit * 1024 * 1024)
    )
    info_table.add_row('Output Limit', get_formatted_memory(package.outputLimit * 1024))

    # Combined details
    samples, hidden = await _count_testcases_details(package)
    info_table.add_row('Tests', f'{samples} samples')
    info_table.add_row('', f'{hidden} hidden tests')

    flags = _get_flags(package)
    if flags:
        info_table.add_row('Flags', ', '.join(flags))

    # Solutions Stats
    sol_counts = _get_solution_counts(package.solutions)
    sol_table = Table(title='Solutions', box=None, show_header=True, padding=(0, 1))
    sol_table.add_column('Outcome', style='bold')
    sol_table.add_column('Count', justify='right')

    has_solutions = False
    for outcome, count in sol_counts.items():
        if count > 0:
            sol_table.add_row(outcome.full_markup(), str(count))
            has_solutions = True

    if not has_solutions:
        sol_table.add_row('[dim]No solutions[/dim]', '')

    # Combine into a grid or just print
    grid = Table.grid(expand=True)
    grid.add_column()
    grid.add_column()
    grid.add_row(info_table, sol_table)

    console.console.print(Panel(grid, title=title, expand=False))


async def print_contest_summary(contest: Contest, problems: List[Package]):
    table = Table(title=f'Contest: {contest.name}')
    table.add_column('#', justify='center', style='bold cyan')
    table.add_column('Problem', style='bold')
    table.add_column('TL', justify='right')
    table.add_column('ML', justify='right')
    table.add_column('Tests', justify='right')
    table.add_column('Flags', justify='center')

    # Fixed Buckets
    buckets = [
        ExpectedOutcome.ACCEPTED,
        ExpectedOutcome.WRONG_ANSWER,
        ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        ExpectedOutcome.RUNTIME_ERROR,
    ]

    for outcome in buckets:
        table.add_column(outcome.icon(), justify='center')

    table.add_column('Total', justify='right')

    for i, problem in enumerate(problems):
        row_data = []
        short_name = contest.problems[i].short_name

        # Determine problem root path (relative to CWD, which is contest root)
        # Handle optional path (though likely present if package loaded)
        raw_path = contest.problems[i].path
        problem_path = pathlib.Path(raw_path) if raw_path else pathlib.Path('.')

        row_data.append(short_name)
        row_data.append(problem.name)
        row_data.append(get_formatted_time(problem.timeLimit))
        row_data.append(get_formatted_memory(problem.memoryLimit * 1024 * 1024))

        with cd.new_package_cd(problem_path):
            row_data.append(await _count_testcases_str(problem))

        row_data.append(_get_flags_short(problem))

        counts = _get_solution_counts(problem.solutions, bucketize=True)
        for outcome in buckets:
            c = counts.get(outcome, 0)
            style = outcome.style() if c > 0 else 'dim'
            row_data.append(f'[{style}]{c}[/{style}]')

        total_sols = len(problem.solutions)
        row_data.append(str(total_sols))

        table.add_row(*row_data)

    console.console.print(table)
