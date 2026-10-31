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
from rbx.box.issue_codes import IssueThresholds
from rbx.box.issues.run_state import RunState
from rbx.box.issues.schema import (
    AssetCompilationWarningsIssue,
    BorderlineTleIssue,
    CompilationFailedIssue,
    CompilationWarningsIssue,
    DuplicateTestIssue,
    HiddenVerdictIssue,
    Issue,
    IssueSeverity,
    LinterWarningsIssue,
    NoisyStderrIssue,
    SanitizerFindingIssue,
    SlowAcceptedSolutionIssue,
    UnexpectedScoreIssue,
    UnmetExpectationIssue,
    UntunedLimitsIssue,
)
from rbx.box.schema import ExpectedOutcome

# How much a solution may print to stderr on a single testcase before it is
# worth a mention, by default. 1MB is far past any plausible deliberate use: a
# solution that writes this much is printing debug output it forgot to remove.
# Tunable as `issues.thresholds.stderrSizeMb` in `env.rbx.yml`.
STDERR_THRESHOLD_IN_BYTES = IssueThresholds().stderr_size_bytes


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


def detect_asset_compilation(state: RunState) -> List[Issue]:
    """Generators, validators, checkers, interactors and visualizers that warned.

    Recorded on the skeleton from what the build ahead of the run compiled, so
    they are as old as the run -- a later `rbx build` alone does not refresh
    them.
    """
    return [
        AssetCompilationWarningsIssue(
            path=str(compilation.path),
            assetKind=compilation.kind,
            warnings=list(compilation.warnings),
            log=compilation.log,
        )
        for compilation in state.skeleton.asset_compilation
    ]


def detect_linter_warnings(state: RunState) -> List[Issue]:
    """Files a configured linter flagged, one issue per file."""
    return [
        LinterWarningsIssue(
            path=str(lint.path),
            assetKind=lint.kind,
            findings=list(lint.findings),
        )
        for lint in state.skeleton.lints
        if lint.findings
    ]


def detect_duplicate_tests(state: RunState) -> List[Issue]:
    """Tests the build found repeating an earlier one, in build order."""
    return [
        DuplicateTestIssue(duplicate=duplicate)
        for duplicate in state.skeleton.duplicate_tests
    ]


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


def detect_noisy_stderr(state: RunState) -> List[Issue]:
    """Solutions that printed a lot to stderr.

    One issue per solution rather than per testcase: the remedy is a single edit
    to the solution, and a package whose debug output is on every testcase would
    otherwise produce one issue per test. The artifact named is the noisiest
    one, which is the one worth opening.

    The sizes were taken by `run_state.size_stderr_artifacts`; this detector,
    like every other, only reads the state it was handed.
    """
    issues: List[Issue] = []
    for solution in state.report.solutions:
        artifact = state.stderr.get(solution.index)
        if artifact is None or artifact.size <= state.thresholds.stderr_size_bytes:
            continue
        issues.append(
            NoisyStderrIssue(
                solution=solution.path,
                path=artifact.path,
                size=artifact.size,
            )
        )
    return issues


def detect_slow_accepted_solutions(state: RunState) -> List[Issue]:
    """Accepted solutions whose total CPU time over the testset is too high.

    Only a solution declared `accepted` counts: one declared slow is *meant* to
    burn its time limit on every test, and summing that says nothing new.

    Only on a run that evaluated everything, since a sum over part of the
    testset understates the total, and never on a sanitized run, which is slow
    by construction.
    """
    if state.skeleton.sanitized:
        return []
    threshold = state.thresholds.acceptedTotalTimeSeconds
    issues: List[Issue] = []
    for solution in state.report.solutions:
        if solution.expectedOutcome != ExpectedOutcome.ACCEPTED:
            continue
        if not solution.complete or solution.totalTime is None:
            continue
        if solution.totalTime <= threshold:
            continue
        issues.append(
            SlowAcceptedSolutionIssue(
                solution=solution.path,
                totalTime=solution.totalTime,
                threshold=threshold,
            )
        )
    return issues


def detect_sanitizer_findings(state: RunState) -> List[Issue]:
    """Solutions a sanitizer had something to say about.

    Not filtered to the runs that passed, even though those are the case this
    exists for: on a solution that failed, an ASAN or UBSAN finding is very
    often *why* it failed, and dropping it there would hide the one line that
    explains the verdict.

    The flag is read off the report rather than pooled from the groups, for the
    reason `run_report` gives for publishing it: rbx pools over the evaluations
    it actually ran, and a subset run or a `--fail-fast` abort leaves that set
    and the one a reader finds on disk disagreeing. The groups only *name* where
    it fired.
    """
    issues: List[Issue] = []
    for solution in state.report.solutions:
        if not solution.sanitizerWarnings:
            continue
        issues.append(
            SanitizerFindingIssue(
                solution=solution.path,
                groups=[
                    group.name for group in solution.groups if group.sanitizerWarnings
                ],
                log=state.sanitizer_logs.get(solution.path),
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
    detect_asset_compilation,
    detect_linter_warnings,
    detect_duplicate_tests,
    detect_sanitizer_findings,
    detect_borderline_tle,
    detect_hidden_verdicts,
    detect_noisy_stderr,
    detect_slow_accepted_solutions,
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
