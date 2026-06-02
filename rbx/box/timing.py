from typing import Any, Dict, List, Optional

import rich
import rich.console
import typer
from ordered_set import OrderedSet
from pydantic import BaseModel, Field

from rbx import console, utils
from rbx.box import (
    environment,
    limits_info,
    package,
    safeeval,
    schema,
    timing_group_picker,
    timing_groups,
)
from rbx.box.code import find_language_name
from rbx.box.environment import VerificationLevel
from rbx.box.formatting import href
from rbx.box.schema import ExpectedOutcome
from rbx.box.solutions import (
    RunSolutionResult,
    consume_and_key_evaluation_items,
    get_exact_matching_solutions,
    print_run_report,
    run_solutions,
)


class TimingProfile(BaseModel):
    timeLimit: int
    formula: Optional[str] = None
    timeLimitPerLanguage: Dict[str, int] = Field(default_factory=dict)
    groups: Optional[List[schema.TimingGroupReport]] = None

    def to_limits(self):
        return schema.LimitsProfile(
            timeLimit=self.timeLimit,
            formula=self.formula,
            modifiers={
                lang: schema.LimitModifiers(time=tl)
                for lang, tl in self.timeLimitPerLanguage.items()
            },
            groups=self.groups,
        )


def pretty_print_profile(profile: TimingProfile):
    console.console.print(f'[bstatus]Time limit:[/bstatus] {profile.timeLimit} ms')
    console.console.print(
        f'[bstatus]Time limit per language:[/bstatus] {profile.timeLimitPerLanguage}'
    )
    if profile.formula:
        console.console.print(f'[bstatus]Used formula:[/bstatus] {profile.formula}')


def step_down(x: Any, step: int) -> int:
    x = int(x)
    return x // step * step


def step_up(x: Any, step: int) -> int:
    x = int(x)
    return (x + step - 1) // step * step


def build_timing_profile(
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    formula: str,
    env_groups: List[environment.LanguageGroup],
    all_languages: List[str],
    repartition: Optional[Dict[str, int]] = None,
) -> TimingProfile:
    def _eval(fastest: int, slowest: int) -> int:
        return int(safeeval.eval_int(formula, {'fastest': fastest, 'slowest': slowest}))

    if repartition is not None:
        groups = timing_groups.partition_from_assignment(repartition, env_groups)
    else:
        groups = timing_groups.build_partition(env_groups, all_languages)
    timing_groups.validate_partition(groups)

    pooled: Dict[int, timing_groups.GroupTimings] = {}
    all_values: List[int] = []
    for idx, group in enumerate(groups):
        values: List[int] = []
        count = 0
        for lang in group.languages:
            per_sol = timing_per_solution_per_language.get(lang, {})
            values.extend(per_sol.values())
            count += len(per_sol)
        if values:
            pooled[idx] = timing_groups.GroupTimings(
                fastest=min(values), slowest=max(values), solution_count=count
            )
            all_values.extend(values)

    base = timing_groups.GroupTimings(
        fastest=min(all_values),
        slowest=max(all_values),
        solution_count=len(all_values),
    )
    result = timing_groups.resolve_groups(groups, pooled, base, _eval)
    return TimingProfile(
        timeLimit=result.base_time_limit,
        formula=formula,
        timeLimitPerLanguage=result.time_limit_per_language,
        groups=result.reports,
    )


def default_assignment(
    all_languages: List[str],
    env_groups: List[environment.LanguageGroup],
) -> Dict[str, int]:
    """Prepopulated picker state from env groups: env group #1 -> 1, etc.;
    every other language -> 0 (unbucketed). Feeding this straight into
    partition_from_assignment reproduces the env grouping (so whenEmpty carries
    over) with all ungrouped languages pooled together."""
    default_number: Dict[str, int] = {lang: 0 for lang in all_languages}
    for i, group in enumerate(env_groups, start=1):
        for lang in group.languages:
            if lang in default_number:
                default_number[lang] = i
    return default_number


