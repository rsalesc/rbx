import pathlib
from typing import Any, Dict, Optional

import questionary
import rich
import rich.console
import typer
from ordered_set import OrderedSet
from pydantic import BaseModel, Field

from rbx import console, utils
from rbx.box import environment, limits_info, package, schema
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

    def to_limits(self):
        return schema.LimitsProfile(
            timeLimit=self.timeLimit,
            formula=self.formula,
            modifiers={
                lang: schema.LimitModifiers(time=tl)
                for lang, tl in self.timeLimitPerLanguage.items()
            },
        )


def get_timing_profile(
    profile: str, root: pathlib.Path = pathlib.Path()
) -> Optional[TimingProfile]:
    path = package.get_limits_file(profile, root)
    if not path.exists():
        return None
    return utils.model_from_yaml(TimingProfile, path.read_text())


def step_down(x: Any, step: int) -> int:
    x = int(x)
    return x // step * step


def step_up(x: Any, step: int) -> int:
    x = int(x)
    return (x + step - 1) // step * step


async def estimate_time_limit(
    console: rich.console.Console,
    result: RunSolutionResult,
    formula: Optional[str] = None,
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
                f'[warning]No timings for solution {href(solution.path)}.[/warning]'
            )
            continue

        timing_per_solution[str(solution.path)] = max(timings)
        lang = find_language_name(solution)
        if lang not in timing_per_solution_per_language:
            timing_per_solution_per_language[lang] = {}
        timing_per_solution_per_language[lang][str(solution.path)] = max(timings)

    console.rule('[status]Time report[/status]', style='status')

    fastest_time = min(timing_per_solution.values())
    slowest_time = max(timing_per_solution.values())

    console.print(f'Fastest solution: {fastest_time} ms')
    console.print(f'Slowest solution: {slowest_time} ms')

    def _get_lang_fastest(lang: str) -> int:
        return min(timing_per_solution_per_language[lang].values())

    def _get_lang_slowest(lang: str) -> int:
        return max(timing_per_solution_per_language[lang].values())

    env = environment.get_environment()
    if formula is None:
        formula = env.timing.formula

    def _eval(fastest_time: int, slowest_time: int) -> int:
        return int(
            eval(
                formula,
                {
                    'fastest': fastest_time,
                    'slowest': slowest_time,
                    'step_up': step_up,
                    'step_down': step_down,
                },
            )
        )

    if len(timing_per_solution_per_language) > 1:
        timing_language_list = [
            (_get_lang_fastest(lang), lang) for lang in timing_per_solution_per_language
        ]
        fastest_language_time, fastest_language = min(timing_language_list)
        slowest_language_time, slowest_language = max(timing_language_list)

        console.print(
            f'Fastest language: {fastest_language} ({fastest_language_time} ms)'
        )
        console.print(
            f'Slowest language: {slowest_language} ({slowest_language_time} ms)'
        )

    console.print()
    console.rule('[status]Time estimation[/status]', style='status')

    console.print(f'Using formula: {formula}')

    estimated_tl = _eval(fastest_time, slowest_time)
    console.print(f'[success]Estimated time limit:[/success] {estimated_tl} ms')

    estimated_tl_per_language = {}
    if len(timing_per_solution_per_language) > 1:
        for lang in timing_per_solution_per_language:
            estimated_tl_per_language[lang] = _eval(
                _get_lang_fastest(lang), _get_lang_slowest(lang)
            )

    final_estimated_tls_per_language = {}
    if estimated_tl_per_language:
        for lang, tl in estimated_tl_per_language.items():
            console.print(f'Estimated time limit for {lang}: {tl} ms')

        all_distinct_tls = set(estimated_tl_per_language.values())
        if len(all_distinct_tls) > 1:
            console.print()
            console.print('It seems your problem has solutions for multiple languages!')
            selected_langs = await questionary.checkbox(
                'Please select which languages you want to have a specific time limit for '
                '(or leave all unselected if you want to use a single global time limit)',
                choices=list(estimated_tl_per_language.keys()),
            ).ask_async()
            if selected_langs:
                for lang in selected_langs:
                    final_estimated_tls_per_language[lang] = estimated_tl_per_language[
                        lang
                    ]

    return TimingProfile(
        timeLimit=estimated_tl,
        formula=formula,
        timeLimitPerLanguage=final_estimated_tls_per_language,
    )


async def compute_time_limits(
    check: bool,
    detailed: bool,
    runs: int = 0,
    profile: str = 'local',
    formula: Optional[str] = None,
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
        solution_result = run_solutions(
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

    estimated_tl = await estimate_time_limit(console.console, solution_result, formula)
    if estimated_tl is None:
        return None

    limits_path = package.get_limits_file(profile)
    console.console.print(
        f'[green]Writing the following timing profile to [item]{href(limits_path)}[/item].[/green]'
    )
    console.console.print(estimated_tl, highlight=True)
    limits_path.write_text(utils.model_to_yaml(estimated_tl.to_limits()))

    return estimated_tl


def inherit_time_limits(profile: str = 'local'):
    limits_path = package.get_limits_file(profile)
    limits = schema.LimitsProfile(inheritFromPackage=True)
    limits_path.write_text(utils.model_to_yaml(limits))

    console.console.print(
        f'[green]Inherit time limits from package for profile [item]{profile}[/item].[/green]'
    )


def set_time_limit(timelimit: int, profile: str = 'local'):
    limits = schema.LimitsProfile(timeLimit=timelimit)
    limits_path = package.get_limits_file(profile)
    limits_path.write_text(utils.model_to_yaml(limits))

    console.console.print(
        f'[green]Set time limit for profile [item]{profile}[/item] to [item]{timelimit} ms[/item].[/green]'
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
        f'[green]Integrated limits profile [item]{profile}[/item] into package.[/green]'
    )
