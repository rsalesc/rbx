"""The public names of issues, and the config that tunes or silences them.

A leaf module on purpose. `problem.rbx.yml`, `contest.rbx.yml` and `env.rbx.yml`
all carry an `issues:` block, so `rbx.box.schema`, `rbx.box.contest.schema` and
`rbx.box.environment` all import from here -- and `rbx.box.issues` loads a
package to do its work, so living there would close an import cycle through
every one of them.

A code is the *user-facing* name of an issue kind: what the console prints next
to each finding, what the docs page is anchored by, and what a setter writes in
`issues.ignore`. The `kind` discriminator on the issue models is a separate,
older name that the JSON format already published, so it stays as it is and
`rbx.box.issues.schema` maps one to the other.

Once released, a code is forever: renaming one silently turns every
`ignore:` entry that spelled the old name into a validation error.
"""

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field

# Where every code is documented, one section per code. Short on purpose: it is
# printed under every issue list.
DOCS_URL = 'https://rbx.rsalesc.dev/issues/'


class IssueCode(str, Enum):
    # Run family: derived from the last run.
    UNMET_EXPECTATION = 'unmet-expectation'
    UNEXPECTED_SCORE = 'unexpected-score'
    COMPILATION_FAILED = 'compilation-failed'
    COMPILATION_WARNINGS = 'compilation-warnings'
    SANITIZER_FINDING = 'sanitizer-finding'
    BORDERLINE_TLE = 'borderline-tle'
    HIDDEN_VERDICT = 'hidden-verdict'
    NOISY_STDERR = 'noisy-stderr'
    SLOW_ACCEPTED_SOLUTION = 'slow-accepted-solution'
    UNTUNED_LIMITS = 'untuned-limits'
    # Config family: true before anything is run.
    NO_ACCEPTED_SOLUTION = 'no-accepted-solution'
    NO_VALIDATOR = 'no-validator'
    NO_SAMPLES = 'no-samples'
    EMPTY_TEST_GROUP = 'empty-test-group'
    LARGE_TESTSET = 'large-testset'
    MISSING_STATEMENT_LANGUAGE = 'missing-statement-language'
    EXPLANATION_MISSING_LANGUAGE = 'explanation-missing-language'


def docs_url(code: IssueCode) -> str:
    """The section of the issues page that documents `code`."""
    return f'{DOCS_URL}#{code.value}'


class IssuesConfig(BaseModel):
    """The `issues:` block of `problem.rbx.yml` and `contest.rbx.yml`."""

    model_config = ConfigDict(extra='forbid')

    ignore: List[IssueCode] = Field(
        default=[],
        description="""Issue codes not to report for this problem (or, in `contest.rbx.yml`,
for every problem of the contest). A problem's list adds to its contest's. Ignored
issues are still listed by `rbx issues --all`.
See https://rbx.rsalesc.dev/issues/ for every code.""",
    )


class IssueThresholds(BaseModel):
    """How large or slow something may be before an issue reports it."""

    model_config = ConfigDict(extra='forbid')

    testsetSizeMb: float = Field(
        default=20,
        gt=0,
        description="""Largest total size, in MiB, of the built testset (every input plus
every expected answer) before `large-testset` is reported.""",
    )

    acceptedTotalTimeSeconds: float = Field(
        default=60,
        gt=0,
        description="""Largest total CPU time, in seconds, an accepted solution may spend
over the whole testset before `slow-accepted-solution` is reported.""",
    )

    stderrSizeMb: float = Field(
        default=1,
        gt=0,
        description="""Largest stderr, in MiB, a solution may write on a single testcase
before `noisy-stderr` is reported.""",
    )

    @property
    def testset_size_bytes(self) -> int:
        return int(self.testsetSizeMb * 1024 * 1024)

    @property
    def stderr_size_bytes(self) -> int:
        return int(self.stderrSizeMb * 1024 * 1024)


class EnvironmentIssuesConfig(BaseModel):
    """The `issues:` block of `env.rbx.yml`."""

    model_config = ConfigDict(extra='forbid')

    thresholds: IssueThresholds = Field(
        default_factory=IssueThresholds,
        description="""Thresholds for the issues that measure a size or a duration.""",
    )
