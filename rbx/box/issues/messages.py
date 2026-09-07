"""How each kind of issue words itself.

The wording lives here and only here, so the post-run section of `rbx run`, a
later `rbx issues` and `rbx summary` cannot word the same finding three ways.
`rbx.box.issues.rendering` owns the *layout* -- markers, padding, tables -- and
asks this module what to say.

One class per issue kind, registered against it, rather than one function
branching over fourteen kinds. The point is that everything said about a kind
sits in one place next to the kind's name: its one-liner and its detail lines
are two methods on the same class, and adding a kind is adding a class rather
than editing the middle of two long chains. `MESSAGES_BY_KIND` is checked against the
`Issue` union at import time, so a kind that forgets its message is a loud
error at startup instead of an "unknown issue" line in front of a user.

Two levels, because both surfaces show both:

- `summary()`, one line: what is wrong, and with what;
- `details()`, the lines `-d` expands it into. Empty by default -- padding
  every issue out to a paragraph makes the detailed view harder to read than
  the compact one, not easier, so a kind whose one-liner already says
  everything simply does not override it.
"""

import pathlib
import typing
from typing import Callable, Dict, Generic, Iterable, List, Optional, Type, TypeVar

from rbx.box.compilation_findings import CompilationWarning
from rbx.box.formatting import get_formatted_time, href
from rbx.box.issues.schema import (
    BorderlineTleIssue,
    CompilationFailedIssue,
    CompilationWarningsIssue,
    EmptyTestGroupIssue,
    ExplanationMissingLanguageIssue,
    HiddenVerdictIssue,
    Issue,
    MissingStatementLanguageIssue,
    NoAcceptedSolutionIssue,
    NoSamplesIssue,
    NoValidatorIssue,
    TightTimeMarginIssue,
    UnexpectedScoreIssue,
    UnmetExpectationIssue,
    UntunedLimitsIssue,
)

IssueT = TypeVar('IssueT')


def _verdicts(outcomes) -> str:
    return ' '.join(outcome.name for outcome in outcomes)


class IssueMessage(Generic[IssueT]):
    """What one kind of issue says about itself.

    `runs_dir` is carried rather than passed to `details()` because it is
    context about *where the issue was read from*, not about the issue: a
    compilation log is stored as `compilation/0.log` so a package read on
    another host still resolves it, and only the reader knows what that hangs
    off. Kinds that store no paths ignore it.
    """

    def __init__(self, issue: IssueT, runs_dir: Optional[str] = None):
        self.issue = issue
        self.runs_dir = runs_dir

    def summary(self) -> str:
        raise NotImplementedError

    def details(self) -> List[str]:
        return []

    def _resolve(self, path: pathlib.Path) -> pathlib.Path:
        """A path relative to the runs dir, made openable from here.

        Compilation logs are stored relative so a package read on another host
        still resolves them; a terminal hyperlink needs the other form.
        """
        if self.runs_dir is None:
            return path
        return pathlib.Path(self.runs_dir) / path


MESSAGES_BY_KIND: Dict[type, Type[IssueMessage]] = {}


def messages_for(
    issue_cls: type,
) -> Callable[[Type[IssueMessage]], Type[IssueMessage]]:
    """Register a message class as the wording for an issue kind."""

    def decorator(message_cls: Type[IssueMessage]) -> Type[IssueMessage]:
        MESSAGES_BY_KIND[issue_cls] = message_cls
        return message_cls

    return decorator


@messages_for(UnmetExpectationIssue)
class UnmetExpectationMessage(IssueMessage[UnmetExpectationIssue]):
    def summary(self) -> str:
        # Never name the pooled expectation when the pooled layer is the one
        # that held -- doing so accuses an expectation that did its job. The
        # groups are the honest answer there.
        if not self.issue.pooledMatchesExpectation:
            got = self.issue.got.name if self.issue.got is not None else 'nothing'
            return f'expected {self.issue.expected}, got {got}'
        if self.issue.failedGroups:
            return f'failed group(s): {", ".join(self.issue.failedGroups)}'
        return 'did not meet its expectation'

    def details(self) -> List[str]:
        lines = [f'expected: {self.issue.expected}']
        if self.issue.got is not None:
            lines.append(f'got:      {self.issue.got.name}')
        if self.issue.failedGroups:
            lines.append(f'groups:   {", ".join(self.issue.failedGroups)}')
        if self.issue.pooledMatchesExpectation and self.issue.failedGroups:
            lines.append(
                'the solution-wide expectation held; only per-group ones failed'
            )
        return lines


