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

import functools
import re
from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Where every code is documented, one section per code. Short on purpose: it is
# printed under every issue list.
DOCS_URL = 'https://rbx.rsalesc.dev/issues/'


class IssueCode(str, Enum):
    # Run family: derived from the last run.
    UNMET_EXPECTATION = 'unmet-expectation'
    UNEXPECTED_SCORE = 'unexpected-score'
    COMPILATION_FAILED = 'compilation-failed'
    COMPILATION_WARNINGS = 'compilation-warnings'
    ASSET_COMPILATION_WARNINGS = 'asset-compilation-warnings'
    LINTER_WARNINGS = 'linter-warnings'
    DUPLICATE_TEST = 'duplicate-test'
    BOUNDS_NOT_HIT = 'bounds-not-hit'
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
    LARGE_TESTCASE = 'large-testcase'
    MISSING_STATEMENT_LANGUAGE = 'missing-statement-language'
    EXPLANATION_MISSING_LANGUAGE = 'explanation-missing-language'
    STALE_IGNORE_RULE = 'stale-ignore-rule'


def docs_url(code: IssueCode) -> str:
    """The section of the issues page that documents `code`."""
    return f'{DOCS_URL}#{code.value}'


class IssueSubject(str, Enum):
    """What an issue is about, for codes that are about one thing in particular.

    The value a scoped `issues.ignore` rule's `on:` glob is matched against.
    """

    # The solution's declared path, e.g. `sols/slow.cpp`.
    SOLUTION = 'solution'
    # Any other file of the package, e.g. `gens/gen.cpp`.
    FILE = 'file'
    # A test group's name, e.g. `small`.
    GROUP = 'group'
    # A test's group and index, e.g. `main/3`.
    TEST = 'test'


# Codes with no entry here are about the problem as a whole, so a rule cannot
# narrow them: there is nothing for `on:` to match.
CODE_SUBJECTS: Dict[IssueCode, IssueSubject] = {
    IssueCode.UNMET_EXPECTATION: IssueSubject.SOLUTION,
    IssueCode.UNEXPECTED_SCORE: IssueSubject.SOLUTION,
    IssueCode.COMPILATION_FAILED: IssueSubject.SOLUTION,
    IssueCode.COMPILATION_WARNINGS: IssueSubject.SOLUTION,
    IssueCode.SANITIZER_FINDING: IssueSubject.SOLUTION,
    IssueCode.BORDERLINE_TLE: IssueSubject.SOLUTION,
    IssueCode.HIDDEN_VERDICT: IssueSubject.SOLUTION,
    IssueCode.NOISY_STDERR: IssueSubject.SOLUTION,
    IssueCode.SLOW_ACCEPTED_SOLUTION: IssueSubject.SOLUTION,
    IssueCode.ASSET_COMPILATION_WARNINGS: IssueSubject.FILE,
    IssueCode.LINTER_WARNINGS: IssueSubject.FILE,
    IssueCode.BOUNDS_NOT_HIT: IssueSubject.GROUP,
    IssueCode.EMPTY_TEST_GROUP: IssueSubject.GROUP,
    IssueCode.DUPLICATE_TEST: IssueSubject.TEST,
}


@functools.lru_cache(maxsize=None)
def _glob_regex(pattern: str) -> 're.Pattern[str]':
    """`pattern` as a regex, with the semantics `solutions:` globs already have.

    Those go through `Path.glob`: `*` and `?` stay inside one path segment, and
    `**` spans any number of them. A rule spelled the way its solution entry is
    spelled must match the same files.
    """
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif pattern.startswith('**', i):
            out.append('.*')
            i += 2
        elif pattern[i] == '*':
            out.append('[^/]*')
            i += 1
        elif pattern[i] == '?':
            out.append('[^/]')
            i += 1
        elif pattern[i] == '[':
            end = pattern.find(']', i + 1)
            if end == -1:
                out.append(re.escape(pattern[i]))
                i += 1
                continue
            body = pattern[i + 1 : end]
            if body.startswith('!'):
                body = '^' + body[1:]
            out.append(f'[{body}]')
            i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(''.join(out))


