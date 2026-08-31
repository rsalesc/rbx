"""Collecting issues across every problem in a contest.

Read-only, and deliberately so: this never builds, never runs and never judges.
It reads each problem's `.rbx/runs` exactly the way the problem-level command
does, so a contest-wide view costs about as much as listing the directories.

That means a problem nobody has run shows up as "never run" rather than being
run on the spot. Which is the honest answer -- and at contest level it is
usually the most important row in the table.
"""

import pathlib
from typing import List

from rbx.box import cd, package, package_utils
from rbx.box.contest.schema import Contest
from rbx.box.issues.detectors import detect_all
from rbx.box.issues.run_state import load_run_state
from rbx.box.issues.schema import ContestIssueRow, IssueReport
from rbx.box.schema import Package


def collect_contest_rows(
    contest: Contest, problems: List[Package]
) -> List[ContestIssueRow]:
    """One row per problem, in contest order.

    A problem that cannot be read becomes a `failed_to_load` row instead of
    aborting the table, matching what `summary.print_contest_summary` does: one
    broken package must not hide the state of the other nine.
    """
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
                rows.append(
                    ContestIssueRow(
                        short_name=short_name,
                        name=problem.name,
                        report=build_report(package.get_problem_runs_dir()),
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


def build_report(runs_dir: pathlib.Path) -> IssueReport:
    """Everything the last run in `runs_dir` reveals.

    The single place a `RunState` becomes an `IssueReport`, so the problem
    command, the contest table and the post-run section cannot disagree about
    what "no run" or "no issues" looks like.
    """
    state = load_run_state(runs_dir)
    if state is None:
        return IssueReport(neverRun=True)
    return IssueReport(
        ranAt=state.ran_at,
        runsDir=str(state.runs_dir),
        issues=detect_all(state),
    )