async def _prompt_repartition(
    all_languages: List[str],
    env_groups: List[environment.LanguageGroup],
) -> Optional[Dict[str, int]]:
    return await timing_group_picker.prompt_group_assignment(
        all_languages, default_assignment(all_languages, env_groups)
    )


def relevant_languages_for_estimation(
    env_languages: List[str],
    timing_languages: List[str],
) -> List[str]:
    """Languages that participate in the partition during estimation: every
    environment language (so unrepresented ones land in the picker and the
    leftover pool / DEFAULTED warning), followed by any timing language not
    declared in the environment. Ordered by the environment's language order."""
    ordered = list(env_languages)
    for lang in timing_languages:
        if lang not in ordered:
            ordered.append(lang)
    return ordered


async def estimate_time_limit(
    console: rich.console.Console,
    result: RunSolutionResult,
    formula: Optional[str] = None,
    auto: bool = False,
) -> Optional[TimingProfile]:
    structured_evaluations = consume_and_key_evaluation_items(
        result.items, result.skeleton
    )

    timing_per_solution = {}
    timing_per_solution_per_language = {}

    if not result.skeleton.solutions:
        console.print('[error]No solutions to estimate time limit from.[/error]')
        return None

    for solution in result.skeleton.solutions:
        timings = []
        for evals in structured_evaluations[str(solution.path)].values():
            for ev in evals:
                if ev is None:
                    continue
                ev = await ev()
                if ev.log.time is not None:
                    timings.append(int(ev.log.time * 1000))

        if not timings:
            console.print(
                f'[warning]No timings for solution {solution.href()}.[/warning]'
            )
            continue

        timing_per_solution[str(solution.path)] = max(timings)
        lang = find_language_name(solution)
        if lang not in timing_per_solution_per_language:
            timing_per_solution_per_language[lang] = {}
        timing_per_solution_per_language[lang][str(solution.path)] = max(timings)

    console.rule('[status]Time report[/status]', style='status')

    if not timing_per_solution:
        console.print('[error]No timings collected from solutions.[/error]')
        return None

    fastest_time = min(timing_per_solution.values())
    slowest_time = max(timing_per_solution.values())
    console.print(f'Fastest solution: {fastest_time} ms')
    console.print(f'Slowest solution: {slowest_time} ms')

    env = environment.get_environment()
    if formula is None:
        formula = env.timing.formula
    env_groups = env.timing.groups

    all_languages = relevant_languages_for_estimation(
        env_languages=[lang.name for lang in env.languages],
        timing_languages=list(timing_per_solution_per_language.keys()),
    )

    repartition = None
    if not auto and len(all_languages) > 1:
        repartition = await _prompt_repartition(all_languages, env_groups)
        if repartition is None:
            console.print('[error]Time limit estimation cancelled.[/error]')
            return None

    console.print()
    console.rule('[status]Time estimation[/status]', style='status')
    console.print(f'Using formula: {formula}')

    try:
        profile = build_timing_profile(
            timing_per_solution_per_language=timing_per_solution_per_language,
            formula=formula,
            env_groups=env_groups,
            all_languages=all_languages,
            repartition=repartition,
        )
    except timing_groups.GroupValidationError as e:
        console.print(f'[error]Invalid language groups: {e}[/error]')
        return None

    console.print(f'[success]Estimated time limit:[/success] {profile.timeLimit} ms')

    defaulted = [
        lang
        for report in (profile.groups or [])
        if report.origin == schema.TimingGroupOrigin.DEFAULTED
        for lang in report.languages
    ]
    if defaulted:
        console.print(
            '[warning]⚠ The following languages have no solution and no whenEmpty '
            f'rule, so they fall back to the base time limit of {profile.timeLimit} '
            f'ms: {", ".join(defaulted)}.[/warning]'
        )

    return profile


