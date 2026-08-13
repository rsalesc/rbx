from typing import Callable, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel

from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingBound, TimingGroupOrigin, TimingGroupReport


class ResolvedGroup(BaseModel):
    languages: List[str]
    whenEmpty: Optional[LanguageGroupFallback] = None
    forced_relative: Optional[LanguageGroupFallback] = None
    is_leftover: bool = False


def _effective_fallback(group: 'ResolvedGroup') -> Optional[LanguageGroupFallback]:
    """The fallback whose reference edge matters for validation: a forced
    relative (picker path) takes precedence, else the env whenEmpty."""
    return group.forced_relative or group.whenEmpty


def build_partition(
    env_groups: List[LanguageGroup],
    all_languages: List[str],
) -> List[ResolvedGroup]:
    """Build a disjoint partition: explicit env groups first (in order), then a
    single leftover pool holding every language not covered by an explicit group."""
    grouped: set[str] = set()
    result: List[ResolvedGroup] = []
    for group in env_groups:
        result.append(
            ResolvedGroup(languages=list(group.languages), whenEmpty=group.whenEmpty)
        )
        grouped.update(group.languages)
    leftover = [lang for lang in all_languages if lang not in grouped]
    if leftover:
        result.append(ResolvedGroup(languages=leftover, is_leftover=True))
    return result


def group_key(state: int, lang: str) -> str:
    """Stable key for the group a language currently belongs to."""
    if state > 0:
        return f'g{state}'
    if state < 0:
        return f's:{lang}'
    return 'leftover'


def partition_from_assignment(
    assignment: Dict[str, int],
    relatives: Optional[Dict[str, LanguageGroupFallback]] = None,
) -> List[ResolvedGroup]:
    """Build groups from a {language: state} map. State per language:
    N>=1 share bucket N; -1 = own singleton group; 0 = the shared leftover pool.
    Optional ``relatives`` maps a group-key (see group_key) to a forced relative
    spec, stamped onto the matching group as ``forced_relative``."""
    relatives = relatives or {}
    buckets: Dict[int, List[str]] = {}
    singletons: List[Tuple[str, List[str]]] = []
    leftover: List[str] = []
    for lang, state in assignment.items():
        if state == 0:
            leftover.append(lang)
        elif state < 0:
            singletons.append((group_key(state, lang), [lang]))
        else:
            buckets.setdefault(state, []).append(lang)

    result: List[ResolvedGroup] = []
    for number, langs in sorted(buckets.items()):
        result.append(
            ResolvedGroup(
                languages=langs,
                forced_relative=relatives.get(group_key(number, langs[0])),
            )
        )
    for key, langs in singletons:
        result.append(
            ResolvedGroup(languages=langs, forced_relative=relatives.get(key))
        )
    if leftover:
        result.append(
            ResolvedGroup(
                languages=leftover,
                is_leftover=True,
                forced_relative=relatives.get(group_key(0, '')),
            )
        )
    return result


# One solution's measurement: (time in ms, solution path). Ordered by time
# first, so min/max pick the extreme measurement -- and, on a tie, a stable
# solution path.
Measurement = Tuple[int, str]


class GroupTimings(BaseModel):
    """Lower-bound evidence: how long the group's accepted solutions took."""

    fastest: int
    slowest: int
    solution_count: int
    # Which solution took ``slowest`` -- the one that drives the limit up.
    slowest_solution: Optional[str] = None


class UpperTimings(BaseModel):
    """Upper-bound evidence: how long the group's slow solutions took.

    Tracked separately from ``GroupTimings`` because the two sides are populated
    by disjoint sets of solutions: a group may have slow solutions and no
    accepted ones (so no ``GroupTimings`` at all) and still must have its limit
    checked against this bound.
    """

    # Absent when every slow solution of the group was dropped: the group then
    # bounds nothing from above, but still has to carry ``dropped_upper`` so the
    # drop is reported against the group it happened in.
    fastest_slow: Optional[int] = None
    fastest_slow_solution: Optional[str] = None
    # Slow solutions that were measured but cannot bound the limit (e.g. they
    # hit the inference timeout).
    dropped_upper: List[str] = []


class GroupMeasurements(BaseModel):
    """Everything measured for one group. The two sides are populated by
    disjoint sets of solutions, so either may be absent independently: a group
    can have slow solutions and no accepted ones, and vice versa."""

    lower: Optional[GroupTimings] = None
    upper: Optional[UpperTimings] = None


