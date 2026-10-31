"""Where a problem's issue thresholds and ignore list come from.

The impure half of tuning, kept apart from the detectors for the reason
`config_state` is: a detector is handed thresholds, it never goes looking for an
`env.rbx.yml`.

- Thresholds are the environment's, and only the environment's: they describe
  the judge a problem is headed for, not the problem.
- The ignore list is the contest's plus the problem's. A problem can only add
  to what its contest silences, never take something back.
"""

from typing import List, Optional

from rbx.box import environment
from rbx.box.contest import contest_package
from rbx.box.contest.schema import Contest
from rbx.box.issue_codes import IssueCode, IssueThresholds
from rbx.box.schema import Package


def resolve_thresholds() -> IssueThresholds:
    return environment.get_environment().issues.thresholds


def merge_ignored(contest: Optional[Contest], problem: Package) -> List[IssueCode]:
    """The contest's codes, then the problem's, each once."""
    codes: List[IssueCode] = []
    sources = (contest.issues.ignore if contest is not None else []) + list(
        problem.issues.ignore
    )
    for code in sources:
        if code not in codes:
            codes.append(code)
    return codes


def resolve_ignored(problem: Package) -> List[IssueCode]:
    """The ignore list for the problem in the current directory.

    The enclosing contest is read through `find_contest_without_validation`, which skips the
    per-problem validation `find_contest_package` does: that validation loads
    every problem of the contest, which is no price to pay for one list.
    """
    return merge_ignored(contest_package.find_contest_without_validation(), problem)
