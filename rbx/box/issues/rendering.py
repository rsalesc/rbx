"""Turning issues into something to look at.

Wording lives here and only here. The detectors produce facts; this module is
the one place that decides an unmet expectation reads as "expected wrong-answer,
got accepted", so the post-run section of `rbx run` and a later `rbx issues`
cannot word the same finding two ways.

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
from rbx.box.formatting import get_formatted_time, href
from rbx.box.issues.schema import (
    BorderlineTleIssue,
    CompilationFailedIssue,
    CompilationWarningsIssue,
    ContestIssueRow,
    HiddenVerdictIssue,
    Issue,
    IssueReport,
    IssueSeverity,
    TightTimeMarginIssue,
    UnexpectedScoreIssue,
    UnmetExpectationIssue,
    UntunedLimitsIssue,
)


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


def _verdicts(outcomes) -> str:
    return ' '.join(outcome.name for outcome in outcomes)


def summarize(issue: Issue) -> str:
    """One line: what is wrong, and with what."""
    if isinstance(issue, UnmetExpectationIssue):
        # Never name the pooled expectation when the pooled layer is the one
        # that held -- doing so accuses an expectation that did its job. The
        # groups are the honest answer there.
        if not issue.pooledMatchesExpectation:
            got = issue.got.name if issue.got is not None else 'nothing'
            return f'expected {issue.expected}, got {got}'
        if issue.failedGroups:
            return f'failed group(s): {", ".join(issue.failedGroups)}'
        return 'did not meet its expectation'
    if isinstance(issue, UnexpectedScoreIssue):
        low, high = issue.expectedScore
        return (
            f'scored {issue.score}/{issue.maxScore}, expected between {low} and {high}'
        )
    if isinstance(issue, CompilationFailedIssue):
        return (
            f'failed to compile: {issue.reason}'
            if issue.reason
            else 'failed to compile'
        )
    if isinstance(issue, CompilationWarningsIssue):
        return f'compiled with {len(issue.warnings)} warning(s)'
    if isinstance(issue, BorderlineTleIssue):
        return 'slow only within 2x the time limit'
    if isinstance(issue, HiddenVerdictIssue):
        return f'a soft TLE hid: {_verdicts(issue.verdicts)}'
    if isinstance(issue, TightTimeMarginIssue):
        return (
            f'used {get_formatted_time(int(issue.maxTime * 1000))} of a '
            f'{get_formatted_time(int(issue.timeLimit * 1000))} limit'
        )
    if isinstance(issue, UntunedLimitsIssue):
        return 'the time limit may not be tuned to this machine'
    return 'unknown issue'


def explain(issue: Issue, runs_dir: Optional[str] = None) -> List[str]:
    """The detail lines under an issue in `-d` mode.

    Empty when the one-liner already says everything -- padding every issue out
    to a paragraph would make the detailed view harder to read than the compact
    one, not easier.
    """
    if isinstance(issue, UnmetExpectationIssue):
        lines = [f'expected: {issue.expected}']
        if issue.got is not None:
            lines.append(f'got:      {issue.got.name}')
        if issue.failedGroups:
            lines.append(f'groups:   {", ".join(issue.failedGroups)}')
        if issue.pooledMatchesExpectation and issue.failedGroups:
            lines.append(
                'the solution-wide expectation held; only per-group ones failed'
            )
        return lines
    if isinstance(issue, (CompilationFailedIssue, CompilationWarningsIssue)):
        lines = []
        for warning in getattr(issue, 'warnings', [])[:5]:
            flag = f' [{warning.flag}]' if warning.flag else ''
            lines.append(f'{warning.file}:{warning.line}{flag} {warning.msg}')
        remaining = len(getattr(issue, 'warnings', [])) - 5
        if remaining > 0:
            lines.append(f'... and {remaining} more')
        lines.append(f'log: {href(_resolve(issue.log, runs_dir))}')
        return lines
    if isinstance(issue, BorderlineTleIssue):
        lines = [
            'rbx judges at 2x the time limit and reports TLE past 1x, so this '
            'solution timed out but finished inside the doubled window -- the '
            'testset does not prove it is decisively slow.'
        ]
        if issue.groups:
            lines.append(f'groups:   {", ".join(issue.groups)}')
        if issue.doubleTlVerdicts:
            lines.append(
                f'without a TL it would have: {_verdicts(issue.doubleTlVerdicts)}'
            )
        return lines
    if isinstance(issue, HiddenVerdictIssue):
        lines = [
            'reported TLE at 1x the time limit, but underneath it was doing '
            'something the declaration does not allow.'
        ]
        if issue.groups:
            lines.append(f'groups:   {", ".join(issue.groups)}')
        return lines
    if isinstance(issue, TightTimeMarginIssue):
        ratio = issue.maxTime / issue.timeLimit
        return [
            f'{ratio:.0%} of the time limit on this machine. Fine here, tight '
            f'on a slower judge.'
        ]
    if isinstance(issue, UntunedLimitsIssue):
        return [
            'Solutions failed their expectations by being too fast or too slow, '
            'and this run used the limits declared in the package rather than a '
            'profile. They may simply not suit this hardware.',
            f'affected: {", ".join(issue.affectedSolutions)}',
            'run [item]rbx time[/item] to estimate limits here.',
        ]
    return []


def _headline(report: IssueReport) -> str:
    if report.neverRun:
        return '[warning]This problem has not been run yet.[/warning]'
    errors = len(report.errors())
    warnings = len(report.warnings())
    when = f'[info](last run {humanize_since(report.ranAt)})[/info]'
    if not errors and not warnings:
        return f'[success]No issues.[/success] {when}'
    parts = []
    if errors:
        parts.append(f'[error]{errors} error(s)[/error]')
    if warnings:
        parts.append(f'[warning]{warnings} warning(s)[/warning]')
    return f'{", ".join(parts)} {when}'


def print_report(report: IssueReport, detailed: bool = False) -> None:
    """The problem-level view, compact or detailed."""
    console.console.print(_headline(report))
    if report.neverRun:
        console.console.print('[info]Run [item]rbx run[/item] to populate it.[/info]')
        return
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
        if report.neverRun:
            table.add_row(
                row.short_name,
                row.name,
                '[warning]never[/warning]',
                '-',
                '-',
                '[warning]not run[/warning]',
            )
            continue

        errors = len(report.errors())
        warnings = len(report.warnings())
        worst = report.issues[0] if report.issues else None
        if worst is None:
            worst_str = '[success]-[/success]'
        else:
            solution = _solution_of(worst)
            prefix = f'{solution}: ' if solution else ''
            worst_str = f'{prefix}{summarize(worst)}'

        table.add_row(
            row.short_name,
            row.name,
            humanize_since(report.ranAt),
            f'[error]{errors}[/error]' if errors else '[info]0[/info]',
            f'[warning]{warnings}[/warning]' if warnings else '[info]0[/info]',
            worst_str,
        )

    console.console.print(table)

    if not detailed:
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