class ResolutionResult(BaseModel):
    base_time_limit: int
    base_report: TimingGroupReport
    reports: List[TimingGroupReport]
    time_limit_per_language: Dict[str, int]
    defaulted_languages: List[str]


class EvalResult(BaseModel):
    """A group's estimated limit and the bounds that produced it.

    An estimator that computes bounds returns them here rather than leaving the
    reporting layer to recompute them: two implementations of that arithmetic is
    exactly where the recorded provenance and the limit it explains would
    silently diverge.
    """

    time_limit: int
    lower_bound: Optional[TimingBound] = None
    upper_bound: Optional[TimingBound] = None


# An estimator that derives no bounds at all (the formula path) may return the
# limit on its own.
EvalOutcome = Union[int, EvalResult]

# Estimates a group's limit from its own measurements.
EvalFn = Callable[[GroupMeasurements], EvalOutcome]
# Post-processes a limit that was NOT estimated from the group's own accepted
# solutions -- derived from a reference group (``whenEmpty`` or a forced
# relative) or inherited from the base estimate (``DEFAULTED``) -- so it can
# still be checked against the group's own upper bound.
DeriveFn = Callable[[int, GroupMeasurements], EvalOutcome]


def _limit_of(outcome: EvalOutcome) -> int:
    return outcome.time_limit if isinstance(outcome, EvalResult) else outcome


def _provenance_of(outcome: EvalOutcome) -> Optional[EvalResult]:
    """Only an estimator that reports its bounds records provenance: a bare limit
    (the formula path) knows nothing about the slow solutions, so its group
    reports must say nothing about them either."""
    return outcome if isinstance(outcome, EvalResult) else None


