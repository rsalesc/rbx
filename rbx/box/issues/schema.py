"""What an issue with a run *is*, as data.

Structured, never rendered -- the same rule `rbx.box.run_report` follows, and
for the same reason. An issue carries the facts that make it an issue: which
solution, which groups, what was expected, what happened. Turning that into
"expected wrong-answer, got accepted" is `rbx.box.issues.rendering`'s business,
and the VS Code extension reading `--format json` may reasonably word it
differently.

Severity is a property of the *kind*, not a field a producer chooses: two
unmet expectations are never one an error and one a warning. It is exposed as a
computed field so it still lands in the JSON, and no client has to keep its own
table of which kinds are which.
"""

import pathlib
from enum import Enum
from typing import Annotated, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, computed_field

from rbx.box.compilation_findings import CompilationWarning
from rbx.box.schema import ExpectedOutcome
from rbx.grading.steps import Outcome

# Bump when a change would make an older reader misread the output.
#
# Adding a new issue *kind* is such a change only in the sense that an older
# reader will not know how to word it; the discriminated union means it can
# still read `kind` and `severity` and show something. Adding an optional field
# to an existing kind is not a change at all.
ISSUES_FORMAT_VERSION = 1


class IssueSeverity(str, Enum):
    # Something is wrong: the package does not behave the way it says it does.
    ERROR = 'error'
    # Something is worth a look, but the package may well be fine.
    WARNING = 'warning'


class _BaseIssue(BaseModel):
    # The solution this issue is about, as its declared path. Every kind has one
    # today; it stays on the subclasses rather than here so a future issue that
    # is about the package as a whole does not have to invent a fake one.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        raise NotImplementedError


class UnmetExpectationIssue(_BaseIssue):
    """A solution did not behave the way `problem.rbx.yml` says it does."""

    kind: Literal['unmet_expectation'] = 'unmet_expectation'
    solution: str
    expected: ExpectedOutcome
    # Absent when nothing was evaluated, which is what an interrupted run looks
    # like.
    got: Optional[Outcome] = None
    # `SolutionOutcomeStatus`, as its value.
    status: str
    failedGroups: List[str] = []
    # Whether the *pooled* expectation held on its own.
    #
    # Carried so the renderer never accuses an expectation that was met: a
    # solution declaring `outcome: incorrect` with an `outcomePerGroup` can fail
    # only the per-group layer, and saying "expected incorrect, got wrong-answer"
    # there names the one layer that did its job.
    pooledMatchesExpectation: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.ERROR


class UnexpectedScoreIssue(_BaseIssue):
    """A solution scored outside the range it declared."""

    kind: Literal['unexpected_score'] = 'unexpected_score'
    solution: str
    score: int
    maxScore: int
    expectedScore: Tuple[int, int]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.ERROR


class CompilationFailedIssue(_BaseIssue):
    """A solution did not compile.

    Worth surfacing loudly because it is otherwise close to invisible: a
    solution that failed to compile is filtered out of the skeleton's
    `solutions`, so it is absent from the run entirely rather than showing up
    with a bad verdict.
    """

    kind: Literal['compilation_failed'] = 'compilation_failed'
    solution: str
    # Why, when there is a one-line answer: "'g++' was not found".
    reason: Optional[str] = None
    # Relative to the runs dir, e.g. `compilation/0.log`.
    log: pathlib.Path

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.ERROR


class CompilationWarningsIssue(_BaseIssue):
    """A solution compiled, but the compiler had something to say."""

    kind: Literal['compilation_warnings'] = 'compilation_warnings'
    solution: str
    warnings: List[CompilationWarning] = []
    log: pathlib.Path

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


class BorderlineTleIssue(_BaseIssue):
    """A solution declared slow was only slow inside the doubled time limit.

    Under `-v4` (the default) rbx judges at 2x the time limit and rewrites an
    over-TL run to TLE, so a solution that fits inside that doubled window is
    borderline rather than decisively slow -- the testset does not really prove
    what the declaration claims. The run itself passes, which is exactly why
    this needs saying: `status` is OK and the expectation matched.
    """

    kind: Literal['borderline_tle'] = 'borderline_tle'
    solution: str
    # The groups that contributed, empty when only the pooled layer did.
    groups: List[str] = []
    # The verdicts the solution would have had without the time limit: it
    # finished inside double TL, but wrongly.
    doubleTlVerdicts: List[Outcome] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


class HiddenVerdictIssue(_BaseIssue):
    """A soft TLE hid a verdict that no expectation accepts.

    The solution was reported TLE at 1x, but underneath it was doing something
    else -- a wrong answer, a crash -- that the declaration does not allow.
    """

    kind: Literal['hidden_verdict'] = 'hidden_verdict'
    solution: str
    groups: List[str] = []
    verdicts: List[Outcome] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


class TightTimeMarginIssue(_BaseIssue):
    """A solution that passed came uncomfortably close to the time limit."""

    kind: Literal['tight_time_margin'] = 'tight_time_margin'
    solution: str
    maxTime: float  # seconds
    timeLimit: float  # seconds

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


class UntunedLimitsIssue(_BaseIssue):
    """Expectations failed on timing, and the limits were never tuned here.

    A package-level issue rather than a per-solution one: the answer is a single
    `rbx time`, not one per solution, so the affected solutions are listed on one
    issue instead of producing several that all say the same thing.
    """

    kind: Literal['untuned_limits'] = 'untuned_limits'
    affectedSolutions: List[str] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


Issue = Annotated[
    Union[
        UnmetExpectationIssue,
        UnexpectedScoreIssue,
        CompilationFailedIssue,
        CompilationWarningsIssue,
        BorderlineTleIssue,
        HiddenVerdictIssue,
        TightTimeMarginIssue,
        UntunedLimitsIssue,
    ],
    Field(discriminator='kind'),
]


class IssueReport(BaseModel):
    """Everything `rbx issues` found, and enough context to read it.

    `ranAt` is a POSIX timestamp rather than a rendered "4m ago": the client
    decides how to say it, and a machine reader wants the number. It is absent
    only alongside an empty `issues` on a package that was never run -- which
    `neverRun` says outright, since "no issues" and "no run" are opposite news.
    """

    version: int = ISSUES_FORMAT_VERSION
    neverRun: bool = False
    ranAt: Optional[float] = None
    # The runs directory the relative paths on these issues hang off -- a
    # compilation log is `compilation/0.log`, and on its own that resolves
    # against whatever the reader's working directory happens to be. Published
    # rather than left implicit because a client is not necessarily running from
    # the package root, and the contest view is never running from any of them.
    runsDir: Optional[str] = None
    issues: List[Issue] = []

    def errors(self) -> List[Issue]:
        return [issue for issue in self.issues if issue.severity == IssueSeverity.ERROR]

    def warnings(self) -> List[Issue]:
        return [
            issue for issue in self.issues if issue.severity == IssueSeverity.WARNING
        ]


class ContestIssueRow(BaseModel):
    """One problem's line in the contest-wide view.

    `failedToLoad` is its own state rather than an empty report: a problem whose
    package could not be read is not a problem without issues, and a contest
    table that renders the two the same way is lying about the one case the
    reader most needs to see.
    """

    short_name: str
    name: str
    report: IssueReport = IssueReport()
    failed_to_load: bool = False