async def compute_time_limits(
    check: bool,
    detailed: bool,
    runs: int = 0,
    profile: str = 'local',
    formula: Optional[str] = None,
    auto: bool = False,
):
    if package.get_main_solution() is None:
        console.console.print(
            '[warning]No main solution found, so cannot estimate a time limit.[/warning]'
        )
        return None

    verification = VerificationLevel.ALL_SOLUTIONS.value

    with utils.StatusProgress('Running ACCEPTED solutions...') as s:
        tracked_solutions = OrderedSet(
            str(solution.path)
            for solution in get_exact_matching_solutions(ExpectedOutcome.ACCEPTED)
        )
        solution_result = await run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            verification=VerificationLevel(verification),
            timelimit_override=-1,  # Unlimited for time limit estimation
            nruns=runs,
        )

    console.console.print()
    console.console.rule(
        '[status]Run report (for time estimation)[/status]', style='status'
    )
    ok = await print_run_report(
        solution_result,
        console.console,
        VerificationLevel(verification),
        detailed=detailed,
        skip_printing_limits=True,
    )

    if not ok:
        console.console.print(
            '[error]Failed to run ACCEPTED solutions, so cannot estimate a reliable time limit.[/error]'
        )
        return None

    estimated_tl = await estimate_time_limit(
        console.console, solution_result, formula, auto=auto
    )
    if estimated_tl is None:
        return None

    limits_path = package.get_limits_file(profile)
    console.console.print(
        f'[success]Writing the following timing profile to [item]{href(limits_path)}[/item].[/success]'
    )
    limits = estimated_tl.to_limits()
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(utils.model_to_yaml(limits))

    limits_info.render_limits_table(limits, title=f'Time limits ({profile})')

    return estimated_tl


def inherit_time_limits(profile: str = 'local'):
    limits_path = package.get_limits_file(profile)
    limits = schema.LimitsProfile(inheritFromPackage=True)
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(utils.model_to_yaml(limits))

    console.console.print(
        f'[success]Inherit time limits from package for profile [item]{profile}[/item].[/success]'
    )


def set_time_limit(timelimit: int, profile: str = 'local'):
    limits = schema.LimitsProfile(timeLimit=timelimit)
    limits_path = package.get_limits_file(profile)
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(utils.model_to_yaml(limits))

    console.console.print(
        f'[success]Set time limit for profile [item]{profile}[/item] to [item]{timelimit} ms[/item].[/success]'
    )


def integrate(profile: str = 'local'):
    limits_profile = limits_info.get_saved_limits_profile(profile)
    if limits_profile is None:
        console.console.print(
            f'[error]No limits profile found for profile [item]{profile}[/item].[/error]'
        )
        raise typer.Exit(1)

    if limits_profile.inheritFromPackage:
        console.console.print(
            f'[warning]Limits profile [item]{profile}[/item] already inherits from package.[/warning]'
        )
        console.console.print('[warning]This operation is a no-op.[/warning]')
        return

    ru, pkg = package.get_ruyaml()

    if limits_profile.timeLimit is not None:
        pkg['timeLimit'] = limits_profile.timeLimit
    if limits_profile.memoryLimit is not None:
        pkg['memoryLimit'] = limits_profile.memoryLimit
    if limits_profile.outputLimit is not None:
        pkg['outputLimit'] = limits_profile.outputLimit

    for lang, limits in limits_profile.modifiers.items():
        if limits.time is not None:
            pkg['modifiers'][lang]['time'] = limits.time
        if limits.memory is not None:
            pkg['modifiers'][lang]['memory'] = limits.memory
        if limits.timeMultiplier is not None:
            pkg['modifiers'][lang]['timeMultiplier'] = limits.timeMultiplier

    dest_yml = package.find_problem_yaml()
    assert dest_yml is not None
    utils.save_ruyaml(dest_yml, ru, pkg)

    console.console.print(
        f'[success]Integrated limits profile [item]{profile}[/item] into package.[/success]'
    )
