from typing import Callable, Dict, List, Optional

from pydantic import BaseModel

from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingGroupOrigin, TimingGroupReport


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


def partition_from_assignment(
    assignment: Dict[str, int],
    env_groups: List[LanguageGroup],
) -> List[ResolvedGroup]:
    """Build groups from a {language: state} map. State per language:
    N>=1 share bucket N; -1 = own singleton group; 0 = the shared leftover pool.
    Carries over an env group's whenEmpty only when the resulting membership is
    identical to that env group."""
    buckets: Dict[int, List[str]] = {}
    singletons: List[List[str]] = []
    leftover: List[str] = []
    for lang, state in assignment.items():
        if state == 0:
            leftover.append(lang)
        elif state < 0:
            singletons.append([lang])
        else:
            buckets.setdefault(state, []).append(lang)

    env_when_empty = {frozenset(g.languages): g.whenEmpty for g in env_groups}
    result: List[ResolvedGroup] = []
    for _, langs in sorted(buckets.items()):
        when_empty = env_when_empty.get(frozenset(langs))
        result.append(ResolvedGroup(languages=langs, whenEmpty=when_empty))
    result.extend(ResolvedGroup(languages=s) for s in singletons)
    if leftover:
        result.append(ResolvedGroup(languages=leftover, is_leftover=True))
    return result


class GroupTimings(BaseModel):
    fastest: int
    slowest: int
    solution_count: int


class ResolutionResult(BaseModel):
    base_time_limit: int
    base_report: TimingGroupReport
    reports: List[TimingGroupReport]
    time_limit_per_language: Dict[str, int]
    defaulted_languages: List[str]


EvalFn = Callable[[int, int], int]


def _lang_to_group_index(groups: List[ResolvedGroup]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for idx, group in enumerate(groups):
        for lang in group.languages:
            out[lang] = idx
    return out


class GroupValidationError(ValueError):
    pass


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
    pooled: Dict[int, GroupTimings],  # group index -> pooled timings (non-empty only)
    base: GroupTimings,
    eval_fn: EvalFn,
) -> ResolutionResult:
    base_tl = eval_fn(base.fastest, base.slowest)
    base_report = TimingGroupReport(
        languages=[],
        timeLimit=base_tl,
        origin=TimingGroupOrigin.ESTIMATED,
        solutionCount=base.solution_count,
        fastest=base.fastest,
        slowest=base.slowest,
    )
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
        timings = pooled.get(idx)
        if group.forced_relative is not None:
            fb = group.forced_relative
            ref = fb.relativeTo
            ref_tl = base_tl if ref is None else resolve(lang_index[ref])
            increment = fb.increment or 0
            tl = int(ref_tl * fb.multiplier + increment)
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
            tl = eval_fn(timings.fastest, timings.slowest)
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
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.DEFAULTED,
                solutionCount=0,
                isLeftover=group.is_leftover,
            )
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
