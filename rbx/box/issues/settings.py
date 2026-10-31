"""Where a problem's issue thresholds and ignore list come from.

The impure half of tuning, kept apart from the detectors for the reason
`config_state` is: a detector is handed thresholds, it never goes looking for an
`env.rbx.yml`.

- Thresholds are the environment's, and only the environment's: they describe
  the judge a problem is headed for, not the problem.
- The ignore list is the contest's plus the problem's. A problem can only add
  to what its contest silences, never take something back.
"""

from typing import Iterable, List, Optional, Union

from rbx.box import environment
from rbx.box.contest import contest_package
from rbx.box.contest.schema import Contest
from rbx.box.issue_codes import IgnoreRule, IssueCode, IssueThresholds, as_rule
from rbx.box.issues.schema import Issue, subject_of
from rbx.box.schema import Package


def resolve_thresholds() -> IssueThresholds:
    return environment.get_environment().issues.thresholds


def merge_ignored(contest: Optional[Contest], problem: Package) -> List[IgnoreRule]:
    """The contest's rules, then the problem's, each once.

    A plain code comes back as a rule with no `on`, so every caller deals in
    one shape.
    """
    rules: List[IgnoreRule] = []
    sources = (contest.issues.rules() if contest is not None else []) + list(
        problem.issues.rules()
    )
    for rule in sources:
        if rule not in rules:
            rules.append(rule)
    return rules


def silencing_rule(
    issue: Issue, rules: Iterable[Union[IssueCode, IgnoreRule]]
) -> Optional[IgnoreRule]:
    """The first rule that silences `issue`, if any.

    The first, so `rbx issues --all` credits the rule a reader meets first when
    reading the list top to bottom -- the contest's before the problem's.
    """
    subject = subject_of(issue)
    for entry in rules:
        rule = as_rule(entry)
        if rule.matches(issue.code, subject):
            return rule
    return None


def resolve_ignored(problem: Package) -> List[IgnoreRule]:
    """The ignore list for the problem in the current directory.

    The enclosing contest is read through `find_contest_without_validation`, which skips the
    per-problem validation `find_contest_package` does: that validation loads
    every problem of the contest, which is no price to pay for one list.
    """
    return merge_ignored(contest_package.find_contest_without_validation(), problem)