def _normalize(path: str) -> str:
    return path[2:] if path.startswith('./') else path


def glob_matches(pattern: str, subject: str) -> bool:
    """Whether `subject` matches `pattern`, as `Path.glob` would decide it."""
    return _glob_regex(_normalize(pattern)).fullmatch(_normalize(subject)) is not None


class IgnoreRule(BaseModel):
    """One entry of `issues.ignore`, in its mapping form."""

    model_config = ConfigDict(extra='forbid')

    code: IssueCode = Field(description='The issue code to silence.')
    on: Optional[str] = Field(
        default=None,
        description="""Silence `code` only for what this glob matches, instead of for the
whole problem: a solution or file path (`sols/slow-*.cpp`), a test group name (`small`) or a
test (`main/3`), depending on the code. `*` stays within one path segment and `**` spans any
number of them, as in `solutions:`. Omit it to silence the code everywhere.""",
    )
    reason: Optional[str] = Field(
        default=None,
        description='Why this is silenced. Shown by `rbx issues --all`.',
    )

    @model_validator(mode='after')
    def _on_needs_a_subject(self) -> 'IgnoreRule':
        if self.on is not None and (not self.on.strip() or self.on.startswith('/')):
            raise ValueError(
                '`on` must be a non-empty glob relative to the problem folder, '
                f'got {self.on!r}.'
            )
        if self.on is not None and self.code not in CODE_SUBJECTS:
            raise ValueError(
                f'`{self.code.value}` is about the problem as a whole, so it cannot '
                'be narrowed with `on`; list the code alone to silence it.'
            )
        return self

    def matches(self, code: IssueCode, subject: Optional[str]) -> bool:
        if code != self.code:
            return False
        if self.on is None:
            return True
        return subject is not None and glob_matches(self.on, subject)


def as_rule(entry: Union[IssueCode, IgnoreRule]) -> IgnoreRule:
    """A plain code is a rule with no `on`: it silences the code everywhere."""
    return entry if isinstance(entry, IgnoreRule) else IgnoreRule(code=entry)


class IssuesConfig(BaseModel):
    """The `issues:` block of `problem.rbx.yml` and `contest.rbx.yml`."""

    model_config = ConfigDict(extra='forbid')

    ignore: List[Union[IssueCode, IgnoreRule]] = Field(
        default=[],
        description="""Issues not to report for this problem (or, in `contest.rbx.yml`,
for every problem of the contest). Each entry is a code, which silences it everywhere, or a
`{code, on, reason}` rule, which silences it only for what `on` matches. A problem's list adds
to its contest's. Ignored issues are still listed by `rbx issues --all`.
See https://rbx.rsalesc.dev/issues/ for every code.""",
    )

    def rules(self) -> List[IgnoreRule]:
        return [as_rule(entry) for entry in self.ignore]


class IssueThresholds(BaseModel):
    """How large or slow something may be before an issue reports it."""

    model_config = ConfigDict(extra='forbid')

    testsetSizeMb: float = Field(
        default=200,
        gt=0,
        description="""Largest total size, in MiB, of the built testset (every input plus
every expected answer) before `large-testset` is reported.""",
    )

    testcaseInputSizeMb: float = Field(
        default=20,
        gt=0,
        description="""Largest size, in MiB, of a single built input before `large-testcase`
is reported.""",
    )

    testcaseAnswerSizeMb: float = Field(
        default=20,
        gt=0,
        description="""Largest size, in MiB, of a single expected answer before
`large-testcase` is reported.""",
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
    def testcase_input_size_bytes(self) -> int:
        return int(self.testcaseInputSizeMb * 1024 * 1024)

    @property
    def testcase_answer_size_bytes(self) -> int:
        return int(self.testcaseAnswerSizeMb * 1024 * 1024)

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
