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
    timing_validation,
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


def _as_eval_result(bounds: TimingBounds, time_limit: int) -> timing_groups.EvalResult:
    """The estimated limit together with the bounds that produced it, so the
    group report can record them without computing them a second time."""
    return timing_groups.EvalResult(
        time_limit=time_limit,
        # A derived lower bound names no solution: it is the limit of the group
        # this one derives from, not a measurement of its own.
        lower_bound=schema.TimingBound(
            value=bounds.lower, solution=bounds.lower_solution
        ),
        upper_bound=(
            None
            if bounds.upper is None
            else schema.TimingBound(value=bounds.upper, solution=bounds.upper_solution)
        ),
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
    force: bool = False,
) -> int:
    """Return the quantized limit if the group's slow solutions allow it, else
    raise naming the binding solution on each side and the knob to turn.

    ``force`` keeps the limit anyway, for a setter who has seen the violation and
    decided to accept it. The violation is not swallowed: the bounds it breaks
    stay on the group report, so the profile records what was overridden.
    """
    if bounds.fits or force:
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
    force: bool = False,
) -> timing_groups.EvalFn:
    """Estimator that bounds the limit from below by the group's accepted
    solutions, quantizes it to ``timeResolution``, and checks it against the
    upper bound its slow solutions impose. ``force`` keeps a limit that fails
    that check."""

    def _eval(measured: timing_groups.GroupMeasurements) -> timing_groups.EvalResult:
        bounds = compute_bounds(multipliers, measured)
        return _as_eval_result(
            bounds, _check_bounds(bounds, multipliers, measured, force=force)
        )

    return _eval


def make_multipliers_derive(
    multipliers: schema.TimingMultipliers,
    force: bool = False,
) -> timing_groups.DeriveFn:
    """Post-processor for a limit that did NOT come from the group's own accepted
    solutions: it is quantized to ``timeResolution`` and still checked against
    the group's own upper bound."""

    def _derive(
        tl: int, measured: timing_groups.GroupMeasurements
    ) -> timing_groups.EvalResult:
        bounds = compute_bounds(multipliers, measured, derived_from=tl)
        return _as_eval_result(
            bounds, _check_bounds(bounds, multipliers, measured, force=force)
        )

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
    confirmed: List[str],
    skipped: Optional[List[str]] = None,
) -> Optional[timing_groups.UpperTimings]:
    """The upper-bound evidence for one group.

    ``pooled`` holds the slow solutions that finished under the limit they were
    probed at, so every one of them violates the bound; ``confirmed`` holds the
    ones that did not finish, which is the outcome the estimate needs.
    """
    skipped = skipped or []
    if not pooled and not confirmed and not skipped:
        return None
    if not pooled:
        # No slow solution of the group was measured: it bounds nothing from
        # above, but the outcome still belongs to this group.
        return timing_groups.UpperTimings(
            confirmed_upper=confirmed, skipped_upper=skipped
        )
    fastest_slow, fastest_slow_solution = min(pooled)
    return timing_groups.UpperTimings(
        fastest_slow=fastest_slow,
        fastest_slow_solution=fastest_slow_solution,
        confirmed_upper=confirmed,
        violating_upper=sorted(pooled),
        skipped_upper=skipped,
    )


