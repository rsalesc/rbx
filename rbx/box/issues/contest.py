"""Collecting issues across every problem in a contest.

Read-only, and deliberately so: this never builds, never runs and never judges.
It reads each problem's `.rbx/runs` exactly the way the problem-level command
does, so a contest-wide view costs about as much as listing the directories.

That means a problem nobody has run shows up as "never run" rather than being
run on the spot. Which is the honest answer -- and at contest level it is
usually the most important row in the table.
"""

import pathlib
from typing import List, Optional

from rbx.box import cd, package, package_utils
from rbx.box.contest.schema import Contest
from rbx.box.issues.config_detectors import detect_all_config
from rbx.box.issues.config_state import ConfigState, collect_config_state
from rbx.box.issues.detectors import detect_all
from rbx.box.issues.run_state import load_run_state
from rbx.box.issues.schema import (
    ContestIssueRow,
    Issue,
    IssueFamily,
    IssueReport,
    IssueSeverity,
)
from rbx.box.schema import Package


async def collect_contest_rows(
    contest: Contest, problems: List[Package]
) -> List[ContestIssueRow]:
    """One row per problem, in contest order.

    A problem that cannot be read becomes a `failed_to_load` row instead of
    aborting the table, matching what `summary.print_contest_summary` does: one
    broken package must not hide the state of the other nine.
    """
    # Every problem in the contest is checked against the same declared
    # languages: "problem C has no Portuguese statement" is a fact about the
    # contest's intent, not about C's own preferences.
    contest_languages = [
        statement.language for statement in contest.expanded_statements
    ]

    rows: List[ContestIssueRow] = []
    for index, problem in enumerate(problems):
        contest_problem = contest.problems[index]
        short_name = contest_problem.short_name
        # `get_path()`, never the raw `path`: it is None for a problem that
        # relies on the default `./{short_name}/` layout, and reading the field
        # directly sends every such problem to the contest root instead.
        problem_path = contest_problem.get_path()

        try:
            with cd.new_package_cd(problem_path):
                package_utils.clear_package_cache()
                config_state = await collect_config_state(
                    problem, contest_languages=contest_languages
                )
                rows.append(
                    ContestIssueRow(
                        short_name=short_name,
                        name=problem.name,
                        report=build_report(
                            package.get_problem_runs_dir(),
                            config_state=config_state,
                        ),
                    )
                )
        except Exception:
            rows.append(
                ContestIssueRow(
                    short_name=short_name,
                    name=problem.name,
                    failed_to_load=True,
                )
            )
    return rows


def _ordered(issues: List[Issue]) -> List[Issue]:
    """Errors before warnings, and config before run inside each band.

    Config first because the run is downstream of the config: "no solution is
    declared as accepted" explains half the verdict failures underneath it, and
    reading it after them is reading the answer after the puzzle.

    `sorted` is stable, so the detector-then-declaration order each family
    already has survives inside each cell.
    """
    return sorted(
        issues,
        key=lambda issue: (
            issue.severity != IssueSeverity.ERROR,
            issue.family != IssueFamily.CONFIG,
        ),
    )


def build_report(
    runs_dir: pathlib.Path,
    config_state: Optional[ConfigState] = None,
) -> IssueReport:
    """Everything known about a problem: what its config says, and what its last
    run revealed.

    Still the single place an `IssueReport` is built, so the problem command,
    the contest table and the post-run section cannot disagree about what "no
    run" or "no issues" looks like.

    `config_state` is optional because a caller may legitimately have none --
    the contest collector can fail to load a package at all. An absent state
    means the run family only; it never means a package with nothing wrong.

    Note that `neverRun` no longer implies an empty `issues`: a problem nobody
    has run still has whatever its config says about it. That is the change
    `ISSUES_FORMAT_VERSION` 2 records.
    """
    config_issues = detect_all_config(config_state) if config_state is not None else []
    state = load_run_state(runs_dir)
    run_issues = detect_all(state) if state is not None else []

    return IssueReport(
        neverRun=state is None,
        ranAt=state.ran_at if state is not None else None,
        runsDir=str(state.runs_dir) if state is not None else None,
        issues=_ordered(config_issues + run_issues),
    )
