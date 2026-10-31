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
    LargeTestcaseIssue,
    LargeTestsetIssue,
    MissingStatementLanguageIssue,
    NoAcceptedSolutionIssue,
    NoSamplesIssue,
    NoValidatorIssue,
    StaleIgnoreRuleIssue,
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


def detect_large_testset(state: ConfigState) -> List[Issue]:
    """The built testset, inputs and answers together, is over budget.

    Silent when nothing is built: an unbuilt testset has no size to report, and
    `rbx build` is what would give it one.
    """
    if state.testset_input_bytes is None or state.testset_answer_bytes is None:
        return []
    threshold = state.thresholds.testset_size_bytes
    if state.testset_input_bytes + state.testset_answer_bytes <= threshold:
        return []
    return [
        LargeTestsetIssue(
            inputBytes=state.testset_input_bytes,
            answerBytes=state.testset_answer_bytes,
            thresholdBytes=threshold,
        )
    ]


def detect_large_testcases(state: ConfigState) -> List[Issue]:
    """Built inputs, or answers, that are each over the per-file budget.

    At most one issue for inputs and one for answers, naming the largest and
    counting the rest: an oversized generator makes a whole group oversized,
    and one issue per test would bury every other finding.
    """
    thresholds = state.thresholds
    issues: List[Issue] = []
    for file, threshold, pick in (
        (
            'input',
            thresholds.testcase_input_size_bytes,
            lambda size: (size.input_path, size.input_bytes),
        ),
        (
            'answer',
            thresholds.testcase_answer_size_bytes,
            lambda size: (size.answer_path, size.answer_bytes),
        ),
    ):
        over = [
            (path, nbytes)
            for path, nbytes in map(pick, state.testcase_sizes)
            if path is not None and nbytes > threshold
        ]
        if not over:
            continue
        path, nbytes = max(over, key=lambda item: item[1])
        issues.append(
            LargeTestcaseIssue(
                file=file,
                path=path,
                size=nbytes,
                count=len(over),
                thresholdBytes=threshold,
            )
        )
    return issues


def detect_stale_ignore_rules(state: ConfigState) -> List[Issue]:
    """Scoped `issues.ignore` rules that match nothing in the package."""
    return [StaleIgnoreRuleIssue(rule=rule) for rule in state.stale_ignore_rules]


CONFIG_DETECTORS: List[Callable[[ConfigState], List[Issue]]] = [
    detect_no_accepted_solution,
    detect_no_validator,
    detect_no_samples,
    detect_empty_test_groups,
    detect_large_testset,
    detect_large_testcases,
    detect_missing_statement_languages,
    detect_explanation_languages,
    detect_stale_ignore_rules,
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