def build_timing_profile(
    timing_per_solution_per_language: Dict[str, Dict[str, int]],
    strategy: timing_config.TimingStrategy,
    env_groups: List[environment.LanguageGroup],
    all_languages: List[str],
    slow_timing_per_solution_per_language: Optional[Dict[str, Dict[str, int]]] = None,
    confirmed_upper_per_language: Optional[Dict[str, List[str]]] = None,
    skipped_upper_per_language: Optional[Dict[str, List[str]]] = None,
    repartition: Optional[Dict[str, int]] = None,
    relatives: Optional[Dict[str, environment.LanguageGroupFallback]] = None,
    force: bool = False,
) -> TimingProfile:
    multipliers = strategy.multipliers
    if multipliers is not None:
        eval_fn = make_multipliers_eval(multipliers, force=force)
        derive_fn: Optional[timing_groups.DeriveFn] = make_multipliers_derive(
            multipliers, force=force
        )
    else:
        eval_fn = make_formula_eval(strategy.formula_or_die())
        derive_fn = None

    slow_per_language = slow_timing_per_solution_per_language or {}
    confirmed_per_language = confirmed_upper_per_language or {}
    skipped_per_language = skipped_upper_per_language or {}

    if repartition is not None:
        groups = timing_groups.partition_from_assignment(repartition, relatives)
    else:
        groups = timing_groups.build_partition(env_groups, all_languages)
    timing_groups.validate_partition(groups)

    measured: Dict[int, timing_groups.GroupMeasurements] = {}
    all_values: List[timing_groups.Measurement] = []
    all_slow_values: List[timing_groups.Measurement] = []
    all_confirmed: List[str] = []
    all_skipped: List[str] = []
    for idx, group in enumerate(groups):
        values = _pooled(timing_per_solution_per_language, group.languages)
        slow_values = _pooled(slow_per_language, group.languages)
        confirmed = [
            path
            for lang in group.languages
            for path in (confirmed_per_language.get(lang) or [])
        ]
        skipped = [
            path
            for lang in group.languages
            for path in (skipped_per_language.get(lang) or [])
        ]
        if not values and not slow_values and not confirmed and not skipped:
            continue
        measured[idx] = timing_groups.GroupMeasurements(
            lower=_lower_timings(values),
            upper=_upper_timings(slow_values, confirmed, skipped),
        )
        all_values.extend(values)
        all_slow_values.extend(slow_values)
        all_confirmed.extend(confirmed)
        all_skipped.extend(skipped)

    if not all_values:
        raise MissingLowerBoundError(_NO_LOWER_BOUND_MESSAGE)

    base = timing_groups.GroupMeasurements(
        lower=_lower_timings(all_values),
        upper=_upper_timings(all_slow_values, all_confirmed, all_skipped),
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
    confirmed_upper_per_language: Optional[Dict[str, List[str]]] = None,
    skipped_upper_per_language: Optional[Dict[str, List[str]]] = None,
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
                confirmed_upper_per_language=confirmed_upper_per_language,
                skipped_upper_per_language=skipped_upper_per_language,
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
    confirmed_upper_per_language: Optional[Dict[str, List[str]]] = None,
    skipped_upper_per_language: Optional[Dict[str, List[str]]] = None,
    allow_force: bool = False,
) -> Optional[timing_group_picker.GroupAssignment]:
    preview = build_preview_renderer(
        timing_per_solution_per_language=timing_per_solution_per_language,
        strategy=strategy,
        env_groups=env_groups,
        all_languages=all_languages,
        slow_timing_per_solution_per_language=slow_timing_per_solution_per_language,
        confirmed_upper_per_language=confirmed_upper_per_language,
        skipped_upper_per_language=skipped_upper_per_language,
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
        allow_force=allow_force,
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
    cap_line = (
        f'  every solution runs capped at {strategy.inferenceTimeout} ms '
        f'(inferenceTimeout)'
    )
    if not strategy.uses_multipliers:
        return f'Using formula: {strategy.formula_or_die()}\n{cap_line}'
    multipliers = strategy.multipliers_or_die()
    lines = [
        'Using ratios:',
        f'  the limit is at least {multipliers.acToTimeLimit}x the slowest accepted '
        f'solution (acToTimeLimit)',
    ]
    if multipliers.timeLimitToTle is not None:
        lines.append(
            f'  and at most 1/{multipliers.timeLimitToTle} of the fastest solution '
            f'expected to be too slow (timeLimitToTle)'
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
    lines.append(cap_line)
    return '\n'.join(lines)


def describe_strategy_briefly(strategy: timing_config.TimingStrategy) -> str:
    """The strategy in effect on a single line, to complete a sentence like
    "Estimate time limits ...".

    The full block ``_describe_strategy`` prints does not fit a menu entry, and
    re-deriving the prose at the call site is how the two drift apart.
    """
    if not strategy.uses_multipliers:
        return f'based on the formula {strategy.formula_or_die()}'
    multipliers = strategy.multipliers_or_die()
    ratios = f'acToTimeLimit {multipliers.acToTimeLimit}'
    if multipliers.timeLimitToTle is not None:
        ratios += f' and timeLimitToTle {multipliers.timeLimitToTle}'
    else:
        ratios += ' and no upper bound'
    return f'with ratios {ratios}, rounded up to {multipliers.timeResolution} ms'


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
                # A skipped testcase never ran, so it measures nothing. The
                # exclusion rests on the verdict rather than on the absent time:
                # a skipped run is the consequence of an earlier failure, and
                # nothing its log happens to carry says anything about timing.
                if ev.result.outcome == Outcome.SKIPPED:
                    continue
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


@dataclasses.dataclass(frozen=True)
class _SlowEvidence:
    """What is known about the slow solutions, pooled by language.

    Three disjoint buckets, because they mean three different things to the
    estimate: a measured solution bounds the limit from above, a confirmed one
    respects whatever bound it was checked against, and a skipped one was never
    asked.
    """

    measured: Dict[str, Dict[str, int]]
    confirmed: Dict[str, List[str]]
    skipped: Dict[str, List[str]]

    @property
    def languages(self) -> List[str]:
        return list(OrderedSet([*self.measured, *self.confirmed, *self.skipped]))


@dataclasses.dataclass(frozen=True)
class _Picked:
    """How the setter answered the grouping question.

    ``assignment`` is None when nothing was asked -- ``--auto``, or a problem
    with a single language -- and the environment's own partition stands.
    """

    assignment: Optional[timing_group_picker.GroupAssignment]
    force: bool = False

    @property
    def numbers(self) -> Optional[Dict[str, int]]:
        return self.assignment.numbers if self.assignment is not None else None

    @property
    def relatives(self) -> Optional[Dict[str, environment.LanguageGroupFallback]]:
        return self.assignment.relatives if self.assignment is not None else None


@dataclasses.dataclass
class _EstimationContext:
    """Phase 1's measurements, ready to be estimated from repeatedly.

    The picker may be re-entered once the validation phase has something to say,
    so everything that does not change between iterations is computed once. What
    does change is the evidence about the slow solutions, which is read out of
    the knowledge passed in at each call.
    """

    console: rich.console.Console
    strategy: timing_config.TimingStrategy
    env_groups: List[environment.LanguageGroup]
    all_languages: List[str]
    lower_timings: Dict[str, Dict[str, int]]
    upper_solutions: List[Solution]

    @property
    def can_prompt(self) -> bool:
        """Whether there is a grouping decision for the setter to make."""
        return len(self.all_languages) > 1

    def slow_evidence(self, knowledge: timing_validation.SlowKnowledge):
        measured: Dict[str, Dict[str, int]] = {}
        confirmed: Dict[str, List[str]] = {}
        skipped: Dict[str, List[str]] = {}
        for solution in self.upper_solutions:
            lang = find_language_name(solution)
            path = str(solution.path)
            time = knowledge.measured_time(path)
            if time is not None:
                measured.setdefault(lang, {})[path] = time
            elif knowledge.is_confirmed(path):
                confirmed.setdefault(lang, []).append(path)
            else:
                skipped.setdefault(lang, []).append(path)
        return _SlowEvidence(measured=measured, confirmed=confirmed, skipped=skipped)

    async def prompt(
        self,
        auto: bool,
        knowledge: timing_validation.SlowKnowledge,
        allow_force: bool = False,
    ) -> Optional[_Picked]:
        """Ask how to group the languages, or answer for the setter when there
        is nothing to ask. ``None`` when the setter cancelled."""
        if auto or not self.can_prompt:
            # Nothing was picked, so the environment's own partition stands.
            return _Picked(assignment=None)
        evidence = self.slow_evidence(knowledge)
        assignment = await _prompt_repartition(
            self.all_languages,
            self.env_groups,
            self.lower_timings,
            self.strategy,
            slow_timing_per_solution_per_language=evidence.measured,
            confirmed_upper_per_language=evidence.confirmed,
            skipped_upper_per_language=evidence.skipped,
            allow_force=allow_force,
        )
        if assignment is None:
            return None
        return _Picked(assignment=assignment, force=assignment.force)

    def build(
        self,
        picked: _Picked,
        knowledge: timing_validation.SlowKnowledge,
        force: bool = False,
        announce: bool = True,
    ) -> Optional[TimingProfile]:
        """The profile this grouping produces, or ``None`` when no limit fits."""
        evidence = self.slow_evidence(knowledge)
        if announce:
            self.console.print()
            self.console.rule('[status]Time estimation[/status]', style='status')
            self.console.print(_describe_strategy(self.strategy))

        try:
            profile = build_timing_profile(
                timing_per_solution_per_language=self.lower_timings,
                strategy=self.strategy,
                env_groups=self.env_groups,
                all_languages=self.all_languages,
                slow_timing_per_solution_per_language=evidence.measured,
                confirmed_upper_per_language=evidence.confirmed,
                skipped_upper_per_language=evidence.skipped,
                repartition=picked.numbers,
                relatives=picked.relatives,
                force=force or picked.force,
            )
        except timing_groups.GroupValidationError as e:
            self.console.print(f'[error]Invalid language groups: {e}[/error]')
            return None

        defaulted = [
            lang
            for report in (profile.groups or [])
            if report.origin == schema.TimingGroupOrigin.DEFAULTED
            for lang in report.languages
        ]
        if defaulted:
            self.console.print(
                '[warning]⚠ The following languages have no solution and no whenEmpty '
                f'rule, so they fall back to the base time limit of {profile.timeLimit} '
                f'ms: {", ".join(defaulted)}.[/warning]'
            )
        return profile


async def build_estimation_context(
    console: rich.console.Console,
    result: RunSolutionResult,
    strategy: Optional[timing_config.TimingStrategy] = None,
    upper_solutions: Optional[List[Solution]] = None,
    knowledge: Optional[timing_validation.SlowKnowledge] = None,
) -> Optional[_EstimationContext]:
    """Measure what the estimation run produced and report it.

    ``upper_solutions`` names the solutions expected to be too slow, which the
    estimation run does not include; it defaults to any the result happens to
    carry. Measurements the result holds for them seed ``knowledge``, so a caller
    that already ran them does not run them again.
    """
    if not result.skeleton.solutions:
        console.print('[error]No solutions to estimate time limit from.[/error]')
        return None

    structured_evaluations = consume_and_key_evaluation_items(
        result.items, result.skeleton
    )

    lower_solutions = [
        solution
        for solution in result.skeleton.solutions
        if inference_role_of(solution) == InferenceRole.LOWER
    ]
    if not lower_solutions:
        # Knowable from `problem.rbx.yml` alone and fixable only there, so fail
        # before the setter navigates a picker in which no grouping can succeed.
        raise MissingLowerBoundError(_NO_LOWER_BOUND_MESSAGE)

    if upper_solutions is None:
        upper_solutions = [
            solution
            for solution in result.skeleton.solutions
            if inference_role_of(solution) == InferenceRole.UPPER
        ]

    lower_timings = await _timings_per_language(
        console, structured_evaluations, lower_solutions
    )

    # Anything the result already measured for a slow solution is knowledge, so
    # the validation phase does not ask a question it can already answer.
    seeded = await _timings_per_language(
        console,
        structured_evaluations,
        [
            solution
            for solution in upper_solutions
            if str(solution.path) in structured_evaluations
        ],
    )
    if knowledge is not None:
        for per_solution in seeded.values():
            for path, time in per_solution.items():
                knowledge.record_time(path, time)

    console.rule('[status]Time report[/status]', style='status')

    # Only the lower-bound measurements: the limit is computed from them, so
    # pooling the slow ones in here would headline a number that no limit on
    # screen derives from.
    lower_flat = _flatten(lower_timings)
    if not lower_flat:
        console.print('[error]No timings collected from solutions.[/error]')
        return None

    console.print(f'Fastest solution: {min(lower_flat)} ms')
    console.print(f'Slowest solution: {max(lower_flat)} ms')
    slow_flat = _flatten(seeded)
    if slow_flat:
        console.print(f'Fastest solution expected to be too slow: {min(slow_flat)} ms')

    env = environment.get_environment()
    if strategy is None:
        strategy = timing_config.resolve_strategy(
            env.timing, package.find_problem_package_or_die().timing
        )

    all_languages = relevant_languages_for_estimation(
        env_languages=[lang.name for lang in env.languages],
        # A language may show up on the slow side only; it still needs a group,
        # or its solutions would be pooled nowhere.
        timing_languages=list(
            OrderedSet(
                [
                    *lower_timings,
                    *(find_language_name(solution) for solution in upper_solutions),
                ]
            )
        ),
    )

    return _EstimationContext(
        console=console,
        strategy=strategy,
        env_groups=env.timing.groups,
        all_languages=all_languages,
        lower_timings=lower_timings,
        upper_solutions=upper_solutions,
    )


async def estimate_time_limit(
    console: rich.console.Console,
    result: RunSolutionResult,
    strategy: Optional[timing_config.TimingStrategy] = None,
    auto: bool = False,
) -> Optional[TimingProfile]:
    """One estimate from one run, with no validation phase behind it."""
    knowledge = timing_validation.SlowKnowledge()
    ctx = await build_estimation_context(console, result, strategy, knowledge=knowledge)
    if ctx is None:
        return None
    picked = await ctx.prompt(auto=auto, knowledge=knowledge)
    if picked is None:
        console.print('[error]Time limit estimation cancelled.[/error]')
        return None
    return ctx.build(picked, knowledge=knowledge)


@dataclasses.dataclass
class _InferenceDiagnosis:
    """What the capped estimation run says about the solutions it measured."""

    # Accepted solutions killed at the cap: the estimate would rest on a
    # truncated measurement.
    truncated_lower: List[Solution] = dataclasses.field(default_factory=list)


async def _diagnose_inference_run(result: RunSolutionResult) -> _InferenceDiagnosis:
    structured_evaluations = consume_and_key_evaluation_items(
        result.items, result.skeleton
    )
    diagnosis = _InferenceDiagnosis()
    for solution in result.skeleton.solutions:
        if inference_role_of(solution) != InferenceRole.LOWER:
            continue
        outcomes: List[Outcome] = []
        for evals in structured_evaluations.get(str(solution.path), {}).values():
            for ev in evals:
                if ev is None:
                    continue
                outcome = (await ev()).result.outcome
                # A skipped testcase is the CONSEQUENCE of an earlier verdict,
                # never evidence of its own. SKIPPED is both non-accepted and
                # non-slow, so counting it would classify every aborted run as a
                # solution that broke for a non-timing reason -- fatal -- and
                # would mask the timeout that actually stopped it.
                if outcome == Outcome.SKIPPED:
                    continue
                outcomes.append(outcome)
        if any(outcome.is_slow() for outcome in outcomes):
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


def _report_inference_diagnosis(diagnosis: _InferenceDiagnosis, timeout: int) -> bool:
    """Print what the run says about each solution; return whether the estimate
    may proceed."""
    for solution in diagnosis.truncated_lower:
        console.console.print(
            f'[error]✗ {solution.href()} was still running at the inference '
            f'timeout of {timeout} ms, so its measured time is truncated and '
            f'cannot bound the time limit from below. Raise '
            f'[item]inferenceTimeout[/item], or speed the solution up.[/error]'
        )
    return not diagnosis.truncated_lower


@dataclasses.dataclass
class _InferenceRun:
    """A finished estimation run, ready to be estimated from."""

    result: RunSolutionResult
    strategy: timing_config.TimingStrategy
    # The cap this run enforced. Always present: every run is capped.
    timeout: int


def _resolve_inference_strategy(
    formula: Optional[str],
) -> timing_config.TimingStrategy:
    env_timing = environment.get_environment().timing
    package_timing = package.find_problem_package_or_die().timing
    # A formula passed in here is the CLI's custom-formula escape hatch: it forces
    # the formula path for this run regardless of what the environment configures.
    # The cap is not part of that escape hatch -- it still comes from the config.
    if formula is not None:
        return timing_config.TimingStrategy(
            formula=formula,
            inferenceTimeout=timing_config.resolve_inference_timeout(
                env_timing, package_timing
            ),
        )
    return timing_config.resolve_strategy(env_timing, package_timing)


async def _run_for_inference(
    check: bool,
    detailed: bool,
    runs: int,
    formula: Optional[str],
) -> Optional[_InferenceRun]:
    """Run the solutions the time limit is inferred from, report them, and say
    what their verdicts mean. ``None`` when the estimate must not proceed."""
    strategy = _resolve_inference_strategy(formula)

    lower_solutions = get_inference_solutions(InferenceRole.LOWER)
    if not lower_solutions:
        # Knowable from `problem.rbx.yml` alone, so say so before running
        # anything: no run and no grouping could rescue the estimate.
        raise MissingLowerBoundError(_NO_LOWER_BOUND_MESSAGE)

    # The solutions expected to be too slow are NOT run here. Nothing bounds how
    # long they take, so the only limit that could terminate them is the cap --
    # which is set for the accepted solutions and says nothing about the limit
    # they are meant to bound. They are checked in the validation phase instead,
    # against the limit this run estimates.
    timeout = strategy.inferenceTimeout

    with utils.StatusProgress('Running ACCEPTED solutions...') as s:
        tracked_solutions = OrderedSet(
            str(solution.path) for solution in lower_solutions
        )
        result = await run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            # ALL_SOLUTIONS keeps `isDoubleTL` off (only FULL turns it on):
            # doubling the limit here would double the very cap that exists to
            # bound the solutions running under it.
            verification=_INFERENCE_VERIFICATION,
            timelimit_override=timeout,
            nruns=runs,
            # An accepted solution killed at the cap fails the estimate outright,
            # so its remaining tests only cost wall clock.
            abort_on=lambda ctx: ctx.evaluation.result.outcome.is_slow(),
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
        gating_solutions={str(solution.path) for solution in lower_solutions},
    )

    diagnosis = await _diagnose_inference_run(result)
    if not _report_inference_diagnosis(diagnosis, timeout):
        return None

    if not ok:
        console.console.print(
            '[error]Failed to run ACCEPTED solutions, so cannot estimate a reliable time limit.[/error]'
        )
        return None

    return _InferenceRun(result=result, strategy=strategy, timeout=timeout)


def violates_upper_bound(time: int, time_limit: int, time_limit_to_tle: float) -> bool:
    """Whether a slow solution taking ``time`` is too fast for ``time_limit``.

    The same comparison `compute_bounds` makes, in the same exact arithmetic:
    the limit may be at most ``time / timeLimitToTle``, so the solution must take
    at least ``time_limit * timeLimitToTle``.
    """
    return time < time_limit * _exact(time_limit_to_tle)


def can_validate_upper_bound(
    profile: TimingProfile, upper_solutions: List[Solution]
) -> bool:
    """Whether this estimate has an upper bound to check, and something to check
    it against. Without ``timeLimitToTle`` the limit is not bounded from above at
    all, so the slow solutions are not run."""
    multipliers = profile.multipliers
    return (
        multipliers is not None
        and multipliers.timeLimitToTle is not None
        and bool(upper_solutions)
    )


@dataclasses.dataclass
class _ValidationOutcome:
    """What checking an estimate against its slow solutions found."""

    # Confirmed too slow: still running when the limit they had to clear elapsed.
    confirmed: List[Solution] = dataclasses.field(default_factory=list)
    # Fast enough to break the upper bound, with the time they actually took.
    violating: List[Tuple[Solution, int]] = dataclasses.field(default_factory=list)
    # Broke for a reason other than running out of time, so they are evidence of
    # nothing either way.
    failed: List[Tuple[Solution, Outcome]] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violating and not self.failed


def _probe_limits(
    profile: TimingProfile,
    upper_solutions: List[Solution],
) -> Dict[str, int]:
    """The limit each language's slow solutions have to survive."""
    multipliers = profile.multipliers
    assert multipliers is not None and multipliers.timeLimitToTle is not None
    limits: Dict[str, int] = {}
    for solution in upper_solutions:
        lang = find_language_name(solution)
        time_limit = profile.timeLimitPerLanguage.get(lang, profile.timeLimit)
        limits[lang] = timing_validation.probe_limit(
            time_limit, multipliers.timeLimitToTle
        )
    return limits


async def _record_validation_run(
    result: RunSolutionResult,
    solutions_run: List[Solution],
    limits: Dict[str, int],
    knowledge: timing_validation.SlowKnowledge,
) -> List[Tuple[Solution, Outcome]]:
    """Fold what the run said into ``knowledge``; return the solutions that broke
    for a reason other than running out of time."""
    structured_evaluations = consume_and_key_evaluation_items(
        result.items, result.skeleton
    )
    failed: List[Tuple[Solution, Outcome]] = []
    for solution in solutions_run:
        path = str(solution.path)
        outcomes: List[Outcome] = []
        timings: List[int] = []
        for evals in structured_evaluations.get(path, {}).values():
            for ev in evals:
                if ev is None:
                    continue
                evaluation = await ev()
                outcome = evaluation.result.outcome
                # A skipped testcase is the CONSEQUENCE of an earlier verdict,
                # never evidence of its own: counting it would read the abort
                # that follows a timeout as a solution breaking outright.
                if outcome == Outcome.SKIPPED:
                    continue
                outcomes.append(outcome)
                if evaluation.log.time is not None:
                    timings.append(int(evaluation.log.time * 1000))

        broken = [
            outcome
            for outcome in outcomes
            if outcome != Outcome.ACCEPTED and not outcome.is_slow()
        ]
        if broken:
            failed.append((solution, broken[0]))
        elif any(outcome.is_slow() for outcome in outcomes):
            knowledge.record_timeout(path, limits[find_language_name(solution)])
        elif timings:
            # Its time is the slowest testcase, as everywhere else: that is the
            # one the limit has to accommodate.
            knowledge.record_time(path, max(timings))
    return failed


def _classify_slow_solutions(
    profile: TimingProfile,
    upper_solutions: List[Solution],
    knowledge: timing_validation.SlowKnowledge,
    failed: List[Tuple[Solution, Outcome]],
) -> _ValidationOutcome:
    """What is now known about every slow solution, not only the ones that just
    ran: an earlier iteration may already have settled some of them."""
    multipliers = profile.multipliers
    assert multipliers is not None and multipliers.timeLimitToTle is not None
    broken = {str(solution.path) for solution, _ in failed}
    outcome = _ValidationOutcome(failed=list(failed))
    for solution in upper_solutions:
        path = str(solution.path)
        if path in broken:
            continue
        time = knowledge.measured_time(path)
        if time is None:
            if knowledge.is_confirmed(path):
                outcome.confirmed.append(solution)
            continue
        lang = find_language_name(solution)
        time_limit = profile.timeLimitPerLanguage.get(lang, profile.timeLimit)
        if violates_upper_bound(time, time_limit, multipliers.timeLimitToTle):
            outcome.violating.append((solution, time))
        else:
            outcome.confirmed.append(solution)
    return outcome


async def _validate_upper_bound(
    profile: TimingProfile,
    upper_solutions: List[Solution],
    knowledge: timing_validation.SlowKnowledge,
    check: bool,
    detailed: bool,
    runs: int,
) -> _ValidationOutcome:
    """Run each slow solution at the limit this estimate demands of it, and say
    whether it is genuinely too slow.

    Only the solutions whose answer is not already known are run: ``knowledge``
    carries what earlier iterations established, and a lower limit never needs
    re-asking.
    """
    if not upper_solutions:
        return _ValidationOutcome()

    limits = _probe_limits(profile, upper_solutions)
    to_run = [
        solution
        for solution in upper_solutions
        if knowledge.needs_run(str(solution.path), limits[find_language_name(solution)])
    ]
    if not to_run:
        return _classify_slow_solutions(profile, upper_solutions, knowledge, [])

    tracked_solutions = OrderedSet(str(solution.path) for solution in to_run)
    languages = {find_language_name(solution) for solution in to_run}
    with utils.StatusProgress('Checking solutions expected to be too slow...') as s:
        result = await run_solutions(
            progress=s,
            tracked_solutions=tracked_solutions,
            check=check,
            # ALL_SOLUTIONS keeps `isDoubleTL` off (only FULL turns it on):
            # doubling here would double the very limit being probed at.
            verification=_INFERENCE_VERIFICATION,
            timelimit_override={
                lang: limit for lang, limit in limits.items() if lang in languages
            },
            nruns=runs,
            # One timeout settles the question, so the remaining testcases only
            # cost wall clock.
            abort_on=lambda ctx: ctx.evaluation.result.outcome.is_slow(),
        )

    console.console.print()
    console.console.rule(
        '[status]Run report (upper-bound validation)[/status]', style='status'
    )
    await print_run_report(
        result,
        console.console,
        _INFERENCE_VERIFICATION,
        detailed=detailed,
        skip_printing_limits=True,
        gating_solutions=set(tracked_solutions),
    )

    failed = await _record_validation_run(result, to_run, limits, knowledge)
    return _classify_slow_solutions(profile, upper_solutions, knowledge, failed)


def _report_validation_outcome(
    outcome: _ValidationOutcome,
    profile: TimingProfile,
) -> None:
    """Say what the check found, naming the solution and the bound it broke."""
    multipliers = profile.multipliers
    assert multipliers is not None and multipliers.timeLimitToTle is not None
    for solution in outcome.confirmed:
        console.console.print(
            f'[success]✓ {solution.href()} is too slow for the estimated time '
            f'limit, as expected.[/success]'
        )
    for solution, outcome_value in outcome.failed:
        console.console.print(_failed_upper_message(solution, outcome_value))
    for solution, time in outcome.violating:
        lang = find_language_name(solution)
        time_limit = profile.timeLimitPerLanguage.get(lang, profile.timeLimit)
        required = timing_validation.probe_limit(time_limit, multipliers.timeLimitToTle)
        console.console.print(
            f'[error]✗ {solution.href()} runs in {time} ms, but the estimated '
            f'limit of {time_limit} ms requires every solution expected to be too '
            f'slow to take at least {required} ms (timeLimitToTle '
            f'{multipliers.timeLimitToTle}). Speed up the accepted solutions, slow '
            f'this one down, or relax the ratios.[/error]'
        )


async def _estimate_and_validate(
    ctx: _EstimationContext,
    knowledge: timing_validation.SlowKnowledge,
    auto: bool,
    skip_slow: bool,
    check: bool,
    detailed: bool,
    runs: int,
) -> Optional[TimingProfile]:
    """Estimate a limit and check it against the solutions expected to be too
    slow, letting the setter re-decide until the two agree.

    A violation is not fatal: it is new evidence. Carrying it back into the
    picker is what makes the second pass better informed than the first -- the
    preview can now show which groupings are impossible -- and the setter either
    picks one that works, keeps the limit anyway, or gives up. Where there is no
    picker to go back to, the violation is recorded and reported instead, and the
    profile is written with it.
    """
    violated = False
    while True:
        picked = await ctx.prompt(auto=auto, knowledge=knowledge, allow_force=violated)
        if picked is None:
            ctx.console.print('[error]Time limit estimation cancelled.[/error]')
            return None

        profile = ctx.build(
            picked, knowledge=knowledge, force=violated and picked.force
        )
        if profile is None:
            return None

        if skip_slow or picked.force:
            return profile
        if not can_validate_upper_bound(profile, ctx.upper_solutions):
            return profile

        outcome = await _validate_upper_bound(
            profile,
            ctx.upper_solutions,
            knowledge,
            check=check,
            detailed=detailed,
            runs=runs,
        )
        _report_validation_outcome(outcome, profile)
        if outcome.ok:
            return profile

        violated = True
        if auto or not ctx.can_prompt:
            # Nothing to go back to: record what was found and write it anyway,
            # so the profile carries the violation rather than hiding it.
            ctx.console.print(
                '[warning]⚠ The estimated time limit does not respect its upper '
                'bound, and there is no grouping to re-pick. Writing it anyway; '
                'the offending solutions are named under upperValidation in the '
                'limits profile.[/warning]'
            )
            return ctx.build(picked, knowledge=knowledge, force=True, announce=False)

        ctx.console.print(
            '[warning]⚠ Re-opening the picker with what the check found. Regroup '
            'to satisfy the bound, keep these limits anyway, or cancel.[/warning]'
        )


async def compute_time_limits(
    check: bool,
    detailed: bool,
    runs: int = 0,
    profile: str = 'local',
    formula: Optional[str] = None,
    auto: bool = False,
    share: Optional[str] = None,
    skip_slow: bool = False,
):
    if package.get_main_solution() is None:
        # An error, not a warning: with no accepted solution nothing bounds the
        # limit from below, so no profile is written and the command fails.
        console.console.print(
            '[error]No main solution found, so cannot estimate a time limit.[/error]'
        )
        return None

    run = await _run_for_inference(
        check=check, detailed=detailed, runs=runs, formula=formula
    )
    if run is None:
        return None

    knowledge = timing_validation.SlowKnowledge()
    ctx = await build_estimation_context(
        console.console,
        run.result,
        run.strategy,
        upper_solutions=get_inference_solutions(InferenceRole.UPPER),
        knowledge=knowledge,
    )
    if ctx is None:
        return None

    estimated_tl = await _estimate_and_validate(
        ctx,
        knowledge,
        auto=auto,
        skip_slow=skip_slow,
        check=check,
        detailed=detailed,
        runs=runs,
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
