import pathlib
from typing import Dict, List, Optional

from pydantic import BaseModel
from rich.panel import Panel
from rich.table import Table

from rbx import console
from rbx.box import cd, package, testcase_extractors
from rbx.box.contest.schema import Contest
from rbx.box.formatting import get_formatted_memory, get_formatted_time
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.schema import ExpectedOutcome, Package, Solution, TaskType

# --- Data models ---


class TestcaseCounts(BaseModel):
    samples: int
    hidden: int


class ProblemFlags(BaseModel):
    is_interactive: bool
    has_validator: bool
    has_custom_checker: bool


class ProblemSummary(BaseModel):
    name: str
    short_name: Optional[str] = None
    time_limit_ms: int
    memory_limit_mb: int
    output_limit_kb: int
    testcase_counts: TestcaseCounts
    flags: ProblemFlags
    interactor_display: Optional[str] = None
    checker_display: Optional[str] = None
    validator_display: Optional[str] = None
    solutions: List[Solution]
    solution_counts: Dict[ExpectedOutcome, int]


class ContestProblemSummary(BaseModel):
    short_name: str
    name: str
    time_limit_ms: int
    memory_limit_mb: int
    testcase_counts: TestcaseCounts
    flags: ProblemFlags
    solution_counts_bucketed: Dict[ExpectedOutcome, int]
    total_solutions: int


# --- Pure functions ---


def count_testcases(entries: List[GenerationTestcaseEntry]) -> TestcaseCounts:
    samples = 0
    hidden = 0
    for entry in entries:
        if entry.is_sample():
            samples += 1
        else:
            hidden += 1
    return TestcaseCounts(samples=samples, hidden=hidden)


def get_outcome_bucket(outcome: ExpectedOutcome) -> Optional[ExpectedOutcome]:
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
    # ANY and any unknown outcomes are not bucketed.
    return None


def get_solution_counts(
    solutions: List[Solution], bucketize: bool = False
) -> Dict[ExpectedOutcome, int]:
    if bucketize:
        counts: Dict[ExpectedOutcome, int] = {
            ExpectedOutcome.ACCEPTED: 0,
            ExpectedOutcome.WRONG_ANSWER: 0,
            ExpectedOutcome.TIME_LIMIT_EXCEEDED: 0,
            ExpectedOutcome.RUNTIME_ERROR: 0,
        }
    else:
        counts = {outcome: 0 for outcome in ExpectedOutcome}

    for sol in solutions:
        if bucketize:
            bucket = get_outcome_bucket(sol.outcome)
            if bucket is not None:
                counts[bucket] += 1
        elif sol.outcome in counts:
            counts[sol.outcome] += 1
    return counts


def get_problem_flags(pkg: Package) -> ProblemFlags:
    return ProblemFlags(
        is_interactive=pkg.type == TaskType.COMMUNICATION,
        has_validator=pkg.validator is not None,
        has_custom_checker=pkg.checker is not None,
    )


def get_problem_summary(
    pkg: Package,
    solutions: List[Solution],
    testcase_entries: List[GenerationTestcaseEntry],
    short_name: Optional[str] = None,
) -> ProblemSummary:
    return ProblemSummary(
        name=pkg.name,
        short_name=short_name,
        time_limit_ms=pkg.timeLimit,
        memory_limit_mb=pkg.memoryLimit,
        output_limit_kb=pkg.outputLimit,
        testcase_counts=count_testcases(testcase_entries),
        flags=get_problem_flags(pkg),
        interactor_display=pkg.interactor.display() if pkg.interactor else None,
        checker_display=pkg.checker.display() if pkg.checker else None,
        validator_display=pkg.validator.display() if pkg.validator else None,
        solutions=solutions,
        solution_counts=get_solution_counts(solutions),
    )


def get_contest_problem_summary(
    pkg: Package,
    solutions: List[Solution],
    testcase_entries: List[GenerationTestcaseEntry],
    short_name: str,
) -> ContestProblemSummary:
    return ContestProblemSummary(
        short_name=short_name,
        name=pkg.name,
        time_limit_ms=pkg.timeLimit,
        memory_limit_mb=pkg.memoryLimit,
        testcase_counts=count_testcases(testcase_entries),
        flags=get_problem_flags(pkg),
        solution_counts_bucketed=get_solution_counts(solutions, bucketize=True),
        total_solutions=len(solutions),
    )


# --- Rendering helpers ---


