"""The detectors: pure functions from a run to the issues in it.

Each one takes a `RunState` and returns a list of issues. None of them touches a
contextvar, a console, or the filesystem beyond the state it was handed, which
is the whole point -- the issue stack this replaces could only be exercised by
running a real package through a real sandbox, while every detector here is
testable against a `RunState` built by hand.

Detectors never *recompute* a verdict. Everything they read has already been
decided by `solutions.get_solution_outcome_report` and published by
`run_report`; a detector's job is to notice, not to judge. Anything that would
need `ExpectedOutcome.match` or the per-layer verdict sets belongs upstream, as
a field on the report -- see `untunedLimitsSuspected`.
"""

from typing import Callable, List

from rbx.box.compilation_findings import SolutionCompilation
from rbx.box.issues.run_state import RunState
from rbx.box.issues.schema import (
    BorderlineTleIssue,
    CompilationFailedIssue,
    CompilationWarningsIssue,
    HiddenVerdictIssue,
    Issue,
    IssueSeverity,
    TightTimeMarginIssue,
    UnexpectedScoreIssue,
    UnmetExpectationIssue,
    UntunedLimitsIssue,
)

# How much of its time limit a passing solution may use before it is worth a
# mention. 0.8 rather than something tighter because the measurement is one
# machine's, on one run: flagging at 0.95 would only fire once the limit is
# already effectively broken, and flagging at 0.5 would fire on every package
# whose limits are deliberately snug.
TIGHT_TIME_MARGIN_RATIO = 0.8


def detect_unmet_expectations(state: RunState) -> List[Issue]:
    """Solutions that did not behave the way the package says they do."""
    issues: List[Issue] = []
    for solution in state.report.solutions:
        if solution.matchesExpectation:
            continue
        # An unexpected *score* is reported by its own detector, which can say
        # what the range was. Reporting both would name one failure twice.
        if solution.status == 'UNEXPECTED_SCORE':
            continue
        issues.append(
            UnmetExpectationIssue(
                solution=solution.path,
                expected=solution.expectedOutcome,
                got=solution.outcome,
                status=solution.status,
                failedGroups=list(solution.failedGroups),
                pooledMatchesExpectation=solution.pooledMatchesExpectation,
            )
        )
    return issues


def detect_unexpected_scores(state: RunState) -> List[Issue]:
    """Solutions that scored outside their declared range."""
    issues: List[Issue] = []
    for solution in state.report.solutions:
        if solution.status != 'UNEXPECTED_SCORE':
            continue
        # The range is what makes this issue sayable; without it there is
        # nothing to report beyond "the score was wrong", which the verdict
        # already covers.
        if solution.expectedScore is None:
            continue
        issues.append(
            UnexpectedScoreIssue(
                solution=solution.path,
                score=solution.score,
                maxScore=solution.maxScore,
                expectedScore=solution.expectedScore,
            )
        )
    return issues


def detect_compilation(state: RunState) -> List[Issue]:
    """Solutions the compiler failed or complained about.

    Read off the skeleton rather than the report: a solution that failed to
    compile never ran, so it has no report entry at all. This is the only record
    that it exists.
    """
    issues: List[Issue] = []
    for compilation in state.skeleton.compilation:
        issues.append(_compilation_issue(compilation))
    return issues


def _compilation_issue(compilation: SolutionCompilation) -> Issue:
    if compilation.status == 'FAILED':
        return CompilationFailedIssue(
            solution=str(compilation.path),
            reason=compilation.reason,
            log=compilation.log,
        )
    return CompilationWarningsIssue(
        solution=str(compilation.path),
        warnings=list(compilation.warnings),
        log=compilation.log,
    )


def detect_borderline_tle(state: RunState) -> List[Issue]:
    """Solutions declared slow that were only slow inside the doubled TL."""
    issues: List[Issue] = []
    for solution in state.report.solutions:
        if not solution.runUnderDoubleTl:
            continue
        issues.append(
            BorderlineTleIssue(
                solution=solution.path,
                groups=[
                    group.name for group in solution.groups if group.runUnderDoubleTl
                ],
                doubleTlVerdicts=list(solution.doubleTlVerdicts),
            )
        )
    return issues


def detect_hidden_verdicts(state: RunState) -> List[Issue]:
    """Verdicts a soft TLE hid that no expectation accepts.

    Pooled up from the groups, because that is the only place the report
    publishes them: `RunGroupReport.unexpectedNoTleVerdicts` has already been
    intersected with whichever expectation layer covers the group, so a group
    that ran clean cannot inherit a verdict hidden three groups away.
    """
    issues: List[Issue] = []
    for solution in state.report.solutions:
        groups = [group for group in solution.groups if group.unexpectedNoTleVerdicts]
        if not groups:
            continue
        verdicts = sorted(
            {verdict for group in groups for verdict in group.unexpectedNoTleVerdicts},
            key=lambda verdict: verdict.name,
        )
        issues.append(
            HiddenVerdictIssue(
                solution=solution.path,
                groups=[group.name for group in groups],
                verdicts=verdicts,
            )
        )
    return issues


def detect_tight_time_margin(state: RunState) -> List[Issue]:
    """Solutions that passed, but with little room left against the TL.

    Only solutions that met their expectation: one declared slow is *supposed*
    to sit against the limit, and one that failed has a louder issue already.
    """
    issues: List[Issue] = []
    for solution in state.report.solutions:
        if not solution.matchesExpectation:
            continue
        if solution.maxTime is None or not solution.timeLimit:
            continue
        # A solution declared slow is expected to be up against the limit; that
        # is the declaration working, not a margin worth warning about.
        if solution.expectedOutcome.is_slow():
            continue
        if solution.maxTime < solution.timeLimit * TIGHT_TIME_MARGIN_RATIO:
            continue
        issues.append(
            TightTimeMarginIssue(
                solution=solution.path,
                maxTime=solution.maxTime,
                timeLimit=solution.timeLimit,
            )
        )
    return issues


def detect_untuned_limits(state: RunState) -> List[Issue]:
    """Timing failures on a package whose limits were never tuned here.

    One issue for the whole package, not one per solution: the remedy is a
    single `rbx time`, and repeating it per solution would bury the actual
    verdict failures under copies of the same advice.
    """
    affected = [
        solution.path
        for solution in state.report.solutions
        if solution.untunedLimitsSuspected
    ]
    if not affected:
        return []
    return [UntunedLimitsIssue(affectedSolutions=affected)]


DETECTORS: List[Callable[[RunState], List[Issue]]] = [
    detect_unmet_expectations,
    detect_unexpected_scores,
    detect_compilation,
    detect_borderline_tle,
    detect_hidden_verdicts,
    detect_tight_time_margin,
    detect_untuned_limits,
]


def detect_all(state: RunState) -> List[Issue]:
    """Every issue in a run, worst first.

    Sorted by severity and then by detector order, which puts the verdict
    failures above the compilation warnings above the advice. Within a detector
    the order is the report's, which is the order the solutions were declared --
    so the list lines up with the run's own table.
    """
    issues: List[Issue] = []
    for detector in DETECTORS:
        issues.extend(detector(state))
    # `sorted` is stable, so this reorders by severity while leaving the
    # detector-then-declaration order intact inside each band.
    return sorted(issues, key=lambda issue: issue.severity != IssueSeverity.ERROR)