def _lang_to_group_index(groups: List[ResolvedGroup]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for idx, group in enumerate(groups):
        for lang in group.languages:
            out[lang] = idx
    return out


def _record_provenance(
    report: TimingGroupReport,
    result: Optional[EvalResult],
    measured: GroupMeasurements,
) -> None:
    """Stamp onto a report what decided its limit: the bounds the estimator
    computed and the slow solutions that were measured but bound nothing.
    Presentation-only -- nothing here feeds limit resolution."""
    if result is None:
        return
    report.lowerBound = result.lower_bound
    report.upperBound = result.upper_bound
    if measured.upper is not None:
        report.droppedUpper = list(measured.upper.dropped_upper)


class GroupValidationError(ValueError):
    pass


class TimingRangeError(GroupValidationError):
    """No time limit satisfies both bounds of some group.

    Subclasses ``GroupValidationError`` so the interactive group picker renders
    it inline for the offending grouping, exactly as it does an invalid
    partition.
    """


def validate_partition(groups: List[ResolvedGroup]) -> None:
    lang_index = _lang_to_group_index(groups)
    # reference target existence + not-self
    for idx, group in enumerate(groups):
        fallback = _effective_fallback(group)
        if fallback is None or fallback.relativeTo is None:
            continue
        ref = fallback.relativeTo
        if ref not in lang_index:
            raise GroupValidationError(
                f'relative reference points to unknown language {ref!r}.'
            )
        if lang_index[ref] == idx:
            raise GroupValidationError(
                f'relative reference {ref!r} points to the same group; it must '
                'reference a different group.'
            )
    # cycle detection over group-to-group reference edges
    WHITE, GRAY, BLACK = 0, 1, 2
    color = [WHITE] * len(groups)

    def visit(idx: int) -> None:
        color[idx] = GRAY
        fallback = _effective_fallback(groups[idx])
        if fallback is not None and fallback.relativeTo is not None:
            nxt = lang_index[fallback.relativeTo]
            if color[nxt] == GRAY:
                raise GroupValidationError(
                    'relative references form a cycle between timing groups.'
                )
            if color[nxt] == WHITE:
                visit(nxt)
        color[idx] = BLACK

    for idx in range(len(groups)):
        if color[idx] == WHITE:
            visit(idx)


def resolve_groups(
    groups: List[ResolvedGroup],
    measured: Dict[int, GroupMeasurements],  # group index -> its measurements
    base: GroupMeasurements,
    eval_fn: EvalFn,
    derive_fn: Optional[DeriveFn] = None,
) -> ResolutionResult:
    base_outcome = eval_fn(base)
    base_tl = _limit_of(base_outcome)
    base_report = TimingGroupReport(
        languages=[],
        timeLimit=base_tl,
        origin=TimingGroupOrigin.ESTIMATED,
        solutionCount=base.lower.solution_count if base.lower else 0,
        fastest=base.lower.fastest if base.lower else None,
        slowest=base.lower.slowest if base.lower else None,
    )
    _record_provenance(base_report, _provenance_of(base_outcome), base)
    lang_index = _lang_to_group_index(groups)

    resolved_tl: Dict[int, int] = {}
    resolved_report: Dict[int, TimingGroupReport] = {}
    resolving: set[int] = set()  # cycle guard (validation should prevent cycles)

    def resolve(idx: int) -> int:
        if idx in resolved_tl:
            return resolved_tl[idx]
        if idx in resolving:
            # Acyclic is guaranteed by env validation; fall back defensively.
            return base_tl
        resolving.add(idx)
        group = groups[idx]
        group_measured = measured.get(idx) or GroupMeasurements()
        timings = group_measured.lower
        # The bounds the estimator computed for this group, when it computes any.
        result: Optional[EvalResult] = None
        if group.forced_relative is not None:
            fb = group.forced_relative
            ref = fb.relativeTo
            ref_tl = base_tl if ref is None else resolve(lang_index[ref])
            increment = fb.increment or 0
            tl = int(ref_tl * fb.multiplier + increment)
            if derive_fn is not None:
                outcome = derive_fn(tl, group_measured)
                tl = _limit_of(outcome)
                result = _provenance_of(outcome)
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.MULTIPLIER,
                solutionCount=timings.solution_count if timings else 0,
                fastest=timings.fastest if timings else None,
                slowest=timings.slowest if timings else None,
                relativeToLanguage=ref,
                multiplier=fb.multiplier,
                increment=fb.increment,
                isLeftover=group.is_leftover,
            )
        elif timings is not None:
            outcome = eval_fn(group_measured)
            tl = _limit_of(outcome)
            result = _provenance_of(outcome)
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=timings.solution_count,
                fastest=timings.fastest,
                slowest=timings.slowest,
                isLeftover=group.is_leftover,
            )
        elif group.whenEmpty is not None:
            ref = group.whenEmpty.relativeTo
            ref_tl = base_tl if ref is None else resolve(lang_index[ref])
            increment = group.whenEmpty.increment or 0
            tl = int(ref_tl * group.whenEmpty.multiplier + increment)
            if derive_fn is not None:
                outcome = derive_fn(tl, group_measured)
                tl = _limit_of(outcome)
                result = _provenance_of(outcome)
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.MULTIPLIER,
                solutionCount=0,
                relativeToLanguage=ref,
                multiplier=group.whenEmpty.multiplier,
                increment=group.whenEmpty.increment,
                isLeftover=group.is_leftover,
            )
        else:
            tl = base_tl
            if derive_fn is not None:
                # Check-only: the report and the UI both state that a defaulted
                # group fell back to the base limit, so it must not move off it
                # -- and requantizing an already-quantized base_tl is identity
                # anyway. derive_fn runs solely so it can raise when the group's
                # own upper bound rules the base limit out; its *limit* is
                # deliberately discarded -- only the bounds it reports are kept.
                result = _provenance_of(derive_fn(tl, group_measured))
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.DEFAULTED,
                solutionCount=0,
                isLeftover=group.is_leftover,
            )
        _record_provenance(report, result, group_measured)
        resolving.discard(idx)
        resolved_tl[idx] = tl
        resolved_report[idx] = report
        return tl

    for idx in range(len(groups)):
        resolve(idx)

    reports = [resolved_report[i] for i in range(len(groups))]
    tl_per_language: Dict[str, int] = {}
    defaulted: List[str] = []
    for idx, group in enumerate(groups):
        report = resolved_report[idx]
        if report.origin == TimingGroupOrigin.DEFAULTED:
            defaulted.extend(group.languages)
            continue  # uses base TL -> no modifier
        for lang in group.languages:
            tl_per_language[lang] = report.timeLimit
    return ResolutionResult(
        base_time_limit=base_tl,
        base_report=base_report,
        reports=reports,
        time_limit_per_language=tl_per_language,
        defaulted_languages=defaulted,
    )
