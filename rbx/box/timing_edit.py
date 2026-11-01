"""Checking a time limit against the evidence an estimate left behind.

`rbx time` records, on each group of a limits profile, what bounded its limit:
the slowest accepted solution (`slowest`, `lowerBound`), the slow solutions that
capped it (`upperBound`) and what checking them against the limit found
(`upperValidation`). That is enough to judge *any* limit for the group, not only
the one that was estimated, without running a single solution -- which is what
`rbx time --edit` does on every keystroke.

A leaf module on purpose: `limits_info` renders the result in every limits
table, and `timing` (which imports `limits_info`) reuses the arithmetic, so this
may import neither.
"""

import enum
import math
from fractions import Fraction
from typing import List, Optional, Tuple

from pydantic import BaseModel

from rbx.box.schema import (
    EstimationSolutionTiming,
    InferenceRole,
    LimitModifiers,
    LimitsProfile,
    TimingBound,
    TimingGroupReport,
    TimingMultipliers,
)


def exact_ratio(ratio: float) -> Fraction:
    """The ratio the setter typed in YAML, as an exact rational.

    ``str()`` yields the shortest repr that round-trips, so the 1.1 stored as
    1.100000000000000088... comes back as exactly 11/10. Every bound is computed
    in this arithmetic: the numbers end up serialized in the limits profile, so
    a setter recomputing them by hand must get the same answer rbx did.
    """
    return Fraction(str(ratio))


def violates_upper_bound(time: int, time_limit: int, time_limit_to_tle: float) -> bool:
    """Whether a slow solution taking ``time`` is too fast for ``time_limit``.

    The same comparison `compute_bounds` makes, in the same exact arithmetic:
    the limit may be at most ``time / timeLimitToTle``, so the solution must take
    at least ``time_limit * timeLimitToTle``.
    """
    return time < time_limit * exact_ratio(time_limit_to_tle)


def multipliers_lower_bound(
    multipliers: TimingMultipliers, slowest: int, fastest: Optional[int]
) -> Tuple[int, bool]:
    """The smallest limit the accepted solutions allow under ``multipliers``, and
    whether ``fastestToTimeLimit`` (rather than ``acToTimeLimit``) is what set it.

    The slowest accepted solution times ``acToTimeLimit`` must fit, and so must
    the fastest times ``fastestToTimeLimit`` when that is configured. The
    single source of this rule: `timing.compute_bounds` estimates with it and
    `assess` judges hand-set limits with it.
    """
    by_slowest = math.ceil(slowest * exact_ratio(multipliers.acToTimeLimit))
    if multipliers.fastestToTimeLimit is None or fastest is None:
        return by_slowest, False
    by_fastest = math.ceil(fastest * exact_ratio(multipliers.fastestToTimeLimit))
    if by_fastest > by_slowest:
        return by_fastest, True
    return by_slowest, False


class GroupCheck(BaseModel):
    """How one group's time limit fares against the evidence recorded for it."""

    time_limit: int
    # The limit the evidence was measured against, when it is not `time_limit`.
    estimated: Optional[int] = None

    # The smallest limit the group's own accepted solutions allow: their slowest
    # scaled by `acToTimeLimit` (and the fastest by `fastestToTimeLimit`, when
    # set), or the slowest itself without multipliers.
    min_ms: Optional[int] = None
    min_solution: Optional[str] = None
    # The largest limit its slow solutions allow.
    max_ms: Optional[int] = None
    max_solution: Optional[str] = None
    # The group's slowest accepted solution, to tell a limit it outright fails
    # from one it clears without the configured margin.
    slowest_ms: Optional[int] = None

    # Slow solutions measured to finish within `time_limit * timeLimitToTle`.
    violating: List[TimingBound] = []
    # Slow solutions seen still running at a limit at least this one.
    confirmed: List[str] = []
    # Slow solutions only seen still running at a *lower* limit than this one:
    # they may well finish in time now, and nothing measured says either way.
    unverified: List[str] = []

    @property
    def rejects_own_solutions(self) -> bool:
        return self.slowest_ms is not None and self.time_limit < self.slowest_ms

    @property
    def below_min(self) -> bool:
        return self.min_ms is not None and self.time_limit < self.min_ms

    @property
    def above_max(self) -> bool:
        return self.max_ms is not None and self.time_limit > self.max_ms

    @property
    def breaks_upper(self) -> bool:
        return self.above_max or bool(self.violating)

    @property
    def ok(self) -> bool:
        return not (self.below_min or self.breaks_upper or self.unverified)


def evidence_limit(report: TimingGroupReport) -> int:
    """The limit the report's bounds and validation were measured against."""
    if report.estimatedTimeLimit is not None:
        return report.estimatedTimeLimit
    return report.timeLimit


