"""Turning issues into something to look at.

Layout, not wording: the markers, the padding, the headline, the contest table.
What an issue *says* belongs to the class that owns it in
`rbx.box.issues.messages`, so the post-run section of `rbx run` and a later
`rbx issues` cannot word the same finding two ways. `summarize` and `explain`
are re-exported here because that is where every caller already looks for them.

Two levels, and the *same* renderer serves both surfaces at each level:

- compact, one line per issue, which is what you get by default everywhere;
- detailed (`-d`), which expands each issue into what it actually means and
  where to look next.
"""

import json
import pathlib
import time
from enum import Enum
from typing import List, Optional

from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from rbx import console
from rbx.box.formatting import href
from rbx.box.issues.messages import explain, summarize
from rbx.box.issues.schema import (
    ContestIssueRow,
    Issue,
    IssueReport,
    IssueSeverity,
)

__all__ = [
    'IssuesFormat',
    'contest_to_json',
    'explain',
    'humanize_since',
    'print_contest_report',
    'print_report',
    'severity_marker',
    'summarize',
    'to_json',
]


class IssuesFormat(str, Enum):
    """How to print issues.

    Lives here rather than in either command so the problem-level and
    contest-level flags cannot drift into accepting different spellings.
    """

    RICH = 'rich'
    JSON = 'json'


_SEVERITY_MARKER = {
    IssueSeverity.ERROR: '[error]x[/error]',
    IssueSeverity.WARNING: '[warning]![/warning]',
}


def severity_marker(issue: Issue) -> str:
    """The `x` or `!` an issue is printed behind.

    Exposed so `rbx summary` can print a findings line that looks exactly like
    `rbx issues`' without reaching into the private table.
    """
    return _SEVERITY_MARKER[issue.severity]


def humanize_since(timestamp: Optional[float]) -> str:
    """ "4m ago", roughly.

    Deliberately coarse. The reader is asking "is this from the run I just did,
    or from before lunch?", and a precise duration invites a precision the
    number does not have.
    """
    if timestamp is None:
        return 'never'
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 60:
        return 'just now'
    for amount, unit in ((60, 'm'), (3600, 'h'), (86400, 'd')):
        if seconds < amount * 60 or unit == 'd':
            return f'{seconds // amount}{unit} ago'
    return f'{seconds // 86400}d ago'


def _resolve(path: pathlib.Path, runs_dir: Optional[str]) -> pathlib.Path:
    """A path relative to the runs dir, made openable from here.

    Compilation logs are stored relative so a package read on another host still
    resolves them; a terminal hyperlink needs the other form.
    """
    if runs_dir is None:
        return path
    return pathlib.Path(runs_dir) / path


def _solution_of(issue: Issue) -> Optional[str]:
    return getattr(issue, 'solution', None)


def _counts(errors: int, warnings: int) -> str:
    """The `2 error(s), 1 warning(s)` fragment.

    Extracted so the run and never-run headlines cannot come to count the same
    findings two different ways.
    """
    parts = []
    if errors:
        parts.append(f'[error]{errors} error(s)[/error]')
    if warnings:
        parts.append(f'[warning]{warnings} warning(s)[/warning]')
    return ', '.join(parts)


def _headline(report: IssueReport) -> str:
    errors = len(report.errors())
    warnings = len(report.warnings())
    if report.neverRun:
        # A never-run problem can still have config findings: those are true
        # about the package whether or not anything was ever run, so the
        # headline counts them rather than reporting an empty package.
        if not errors and not warnings:
            return '[warning]This problem has not been run yet.[/warning]'
        return f'{_counts(errors, warnings)} [warning](not run yet)[/warning]'
    when = f'[info](last run {humanize_since(report.ranAt)})[/info]'
    if not errors and not warnings:
        return f'[success]No issues.[/success] {when}'
    return f'{_counts(errors, warnings)} {when}'


