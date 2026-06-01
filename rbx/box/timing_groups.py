from typing import Callable, Dict, List, Optional

from pydantic import BaseModel

from rbx.box.environment import LanguageGroup, LanguageGroupFallback
from rbx.box.schema import TimingGroupOrigin, TimingGroupReport


class ResolvedGroup(BaseModel):
    languages: List[str]
    whenEmpty: Optional[LanguageGroupFallback] = None


def build_partition(
    env_groups: List[LanguageGroup],
    all_languages: List[str],
) -> List[ResolvedGroup]:
    """Build a disjoint partition: explicit env groups first (in order), then an
    implicit singleton for every language not covered by an explicit group."""
    grouped: set[str] = set()
    result: List[ResolvedGroup] = []
    for group in env_groups:
        result.append(
            ResolvedGroup(languages=list(group.languages), whenEmpty=group.whenEmpty)
        )
        grouped.update(group.languages)
    for lang in all_languages:
        if lang not in grouped:
            result.append(ResolvedGroup(languages=[lang]))
            grouped.add(lang)
    return result


class GroupTimings(BaseModel):
    fastest: int
    slowest: int
    solution_count: int


class ResolutionResult(BaseModel):
    base_time_limit: int
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


def resolve_groups(
    groups: List[ResolvedGroup],
    pooled: Dict[int, GroupTimings],  # group index -> pooled timings (non-empty only)
    base: GroupTimings,
    eval_fn: EvalFn,
) -> ResolutionResult:
    base_tl = eval_fn(base.fastest, base.slowest)
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
        if timings is not None:
            tl = eval_fn(timings.fastest, timings.slowest)
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=timings.solution_count,
                fastest=timings.fastest,
                slowest=timings.slowest,
            )
        elif group.whenEmpty is not None:
            ref = group.whenEmpty.relativeTo
            ref_tl = base_tl if ref is None else resolve(lang_index[ref])
            tl = int(ref_tl * group.whenEmpty.multiplier)
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.MULTIPLIER,
                solutionCount=0,
                relativeToLanguage=ref,
                multiplier=group.whenEmpty.multiplier,
            )
        else:
            tl = base_tl
            report = TimingGroupReport(
                languages=list(group.languages),
                timeLimit=tl,
                origin=TimingGroupOrigin.DEFAULTED,
                solutionCount=0,
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
        reports=reports,
        time_limit_per_language=tl_per_language,
        defaulted_languages=defaulted,
    )
