import functools
import math
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional

import rich
import rich.console
import typer
from ordered_set import OrderedSet
from prompt_toolkit.formatted_text import ANSI
from pydantic import BaseModel, Field

from rbx import console, utils
from rbx.box import (
    environment,
    limits_info,
    package,
    safeeval,
    schema,
    sharing,
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
    baseEstimate: Optional[schema.TimingGroupReport] = None

    def to_limits(self):
        return schema.LimitsProfile(
            timeLimit=self.timeLimit,
            formula=self.formula,
            modifiers={
                lang: schema.LimitModifiers(time=tl)
                for lang, tl in self.timeLimitPerLanguage.items()
            },
            groups=self.groups,
            baseEstimate=self.baseEstimate,
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


def _exact(ratio: float) -> Fraction:
    """The ratio the setter typed in YAML, as an exact rational.

    ``str()`` yields the shortest repr that round-trips, so the 1.1 stored as
    1.100000000000000088... comes back as exactly 11/10. Every bound is computed
    in this arithmetic: the numbers end up serialized in the limits profile, so
    a setter recomputing them by hand must get the same answer rbx did.
    """
    return Fraction(str(ratio))


class TimingBounds(BaseModel):
    """The bounds that decide one group's time limit, in integer milliseconds.

    Computed exactly, so these are the values the limits profile reports.
    """

    # Smallest limit the lower side allows, before quantization.
    lower: int
    lower_solution: Optional[str] = None
    # ``lower`` rounded up to the configured ``timeResolution``.
    time_limit: int
    # Largest limit the group's slow solutions allow, when any bounds it.
    upper: Optional[int] = None
    upper_solution: Optional[str] = None
    # Whether ``lower`` came from a reference group instead of this group's own
    # accepted solutions.
    derived: bool = False

    @property
    def fits(self) -> bool:
        """Whether the quantized limit respects the upper bound."""
        return self.upper is None or self.time_limit <= self.upper

    @property
    def quantization_is_binding(self) -> bool:
        """Whether the raw lower bound fits but rounding it up does not -- i.e.
        ``timeResolution``, not the ratios, is what makes the range unsatisfiable."""
        return self.upper is not None and self.lower <= self.upper < self.time_limit


def compute_bounds(
    multipliers: schema.TimingMultipliers,
    measured: timing_groups.GroupMeasurements,
    derived_from: Optional[int] = None,
) -> TimingBounds:
    """The bounds a group's measurements impose on its time limit.

    ``derived_from`` supplies the lower bound for a group whose limit did NOT
    come from its own accepted solutions (a reference group or the base
    estimate); otherwise the lower bound is this group's slowest accepted
    solution scaled by ``acToTimeLimit``.
    """
    lower_solution = None
    if derived_from is not None:
        lower = derived_from
    else:
        assert measured.lower is not None
        lower = math.ceil(measured.lower.slowest * _exact(multipliers.acToTimeLimit))
        lower_solution = measured.lower.slowest_solution

    upper = None
    upper_solution = None
    if multipliers.timeLimitToTle is not None and measured.upper is not None:
        upper = math.floor(
            measured.upper.fastest_slow / _exact(multipliers.timeLimitToTle)
        )
        upper_solution = measured.upper.fastest_slow_solution

    return TimingBounds(
        lower=lower,
        lower_solution=lower_solution,
        time_limit=step_up(lower, multipliers.timeResolution),
        upper=upper,
        upper_solution=upper_solution,
        derived=derived_from is not None,
    )


def make_formula_eval(formula: str) -> timing_groups.EvalFn:
    """Estimator that evaluates the configured formula over the group's accepted
    solutions. Bounded from below only: it never reads the upper measurements,
    so no upper bound is measured for it."""

    def _eval(measured: timing_groups.GroupMeasurements) -> int:
        assert measured.lower is not None
        timings = measured.lower
        return int(
            safeeval.eval_int(
                formula, {'fastest': timings.fastest, 'slowest': timings.slowest}
            )
        )

    return _eval


def _check_bounds(
    bounds: TimingBounds,
    multipliers: schema.TimingMultipliers,
    measured: timing_groups.GroupMeasurements,
) -> int:
    """Return the quantized limit if the group's slow solutions allow it, else
    raise naming the binding solution on each side and the knob to turn."""
    if bounds.fits:
        return bounds.time_limit
    assert bounds.upper is not None

    if bounds.derived:
        fast_solution = 'the accepted solutions of the group this limit derives from'
        lower_side = f'the limit derived for this group is {bounds.lower} ms'
    else:
        fast_solution = bounds.lower_solution or 'the accepted solution'
        assert measured.lower is not None
        lower_side = (
            f'{fast_solution} runs in {measured.lower.slowest} ms, which with '
            f'acToTimeLimit {multipliers.acToTimeLimit} requires a limit of at '
            f'least {bounds.lower} ms'
        )
    slow_solution = bounds.upper_solution or 'the slow solution'
    assert measured.upper is not None
    upper_side = (
        f'{slow_solution} runs in {measured.upper.fastest_slow} ms, which with '
        f'timeLimitToTle {multipliers.timeLimitToTle} caps the limit at '
        f'{bounds.upper} ms'
    )

    if bounds.quantization_is_binding:
        # The ratios are satisfiable on their own; only the rounding is not.
        # Saying "relax the ratios" here would send the setter chasing a
        # speedup that is not needed.
        raise timing_groups.TimingRangeError(
            f'no valid time limit exists for this group: {lower_side}, and '
            f'timeResolution {multipliers.timeResolution} rounds that up to '
            f'{bounds.time_limit} ms, but {upper_side}. The un-rounded bound of '
            f'{bounds.lower} ms does fit under the cap: it is the rounding to '
            f'timeResolution that does not. Lower timeResolution, speed up '
            f'{fast_solution}, slow down {slow_solution}, or relax the ratios.'
        )
    raise timing_groups.TimingRangeError(
        f'no valid time limit exists for this group: {lower_side}, but '
        f'{upper_side}. Speed up {fast_solution}, slow down {slow_solution}, '
        f'or relax the ratios.'
    )


def make_multipliers_eval(
    multipliers: schema.TimingMultipliers,
) -> timing_groups.EvalFn:
    """Estimator that bounds the limit from below by the group's accepted
    solutions, quantizes it to ``timeResolution``, and checks it against the
    upper bound its slow solutions impose."""

    def _eval(measured: timing_groups.GroupMeasurements) -> int:
        bounds = compute_bounds(multipliers, measured)
        return _check_bounds(bounds, multipliers, measured)

    return _eval


def make_multipliers_derive(
    multipliers: schema.TimingMultipliers,
) -> timing_groups.DeriveFn:
    """Post-processor for a limit that did NOT come from the group's own accepted
    solutions: it is quantized to ``timeResolution`` and still checked against
    the group's own upper bound."""

    def _derive(tl: int, measured: timing_groups.GroupMeasurements) -> int:
        bounds = compute_bounds(multipliers, measured, derived_from=tl)
        return _check_bounds(bounds, multipliers, measured)

    return _derive


def build_timing_profile(
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    formula: str,
    env_groups: List[environment.LanguageGroup],
    all_languages: List[str],
    repartition: Optional[Dict[str, int]] = None,
    relatives: Optional[Dict[str, environment.LanguageGroupFallback]] = None,
) -> TimingProfile:
    eval_fn = make_formula_eval(formula)

    if repartition is not None:
        groups = timing_groups.partition_from_assignment(repartition, relatives)
    else:
        groups = timing_groups.build_partition(env_groups, all_languages)
    timing_groups.validate_partition(groups)

    measured: Dict[int, timing_groups.GroupMeasurements] = {}
    all_values: List[int] = []
    for idx, group in enumerate(groups):
        values: List[int] = []
        count = 0
        for lang in group.languages:
            per_sol = timing_per_solution_per_language.get(lang, {})
            values.extend(per_sol.values())
            count += len(per_sol)
        if values:
            measured[idx] = timing_groups.GroupMeasurements(
                lower=timing_groups.GroupTimings(
                    fastest=min(values), slowest=max(values), solution_count=count
                )
            )
            all_values.extend(values)

    base = timing_groups.GroupMeasurements(
        lower=timing_groups.GroupTimings(
            fastest=min(all_values),
            slowest=max(all_values),
            solution_count=len(all_values),
        )
    )
    result = timing_groups.resolve_groups(groups, measured, base, eval_fn)
    return TimingProfile(
        timeLimit=result.base_time_limit,
        formula=formula,
        timeLimitPerLanguage=result.time_limit_per_language,
        groups=result.reports,
        baseEstimate=result.base_report,
    )


def default_assignment(
    all_languages: List[str],
    env_groups: List[environment.LanguageGroup],
) -> Dict[str, int]:
    """Prepopulated picker buckets from env groups: env group #i -> bucket i;
    every other language -> 0 (the shared leftover pool). This reproduces the env
    grouping's membership in the picker only. Forced-relative specs (env
    ``whenEmpty``) no longer flow through ``partition_from_assignment``; they are
    seeded separately (see ``default_relatives``)."""
    default_number: Dict[str, int] = {lang: 0 for lang in all_languages}
    for i, group in enumerate(env_groups, start=1):
        for lang in group.languages:
            if lang in default_number:
                default_number[lang] = i
    return default_number


def default_relatives(
    env_groups: List[environment.LanguageGroup],
    langs_with_solutions: set,
) -> Dict[str, environment.LanguageGroupFallback]:
    """Seed picker relatives from env whenEmpty, but only for groups that have
    NO measured solutions (matching env whenEmpty's empty-only semantics at the
    moment of init). Keyed by the picker group-key the env group maps to
    (env group i -> bucket i -> 'g{i}')."""
    seeded: Dict[str, environment.LanguageGroupFallback] = {}
    for i, group in enumerate(env_groups, start=1):
        if group.whenEmpty is None:
            continue
        if any(lang in langs_with_solutions for lang in group.languages):
            continue
        seeded[f'g{i}'] = group.whenEmpty
    return seeded


def build_preview_renderer(
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    formula: str,
    env_groups: List[environment.LanguageGroup],
    all_languages: List[str],
    width: Optional[int] = None,
) -> Callable[..., ANSI]:
    """Return a memoized callback mapping a picker assignment (and optional
    forced-relative specs) to an ``ANSI`` preview: the resolved limits table, or
    an inline error for invalid groupings. Pure -- reuses the already-collected
    timings, never re-runs solutions."""

    @functools.lru_cache(maxsize=None)
    def _render(assignment_items: tuple, relative_items: tuple) -> ANSI:
        assignment = dict(assignment_items)
        relatives = dict(relative_items)
        try:
            profile = build_timing_profile(
                timing_per_solution_per_language=timing_per_solution_per_language,
                formula=formula,
                env_groups=env_groups,
                all_languages=all_languages,
                repartition=assignment,
                relatives=relatives,
            )
        except timing_groups.GroupValidationError as e:
            return ANSI(
                console.capture_ansi(
                    f'[warning]⚠ Invalid grouping: {e}[/warning]', width=width
                )
            )
        table = limits_info.build_limits_table(profile.to_limits(), title='Preview')
        return ANSI(console.capture_ansi(table, width=width))

    def render(
        assignment: Dict[str, int],
        relatives: Optional[Dict[str, environment.LanguageGroupFallback]] = None,
    ) -> ANSI:
        relatives = relatives or {}
        return _render(
            tuple(sorted(assignment.items())),
            tuple(sorted(relatives.items(), key=lambda kv: kv[0])),
        )

    return render


async def _prompt_repartition(
    all_languages: List[str],
    env_groups: List[environment.LanguageGroup],
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    formula: str,
) -> Optional[timing_group_picker.GroupAssignment]:
    preview = build_preview_renderer(
        timing_per_solution_per_language=timing_per_solution_per_language,
        formula=formula,
        env_groups=env_groups,
        all_languages=all_languages,
        width=console.console.size.width,
    )
    langs_with_solutions = {
        lang for lang, per_sol in timing_per_solution_per_language.items() if per_sol
    }
    return await timing_group_picker.prompt_group_assignment(
        all_languages,
        default_assignment(all_languages, env_groups),
        relatives=default_relatives(env_groups, langs_with_solutions),
        preview=preview,
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
        formula = env.timing.resolved_formula()
    env_groups = env.timing.groups

    all_languages = relevant_languages_for_estimation(
        env_languages=[lang.name for lang in env.languages],
        timing_languages=list(timing_per_solution_per_language.keys()),
    )

    repartition = None
    relatives = None
    if not auto and len(all_languages) > 1:
        picked = await _prompt_repartition(
            all_languages,
            env_groups,
            timing_per_solution_per_language,
            formula,
        )
        if picked is None:
            console.print('[error]Time limit estimation cancelled.[/error]')
            return None
        repartition = picked.numbers
        relatives = picked.relatives

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
            relatives=relatives,
        )
    except timing_groups.GroupValidationError as e:
        console.print(f'[error]Invalid language groups: {e}[/error]')
        return None

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
    share: Optional[str] = None,
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

    if share is not None:
        rec = sharing.recording_console()
        await print_run_report(
            solution_result,
            rec,
            VerificationLevel(verification),
            detailed=detailed,
            skip_printing_limits=True,
        )
        rec.print()
        rec.print(
            limits_info.build_limits_table(limits, title=f'Time limits ({profile})')
        )
        sharing.capture_and_share(rec, fmt=share, title='rbx time report')

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
