import dataclasses
import functools
import math
from fractions import Fraction
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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
    timing_config,
    timing_group_picker,
    timing_groups,
)
from rbx.box.code import find_language_name
from rbx.box.environment import VerificationLevel
from rbx.box.exception import RbxException
from rbx.box.formatting import href
from rbx.box.schema import InferenceRole, Solution
from rbx.box.solutions import (
    RunSolutionResult,
    consume_and_key_evaluation_items,
    get_inference_solutions,
    inference_role_of,
    print_run_report,
    run_solutions,
)
from rbx.grading.steps import Outcome


class MissingLowerBoundError(RbxException):
    """No measurement bounds the time limit from below.

    Reachable from ordinary YAML -- a package whose every accepted solution opts
    out of inference -- so it must read as a setter-facing message rather than a
    bare assertion.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


# Solutions are verified during estimation, but never at FULL -- which is the
# only level that turns `isDoubleTL` on (see `limits_info._get_limits_from_profile`).
_INFERENCE_VERIFICATION = VerificationLevel.ALL_SOLUTIONS

_NO_LOWER_BOUND_MESSAGE = (
    'Nothing bounds the time limit from below: no accepted solution was measured '
    'for the lower bound. At least one accepted solution must leave `inference` '
    'unset or set it to `lower`.'
)


class TimingProfile(BaseModel):
    timeLimit: int
    formula: Optional[str] = None
    multipliers: Optional[schema.TimingMultipliers] = None
    timeLimitPerLanguage: Dict[str, int] = Field(default_factory=dict)
    groups: Optional[List[schema.TimingGroupReport]] = None
    baseEstimate: Optional[schema.TimingGroupReport] = None

    def to_limits(self):
        return schema.LimitsProfile(
            timeLimit=self.timeLimit,
            formula=self.formula,
            multipliers=self.multipliers,
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
    if (
        multipliers.timeLimitToTle is not None
        and measured.upper is not None
        and measured.upper.fastest_slow is not None
    ):
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


def _pooled(
    per_solution_per_language: Dict[str, Dict[str, int]],
    languages: List[str],
) -> List[timing_groups.Measurement]:
    """Every (time, solution) measurement of the given languages, pooled."""
    pooled: List[timing_groups.Measurement] = []
    for lang in languages:
        for path, time in (per_solution_per_language.get(lang) or {}).items():
            pooled.append((time, path))
    return pooled


def _lower_timings(
    pooled: List[timing_groups.Measurement],
) -> Optional[timing_groups.GroupTimings]:
    if not pooled:
        return None
    slowest, slowest_solution = max(pooled)
    return timing_groups.GroupTimings(
        fastest=min(pooled)[0],
        slowest=slowest,
        solution_count=len(pooled),
        slowest_solution=slowest_solution,
    )


def _upper_timings(
    pooled: List[timing_groups.Measurement],
    dropped: List[str],
) -> Optional[timing_groups.UpperTimings]:
    if not pooled and not dropped:
        return None
    if not pooled:
        # Every slow solution of the group was dropped: it bounds nothing from
        # above, but the drop still belongs to this group.
        return timing_groups.UpperTimings(dropped_upper=dropped)
    fastest_slow, fastest_slow_solution = min(pooled)
    return timing_groups.UpperTimings(
        fastest_slow=fastest_slow,
        fastest_slow_solution=fastest_slow_solution,
        dropped_upper=dropped,
    )


def build_timing_profile(
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    strategy: timing_config.TimingStrategy,
    env_groups: List[environment.LanguageGroup],
    all_languages: List[str],
    slow_timing_per_solution_per_language: Optional[Dict[str, Dict[str, int]]] = None,
    dropped_upper_per_language: Optional[Dict[str, List[str]]] = None,
    repartition: Optional[Dict[str, int]] = None,
    relatives: Optional[Dict[str, environment.LanguageGroupFallback]] = None,
) -> TimingProfile:
    multipliers = strategy.multipliers
    if multipliers is not None:
        eval_fn = make_multipliers_eval(multipliers)
        derive_fn: Optional[timing_groups.DeriveFn] = make_multipliers_derive(
            multipliers
        )
    else:
        eval_fn = make_formula_eval(strategy.formula_or_die())
        derive_fn = None

    slow_per_language = slow_timing_per_solution_per_language or {}
    dropped_per_language = dropped_upper_per_language or {}

    if repartition is not None:
        groups = timing_groups.partition_from_assignment(repartition, relatives)
    else:
        groups = timing_groups.build_partition(env_groups, all_languages)
    timing_groups.validate_partition(groups)

    measured: Dict[int, timing_groups.GroupMeasurements] = {}
    all_values: List[timing_groups.Measurement] = []
    all_slow_values: List[timing_groups.Measurement] = []
    all_dropped: List[str] = []
    for idx, group in enumerate(groups):
        values = _pooled(timing_per_solution_per_language, group.languages)
        slow_values = _pooled(slow_per_language, group.languages)
        dropped = [
            path
            for lang in group.languages
            for path in (dropped_per_language.get(lang) or [])
        ]
        if not values and not slow_values and not dropped:
            continue
        measured[idx] = timing_groups.GroupMeasurements(
            lower=_lower_timings(values),
            upper=_upper_timings(slow_values, dropped),
        )
        all_values.extend(values)
        all_slow_values.extend(slow_values)
        all_dropped.extend(dropped)

    if not all_values:
        raise MissingLowerBoundError(_NO_LOWER_BOUND_MESSAGE)

    base = timing_groups.GroupMeasurements(
        lower=_lower_timings(all_values),
        upper=_upper_timings(all_slow_values, all_dropped),
    )
    result = timing_groups.resolve_groups(groups, measured, base, eval_fn, derive_fn)
    return TimingProfile(
        timeLimit=result.base_time_limit,
        formula=strategy.formula,
        multipliers=multipliers,
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
    strategy: timing_config.TimingStrategy,
    env_groups: List[environment.LanguageGroup],
    all_languages: List[str],
    slow_timing_per_solution_per_language: Optional[Dict[str, Dict[str, int]]] = None,
    dropped_upper_per_language: Optional[Dict[str, List[str]]] = None,
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
                strategy=strategy,
                env_groups=env_groups,
                all_languages=all_languages,
                slow_timing_per_solution_per_language=slow_timing_per_solution_per_language,
                dropped_upper_per_language=dropped_upper_per_language,
                repartition=assignment,
                relatives=relatives,
            )
        except timing_groups.GroupValidationError as e:
            return ANSI(
                console.capture_ansi(
                    f'[warning]⚠ Invalid grouping: {e}[/warning]', width=width
                )
            )
        except MissingLowerBoundError as e:
            # Grouping-independent, so no regrouping can fix it -- but the picker
            # must still render rather than crash under the setter's cursor.
            return ANSI(console.capture_ansi(f'[error]⚠ {e}[/error]', width=width))
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
    strategy: timing_config.TimingStrategy,
    slow_timing_per_solution_per_language: Optional[Dict[str, Dict[str, int]]] = None,
    dropped_upper_per_language: Optional[Dict[str, List[str]]] = None,
) -> Optional[timing_group_picker.GroupAssignment]:
    preview = build_preview_renderer(
        timing_per_solution_per_language=timing_per_solution_per_language,
        strategy=strategy,
        env_groups=env_groups,
        all_languages=all_languages,
        slow_timing_per_solution_per_language=slow_timing_per_solution_per_language,
        dropped_upper_per_language=dropped_upper_per_language,
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


def _describe_strategy(strategy: timing_config.TimingStrategy) -> str:
    """What the numbers in effect mean, in the setter's terms.

    The camelCase keys alone say nothing about what they do, and the absence of
    ``timeLimitToTle`` -- which means the slow solutions were never even run --
    is the single most important fact about such a run, so it is spelled out
    instead of merely omitted.
    """
    if not strategy.uses_multipliers:
        return f'Using formula: {strategy.formula_or_die()}'
    multipliers = strategy.multipliers_or_die()
    lines = [
        'Using ratios:',
        f'  the limit is at least {multipliers.acToTimeLimit}x the slowest accepted '
        f'solution (acToTimeLimit)',
    ]
    if multipliers.timeLimitToTle is not None:
        lines.append(
            f'  and at most 1/{multipliers.timeLimitToTle} of the fastest solution '
            f'expected to be too slow (timeLimitToTle); those solutions run '
            f'capped at {multipliers.inferenceTimeout} ms (inferenceTimeout)'
        )
    else:
        lines.append(
            '  and is NOT bounded from above: timeLimitToTle is unset, so the '
            'solutions expected to be too slow were not run and nothing checks '
            'that they still time out'
        )
    lines.append(
        f'  rounded up to a multiple of {multipliers.timeResolution} ms '
        f'(timeResolution)'
    )
    return '\n'.join(lines)


async def _timings_per_language(
    console: rich.console.Console,
    structured_evaluations: Dict[str, Dict[str, List]],
    solutions: List[Solution],
    skip: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, int]]:
    """Each solution's measured time -- the maximum over its testcases -- keyed
    by language and then by solution path. Solutions in ``skip`` are not
    measured at all: their runs were truncated, so their timings mean nothing."""
    skip = skip or set()
    per_language: Dict[str, Dict[str, int]] = {}
    for solution in solutions:
        if str(solution.path) in skip:
            continue
        timings = []
        for evals in structured_evaluations.get(str(solution.path), {}).values():
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

        lang = find_language_name(solution)
        per_language.setdefault(lang, {})[str(solution.path)] = max(timings)
    return per_language


def _flatten(per_language: Dict[str, Dict[str, int]]) -> List[int]:
    return [
        time for per_solution in per_language.values() for time in per_solution.values()
    ]


async def estimate_time_limit(
    console: rich.console.Console,
    result: RunSolutionResult,
    strategy: Optional[timing_config.TimingStrategy] = None,
    auto: bool = False,
    dropped_upper_per_language: Optional[Dict[str, List[str]]] = None,
) -> Optional[TimingProfile]:
    if not result.skeleton.solutions:
        console.print('[error]No solutions to estimate time limit from.[/error]')
        return None

    structured_evaluations = consume_and_key_evaluation_items(
        result.items, result.skeleton
    )

    # The run may carry both roles; each bounds a different side of the limit.
    lower_solutions = [
        solution
        for solution in result.skeleton.solutions
        if inference_role_of(solution) == InferenceRole.LOWER
    ]
    upper_solutions = [
        solution
        for solution in result.skeleton.solutions
        if inference_role_of(solution) == InferenceRole.UPPER
    ]
    if not lower_solutions:
        # Knowable from `problem.rbx.yml` alone and fixable only there, so fail
        # before the setter navigates a picker in which no grouping can succeed.
        raise MissingLowerBoundError(_NO_LOWER_BOUND_MESSAGE)

    dropped_upper_per_language = dropped_upper_per_language or {}
    dropped_paths = {
        path for paths in dropped_upper_per_language.values() for path in paths
    }

    timing_per_solution_per_language = await _timings_per_language(
        console, structured_evaluations, lower_solutions
    )
    slow_timing_per_solution_per_language = await _timings_per_language(
        console, structured_evaluations, upper_solutions, skip=dropped_paths
    )

    console.rule('[status]Time report[/status]', style='status')

    # Only the lower-bound measurements: the limit is computed from them, so
    # pooling the slow ones in here would headline a number -- typically a slow
    # solution sitting at the cap -- that no limit on screen derives from.
    lower_timings = _flatten(timing_per_solution_per_language)
    slow_timings = _flatten(slow_timing_per_solution_per_language)
    if not lower_timings:
        console.print('[error]No timings collected from solutions.[/error]')
        return None

    fastest_time = min(lower_timings)
    slowest_time = max(lower_timings)
    console.print(f'Fastest solution: {fastest_time} ms')
    console.print(f'Slowest solution: {slowest_time} ms')
    if slow_timings:
        console.print(
            f'Fastest solution expected to be too slow: {min(slow_timings)} ms'
        )

    env = environment.get_environment()
    if strategy is None:
        strategy = timing_config.resolve_strategy(
            env.timing, package.find_problem_package_or_die().timing
        )
    env_groups = env.timing.groups

    all_languages = relevant_languages_for_estimation(
        env_languages=[lang.name for lang in env.languages],
        # A language may show up on the slow side only (or only as a drop); it
        # still needs a group, or its cap would be pooled nowhere.
        timing_languages=list(
            OrderedSet(
                [
                    *timing_per_solution_per_language,
                    *slow_timing_per_solution_per_language,
                    *dropped_upper_per_language,
                ]
            )
        ),
    )

    repartition = None
    relatives = None
    if not auto and len(all_languages) > 1:
        picked = await _prompt_repartition(
            all_languages,
            env_groups,
            timing_per_solution_per_language,
            strategy,
            slow_timing_per_solution_per_language=slow_timing_per_solution_per_language,
            dropped_upper_per_language=dropped_upper_per_language,
        )
        if picked is None:
            console.print('[error]Time limit estimation cancelled.[/error]')
            return None
        repartition = picked.numbers
        relatives = picked.relatives

    console.print()
    console.rule('[status]Time estimation[/status]', style='status')
    console.print(_describe_strategy(strategy))

    try:
        profile = build_timing_profile(
            timing_per_solution_per_language=timing_per_solution_per_language,
            strategy=strategy,
            env_groups=env_groups,
            all_languages=all_languages,
            slow_timing_per_solution_per_language=slow_timing_per_solution_per_language,
            dropped_upper_per_language=dropped_upper_per_language,
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


@dataclasses.dataclass(frozen=True)
class _InferenceCap:
    """The cap a capped estimation run enforced, with the ratio that justifies it.

    Its presence *is* the answer to "was this run capped?", so no caller has to
    re-derive that from a timelimit override or re-narrow an optional
    multipliers block.
    """

    timeout: int
    time_limit_to_tle: float

    @property
    def largest_bounded_limit(self) -> int:
        """The largest limit a solution stopped at the cap could still justify.
        Above it, the cap -- not the solution -- is what bounded the estimate."""
        return math.floor(self.timeout / _exact(self.time_limit_to_tle))


@dataclasses.dataclass
class _InferenceDiagnosis:
    """What the capped estimation run says about the solutions it measured."""

    # Slow solutions killed at the cap: measured, but bounding nothing.
    dropped_upper: List[Solution] = dataclasses.field(default_factory=list)
    # Slow solutions that failed for a reason other than running out of time,
    # with the verdict that says so. Their timings are meaningless.
    failed_upper: List[Tuple[Solution, Outcome]] = dataclasses.field(
        default_factory=list
    )
    # Accepted solutions killed at the cap: the estimate would rest on a
    # truncated measurement.
    truncated_lower: List[Solution] = dataclasses.field(default_factory=list)


async def _diagnose_inference_run(result: RunSolutionResult) -> _InferenceDiagnosis:
    structured_evaluations = consume_and_key_evaluation_items(
        result.items, result.skeleton
    )
    diagnosis = _InferenceDiagnosis()
    for solution in result.skeleton.solutions:
        role = inference_role_of(solution)
        if role is None:
            continue
        outcomes: List[Outcome] = []
        for evals in structured_evaluations.get(str(solution.path), {}).values():
            for ev in evals:
                if ev is None:
                    continue
                outcomes.append((await ev()).result.outcome)
        timed_out = any(outcome.is_slow() for outcome in outcomes)
        broken = [
            outcome
            for outcome in outcomes
            if outcome != Outcome.ACCEPTED and not outcome.is_slow()
        ]
        if role == InferenceRole.UPPER:
            if broken:
                diagnosis.failed_upper.append((solution, broken[0]))
            elif timed_out:
                diagnosis.dropped_upper.append(solution)
        elif timed_out:
            diagnosis.truncated_lower.append(solution)
    return diagnosis


def _failed_upper_message(solution: Solution, outcome: Outcome) -> str:
    """Diagnostic (3). A crash or a wrong answer leaves no timing evidence either
    way, so both are errors -- but a solution that declared it might crash did
    exactly what the setter said it would, and must not be accused of a bug it
    does not have.

    Note that `inference: false` excludes the solution from the estimation run
    altogether: it is not run, not merely unused.
    """
    if any(
        expectation.match(outcome) for expectation in solution.all_expected_outcomes()
    ):
        return (
            f'[error]✗ {solution.href()} finished with [item]{outcome.value}[/item], '
            f'which is what its expectation declares -- but a solution that stops '
            f'early leaves no evidence of how long it would have run, so it cannot '
            f'bound the time limit from above. Set [item]inference: false[/item] on '
            f'it to leave it out of the estimation run, or expect '
            f'[item]tle[/item] if it is genuinely meant to run out of time.[/error]'
        )
    return (
        f'[error]✗ {solution.href()} failed with [item]{outcome.value}[/item] '
        f'instead of running out of time, so how long it ran says nothing about '
        f'the time limit. Fix the solution, or set [item]inference: false[/item] '
        f'on it to leave it out of the estimation run.[/error]'
    )


def _report_inference_diagnosis(
    diagnosis: _InferenceDiagnosis, cap: _InferenceCap
) -> bool:
    """Print what the run says about each solution; return whether the estimate
    may proceed."""
    for solution in diagnosis.dropped_upper:
        console.console.print(
            f'[warning]⚠ {solution.href()} was still running at the inference '
            f'timeout of {cap.timeout} ms, so it does not bound the time limit '
            f'from above.[/warning]'
        )
    for solution, outcome in diagnosis.failed_upper:
        console.console.print(_failed_upper_message(solution, outcome))
    for solution in diagnosis.truncated_lower:
        console.console.print(
            f'[error]✗ {solution.href()} was still running at the inference '
            f'timeout of {cap.timeout} ms, so its measured time is truncated and '
            f'cannot bound the time limit from below. Raise '
            f'[item]inferenceTimeout[/item], or speed the solution up.[/error]'
        )
    return not diagnosis.failed_upper and not diagnosis.truncated_lower


def _warn_if_the_cap_bounded_the_estimate(
    estimated: TimingProfile,
    cap: _InferenceCap,
    dropped: List[Solution],
) -> None:
    """Diagnostic (2): something was dropped at the cap AND the resolved limit is
    above what the cap alone allows, so the cap -- not the slow solutions -- is
    what bounded the estimate.

    The drops themselves were reported before the run report and the estimation
    tables, far enough up to have scrolled away, so they are named again here.
    """
    if not dropped:
        return
    resolved = max([estimated.timeLimit, *estimated.timeLimitPerLanguage.values()])
    if resolved <= cap.largest_bounded_limit:
        return
    names = ', '.join(solution.href() for solution in dropped)
    console.console.print(
        f'[warning]⚠ The upper bound of this estimate is not trustworthy: '
        f'{names} stopped at the inference timeout of {cap.timeout} ms, and the '
        f'resolved limit of {resolved} ms is above the '
        f'{cap.largest_bounded_limit} ms that timeout allows on its own '
        f'(inferenceTimeout / timeLimitToTle). The cap, not the slow solutions, '
        f'is what bounded the estimate -- raise [item]inferenceTimeout[/item] to '
        f'measure them for real.[/warning]'
    )


@dataclasses.dataclass
class _InferenceRun:
    """A finished estimation run, ready to be estimated from."""

    result: RunSolutionResult
    strategy: timing_config.TimingStrategy
    # The cap this run enforced, or None when it ran unbounded.
    cap: Optional[_InferenceCap] = None
    # Slow solutions the cap stopped, so they measure nothing usable.
    dropped_upper: List[Solution] = dataclasses.field(default_factory=list)

    def dropped_upper_per_language(self) -> Dict[str, List[str]]:
        per_language: Dict[str, List[str]] = {}
        for solution in self.dropped_upper:
            per_language.setdefault(find_language_name(solution), []).append(
                str(solution.path)
            )
        return per_language


def _resolve_inference_strategy(
    formula: Optional[str],
) -> timing_config.TimingStrategy:
    # A formula passed in here is the CLI's custom-formula escape hatch: it forces
    # the formula path for this run regardless of what the environment configures.
    if formula is not None:
        return timing_config.TimingStrategy(formula=formula)
    return timing_config.resolve_strategy(
        environment.get_environment().timing,
        package.find_problem_package_or_die().timing,
    )


async def _run_for_inference(
    check: bool,
    detailed: bool,
    runs: int,
    formula: Optional[str],
) -> Optional[_InferenceRun]:
    """Run the solutions the time limit is inferred from, report them, and say
    what their verdicts mean. ``None`` when the estimate must not proceed."""
    strategy = _resolve_inference_strategy(formula)
    multipliers = strategy.multipliers

    lower_solutions = get_inference_solutions(InferenceRole.LOWER)
    if not lower_solutions:
        # Knowable from `problem.rbx.yml` alone, so say so before running
        # anything: no run and no grouping could rescue the estimate.
        raise MissingLowerBoundError(_NO_LOWER_BOUND_MESSAGE)

    upper_solutions: List[Solution] = []
    cap: Optional[_InferenceCap] = None
    if multipliers is not None and multipliers.timeLimitToTle is not None:
        # The slow solutions are only worth running when their timings bound
        # something, and they only terminate under a cap.
        upper_solutions = get_inference_solutions(InferenceRole.UPPER)
        if upper_solutions:
            cap = _InferenceCap(
                timeout=multipliers.inferenceTimeout,
                time_limit_to_tle=multipliers.timeLimitToTle,
            )
        # With no slow solution there is nothing to bound the limit from above,
        # so the cap would buy nothing and only add a way for a legitimately
        # slow accepted solution to fail the estimate.

    status = (
        'Running solutions for time estimation...'
        if upper_solutions
        else 'Running ACCEPTED solutions...'
    )
    with utils.StatusProgress(status) as s:
        tracked_solutions = OrderedSet(
            str(solution.path) for solution in [*lower_solutions, *upper_solutions]
        )
        result = await run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            # ALL_SOLUTIONS keeps `isDoubleTL` off (only FULL turns it on):
            # doubling the limit here would double the very cap that exists to
            # bound the solutions running under it.
            verification=_INFERENCE_VERIFICATION,
            timelimit_override=cap.timeout if cap is not None else -1,
            nruns=runs,
        )

    console.console.print()
    console.console.rule(
        '[status]Run report (for time estimation)[/status]', style='status'
    )
    ok = await print_run_report(
        result,
        console.console,
        _INFERENCE_VERIFICATION,
        detailed=detailed,
        skip_printing_limits=True,
        # An upper-bound solution is *supposed* to hit the cap, so only the
        # solutions that bound the limit from below decide whether the run
        # succeeded.
        gating_solutions={str(solution.path) for solution in lower_solutions},
    )

    dropped_upper: List[Solution] = []
    if cap is not None:
        diagnosis = await _diagnose_inference_run(result)
        if not _report_inference_diagnosis(diagnosis, cap):
            return None
        dropped_upper = diagnosis.dropped_upper

    if not ok:
        console.console.print(
            '[error]Failed to run ACCEPTED solutions, so cannot estimate a reliable time limit.[/error]'
        )
        return None

    return _InferenceRun(
        result=result, strategy=strategy, cap=cap, dropped_upper=dropped_upper
    )


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

    run = await _run_for_inference(
        check=check, detailed=detailed, runs=runs, formula=formula
    )
    if run is None:
        return None

    estimated_tl = await estimate_time_limit(
        console.console,
        run.result,
        run.strategy,
        auto=auto,
        dropped_upper_per_language=run.dropped_upper_per_language(),
    )
    if estimated_tl is None:
        return None

    if run.cap is not None:
        _warn_if_the_cap_bounded_the_estimate(estimated_tl, run.cap, run.dropped_upper)

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
            run.result,
            rec,
            _INFERENCE_VERIFICATION,
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