@messages_for(UnexpectedScoreIssue)
class UnexpectedScoreMessage(IssueMessage[UnexpectedScoreIssue]):
    def summary(self) -> str:
        low, high = self.issue.expectedScore
        return (
            f'scored {self.issue.score}/{self.issue.maxScore}, '
            f'expected between {low} and {high}'
        )


_CompilationIssueT = TypeVar(
    '_CompilationIssueT', CompilationFailedIssue, CompilationWarningsIssue
)


class _CompilationMessage(
    IssueMessage[_CompilationIssueT], Generic[_CompilationIssueT]
):
    """The shared detail lines of the two compilation kinds.

    Both end in a link to the same log; only one of them carries the warnings
    that go above it, which is what `_warnings` is for.
    """

    def _warnings(self) -> List[CompilationWarning]:
        return []

    def details(self) -> List[str]:
        warnings = self._warnings()
        lines = []
        for warning in warnings[:5]:
            flag = f' [{warning.flag}]' if warning.flag else ''
            lines.append(f'{warning.file}:{warning.line}{flag} {warning.msg}')
        remaining = len(warnings) - 5
        if remaining > 0:
            lines.append(f'... and {remaining} more')
        lines.append(f'log: {href(self._resolve(self.issue.log))}')
        return lines


@messages_for(CompilationFailedIssue)
class CompilationFailedMessage(_CompilationMessage[CompilationFailedIssue]):
    def summary(self) -> str:
        return (
            f'failed to compile: {self.issue.reason}'
            if self.issue.reason
            else 'failed to compile'
        )


@messages_for(CompilationWarningsIssue)
class CompilationWarningsMessage(_CompilationMessage[CompilationWarningsIssue]):
    def summary(self) -> str:
        return f'compiled with {len(self.issue.warnings)} warning(s)'

    def _warnings(self) -> List[CompilationWarning]:
        return self.issue.warnings


@messages_for(BorderlineTleIssue)
class BorderlineTleMessage(IssueMessage[BorderlineTleIssue]):
    def summary(self) -> str:
        return 'slow only within 2x the time limit'

    def details(self) -> List[str]:
        lines = [
            'rbx judges at 2x the time limit and reports TLE past 1x, so this '
            'solution timed out but finished inside the doubled window -- the '
            'testset does not prove it is decisively slow.'
        ]
        if self.issue.groups:
            lines.append(f'groups:   {", ".join(self.issue.groups)}')
        if self.issue.doubleTlVerdicts:
            lines.append(
                f'without a TL it would have: {_verdicts(self.issue.doubleTlVerdicts)}'
            )
        return lines


@messages_for(HiddenVerdictIssue)
class HiddenVerdictMessage(IssueMessage[HiddenVerdictIssue]):
    def summary(self) -> str:
        return f'a soft TLE hid: {_verdicts(self.issue.verdicts)}'

    def details(self) -> List[str]:
        lines = [
            'reported TLE at 1x the time limit, but underneath it was doing '
            'something the declaration does not allow.'
        ]
        if self.issue.groups:
            lines.append(f'groups:   {", ".join(self.issue.groups)}')
        return lines


@messages_for(TightTimeMarginIssue)
class TightTimeMarginMessage(IssueMessage[TightTimeMarginIssue]):
    def summary(self) -> str:
        return (
            f'used {get_formatted_time(int(self.issue.maxTime * 1000))} of a '
            f'{get_formatted_time(int(self.issue.timeLimit * 1000))} limit'
        )

    def details(self) -> List[str]:
        ratio = self.issue.maxTime / self.issue.timeLimit
        return [
            f'{ratio:.0%} of the time limit on this machine. Fine here, tight '
            f'on a slower judge.'
        ]


