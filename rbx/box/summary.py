import pathlib
from typing import List, Optional

from rich.panel import Panel
from rich.table import Table

from rbx import console
from rbx.box import cd, package, testcase_extractors
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


def _get_flags(pkg: Package) -> List[str]:
    flags = []
    if pkg.type == TaskType.COMMUNICATION:
        flags.append('[bold magenta]Interactive[/bold magenta]')
    if pkg.validator:
        flags.append('[green]Validator[/green]')
    if pkg.checker:
        flags.append('[blue]Custom Checker[/blue]')
    return flags


def _get_flags_short(pkg: Package) -> str:
    parts = []
    if pkg.type == TaskType.COMMUNICATION:
        parts.append('[bold magenta]I[/bold magenta]')
    else:
        parts.append('[dim]I[/dim]')

    if pkg.validator:
        parts.append('[green]V[/green]')
    else:
        parts.append('[dim]V[/dim]')

    if pkg.checker:
        parts.append('[blue]C[/blue]')
    else:
        parts.append('[dim]C[/dim]')

    return ' '.join(parts)


async def print_problem_summary(
    pkg: Package, short_name: Optional[str] = None, detailed: bool = False
):
    title = f'[bold]{pkg.name}[/bold]'
    if short_name:
        title = f'[bold]{short_name}. {pkg.name}[/bold]'

    console.console.print(Panel(title, style='bold blue', expand=False))

    # --- Section: General Info ---
    console.console.print('[bold]General Info[/bold]')
    info_table = Table(show_header=False, box=None, padding=(0, 1))
    info_table.add_column('Property', style='cyan')
    info_table.add_column('Value')

    # Basic Limits (Base Profile)
    if not detailed:
        info_table.add_row('Time Limit', get_formatted_time(pkg.timeLimit))
        info_table.add_row(
            'Memory Limit', get_formatted_memory(pkg.memoryLimit * 1024 * 1024)
        )
        info_table.add_row('Output Limit', get_formatted_memory(pkg.outputLimit * 1024))

    # Testcase Counts
    samples, hidden = await _count_testcases_details(pkg)
    info_table.add_row('Tests', f'{samples} samples, {hidden} hidden tests')

    # Flags
    if detailed:
        if pkg.checker:
            info_table.add_row('Checker', pkg.checker.display())
        if pkg.validator:
            info_table.add_row('Validator', pkg.validator.display())

    flags = _get_flags(pkg)
    if flags:
        info_table.add_row('Flags', ', '.join(flags))

    console.console.print(info_table)
    console.console.print()

    # --- Section: Limits ---
    if detailed:
        console.console.print('[bold]Limits[/bold]')
        from rbx.box import limits_info

        # 1. Package Limits (Base)
        base_table = Table(box=None, padding=(0, 1), show_header=False)
        base_table.add_column('Key', style='cyan')
        base_table.add_column('Value')
        base_table.add_row('Time Limit', get_formatted_time(pkg.timeLimit))
        base_table.add_row(
            'Memory Limit', get_formatted_memory(pkg.memoryLimit * 1024 * 1024)
        )
        base_table.add_row('Output Limit', get_formatted_memory(pkg.outputLimit * 1024))

        console.console.print(
            Panel(base_table, title='[bold]Package (Base)[/bold]', expand=False)
        )

        # 2. Modifiers on Package
        if pkg.modifiers:
            mod_table = Table(box=None, padding=(0, 1), show_header=True)
            mod_table.title = 'Language Modifiers (Package)'
            mod_table.add_column('Language', style='yellow')
            mod_table.add_column('Time', justify='right')
            mod_table.add_column('Memory', justify='right')

            for lang, mod in pkg.modifiers.items():
                t_str = '-'
                if mod.time is not None:
                    t_str = get_formatted_time(mod.time)
                elif mod.timeMultiplier is not None:
                    t_str = f'{mod.timeMultiplier}x'

                m_str = '-'
                if mod.memory is not None:
                    m_str = get_formatted_memory(mod.memory * 1024 * 1024)

                mod_table.add_row(lang, t_str, m_str)
            console.console.print(mod_table)

        # 3. Other Profiles
        profiles = limits_info.get_available_profile_names()
        for profile_name in profiles:
            p = limits_info.get_limits_profile(
                profile_name, fallback_to_package_profile=False
            )

            p_table = Table(box=None, padding=(0, 1), show_header=False)
            p_table.add_column('Key', style='cyan')
            p_table.add_column('Value')

            if p.inheritFromPackage:
                p_table.add_row('Inherits', 'Yes')

            if p.timeLimit is not None:
                p_table.add_row('Time Limit', get_formatted_time(p.timeLimit))
            if p.memoryLimit is not None:
                p_table.add_row(
                    'Memory Limit', get_formatted_memory(p.memoryLimit * 1024 * 1024)
                )
            if p.outputLimit is not None:
                p_table.add_row(
                    'Output Limit', get_formatted_memory(p.outputLimit * 1024)
                )

            console.console.print(
                Panel(
                    p_table, title=f'[bold]Profile: {profile_name}[/bold]', expand=False
                )
            )

            if p.modifiers:
                pm_table = Table(box=None, padding=(0, 1), show_header=True)
                pm_table.title = f'Language Modifiers ({profile_name})'
                pm_table.add_column('Language', style='yellow')
                pm_table.add_column('Time', justify='right')
                pm_table.add_column('Memory', justify='right')

                for lang, mod in p.modifiers.items():
                    t_str = '-'
                    if mod.time is not None:
                        t_str = get_formatted_time(mod.time)
                    elif mod.timeMultiplier is not None:
                        t_str = f'{mod.timeMultiplier}x'

                    m_str = '-'
                    if mod.memory is not None:
                        m_str = get_formatted_memory(mod.memory * 1024 * 1024)

                    pm_table.add_row(lang, t_str, m_str)
                console.console.print(pm_table)
        console.console.print()

    # --- Section: Solutions ---
    console.console.print('[bold]Solutions[/bold]')
    expanded_solutions = package.get_solutions()
    if detailed:
        solutions_by_outcome = {}
        for sol in expanded_solutions:
            bucket = sol.outcome  # Group by exact outcome in detailed mode? Or bucket? Plan said Sort AC -> Wrong etc.
            # Using exact outcome allows scanning for specific issues.
            if bucket not in solutions_by_outcome:
                solutions_by_outcome[bucket] = []
            solutions_by_outcome[bucket].append(sol)

        # Sort keys: Accepted first, then others
        sorted_outcomes = sorted(
            solutions_by_outcome.keys(),
            key=lambda o: (o != ExpectedOutcome.ACCEPTED, o.name),
        )

        for outcome in sorted_outcomes:
            sols = solutions_by_outcome[outcome]
            console.console.print(f'{outcome.full_markup()} ({len(sols)})')
            for sol in sols:
                # One per line, no list indicator.
                # Format: Path [tags/score]
                extras = []
                if sol.tags:
                    tags_str = ', '.join(sol.tags)
                    extras.append(f'\\[{tags_str}]')
                if sol.score is not None:
                    extras.append(f'score: {sol.score}')

                extra_str = f' [dim]({" ".join(extras)})[/dim]' if extras else ''
                console.console.print(f'  {sol.display()}{extra_str}')
            console.console.print()

    else:
        sol_counts = _get_solution_counts(expanded_solutions)
        sol_table = Table(box=None, show_header=True, padding=(0, 1))
        sol_table.add_column('Outcome', style='bold')
        sol_table.add_column('Count', justify='right')

        has_solutions = False
        for outcome, count in sol_counts.items():
            if count > 0:
                sol_table.add_row(outcome.full_markup(), str(count))
                has_solutions = True

        if not has_solutions:
            sol_table.add_row('[dim]No solutions[/dim]', '')

        console.console.print(sol_table)


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

        try:
            with cd.new_package_cd(problem_path):
                row_data.append(await _count_testcases_str(problem))
                row_data.append(_get_flags_short(problem))
                expanded_solutions = package.get_solutions()
                counts = _get_solution_counts(expanded_solutions, bucketize=True)
        except Exception:
            console.console.print(
                f'[error]Failed to summarize problem [item]{short_name} - {problem.name}[/item][/error]'
            )
            continue

        for outcome in buckets:
            c = counts.get(outcome, 0)
            style = outcome.style() if c > 0 else 'dim'
            row_data.append(f'[{style}]{c}[/{style}]')

        total_sols = len(expanded_solutions)
        row_data.append(str(total_sols))

        table.add_row(*row_data)

    console.console.print(table)