def _min_solution(report: TimingGroupReport) -> Optional[str]:
    # An estimated group's lower bound is set by its own slowest solution; a
    # derived one names none, but records its own when the limit undercut it.
    if report.lowerBound is not None and report.lowerBound.solution is not None:
        return report.lowerBound.solution
    if report.lowerViolation is not None:
        return report.lowerViolation.solution
    return None


def assess(
    report: TimingGroupReport,
    multipliers: Optional[TimingMultipliers],
    time_limit: Optional[int] = None,
    solutions: Optional[List[EstimationSolutionTiming]] = None,
) -> GroupCheck:
    """Judge ``time_limit`` (the report's own limit by default) for this group.

    Pure arithmetic over what the report recorded, applying the rules
    `timing.compute_bounds` estimated with -- so at the estimated limit it
    reproduces exactly what the estimation concluded.

    ``solutions`` are the group's own per-solution timings, when the profile
    recorded them (see `group_solutions`). They make the slow side exact: a
    confirmed solution is judged against the limit it was actually seen
    surviving, instead of against the limit the group was estimated at.
    """
    if time_limit is None:
        time_limit = report.timeLimit
    evidence_at = evidence_limit(report)

    min_ms = None
    if report.slowest is not None:
        if multipliers is not None:
            min_ms, _ = multipliers_lower_bound(
                multipliers, report.slowest, report.fastest
            )
        else:
            # A formula bounds nothing; a solution taking T still needs T.
            min_ms = report.slowest

    max_ms = None
    max_solution = None
    to_tle = multipliers.timeLimitToTle if multipliers is not None else None
    if to_tle is not None and report.upperBound is not None:
        max_ms = report.upperBound.value
        max_solution = report.upperBound.solution

    violating: List[TimingBound] = []
    confirmed: List[str] = []
    unverified: List[str] = []
    validation = report.upperValidation
    if validation is not None and to_tle is not None:
        violating = [
            bound
            for bound in validation.violating
            if violates_upper_bound(bound.value, time_limit, to_tle)
        ]
        survived = {
            timing.path: timing.survivedAt
            for timing in solutions or []
            if timing.survivedAt is not None
        }
        for path in validation.confirmed:
            if path in survived:
                # Still running at `survived`: too slow for any limit whose
                # multiple fits under it.
                holds = not violates_upper_bound(survived[path], time_limit, to_tle)
            else:
                # Only known to survive evidence_at * timeLimitToTle, which says
                # nothing about any higher multiple.
                holds = time_limit <= evidence_at
            (confirmed if holds else unverified).append(path)

    return GroupCheck(
        time_limit=time_limit,
        estimated=evidence_at if evidence_at != time_limit else None,
        min_ms=min_ms,
        min_solution=_min_solution(report),
        max_ms=max_ms,
        max_solution=max_solution,
        slowest_ms=report.slowest,
        violating=violating,
        confirmed=confirmed,
        unverified=unverified,
    )


def _retarget(
    report: TimingGroupReport,
    multipliers: Optional[TimingMultipliers],
    time_limit: int,
) -> None:
    """Point ``report`` at ``time_limit``, keeping the evidence it was built on."""
    evidence_at = evidence_limit(report)
    report.timeLimit = time_limit
    report.estimatedTimeLimit = None if time_limit == evidence_at else evidence_at
    # `lowerViolation` keeps its meaning -- recorded only while the limit is
    # below what the group's own accepted solutions allow -- so every reader of
    # it (the limits table, its captions) sees a hand-set limit the same way.
    check = assess(report, multipliers)
    report.lowerViolation = (
        TimingBound(value=check.min_ms, solution=check.min_solution)
        if check.below_min and check.min_ms is not None
        else None
    )


def with_time_limit(
    profile: LimitsProfile, group: Optional[int], time_limit: int
) -> LimitsProfile:
    """A copy of ``profile`` with the limit of one group set to ``time_limit``.

    ``group`` indexes ``profile.groups``; ``None`` is the base limit. The group's
    per-language modifiers move with it, since those -- not the report -- are what
    a run is judged against.
    """
    profile = profile.model_copy(deep=True)
    if group is None:
        profile.timeLimit = time_limit
        if profile.baseEstimate is not None:
            _retarget(profile.baseEstimate, profile.multipliers, time_limit)
        return profile
    assert profile.groups is not None
    report = profile.groups[group]
    _retarget(report, profile.multipliers, time_limit)
    for language in report.languages:
        profile.modifiers.setdefault(language, LimitModifiers()).time = time_limit
    return profile


def is_editable(profile: LimitsProfile) -> bool:
    """Whether ``profile`` carries the evidence of an estimate to edit against."""
    return (
        not profile.inheritFromPackage
        and profile.timeLimit is not None
        and (bool(profile.groups) or profile.baseEstimate is not None)
    )