def print_report(report: IssueReport, detailed: bool = False) -> None:
    """The problem-level view, compact or detailed."""
    console.console.print(_headline(report))
    if report.neverRun:
        console.console.print('[info]Run [item]rbx run[/item] to populate it.[/info]')
        # Deliberately no early return. Config findings are true about the
        # package whether or not it was ever run, and suppressing them behind
        # "not run yet" would hide them from exactly the reader who has not run
        # anything and most needs to be told the package is not ready.
    if not report.issues:
        return
    console.console.print()

    for issue in report.issues:
        marker = _SEVERITY_MARKER[issue.severity]
        solution = _solution_of(issue)
        # A `Path`, not the string: `href` takes its display text before it
        # absolutizes, so this shows the declared relative path but links
        # somewhere a terminal can actually open.
        where = f'{href(pathlib.Path(solution))} ' if solution else ''
        console.console.print(f'{marker} {where}{summarize(issue)}')
        if not detailed:
            continue
        for line in explain(issue, report.runsDir):
            # Padded rather than prefixed with spaces: Rich wraps a long line at
            # the console width and a prefix only indents the first row of it,
            # which puts the continuation hard against the left margin.
            console.console.print(
                Padding(Text.from_markup(f'[info]{line}[/info]'), (0, 0, 0, 4))
            )
        console.console.print()


def print_contest_report(rows: List[ContestIssueRow], detailed: bool = False) -> None:
    """The contest-level view: one row per problem, worst first within a row.

    The table answers "which problems need me", not "what exactly is wrong with
    problem C" -- that is what `-d`, or cd'ing into the problem, is for.
    """
    table = Table(title='Issues')
    table.add_column('#', justify='center', style='bold cyan')
    table.add_column('Problem', style='bold')
    table.add_column('Last run', justify='right')
    table.add_column('Err', justify='right')
    table.add_column('Warn', justify='right')
    table.add_column('Worst issue')

    for row in rows:
        if row.failed_to_load:
            table.add_row(
                row.short_name,
                row.name,
                '[error]error[/error]',
                '-',
                '-',
                '[error]could not read this problem[/error]',
            )
            continue
        report = row.report
        errors = len(report.errors())
        warnings = len(report.warnings())
        worst = report.issues[0] if report.issues else None

        if worst is None:
            # A problem nobody has run has nothing to say about verdicts, and
            # nothing wrong with its config either. `-` would read as "clean".
            worst_str = (
                '[warning]not run[/warning]'
                if report.neverRun
                else '[success]-[/success]'
            )
        else:
            solution = _solution_of(worst)
            prefix = f'{solution}: ' if solution else ''
            worst_str = f'{prefix}{summarize(worst)}'

        # A never-run problem still has counts whenever its config says
        # something: those findings are the pre-contest checklist, and a row of
        # dashes would hide the one thing this table exists to surface. The
        # counts stay `-` only when there is genuinely nothing to count.
        if report.neverRun and worst is None:
            errors_str, warnings_str = '-', '-'
        else:
            errors_str = f'[error]{errors}[/error]' if errors else '[info]0[/info]'
            warnings_str = (
                f'[warning]{warnings}[/warning]' if warnings else '[info]0[/info]'
            )

        table.add_row(
            row.short_name,
            row.name,
            '[warning]never[/warning]'
            if report.neverRun
            else humanize_since(report.ranAt),
            errors_str,
            warnings_str,
            worst_str,
        )

    console.console.print(table)

    if not detailed:
        # Only when there is something to expand: the table names one issue per
        # problem, so a contest with findings is exactly the case where the
        # reader needs telling that the rest are a flag away.
        if any(row.report.issues for row in rows if not row.failed_to_load):
            console.console.print(
                '[info]Run [item]rbx contest issues -d[/item] to expand these.[/info]'
            )
        return

    for row in rows:
        if row.failed_to_load or not row.report.issues:
            continue
        console.console.print()
        console.console.rule(f'[item]{row.short_name}. {row.name}[/item]')
        print_report(row.report, detailed=True)


def to_json(report: IssueReport) -> str:
    return json.dumps(report.model_dump(mode='json'), indent=2)


def contest_to_json(rows: List[ContestIssueRow]) -> str:
    return json.dumps(
        {
            'version': IssueReport().version,
            'problems': [
                {
                    'shortName': row.short_name,
                    'name': row.name,
                    'failedToLoad': row.failed_to_load,
                    'report': row.report.model_dump(mode='json'),
                }
                for row in rows
            ],
        },
        indent=2,
    )