def _get_flags_short(flags: ProblemFlags) -> str:
    parts = []
    if flags.is_interactive:
        parts.append('[bold magenta]I[/bold magenta]')
    else:
        parts.append('[dim]I[/dim]')

    if flags.has_validator:
        parts.append('[green]V[/green]')
    else:
        parts.append('[dim]V[/dim]')

    if flags.has_custom_checker:
        parts.append('[blue]C[/blue]')
    else:
        parts.append('[dim]C[/dim]')

    return ' '.join(parts)


# --- Printing functions ---


async def print_problem_summary(
    pkg: Package, short_name: Optional[str] = None, detailed: bool = False
):
    entries = await testcase_extractors.extract_generation_testcases_from_groups()
    expanded_solutions = package.get_solutions()
    summary = get_problem_summary(pkg, expanded_solutions, entries, short_name)

    title = f'[bold]{summary.name}[/bold]'
    if summary.short_name:
        title = f'[bold]{summary.short_name}. {summary.name}[/bold]'

    console.console.print(Panel(title, style='bold blue', expand=False))

    # --- Section: General Info ---
    console.console.print('[bold]General Info[/bold]')
    info_table = Table(show_header=False, box=None, padding=(0, 1))
    info_table.add_column('Property', style='cyan')
    info_table.add_column('Value')

    if not detailed:
        info_table.add_row('Time Limit', get_formatted_time(summary.time_limit_ms))
        info_table.add_row(
            'Memory Limit',
            get_formatted_memory(summary.memory_limit_mb * 1024 * 1024),
        )
        info_table.add_row(
            'Output Limit', get_formatted_memory(summary.output_limit_kb * 1024)
        )

    tc = summary.testcase_counts
    info_table.add_row('Tests', f'{tc.samples} samples, {tc.hidden} hidden tests')

    if summary.interactor_display:
        info_table.add_row('Interactor', summary.interactor_display)
    if summary.checker_display:
        info_table.add_row('Checker', summary.checker_display)
    if summary.validator_display:
        info_table.add_row('Validator', summary.validator_display)

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
    if detailed:
        solutions_by_outcome: dict[ExpectedOutcome, list[Solution]] = {}
        for sol in summary.solutions:
            if sol.outcome not in solutions_by_outcome:
                solutions_by_outcome[sol.outcome] = []
            solutions_by_outcome[sol.outcome].append(sol)

        sorted_outcomes = sorted(
            solutions_by_outcome.keys(),
            key=lambda o: (o != ExpectedOutcome.ACCEPTED, o.name),
        )

        for outcome in sorted_outcomes:
            sols = solutions_by_outcome[outcome]
            console.console.print(f'{outcome.full_markup()} ({len(sols)})')
            for sol in sols:
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
        sol_table = Table(box=None, show_header=True, padding=(0, 1))
        sol_table.add_column('Outcome', style='bold')
        sol_table.add_column('Count', justify='right')

        has_solutions = False
        for outcome, count in summary.solution_counts.items():
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
        row_data: list[str] = []
        short_name = contest.problems[i].short_name

        raw_path = contest.problems[i].path
        problem_path = pathlib.Path(raw_path) if raw_path else pathlib.Path('.')

        row_data.append(short_name)
        row_data.append(problem.name)
        row_data.append(get_formatted_time(problem.timeLimit))
        row_data.append(get_formatted_memory(problem.memoryLimit * 1024 * 1024))

        try:
            with cd.new_package_cd(problem_path):
                package.clear_package_cache()
                entries = (
                    await testcase_extractors.extract_generation_testcases_from_groups()
                )
                expanded_solutions = package.get_solutions()
                summary = get_contest_problem_summary(
                    problem, expanded_solutions, entries, short_name
                )
        except Exception:
            console.console.print(
                f'[error]Failed to summarize problem [item]{short_name} - {problem.name}[/item][/error]'
            )
            continue

        tc = summary.testcase_counts
        row_data.append(f'{tc.samples} samples, {tc.hidden} hidden tests')
        row_data.append(_get_flags_short(summary.flags))

        for outcome in buckets:
            c = summary.solution_counts_bucketed.get(outcome, 0)
            style = outcome.style() if c > 0 else 'dim'
            row_data.append(f'[{style}]{c}[/{style}]')

        row_data.append(str(summary.total_solutions))

        table.add_row(*row_data)

    console.console.print(table)