@messages_for(UntunedLimitsIssue)
class UntunedLimitsMessage(IssueMessage[UntunedLimitsIssue]):
    def summary(self) -> str:
        return 'the time limit may not be tuned to this machine'

    def details(self) -> List[str]:
        return [
            'Solutions failed their expectations by being too fast or too slow, '
            'and this run used the limits declared in the package rather than a '
            'profile. They may simply not suit this hardware.',
            f'affected: {", ".join(self.issue.affectedSolutions)}',
            'run [item]rbx time[/item] to estimate limits here.',
        ]


@messages_for(NoAcceptedSolutionIssue)
class NoAcceptedSolutionMessage(IssueMessage[NoAcceptedSolutionIssue]):
    def summary(self) -> str:
        return 'no solution is declared as accepted'

    def details(self) -> List[str]:
        return [
            'Without an accepted solution nothing establishes what a correct '
            'output is, so every output this package generates is unverified.',
            'declare one with [item]outcome: accepted[/item] in '
            '[item]problem.rbx.yml[/item].',
        ]


@messages_for(NoValidatorIssue)
class NoValidatorMessage(IssueMessage[NoValidatorIssue]):
    def summary(self) -> str:
        return 'the problem has no validator'

    def details(self) -> List[str]:
        return [
            'Nothing checks that the generated tests obey the constraints the '
            'statement promises.',
        ]


@messages_for(NoSamplesIssue)
class NoSamplesMessage(IssueMessage[NoSamplesIssue]):
    def summary(self) -> str:
        return 'the problem has no samples'


@messages_for(EmptyTestGroupIssue)
class EmptyTestGroupMessage(IssueMessage[EmptyTestGroupIssue]):
    def summary(self) -> str:
        return f'test group [item]{self.issue.group}[/item] has no tests'


@messages_for(MissingStatementLanguageIssue)
class MissingStatementLanguageMessage(IssueMessage[MissingStatementLanguageIssue]):
    def summary(self) -> str:
        if self.issue.hasNoStatements:
            return 'the problem has no statement'
        return f'no statement for language(s): {", ".join(self.issue.missing)}'

    def details(self) -> List[str]:
        if self.issue.hasNoStatements:
            return []
        return [
            f'the contest wants: {", ".join(self.issue.missing)}',
        ]


@messages_for(ExplanationMissingLanguageIssue)
class ExplanationMissingLanguageMessage(IssueMessage[ExplanationMissingLanguageIssue]):
    def summary(self) -> str:
        return (
            f'sample {self.issue.sample}: explanation missing for '
            f'language(s): {", ".join(self.issue.missing)}'
        )

    def details(self) -> List[str]:
        return [
            f'file: {href(self.issue.path)}',
            'A language this file does not define is not an error at build '
            'time -- the explanation is simply left out of that language, with '
            'nothing said about it.',
        ]


class _UnknownMessage(IssueMessage[Issue]):
    """The last resort, for an issue no class claims.

    Unreachable for any kind in the union -- `check_coverage` below refuses to
    let the module import while one is unregistered -- but a caller can hand us
    a model from somewhere else, and a line is better than a traceback.
    """

    def summary(self) -> str:
        return 'unknown issue'


def message_for(issue: Issue, runs_dir: Optional[str] = None) -> IssueMessage:
    """The message class that owns this issue's wording, instantiated."""
    return MESSAGES_BY_KIND.get(type(issue), _UnknownMessage)(issue, runs_dir)


def summarize(issue: Issue) -> str:
    """One line: what is wrong, and with what."""
    return message_for(issue).summary()


def explain(issue: Issue, runs_dir: Optional[str] = None) -> List[str]:
    """The detail lines under an issue in `-d` mode."""
    return message_for(issue, runs_dir).details()


def check_coverage(kinds: Optional[Iterable[type]] = None) -> None:
    """Every kind in the union has a message, checked when this module loads.

    A kind added to `schema.Issue` without a class here would otherwise reach a
    user as "unknown issue", which is a worse way to find out than an import
    error is. `kinds` is a parameter only so a test can ask the question about
    a kind that does not exist.
    """
    if kinds is None:
        kinds = typing.get_args(typing.get_args(Issue)[0])
    missing = [kind.__name__ for kind in kinds if kind not in MESSAGES_BY_KIND]
    if missing:
        raise RuntimeError(
            f'issue kinds without a message class: {", ".join(missing)}. '
            f'Add one to rbx.box.issues.messages.'
        )


check_coverage()
