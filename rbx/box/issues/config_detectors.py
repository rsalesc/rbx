"""The config detectors: pure functions from a package's config to its issues.

The mirror of `detectors`, under the same contract -- a detector reads only the
`ConfigState` it was handed, never a `Package`, a path, a console or a
contextvar. What that buys is what it bought there: the whole suite runs against
states built by hand, with no package on disk and no sandbox.

These answer a different question from the run detectors, which is why they are
a second family rather than more entries in the first. A run detector asks what
happened; these ask whether the package was ever in a state worth running. That
difference is also why they sort first: "no solution is declared as accepted"
explains half the verdict failures underneath it.
"""

from typing import Callable, List

from rbx.box.issues.config_state import ConfigState
from rbx.box.issues.schema import (
    EmptyTestGroupIssue,
    ExplanationMissingLanguageIssue,
    Issue,
    IssueSeverity,
    MissingStatementLanguageIssue,
    NoAcceptedSolutionIssue,
    NoSamplesIssue,
    NoValidatorIssue,
)
from rbx.box.schema import ExpectedOutcome

# The group `GenerationTestcaseEntry.is_sample` recognizes.
SAMPLES_GROUP = 'samples'


def detect_no_accepted_solution(state: ConfigState) -> List[Issue]:
    """No solution claims to be correct.

    `accepted_or_tle` counts: it still asserts the solution is correct, only
    that it may be too slow, so it does pin down what a correct output is.
    """
    for solution in state.solutions:
        if solution.outcome in (
            ExpectedOutcome.ACCEPTED,
            ExpectedOutcome.ACCEPTED_OR_TLE,
        ):
            return []
    return [NoAcceptedSolutionIssue()]


def detect_no_validator(state: ConfigState) -> List[Issue]:
    """Nothing checks that the generated tests obey the stated constraints."""
    if state.has_validator:
        return []
    return [NoValidatorIssue()]


def detect_no_samples(state: ConfigState) -> List[Issue]:
    """The statement will have nothing to show the contestant."""
    if state.sample_count > 0:
        return []
    return [NoSamplesIssue()]


def detect_empty_test_groups(state: ConfigState) -> List[Issue]:
    """A declared group that generated nothing.

    The samples group is skipped: an empty one is already reported, and better,
    by `detect_no_samples`. Naming it twice would make one mistake look like
    two, which is the same reason `detect_unmet_expectations` skips a solution
    whose score detector already spoke for it.
    """
    return [
        EmptyTestGroupIssue(group=group)
        for group, count in state.group_test_counts.items()
        if count == 0 and group != SAMPLES_GROUP
    ]


def detect_missing_statement_languages(state: ConfigState) -> List[Issue]:
    """No statement at all, or none for a language the contest declares.

    Silent outside a contest, where rbx has no way to know which languages were
    wanted: a problem shipping only English is not thereby missing Portuguese,
    and guessing it is would fire on almost every standalone problem.
    """
    if not state.statement_languages:
        return [MissingStatementLanguageIssue(hasNoStatements=True)]
    have = set(state.statement_languages)
    missing = [lang for lang in state.contest_languages if lang not in have]
    if not missing:
        return []
    return [MissingStatementLanguageIssue(missing=missing)]


def detect_explanation_languages(state: ConfigState) -> List[Issue]:
    """A blocks-file explanation that covers only some of the statements.

    One issue per sample, because each explanation file is authored separately
    and fixed separately. Compared against the *problem's* statement languages,
    not the contest's: an explanation can only be expected to cover a language
    the problem actually has a statement in.
    """
    issues: List[Issue] = []
    for index, languages in sorted(state.explanation_languages.items()):
        path = state.explanation_paths.get(index)
        if path is None:
            continue
        covered = set(languages)
        missing = [lang for lang in state.statement_languages if lang not in covered]
        if not missing:
            continue
        issues.append(
            ExplanationMissingLanguageIssue(sample=index, path=path, missing=missing)
        )
    return issues


CONFIG_DETECTORS: List[Callable[[ConfigState], List[Issue]]] = [
    detect_no_accepted_solution,
    detect_no_validator,
    detect_no_samples,
    detect_empty_test_groups,
    detect_missing_statement_languages,
    detect_explanation_languages,
]


def detect_all_config(state: ConfigState) -> List[Issue]:
    """Every config issue, worst first.

    Sorted the way `detect_all` sorts: stable, and by severity only, so the
    detector order and the declaration order survive inside each band.
    """
    issues: List[Issue] = []
    for detector in CONFIG_DETECTORS:
        issues.extend(detector(state))
    return sorted(issues, key=lambda issue: issue.severity != IssueSeverity.ERROR)
