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
import os
import pathlib
import time
from enum import Enum
from typing import List, Optional

from rich.markup import escape
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from rbx import console
from rbx.box.formatting import get_formatted_memory, href
from rbx.box.issue_codes import DOCS_URL, IgnoreRule
from rbx.box.issues.schema import (
    AssetCompilationWarningsIssue,
    BorderlineTleIssue,
    BoundsNotHitIssue,
    CompilationFailedIssue,
    CompilationWarningsIssue,
    ContestIssueRow,
    DuplicateTestIssue,
    EmptyTestGroupIssue,
    ExplanationMissingLanguageIssue,
    HiddenVerdictIssue,
    Issue,
    IssueReport,
    IssueSeverity,
    LargeTestcaseIssue,
    LargeTestsetIssue,
    LinterWarningsIssue,
    MissingStatementLanguageIssue,
    NoAcceptedSolutionIssue,
    NoisyStderrIssue,
    NoSamplesIssue,
    NoValidatorIssue,
    SanitizerFindingIssue,
    SlowAcceptedSolutionIssue,
    StaleIgnoreRuleIssue,
    UnexpectedScoreIssue,
    UnmetExpectationIssue,
    UntunedLimitsIssue,
)
from rbx.box.sanitizers import compilation_warnings, warning_stack
from rbx.box.scoring import partial


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

    Normalized because not every relative path points *into* the runs dir: a
    sanitizer log is kept beside it, so joining gives `.rbx/runs/../warnings/x`,
    which is right but reads as noise and wraps a terminal line for no reason.
    """
    if runs_dir is None:
        return path
    return pathlib.Path(os.path.normpath(pathlib.Path(runs_dir) / path))


def _solution_of(issue: Issue) -> Optional[str]:
    """The file an issue is about: a solution, or any other file of the package."""
    return getattr(issue, 'solution', None) or getattr(issue, 'path', None)


def _compiled_with(warnings) -> str:
    flags = compilation_warnings.summarize_flags(w.flag for w in warnings)
    breakdown = f' [warning]({flags})[/warning]' if flags else ''
    return f'compiled with {len(warnings)} warning(s){breakdown}'


def _lint_locations(locations: List[str]) -> str:
    if not locations:
        return ''
    if len(locations) == 1:
        return f' at {locations[0]}'
    return f' at lines {", ".join(locations)}'


def _linters(issue: LinterWarningsIssue) -> List[str]:
    return sorted({f.linter for f in issue.findings if f.linter})


def _summarize_lints(issue: LinterWarningsIssue) -> str:
    grouped = warning_stack.group_linter_messages(issue.findings)  # type: ignore[arg-type]
    if len(grouped) == 1:
        message, locations = grouped[0]
        linters = _linters(issue)
        # Who and where lead, because a linter's message is a sentence or two
        # long and a location trailing it gets lost at the end of the line.
        who = f'{linters[0]} linter' if len(linters) == 1 else 'linter'
        return f'{who}{_lint_locations(locations)}: {escape(message)}'
    linters = ', '.join(_linters(issue))
    which = f' [warning]({linters})[/warning]' if linters else ''
    return f'{len(issue.findings)} linter warning(s){which}'


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
        low, high = (partial.format_score(bound) for bound in issue.expectedScore)
        score = partial.format_score(issue.score)
        return f'scored {score}/{issue.maxScore}, expected between {low} and {high}'
    if isinstance(issue, CompilationFailedIssue):
        return (
            f'failed to compile: {issue.reason}'
            if issue.reason
            else 'failed to compile'
        )
    if isinstance(issue, (CompilationWarningsIssue, AssetCompilationWarningsIssue)):
        return _compiled_with(issue.warnings)
    if isinstance(issue, LinterWarningsIssue):
        return _summarize_lints(issue)
    if isinstance(issue, DuplicateTestIssue):
        return warning_stack.describe_duplicate_test(issue.duplicate)
    if isinstance(issue, StaleIgnoreRuleIssue):
        return (
            f'the [item]issues.ignore[/item] rule for [item]{issue.rule.code.value}[/item] '
            f'on [item]{escape(issue.rule.on or "")}[/item] matches nothing in the package'
        )
    if isinstance(issue, BoundsNotHitIssue):
        where = f'in group [item]{issue.group}[/item], ' if issue.group else ''
        bounds = ', '.join(
            f'[item]{escape(b.name)}[/item] ({" and ".join(b.missing)})'
            for b in issue.bounds
        )
        return f'{where}no test hits {bounds}'
    if isinstance(issue, BorderlineTleIssue):
        return 'slow only within 2x the time limit'
    if isinstance(issue, HiddenVerdictIssue):
        return f'a soft TLE hid: {_verdicts(issue.verdicts)}'
    if isinstance(issue, NoisyStderrIssue):
        return f'wrote {get_formatted_memory(issue.size)} to stderr on one test'
    if isinstance(issue, SanitizerFindingIssue):
        return 'a sanitizer fired while running this solution'
    if isinstance(issue, SlowAcceptedSolutionIssue):
        return (
            f'took {issue.totalTime:.1f}s over the whole testset '
            f'(budget {issue.threshold:g}s)'
        )
    if isinstance(issue, LargeTestsetIssue):
        return (
            f'the built testset is {get_formatted_memory(issue.totalBytes)} '
            f'(budget {get_formatted_memory(issue.thresholdBytes)})'
        )
    if isinstance(issue, LargeTestcaseIssue):
        others = f' and {issue.count - 1} more' if issue.count > 1 else ''
        return (
            f'{issue.file} [item]{issue.path}[/item] is '
            f'{get_formatted_memory(issue.size)}{others} '
            f'(budget {get_formatted_memory(issue.thresholdBytes)} per {issue.file})'
        )
    if isinstance(issue, UntunedLimitsIssue):
        return 'the time limit may not be tuned to this machine'
    if isinstance(issue, NoAcceptedSolutionIssue):
        return 'no solution is declared as accepted'
    if isinstance(issue, NoValidatorIssue):
        return 'the problem has no validator'
    if isinstance(issue, NoSamplesIssue):
        return 'the problem has no samples'
    if isinstance(issue, EmptyTestGroupIssue):
        return f'test group [item]{issue.group}[/item] has no tests'
    if isinstance(issue, MissingStatementLanguageIssue):
        if issue.hasNoStatements:
            return 'the problem has no statement'
        return f'no statement for language(s): {", ".join(issue.missing)}'
    if isinstance(issue, ExplanationMissingLanguageIssue):
        return (
            f'sample {issue.sample}: explanation missing for '
            f'language(s): {", ".join(issue.missing)}'
        )
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
    if isinstance(issue, StaleIgnoreRuleIssue):
        return [
            'usually a solution, file or group that was renamed: the rule now '
            'silences nothing, and the finding it was written for is back under '
            'its new name.',
            'point `on` at the new name, or delete the rule.',
        ]
    if isinstance(issue, BoundsNotHitIssue):
        scope = 'of this group ' if issue.group else ''
        return [
            f'every test {scope}is valid, but none reaches these extremes, so a '
            'solution too slow or wrong at the limits is never asked to run there.',
            'each name is the one the validator reads the value under, like `N` '
            'in `inf.readInt(1, MAX_N, "N")`.',
        ]
    if isinstance(issue, DuplicateTestIssue):
        how = (
            'the same generator call makes both tests'
            if issue.duplicate.reason == 'call'
            else 'their inputs are byte-identical'
        )
        lines = [
            f'{how}, so the second costs judging time without testing anything new.',
            'if you meant it, end its testplan line with `@allow-duplicate`, or '
            'set `allowDuplicate` on its group.',
        ]
        if issue.duplicate.name:
            lines.append(
                f'to ignore just this one: `on: {escape(issue.duplicate.name)}` '
                'under `issues.ignore`.'
            )
        return lines
    if isinstance(issue, LinterWarningsIssue):
        lines = []
        if issue.assetKind is not None:
            lines.append(f"this is the package's {issue.assetKind.value}")
        for finding in issue.findings:
            location = warning_stack.format_linter_location(finding)  # type: ignore[arg-type]
            where = f'{location} ' if location else ''
            who = f' ({finding.linter})' if finding.linter else ''
            lines.append(f'{where}{escape(finding.message)}{who}')
        for linter in _linters(issue):
            lines.append(
                f'a `{linter}-linter: disable` comment in the file silences '
                f'the {linter} linter there'
            )
        return lines
    if isinstance(
        issue,
        (
            CompilationFailedIssue,
            CompilationWarningsIssue,
            AssetCompilationWarningsIssue,
        ),
    ):
        lines = []
        if isinstance(issue, AssetCompilationWarningsIssue):
            lines.append(f"this is the package's {issue.assetKind.value}")
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
    if isinstance(issue, NoisyStderrIssue):
        return [
            'Stderr this large is almost always debug output left behind. It '
            'costs time on every testcase, and some judges reject a submission '
            'that produces it.',
            f'stderr: {href(_resolve(issue.path, runs_dir))}',
        ]
    if isinstance(issue, SanitizerFindingIssue):
        lines = [
            'ASAN or UBSAN found something -- an out-of-bounds access, signed '
            'overflow, an uninitialised read -- while this solution ran. The '
            'verdict may well be fine here and undefined on the judge.'
        ]
        if issue.groups:
            lines.append(f'groups:   {", ".join(issue.groups)}')
        if issue.log is not None:
            lines.append(f'log: {href(_resolve(issue.log, runs_dir))}')
        return lines
    if isinstance(issue, SlowAcceptedSolutionIssue):
        return [
            'Every testcase may fit the time limit and the sum still cost the '
            'judge this much on every submission of a correct solution.',
            'drop redundant large tests, or raise '
            '[item]issues.thresholds.acceptedTotalTimeSeconds[/item] in '
            '[item]env.rbx.yml[/item].',
        ]
    if isinstance(issue, LargeTestsetIssue):
        return [
            f'inputs:  {get_formatted_memory(issue.inputBytes)}',
            f'answers: {get_formatted_memory(issue.answerBytes)}',
            'Judges cap package sizes, and every test is copied for every '
            'submission. Drop redundant large tests, or raise '
            '[item]issues.thresholds.testsetSizeMb[/item] in '
            '[item]env.rbx.yml[/item].',
        ]
    if isinstance(issue, LargeTestcaseIssue):
        setting = (
            'testcaseInputSizeMb' if issue.file == 'input' else 'testcaseAnswerSizeMb'
        )
        return [
            f'{issue.count} {issue.file}(s) over the budget; the largest is '
            f'{href(issue.path)}.',
            'Some judges cap the size of one test file, and a file this large is '
            'slow to copy and read on every submission. Shrink the test, or raise '
            f'[item]issues.thresholds.{setting}[/item] in [item]env.rbx.yml[/item].',
        ]
    if isinstance(issue, UntunedLimitsIssue):
        return [
            'Solutions failed their expectations by being too fast or too slow, '
            'and this run used the limits declared in the package rather than a '
            'profile. They may simply not suit this hardware.',
            f'affected: {", ".join(issue.affectedSolutions)}',
            'run [item]rbx time[/item] to estimate limits here.',
        ]
    if isinstance(issue, NoAcceptedSolutionIssue):
        return [
            'Without an accepted solution nothing establishes what a correct '
            'output is, so every output this package generates is unverified.',
            'declare one with [item]outcome: accepted[/item] in '
            '[item]problem.rbx.yml[/item].',
        ]
    if isinstance(issue, NoValidatorIssue):
        return [
            'Nothing checks that the generated tests obey the constraints the '
            'statement promises.',
        ]
    if isinstance(issue, MissingStatementLanguageIssue):
        if issue.hasNoStatements:
            return []
        return [
            f'the contest wants: {", ".join(issue.missing)}',
        ]
    if isinstance(issue, ExplanationMissingLanguageIssue):
        return [
            f'file: {href(issue.path)}',
            'A language this file does not define is not an error at build '
            'time -- the explanation is simply left out of that language, with '
            'nothing said about it.',
        ]
    return []


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


def _print_issue(
    issue: Issue,
    runs_dir: Optional[str],
    detailed: bool,
    ignored: bool = False,
    rule: Optional[IgnoreRule] = None,
) -> None:
    marker = '[info]-[/info]' if ignored else _SEVERITY_MARKER[issue.severity]
    solution = _solution_of(issue)
    # A `Path`, not the string: `href` takes its display text before it
    # absolutizes, so this shows the declared relative path but links
    # somewhere a terminal can actually open.
    where = f'{href(pathlib.Path(solution))} ' if solution else ''
    # The code trails the line rather than leading it: the reader scans for
    # what is wrong first, and needs the code only to look it up or silence it.
    tag = 'ignored ' if ignored else ''
    console.console.print(
        f'{marker} {where}{summarize(issue)} [info]({tag}{issue.code.value})[/info]'
    )
    # Not held back for `-d`: a reason is short, and the reason a finding is
    # silenced is the whole point of listing a silenced one.
    if rule is not None and rule.reason:
        console.console.print(
            Padding(
                Text.from_markup(f'[info]reason: {escape(rule.reason)}[/info]'),
                (0, 0, 0, 4),
            )
        )
    if not detailed:
        return
    for line in explain(issue, runs_dir):
        # Padded rather than prefixed with spaces: Rich wraps a long line at
        # the console width and a prefix only indents the first row of it,
        # which puts the continuation hard against the left margin.
        console.console.print(
            Padding(Text.from_markup(f'[info]{line}[/info]'), (0, 0, 0, 4))
        )
    console.console.print()


def print_docs_hint() -> None:
    """The one line pointing at the page that documents every code."""
    console.console.print(
        f'[info]About these codes, and ignoring them: [item]{DOCS_URL}[/item][/info]'
    )


def print_report(
    report: IssueReport,
    detailed: bool = False,
    show_ignored: bool = False,
    docs_hint: bool = True,
) -> None:
    """The problem-level view, compact or detailed.

    `docs_hint` is off only where a caller prints many reports in a row and
    the hint once after all of them.
    """
    console.console.print(_headline(report))
    if report.neverRun:
        console.console.print('[info]Run [item]rbx run[/item] to populate it.[/info]')
        # Deliberately no early return. Config findings are true about the
        # package whether or not it was ever run, and suppressing them behind
        # "not run yet" would hide them from exactly the reader who has not run
        # anything and most needs to be told the package is not ready.
    shown_ignored = report.ignored if show_ignored else []
    if not report.issues and not shown_ignored:
        if report.ignored:
            _print_ignored_note(report)
        return
    console.console.print()

    for issue in report.issues:
        _print_issue(issue, report.runsDir, detailed)
    # Index for index; a report from before `ignoredBy` existed has none.
    rules: List[Optional[IgnoreRule]] = list(report.ignoredBy)
    rules += [None] * (len(shown_ignored) - len(rules))
    for issue, rule in zip(shown_ignored, rules):
        _print_issue(issue, report.runsDir, detailed, ignored=True, rule=rule)

    if not detailed:
        console.console.print()
    if report.ignored and not show_ignored:
        _print_ignored_note(report)
    if docs_hint:
        print_docs_hint()


def _print_ignored_note(report: IssueReport) -> None:
    codes = sorted({issue.code.value for issue in report.ignored})
    console.console.print(
        f'[info]{len(report.ignored)} more silenced by [item]issues.ignore[/item] '
        f'({", ".join(codes)}); [item]rbx issues --all[/item] shows them.[/info]'
    )


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
            print_docs_hint()
        return

    printed = False
    for row in rows:
        if row.failed_to_load or not row.report.issues:
            continue
        console.console.print()
        console.console.rule(f'[item]{row.short_name}. {row.name}[/item]')
        print_report(row.report, detailed=True, docs_hint=False)
        printed = True
    if printed:
        print_docs_hint()


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