def adjusted_checks(profile: LimitsProfile) -> List[GroupCheck]:
    """The checks of every limit in ``profile`` that was set by hand."""
    reports = list(profile.groups or [])
    if profile.baseEstimate is not None:
        reports.append(profile.baseEstimate)
    return [
        assess(
            report,
            profile.multipliers,
            solutions=group_solutions(profile, report),
        )
        for report in reports
        if report.estimatedTimeLimit is not None
    ]


def group_solutions(
    profile: LimitsProfile, report: Optional[TimingGroupReport]
) -> Optional[List[EstimationSolutionTiming]]:
    """The recorded timings of the solutions a row is about: every solution for
    the base row (``report`` is the base estimate, or None), the ones in the
    group's languages otherwise. None when the profile recorded no timings."""
    if profile.solutions is None:
        return None
    if report is None or report is profile.baseEstimate:
        return list(profile.solutions)
    languages = set(report.languages)
    return [timing for timing in profile.solutions if timing.language in languages]


class SolutionStatus(str, enum.Enum):
    # Clears the limit as an accepted or a too-slow solution should.
    OK = 'ok'
    # Accepted and passes, without the headroom `acToTimeLimit` asks for.
    THIN = 'thin'
    # Accepted, and takes longer than the limit.
    FAILS = 'fails'
    # Expected too slow, and finishes within the limit times `timeLimitToTle`.
    PASSES = 'passes'
    # Expected too slow, and only seen running at a lower multiple of the limit.
    UNVERIFIED = 'unverified'
    # Expected too slow, and never run, or nothing bounds it from above.
    UNCHECKED = 'unchecked'


class SolutionCheck(BaseModel):
    """How one solution fares at one limit."""

    path: str
    language: str
    role: InferenceRole
    time: Optional[int] = None
    survived_at: Optional[int] = None
    # The range of limits this solution allows: at least `min_ms` for an
    # accepted one, at most `max_ms` for a slow one.
    min_ms: Optional[int] = None
    max_ms: Optional[int] = None
    # How far the limit is from the solution, as the ratio the multiplier caps:
    # limit / time for an accepted one, time / limit for a slow one.
    ratio: Optional[float] = None
    status: SolutionStatus


def check_solution(
    timing: EstimationSolutionTiming,
    multipliers: Optional[TimingMultipliers],
    time_limit: int,
) -> SolutionCheck:
    common = dict(
        path=timing.path,
        language=timing.language,
        role=timing.role,
        time=timing.time,
        survived_at=timing.survivedAt,
    )
    if timing.role == InferenceRole.LOWER:
        assert timing.time is not None
        need = (
            math.ceil(timing.time * exact_ratio(multipliers.acToTimeLimit))
            if multipliers is not None
            else timing.time
        )
        if time_limit < timing.time:
            status = SolutionStatus.FAILS
        elif time_limit < need:
            status = SolutionStatus.THIN
        else:
            status = SolutionStatus.OK
        return SolutionCheck(
            **common,
            min_ms=need,
            ratio=time_limit / timing.time if timing.time else None,
            status=status,
        )

    to_tle = multipliers.timeLimitToTle if multipliers is not None else None
    if to_tle is None:
        return SolutionCheck(
            **common,
            ratio=timing.time / time_limit if timing.time is not None else None,
            status=SolutionStatus.UNCHECKED,
        )
    if timing.time is not None:
        return SolutionCheck(
            **common,
            max_ms=math.floor(timing.time / exact_ratio(to_tle)),
            ratio=timing.time / time_limit,
            status=(
                SolutionStatus.PASSES
                if violates_upper_bound(timing.time, time_limit, to_tle)
                else SolutionStatus.OK
            ),
        )
    if timing.survivedAt is not None:
        return SolutionCheck(
            **common,
            max_ms=math.floor(timing.survivedAt / exact_ratio(to_tle)),
            status=(
                SolutionStatus.UNVERIFIED
                if violates_upper_bound(timing.survivedAt, time_limit, to_tle)
                else SolutionStatus.OK
            ),
        )
    return SolutionCheck(**common, status=SolutionStatus.UNCHECKED)


def check_solutions(
    timings: List[EstimationSolutionTiming],
    multipliers: Optional[TimingMultipliers],
    time_limit: int,
) -> List[SolutionCheck]:
    """Every solution checked at ``time_limit``: the accepted ones slowest
    first, then the slow ones fastest first -- the closest to the limit lead."""
    lower = sorted(
        (t for t in timings if t.role == InferenceRole.LOWER),
        key=lambda t: -(t.time or 0),
    )
    upper = sorted(
        (t for t in timings if t.role == InferenceRole.UPPER),
        key=lambda t: (
            t.time if t.time is not None else t.survivedAt or float('inf'),
            t.path,
        ),
    )
    return [check_solution(t, multipliers, time_limit) for t in [*lower, *upper]]
