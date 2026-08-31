from __future__ import annotations

import collections
import enum
import pathlib
import re
import typing
from typing import Annotated, Any, Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from rbx import utils
from rbx.autoenum import AutoEnum, alias
from rbx.box.fields import (
    NameField,
    Primitive,
    RecVars,
    Vars,
    check_reserved_statement_var_names,
    expand_vars,
    merge_recvars,
)
from rbx.box.formatting import href
from rbx.box.statements.expander import expand_problem_statements
from rbx.box.statements.schema import Statement, is_unique_problem_statements
from rbx.grading.steps import Outcome


def _check_oneof(model_obj: BaseModel, fields: List[str]):
    has = []
    for field in fields:
        if hasattr(model_obj, field) and getattr(model_obj, field):
            has.append(field)
    if len(has) <= 1:
        return
    raise ValueError(
        f'fields {has} were specified at the same time '
        'in a testgroup; only one of them can be specified'
    )


def _represents_int(s: str) -> bool:
    return re.match(r'[-+]?\d+$', s.strip()) is not None


def _represents_float(s: str) -> bool:
    return re.match(r'[-+]?\d+\.\d+$', s.strip()) is not None


def _represents_bool(s: str) -> bool:
    return s.lower().strip() in ['true', 'false', 'True', 'False']


def convert_to_primitive(value: Any) -> Primitive:
    if _represents_int(value):
        return int(value)
    if _represents_float(value):
        return float(value)
    if _represents_bool(value):
        return value.lower().strip() == 'true'
    return str(value)


def expand_any_vars(vars: Dict[str, Any]) -> Dict[str, Primitive]:
    converted_vars = {key: convert_to_primitive(value) for key, value in vars.items()}
    return expand_vars(typing.cast(RecVars, converted_vars))


# Command-line flags consumed by testlib itself (`__testlib_set_testset_and_group`,
# `registerValidation`, `registerTestlibCmd`) or by rbx (`rbx::getGroup()`, which
# reads `--group` to pick a group's var overrides).
#
# `vars` are flattened to dotted keys and handed to the validator as
# `--<key>=<value>`, so a *top-level* var with one of these names would be
# indistinguishable from the real flag -- and `--group=<value>` would silently
# make every group resolve against the package-level values.
RESERVED_VAR_NAMES = frozenset(
    [
        'group',
        'help',
        'testCase',
        'testCaseFileName',
        'testMarkupFileName',
        'testOverviewLogFileName',
        'testset',
    ]
)


def check_reserved_var_names(vars: RecVars) -> RecVars:
    """Reject top-level var names that collide with a testlib/rbx flag.

    Only top-level *primitive* keys are checked: a nested var is emitted as
    `--<parent>.<key>=<value>`, which no flag parser matches.
    """
    for key, value in vars.items():
        if isinstance(value, dict):
            continue
        if key in RESERVED_VAR_NAMES:
            raise PydanticCustomError(
                'RESERVED_VAR_NAME',
                'Variable "{key}" collides with the testlib/rbx command-line flag '
                '"--{key}": vars are passed to validators as "--{key}=<value>", '
                'which the flag parser would consume instead. '
                'Rename the variable, or nest it under another key '
                '(as in "limits.{key}"). Reserved names: {reserved}.',
                {'key': key, 'reserved': ', '.join(sorted(RESERVED_VAR_NAMES))},
            )
    return vars


CheckedRecVars = Annotated[
    RecVars,
    AfterValidator(check_reserved_var_names),
    AfterValidator(check_reserved_statement_var_names),
]


def is_unique_testcase_group_names(
    groups: List['TestcaseGroup'],
) -> List['TestcaseGroup']:
    names = {g.name for g in groups}
    if len(names) != len(groups):
        raise ValueError('Testcase group names must be unique.')
    return groups


def is_unique_testcase_subgroup_names(
    subgroups: List['TestcaseSubgroup'],
) -> List['TestcaseSubgroup']:
    names = {sg.name for sg in subgroups}
    if len(names) != len(subgroups):
        raise ValueError(
            'Testcase subgroup names must be unique within their parent group.'
        )
    return subgroups


class ExpectedOutcome(AutoEnum):
    ANY = alias('any')  # type: ignore
    """Expected outcome for any outcome."""

    ACCEPTED = alias('accepted', 'ac', 'correct')  # type: ignore
    """Expected outcome for correct solutions (AC)."""

    ACCEPTED_OR_TLE = alias(
        'accepted or time limit exceeded',  # type: ignore
        'accepted or tle',
        'ac or tle',
        'ac/tle',
        'ac+tle',
    )  # type: ignore
    """Expected outcome for solutions that finish with either AC or TLE.
    
    Especially useful when you do not care about the running time of this solution, and
    want it to not be considered when calculating the timelimit for the problem."""

    WRONG_ANSWER = alias('wrong answer', 'wa')  # type: ignore
    """Expected outcome for solutions that finish successfully,
    but the produced output are incorrect (WA)."""

    INCORRECT = alias('fail', 'incorrect')  # type: ignore
    """Expected outcome for solutions that finish with any non-AC verdict."""

    RUNTIME_ERROR = alias('runtime error', 'rte', 're')  # type: ignore
    """Expected outcome solutions that finish with non-zero code (RTE)."""

    TIME_LIMIT_EXCEEDED = alias('time limit exceeded', 'timeout', 'tle', 'tl')  # type: ignore
    """Expected outcome for solutions that do not finish in time."""

    MEMORY_LIMIT_EXCEEDED = alias('memory limit exceeded', 'mle', 'ml')  # type: ignore
    """Expected outcome for solutions that use more memory than allowed."""

    OUTPUT_LIMIT_EXCEEDED = alias('output limit exceeded', 'ole', 'ol')  # type: ignore
    """Expected outcome for solutions that use more output than allowed."""

    TLE_OR_RTE = alias('tle or rte', 'tle/rte', 'tle+rte', 'tle or re', 'tle+re')  # type: ignore
    """Expected outcome for solutions that finish with either TLE or RTE.

    Especially useful for environments where TLE and RTE are indistinguishable."""

    MLE_OR_RTE = alias('mle or rte', 'mle/rte', 'mle+rte', 'ml or re', 'ml+re')  # type: ignore
    """Expected outcome for solutions that finish with either MLE or RTE.

    Which of the two a memory-hungry solution gets depends on how the memory limit is
    enforced, and that differs by platform: on Linux the address space is capped, so the
    allocation fails inside the program and it dies of a runtime error, while on macOS
    the solution is killed once its resident memory crosses the limit. Use this to
    declare a solution that exceeds the memory limit without pinning it to one of them."""

    JUDGE_FAILED = alias('judge failed', 'jf')  # type: ignore
    """Expected outcome for solutions that finish with a judge failed verdict.
    
    Only useful for checker tests."""

    COMPILATION_ERROR = alias('compilation error', 'ce')  # type: ignore
    """Expected outcome for solutions that finish with a compilation error verdict.
    
    Only useful for checker tests."""

    def style(self) -> str:
        if self == ExpectedOutcome.ANY:
            return 'bold white'
        if self.match(Outcome.ACCEPTED):
            return 'green'
        if self == ExpectedOutcome.WRONG_ANSWER:
            return 'red'
        if self == ExpectedOutcome.INCORRECT:
            return 'red'
        if self.match(Outcome.TIME_LIMIT_EXCEEDED):
            return 'yellow'
        if self.match(Outcome.RUNTIME_ERROR):
            return 'blue'
        if self.match(Outcome.MEMORY_LIMIT_EXCEEDED):
            return 'yellow'
        if self.match(Outcome.COMPILATION_ERROR):
            return 'blue'
        return 'magenta'

    def icon(self) -> str:
        if self == ExpectedOutcome.ANY:
            return '?'
        if self.match(Outcome.ACCEPTED):
            return '✓'
        if self.is_slow():
            return '⧖'
        return '✗'

    def icon_markup(self, styled: bool = True) -> str:
        icon = self.icon()
        if styled:
            style = self.style()
            icon = f'[{style}]{icon}[/{style}]'
        return icon

    def full_style(self) -> str:
        style = self.style()
        if self == ExpectedOutcome.ACCEPTED:
            return f'bold {style}'
        return style

    def full_markup(self, styled: bool = True) -> str:
        icon = self.icon_markup()
        name = self.name
        if styled:
            style = self.style()
            name = f'[{style}]{name}[/{style}]'
        return f'{icon} {name}'

    def is_slow(self) -> bool:
        return self in [ExpectedOutcome.TIME_LIMIT_EXCEEDED, ExpectedOutcome.TLE_OR_RTE]

    def matches_tle_and_is_incorrect(self) -> bool:
        return self.match(Outcome.TIME_LIMIT_EXCEEDED) and not self.match(
            Outcome.ACCEPTED
        )

    def match(self, outcome: Outcome) -> bool:
        if self == ExpectedOutcome.ANY:
            return True
        # A skipped testcase was not awarded, so it satisfies any expectation
        # that does not demand success.
        if outcome == Outcome.SKIPPED:
            return self != ExpectedOutcome.ACCEPTED
        if self == ExpectedOutcome.COMPILATION_ERROR:
            return outcome == Outcome.COMPILATION_ERROR
        if self == ExpectedOutcome.ACCEPTED:
            return outcome == Outcome.ACCEPTED
        if self == ExpectedOutcome.ACCEPTED_OR_TLE:
            return outcome in {Outcome.ACCEPTED} or outcome.is_slow()
        if self == ExpectedOutcome.WRONG_ANSWER:
            return outcome == Outcome.WRONG_ANSWER
        if self == ExpectedOutcome.INCORRECT:
            return (
                outcome
                in {
                    Outcome.WRONG_ANSWER,
                    Outcome.RUNTIME_ERROR,
                    Outcome.MEMORY_LIMIT_EXCEEDED,
                    Outcome.OUTPUT_LIMIT_EXCEEDED,
                }
                or outcome.is_slow()
            )
        if self == ExpectedOutcome.RUNTIME_ERROR:
            return outcome == Outcome.RUNTIME_ERROR
        if self == ExpectedOutcome.TIME_LIMIT_EXCEEDED:
            return outcome.is_slow()
        if self == ExpectedOutcome.MEMORY_LIMIT_EXCEEDED:
            return outcome == Outcome.MEMORY_LIMIT_EXCEEDED
        if self == ExpectedOutcome.TLE_OR_RTE:
            return outcome in {Outcome.RUNTIME_ERROR} or outcome.is_slow()
        if self == ExpectedOutcome.MLE_OR_RTE:
            return outcome in {
                Outcome.RUNTIME_ERROR,
                Outcome.MEMORY_LIMIT_EXCEEDED,
            }
        if self == ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED:
            return outcome == Outcome.OUTPUT_LIMIT_EXCEEDED
        if self == ExpectedOutcome.JUDGE_FAILED:
            return outcome == Outcome.JUDGE_FAILED
        return False

    def get_matches(self) -> List[Outcome]:
        # SKIPPED is not a verdict a run can be awarded, and it satisfies almost
        # every expectation, so including it here would make every pair of bad
        # expectations look compatible in `intersect`.
        return [
            outcome
            for outcome in Outcome
            if outcome != Outcome.SKIPPED and self.match(outcome)
        ]

    def intersect(self, rhs: 'ExpectedOutcome') -> bool:
        return bool(set(self.get_matches()) & set(rhs.get_matches()))


class ValidatorOutcome(AutoEnum):
    VALID = alias('valid')  # type: ignore
    """Expected outcome for valid tests."""

    INVALID = alias('invalid')  # type: ignore
    """Expected outcome for invalid tests."""


class TaskType(AutoEnum):
    BATCH = alias('batch')  # type: ignore
    """Batch task."""

    COMMUNICATION = alias('communication')  # type: ignore
    """Communication task."""


class ScoreType(AutoEnum):
    BINARY = alias('binary')  # type: ignore
    """Scoring for ICPC-like problems, where the problem is considered a point if it pass all testcases."""

    POINTS = alias('points')  # type: ignore
    """Subtasks scoring, where each passing testgroup is worth a number of points that are summed up."""


class CodeItem(BaseModel):
    model_config = ConfigDict(extra='forbid')

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CodeItem):
            return NotImplemented
        return self.path == other.path

    def __hash__(self) -> int:
        return hash(self.path)

    path: pathlib.Path = Field(
        description="""The path to the code file, relative to the package directory."""
    )

    language: Optional[str] = Field(
        default=None, description="""The language of the code file."""
    )

    compilationFiles: Optional[List[str]] = Field(
        default=[],
        description="""
Extra files that should be available during the compilation of the code file,
such as testlib.h, jngen.h, tgen.h, etc.

The paths should be given relative to the package directory, and are placed at the
same package-relative path inside the sandbox (the package directory structure is
mirrored). This means a code file in a subdirectory can include a file from
elsewhere in the package via a relative path (e.g. `#include "../lib.h"`).

Third-party libraries such as testlib.h, jngen.h and tgen.h are provided by the
preset's `libraries` configuration (see the preset docs), not auto-injected.
""",
    )

    executionFiles: Optional[List[str]] = Field(
        default=[],
        description="""
Extra files that should be available at *execution* time, the runtime equivalent of
`compilationFiles`.

The paths should be given relative to the package directory, and are placed at the
same package-relative path inside the sandbox (the package directory structure is
mirrored). Use this for runtime companion files a compiled binary or interpreted
script needs at run time (data files, sibling modules, etc.).

Sibling Python imports and quoted C++ includes are auto-discovered; this field is the
escape hatch for files that cannot be discovered automatically.
""",
    )

    def href(self, hyperlink: bool = True) -> str:
        return href(self.path, hyperlink=hyperlink)

    def display(self) -> str:
        return self.href(hyperlink=False)


class CodeItemWithDigest(CodeItem):
    model_config = ConfigDict(extra='forbid')

    digest: str = Field(description="""The digest of the code file.""")

    @classmethod
    def create(cls, code_item: CodeItem, digest: str) -> 'CodeItemWithDigest':
        return cls(
            path=code_item.path,
            language=code_item.language,
            compilationFiles=code_item.compilationFiles,
            executionFiles=code_item.executionFiles,
            digest=digest,
        )


class GeneratorScript(CodeItem):
    model_config = ConfigDict(extra='forbid')

    root: pathlib.Path = Field(
        default_factory=pathlib.Path,
        description="""The root directory where the generators should be fetched from.""",
    )

    format: Literal['rbx', 'box'] = Field(
        default='rbx', description="""The format of the generator script."""
    )


class Checker(CodeItem):
    model_config = ConfigDict(extra='forbid')

    fallback_to: Optional[Checker] = Field(
        default=None,
        description="""Checker to fall back to if the mainly specified checker does not exist.""",
    )

    mode: Literal['testlib', 'boca'] = Field(
        default='testlib',
        description="""In which compatibility mode the checker should be run.""",
    )


class Interactor(CodeItem):
    model_config = ConfigDict(extra='forbid')

    legacy: bool = Field(
        default=False,
        description="""
Whether this interactor is a legacy interactor and needs a checker to be specified.
""",
    )

    capture: bool = Field(
        default=True,
        description="""Whether the interactor should capture the pipes.""",
    )


class OutputFromItem(CodeItem):
    model_config = ConfigDict(extra='forbid')

    stderr: bool = Field(
        default=False,
        description="""Whether the output should be taken from stderr instead of the stdout.""",
    )


class OutputFromItemWithDigest(OutputFromItem, CodeItemWithDigest):
    model_config = ConfigDict(extra='forbid')

    @classmethod
    def create(
        cls, output_from_item: OutputFromItem, digest: str
    ) -> 'OutputFromItemWithDigest':
        return cls(
            path=output_from_item.path,
            language=output_from_item.language,
            compilationFiles=output_from_item.compilationFiles,
            executionFiles=output_from_item.executionFiles,
            digest=digest,
        )


OutputFrom = Union[Literal['stderr'], OutputFromItem]
OutputFromWithDigest = Union[Literal['stderr'], OutputFromItemWithDigest]


class Visualizer(CodeItem):
    model_config = ConfigDict(extra='forbid')

    extension: str = Field(
        description="""The extension of the visualization file generated by the visualizer.
        """,
    )

    answer_from: Optional[OutputFrom] = Field(
        default=None,
        description="""Program to generate additional answer file to pass to the visualizer.
        If not specified, the reference answer file will be used.""",
    )

    def get_suffix(self) -> str:
        return f'.{self.extension}'


class Testcase(BaseModel):
    __test__ = False

    model_config = ConfigDict(extra='forbid')

    inputPath: pathlib.Path = Field(description="""The path of the input file.""")

    outputPath: Optional[pathlib.Path] = Field(
        default=None, description="""The path of the output file."""
    )


class GeneratorCall(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(description='The name of the generator to call.')

    args: Optional[str] = Field(
        default=None, description='The arguments to pass to the generator.'
    )

    def __str__(self) -> str:
        return f'{self.name} {self.args}'


class TestcaseSubgroup(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = NameField(description='The name of the test group.')

    testcases: List[Testcase] = Field(
        default=[],
        description="""
The path of testcases to add to this group,
in the order they're defined.""",
    )

    testcaseGlob: Optional[str] = Field(
        default=None,
        description="""
A Python glob that matches input file paths relative to the
package directory. The globbed files should end with the extension
".in", and their corresponding outputs, if defined, should have the same file name,
but ending with ".ans".
""",
    )

    generators: List[GeneratorCall] = Field(
        default=[],
        description="""
A list of generators to call to generate testcases for this group.
""",
    )

    generatorScript: Optional[GeneratorScript] = Field(
        default=None,
        description="""
A generator script to call to generate testcases for this group.
""",
    )

    extraValidators: List[CodeItem] = Field(
        default=[],
        description="""
A list of extra validators to use to validate the testcases of this subgroup.
""",
    )

    outputValidators: List[CodeItem] = Field(
        default=[],
        description="""
A list of output validators to use to validate the output of the testcases of this subgroup.
""",
    )

    visualizer: Optional[Visualizer] = Field(
        default=None,
        description='The visualizer for this problem. Used to produced visualizations for the testcases. '
        'Has priority over the visualizer specified in the package.',
    )

    solutionVisualizer: Optional[Visualizer] = Field(
        default=None,
        description='The solution visualizer for this problem. Used to produced visualizations for the outputs of the testcases. '
        'Has priority over the solution visualizer specified in the package.',
    )

    @model_validator(mode='after')
    def check_oneof(self) -> 'TestcaseSubgroup':
        _check_oneof(
            self,
            [
                'testcases',
                'testcaseGlob',
                'generators',
                'generatorScript',
            ],
        )
        return self


class TestcaseGroup(TestcaseSubgroup):
    model_config = ConfigDict(extra='forbid')

    subgroups: Annotated[
        List[TestcaseSubgroup],
        AfterValidator(is_unique_testcase_subgroup_names),
    ] = Field(
        default=[],
        description="""
A list of test subgroups to define for this group.
        """,
    )

    validator: Optional[CodeItem] = Field(
        default=None,
        description="""
A validator to use to validate the testcases of this group.
If specified, will use this validator instead of the package-level validator.
Useful in cases where the constraints vary across test groups.
""",
    )

    vars: CheckedRecVars = Field(
        default={},
        description="""
Variables that override the package-level `vars` for this group only.

Merged leaf-by-leaf onto the package `vars`, so a partial override keeps its
siblings. The effective values are what `getVar<T>()` returns inside a
validator run for this group, and what `problem.groups.<name>.vars` renders in
a statement. Keys need not exist at package level.
""",
    )

    score: int = Field(
        default=0,
        description="""
The score of this group in the final score. Useful for
problems that have points.
""",
    )

    deps: List[str] = Field(
        default=[],
        description="""
A list of other groups this group depends on to run and be considered accepted.

The `samples` group is implicitly a dependency of every other group.
""",
    )

    model_solution: Optional[Solution] = Field(
        default=None,
        description="""
The solution to be used to generate outputs for this testgroup.

Can only be set for the "samples" testgroup.
""",
    )

    validateStatementFiles: bool = Field(
        default=False,
        description="""
Whether the statement-only testcase files of this group should be validated.

Statement-only files -- `<name>.in.statement` and `<name>.out.statement` -- override
what a sample shows in the statement without touching the testcase that is actually
judged. By default they are taken at face value: nothing is run over them.

Setting this to `true` runs this group's `validator` and `extraValidators` over every
`.in.statement` file, and its `outputValidators` over every `.out.statement` file, so a
malformed statement-only file fails the build instead of shipping. The checker is still
not run over these files -- skipping it is the whole point of the `.statement` extension.

Mostly useful in the `samples` group. Applies to the group's subgroups as well.
""",
    )

    @model_validator(mode='after')
    def check_model_solution_for_samples(self):
        if self.name == 'samples':
            return self
        if self.model_solution is not None:
            raise PydanticCustomError(
                'MODEL_SOLUTION_NOT_ALLOWED',
                'Model solution can only be set for the "samples" testgroup.',
            )
        return self


class Generator(CodeItem):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(description="""The name of the generator.""")


class InferenceRole(AutoEnum):
    LOWER = alias('lower')  # type: ignore
    """The solution bounds the inferred time limit from below.

    The limit will be large enough for this solution to comfortably pass."""

    UPPER = alias('upper')  # type: ignore
    """The solution bounds the inferred time limit from above.

    The limit will be small enough for this solution to comfortably time out."""


PER_GROUP_OUTCOME_WILDCARD = '*'


class Solution(CodeItem):
    model_config = ConfigDict(extra='forbid')

    outcome: ExpectedOutcome = Field(
        default=ExpectedOutcome.ANY,
        description="""The expected outcome of this solution.""",
    )

    outcomePerGroup: Dict[str, ExpectedOutcome] = Field(
        default={},
        description="""The expected outcome of this solution for each testcase group,
keyed by group name.

Only available for problems with `scoring: points`. A binary-scored problem is
judged as a single pooled verdict over the whole testset, so its groups carry no
independent judgement for an expectation to attach to; declaring this field there
is an error.

Keys must be top-level group names declared in `testcases`; subgroups are not
addressable here.

The reserved key `*` sets a default that applies to every group *individually*,
including `samples` -- add an explicit `samples` entry to override it there.
An entry for a specific group takes precedence over `*`. Groups that match
neither are not checked individually.

This is an extra layer of expectations, checked *in addition* to `outcome`:
`outcome` keeps being matched against the whole testset at once, while each
entry here is matched against that group's tests alone. A solution fails if
either layer fails.

```yaml
scoring: points
solutions:
  - path: 'sols/partial.cpp'
    outcome: incorrect  # fails somewhere in the testset
    outcomePerGroup:
      '*': accepted     # ...but is correct on every group
      group3: tle       # ...except group3, where it must time out
```
""",
    )

    inference: Optional[Union[Literal[False], InferenceRole]] = Field(
        default=None,
        description="""The role this solution plays when inferring the time limit.

When unset, the role follows the expected outcomes of this solution: a solution
expected to be `accepted` everywhere bounds the time limit from below, a
solution expected to be slow (`tle`, `tle-or-rte`) anywhere bounds it from
above, and anything else -- notably `accepted-or-tle` -- bounds neither side.

Set it explicitly to override that:

- `false`: the solution is left out of the estimation entirely -- it is not run
  and bounds neither side.
- `lower`: the time limit must be large enough for this solution to pass. Not
  allowed for solutions expected to be slow.
- `upper`: the time limit must be small enough for this solution to time out.

```yaml
solutions:
  - path: 'sols/borderline.cpp'
    outcome: accepted-or-tle
    inference: upper
```
""",
    )

    tags: List[str] = Field(
        default=[],
        description="""Tags to be associated with this solution.""",
    )

    score: Optional[Union[int, Tuple[Optional[int], Optional[int]]]] = Field(
        default=None,
        description="""The score of this solution in the final score.
Should either be an integer, which means the solution should have this exact score,
or a tuple of two integers, which means the solution should have a score between the two integers (inclusive).

If one of the integers is set to be null, it means that the solution should have a score between the other integer and negative/positive infinity.""",
    )

    @model_validator(mode='after')
    def check_inference_role(self):
        if self.inference == InferenceRole.LOWER and any(
            outcome.is_slow() for outcome in self.all_expected_outcomes()
        ):
            raise PydanticCustomError(
                'INFERENCE_LOWER_NOT_ALLOWED_FOR_SLOW',
                'Solution {path} is expected to be slow, so it cannot bound the time '
                'limit from below; use `inference: upper` or `inference: false`.',
                {'path': str(self.path)},
            )
        return self

    def expected_outcome_for_group(self, group_name: str) -> Optional[ExpectedOutcome]:
        """The expectation for a single group, or None if the group has none."""
        if group_name in self.outcomePerGroup:
            return self.outcomePerGroup[group_name]
        return self.outcomePerGroup.get(PER_GROUP_OUTCOME_WILDCARD)

    def all_expected_outcomes(self) -> Set[ExpectedOutcome]:
        """Every expectation this solution declares, pooled and per-group."""
        # Consumers that ask a coarse question about a solution ("is it expected
        # to be slow?") must consider all of them, not just `outcome`.
        return {self.outcome} | set(self.outcomePerGroup.values())

    def expected_score_range(self) -> Optional[Tuple[int, int]]:
        if self.score is None:
            return None
        if isinstance(self.score, int):
            return (self.score, self.score)
        assert isinstance(self.score, tuple)
        assert len(self.score) == 2

        lo, hi = self.score
        if lo is None:
            lo = 0
        if hi is None:
            hi = 10**9
        return (lo, hi)

    def href(self, hyperlink: bool = True) -> str:
        return href(self.path, style=self.outcome.full_style(), hyperlink=hyperlink)


class Stress(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = NameField(description='The name of the stress test.')

    generator: GeneratorCall = Field(
        description='Generator pattern to call during stress-test.'
    )

    finder: str = Field(
        description='Finder expression to be used to match against generated tests.'
    )


class LimitModifiers(BaseModel):
    timeMultiplier: Optional[float] = Field(
        default=None, description='Multiplier for time limit.'
    )
    time: Optional[int] = Field(
        default=None, description='Value to override time limit with, in milliseconds.'
    )
    memory: Optional[int] = Field(
        default=None, description='Value to override memory limit with, in MB.'
    )


class TimingMultipliers(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    acToTimeLimit: float = Field(
        gt=0,
        description="""Minimum ratio between the time limit and the slowest accepted
solution, used to estimate the time limit from below: the slowest accepted solution
times `acToTimeLimit` must fit within the time limit.""",
    )

    timeLimitToTle: Optional[float] = Field(
        default=None,
        gt=0,
        description="""Minimum ratio between the fastest solution expected to be too
slow and the time limit: the time limit times `timeLimitToTle` must fit within the
fastest solution expected to be too slow. When omitted, solutions expected to be too
slow are not run and the time limit is not bounded from above.""",
    )

    inferenceTimeout: Optional[int] = Field(
        default=None,
        gt=0,
        description="""Deprecated: use `timing.inferenceTimeout`, which applies to
every estimation strategy instead of only to multiplier-based ones. Kept for
backwards compatibility; setting both is an error.""",
    )

    timeResolution: int = Field(
        default=100,
        gt=0,
        description="""Granularity (in milliseconds) of the estimated time limit.
The estimate is the smallest multiple of this value that is valid.""",
    )


class TimingMultipliersOverride(BaseModel):
    model_config = ConfigDict(extra='forbid')

    acToTimeLimit: Optional[float] = Field(
        default=None,
        gt=0,
        description="""Overrides the environment `acToTimeLimit`: the minimum ratio
between the time limit and the slowest accepted solution, which bounds the estimated
time limit from below.""",
    )

    timeLimitToTle: Optional[float] = Field(
        default=None,
        gt=0,
        description="""Overrides the environment `timeLimitToTle`: the minimum ratio
between the fastest solution expected to be too slow and the time limit, which bounds
the estimated time limit from above.""",
    )

    inferenceTimeout: Optional[int] = Field(
        default=None,
        gt=0,
        description="""Deprecated: use `timing.inferenceTimeout`, which applies to
every estimation strategy instead of only to multiplier-based ones. Kept for
backwards compatibility; setting both is an error.""",
    )

    timeResolution: Optional[int] = Field(
        default=None,
        gt=0,
        description="""Overrides the environment `timeResolution`: the granularity
(in milliseconds) the estimated time limit is rounded up to.""",
    )


class PackageTiming(BaseModel):
    model_config = ConfigDict(extra='forbid')

    inferenceTimeout: Optional[int] = Field(
        default=None,
        gt=0,
        description="""Overrides the environment `inferenceTimeout`: the time limit
(in milliseconds) enforced on every solution run while the time limit is estimated,
whatever the estimation strategy is. Raise it for a problem whose solutions are
slower than the environment expects.""",
    )

    multipliers: Optional[TimingMultipliersOverride] = Field(
        default=None,
        description="""Per-problem overrides of the environment's timing
multipliers. Only the declared fields are overridden.""",
    )

    @model_validator(mode='after')
    def _validate_single_inference_timeout(self):
        if (
            self.inferenceTimeout is not None
            and self.multipliers is not None
            and self.multipliers.inferenceTimeout is not None
        ):
            raise ValueError(
                'timing.inferenceTimeout and timing.multipliers.inferenceTimeout '
                'are the same setting; keep only timing.inferenceTimeout.'
            )
        return self


class TimingGroupOrigin(str, enum.Enum):
    ESTIMATED = 'estimated'
    MULTIPLIER = 'multiplier'
    DEFAULTED = 'defaulted'


class TimingBound(BaseModel):
    model_config = ConfigDict(extra='forbid')

    value: int = Field(
        description="""The bound, in milliseconds. A lower bound is the smallest
time limit it allows, before it is rounded up to `timeResolution`; an upper bound is
the largest time limit it allows."""
    )

    solution: Optional[str] = Field(
        default=None,
        description="""The solution that set this bound, when it came from a measured
solution of the group. Absent when the bound was derived from another group's limit.""",
    )


class TimingGroupUpperValidation(BaseModel):
    """What checking a group's slow solutions against its time limit found."""

    model_config = ConfigDict(extra='forbid')

    confirmed: List[str] = Field(
        default=[],
        description="""Solutions of this group expected to be too slow that were
confirmed to be so: they were still running once the estimated time limit times
`timeLimitToTle` had elapsed. Presentation-only.""",
    )

    violating: List[TimingBound] = Field(
        default=[],
        description="""Solutions of this group expected to be too slow that finished
within the estimated time limit times `timeLimitToTle`, so they do not respect the
upper bound. `value` is the time the solution actually took. Presentation-only.""",
    )

    skipped: List[str] = Field(
        default=[],
        description="""Solutions of this group expected to be too slow that were not
run, either because `timeLimitToTle` is unset or because the validation phase was
skipped. Presentation-only.""",
    )


class TimingGroupReport(BaseModel):
    # Ignored rather than refused, for the reason `LimitsProfile` gives: this is
    # reachable only from a profile (`groups`, `baseEstimate`), it is written by
    # rbx and never by hand, and under `forbid` a field added to it would break
    # an older rbx's parse of the whole profile just as surely as one added a
    # level up.
    model_config = ConfigDict(extra='ignore')

    languages: List[str]
    timeLimit: int
    origin: TimingGroupOrigin
    solutionCount: int = 0
    fastest: Optional[int] = None
    slowest: Optional[int] = None
    relativeToLanguage: Optional[str] = None
    multiplier: Optional[float] = None
    increment: Optional[int] = None
    isLeftover: bool = False

    lowerBound: Optional[TimingBound] = Field(
        default=None,
        description="""The lower bound this group's time limit had to respect, when it
was estimated from multipliers. Presentation-only.""",
    )

    upperBound: Optional[TimingBound] = Field(
        default=None,
        description="""The upper bound this group's time limit had to respect, when it
was estimated from multipliers and some slow solution of the group bounded it.
Presentation-only.""",
    )

    upperValidation: Optional[TimingGroupUpperValidation] = Field(
        default=None,
        description="""What checking this group's slow solutions against its estimated
time limit found. Absent when the group has no slow solutions. Presentation-only.""",
    )

    lowerViolation: Optional[TimingBound] = Field(
        default=None,
        description="""The smallest time limit this group's own accepted solutions
allow, recorded only when the group's time limit is below it -- that is, when the
limit was derived from a reference group or the base estimate instead of being
estimated from the group's own solutions, and the group's own solutions do not fit
in it. `solution` is the accepted solution that sets the bound. Absent whenever the
limit respects the group's own evidence. Presentation-only.""",
    )

    droppedUpper: List[str] = Field(
        default=[],
        deprecated=True,
        exclude=True,
        description="""Deprecated: replaced by `upperValidation`. Accepted so that a
limits profile written before the estimation was split into two phases still parses;
never written.""",
    )


class ValidatorTest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    glob: Optional[str] = Field(
        default=None,
        description='A glob pattern for the input files to be used as unit test input for the validator.',
    )

    testplan: Optional[pathlib.Path] = Field(
        default=None,
        description='A testplan to be used as unit test input for the validator.',
    )

    outcome: Optional[ValidatorOutcome] = Field(
        default=None,
        description='The expected outcome of the validator.',
    )

    validator: Optional[CodeItem] = Field(
        default=None,
        description='The validator to use for this test. If not specified, will use the package-level validator.',
    )

    @model_validator(mode='after')
    def check_oneof(self):
        if self.glob is None and self.testplan is None:
            raise PydanticCustomError(
                'GLOB_OR_TESTPLAN_REQUIRED',
                'Either a glob or a testplan must be specified.',
            )
        if self.glob is not None and self.testplan is not None:
            raise PydanticCustomError(
                'GLOB_AND_TESTPLAN_NOT_ALLOWED',
                'Either a glob or a testplan must be specified, but not both.',
            )
        return self

    @model_validator(mode='after')
    def check_testplan(self):
        if self.testplan is not None and self.outcome is not None:
            raise PydanticCustomError(
                'OUTCOME_NOT_ALLOWED',
                'Outcome is not allowed for testplan validator tests.',
            )
        return self

    @model_validator(mode='after')
    def check_glob(self):
        if self.glob is not None and self.outcome is None:
            raise PydanticCustomError(
                'OUTCOME_REQUIRED',
                'Outcome is required for glob validator tests.',
            )
        return self


class CheckerTest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    glob: Optional[str] = Field(
        default=None,
        description='A glob pattern for the files to be used as unit test input for the checker.',
    )

    testplan: Optional[pathlib.Path] = Field(
        default=None,
        description='A testplan to be used as unit test input for the checker.',
    )

    outcome: Optional[ExpectedOutcome] = Field(
        default=None,
        description='The expected outcome of the checker.',
    )

    @model_validator(mode='after')
    def check_oneof(self):
        if self.glob is None and self.testplan is None:
            raise PydanticCustomError(
                'GLOB_OR_TESTPLAN_REQUIRED',
                'Either a glob or a testplan must be specified.',
            )
        if self.glob is not None and self.testplan is not None:
            raise PydanticCustomError(
                'GLOB_AND_TESTPLAN_NOT_ALLOWED',
                'Either a glob or a testplan must be specified, but not both.',
            )
        return self

    @model_validator(mode='after')
    def check_testplan(self):
        if self.testplan is not None and self.outcome is not None:
            raise PydanticCustomError(
                'OUTCOME_NOT_ALLOWED',
                'Outcome is not allowed for testplan checker tests.',
            )
        return self

    @model_validator(mode='after')
    def check_glob(self):
        if self.glob is not None and self.outcome is None:
            raise PydanticCustomError(
                'OUTCOME_REQUIRED',
                'Outcome is required for glob checker tests.',
            )
        return self


class UnitTests(BaseModel):
    model_config = ConfigDict(extra='forbid')

    validator: List[ValidatorTest] = Field(
        default=[],
        description='Unit tests for the validator.',
    )

    checker: List[CheckerTest] = Field(
        default=[],
        description='Unit tests for the checker.',
    )


class LimitsProfile(BaseModel):
    # Unknown keys are ignored, not refused -- the one model in this file that
    # tolerates them, and deliberately.
    #
    # A `limits/<name>.yml` is written by rbx (`rbx time --integrate`, the TUI
    # limits editor), so a setter reads profiles that a *different* rbx wrote:
    # a teammate's, or their own after an upgrade or a downgrade. Under
    # `extra='forbid'` every field added here is a hard break in that direction
    # -- the older rbx refuses to parse the profile at all, and the limits it
    # was going to run under are simply unavailable. `estimationChecksum` was
    # the field that made this concrete.
    #
    # Ignoring costs the typo-catching that `forbid` buys elsewhere, which is a
    # real loss on a file a setter may hand-edit. It is the smaller one: a
    # mistyped key falls back to a documented default, while a refused profile
    # stops the command. This is also what `run_report` already relies on for
    # the same reason -- see its `REPORT_VERSION` note on additive fields.
    model_config = ConfigDict(extra='ignore')

    inheritFromPackage: bool = Field(
        default=False,
        description="""
Whether to inherit limits from the package.
""",
    )

    timeLimit: Optional[int] = Field(
        default=None, description='Time limit of the problem, in milliseconds.'
    )

    memoryLimit: Optional[int] = Field(
        default=None, description='Memory limit of the problem, in MB.'
    )

    outputLimit: Optional[int] = Field(
        default=None, description='Output limit of the problem, in KB.'
    )

    modifiers: Dict[str, LimitModifiers] = Field(
        default={},
        description="""
    Limit modifiers that can be specified per language.
    """,
    )

    formula: Optional[str] = Field(
        default=None,
        description="""
A formula to estimate the time limit for the problem.
""",
    )

    multipliers: Optional[TimingMultipliers] = Field(
        default=None,
        description="""
The multipliers this profile was estimated from, when it was estimated from
ratios instead of a formula. Presentation-only; never used for limit resolution.
""",
    )

    groups: Optional[List[TimingGroupReport]] = Field(
        default=None,
        description="""
Metadata describing the language grouping used when this profile was estimated.
Presentation-only; never used for limit resolution.
""",
    )

    baseEstimate: Optional[TimingGroupReport] = Field(
        default=None,
        description="""
Metadata describing how the base (fallback) time limit was estimated, pooled
across every solution. Presentation-only; never used for limit resolution.
""",
    )

    estimationChecksum: Optional[str] = Field(
        default=None,
        description="""
A checksum of everything this estimate was computed from -- the solutions that
bound the limit, and, when the tests were built, the interactor and the test
inputs. Written by `rbx time`; consumers compare it against the package to warn
that a saved limit predates the current solutions or testset.

Presentation-only; never used for limit resolution. Absent on a profile whose
limit was not estimated (inherited from the package, or set by hand).
""",
    )

    def timelimit_for_language(self, language: Optional[str] = None) -> int:
        assert self.timeLimit is not None
        res = self.timeLimit
        if language is not None and language in self.modifiers:
            modifier = self.modifiers[language]
            if modifier.time is not None:
                res = modifier.time
            if modifier.timeMultiplier is not None:
                res = int(res * float(modifier.timeMultiplier))
        if 'RBX_TIME_MULTIPLIER' in utils.environ():
            res = int(res * float(utils.environ()['RBX_TIME_MULTIPLIER']))
        return res

    def memorylimit_for_language(self, language: Optional[str] = None) -> int:
        assert self.memoryLimit is not None
        res = self.memoryLimit
        if language is None:
            return res
        if language not in self.modifiers:
            return res
        modifier = self.modifiers[language]
        if modifier.memory is not None:
            return modifier.memory
        return res


class Package(BaseModel):
    model_config = ConfigDict(extra='forbid')

    # Name of the problem.
    name: str = NameField(description='The name of the problem.')

    titles: Dict[str, str] = Field(
        default={},
        description='Titles for the problem in each language. '
        'Languages should be specified as lowercase ISO 639-1 codes.',
    )

    type: TaskType = Field(
        default=TaskType.BATCH, description='The type of the problem.'
    )

    scoring: ScoreType = Field(
        default=ScoreType.BINARY, description='The scoring type of the problem.'
    )

    timeLimit: int = Field(description='Time limit of the problem, in milliseconds.')

    memoryLimit: int = Field(description='Memory limit of the problem, in MB.')

    outputLimit: int = Field(
        default=4 * 1024, description='Output limit of the problem, in KB.'
    )

    timing: Optional[PackageTiming] = Field(
        default=None,
        description='Problem-level overrides for time limit inference.',
    )

    modifiers: Dict[str, LimitModifiers] = Field(
        default={},
        description="""
    Limit modifiers that can be specified per language.
    """,
    )

    checker: Optional[Checker] = Field(
        default=None, description='The checker for this problem.'
    )

    interactor: Optional[Interactor] = Field(
        default=None, description='The interactor for this problem.'
    )

    validator: Optional[CodeItem] = Field(
        default=None, description='The validator for this problem.'
    )

    extraValidators: List[CodeItem] = Field(
        default=[], description='Extra validators for this problem.'
    )

    outputValidators: List[CodeItem] = Field(
        default=[],
        description="""
A list of output validators to use to validate the output of the testcases of this problem.
""",
    )

    visualizer: Optional[Visualizer] = Field(
        default=None,
        description='The visualizer for this problem. Used to produced visualizations for the testcases.',
    )

    solutionVisualizer: Optional[Visualizer] = Field(
        default=None,
        description='The solution visualizer for this problem. Used to produced visualizations for the outputs of the testcases.',
    )

    generators: List[Generator] = Field(
        default=[], description='Generators for this problem.'
    )

    generatorScript: Optional[GeneratorScript] = Field(
        default=None,
        description="""
A generator script used as the default for any test group or subgroup that does
not specify its own test parameters (testcases, testcaseGlob, generators,
generatorScript) and has no subgroups of its own.

Useful when a single script -- usually partitioned with `@testgroup` blocks --
drives generation for every group, so it does not need to be repeated on each one.
""",
    )

    solutions: List[Solution] = Field(
        default=[],
        description="""
All tested solutions for this problem.

The first solution in this list should be the main solution -- the one
that is correct and used as reference -- and should have the `accepted` outcome.
""",
    )

    testcases: Annotated[
        List[TestcaseGroup],
        AfterValidator(is_unique_testcase_group_names),
    ] = Field(default=[], description='Testcases for the problem.')

    stresses: List[Stress] = Field(
        default=[], description='Stress tests for the problem.'
    )

    statements: Annotated[
        List[Statement],
        AfterValidator(is_unique_problem_statements),
    ] = Field(default=[], description='Statements for the problem.')

    tutorials: Annotated[
        List[Statement],
        AfterValidator(is_unique_problem_statements),
    ] = Field(default=[], description='Tutorials (editorials) for the problem.')

    # Vars to be re-used across the package.
    #   - It will be passed as --key=value arguments to the validator.
    #   - It will be available as \VAR{key} variables in the rbx statement.
    vars: CheckedRecVars = Field(
        default={}, description='Variables to be re-used across the package.'
    )

    unitTests: UnitTests = Field(
        default_factory=UnitTests,
        description='Unit tests for components of this problem.',
    )

    @property
    def expanded_statements(self) -> List[Statement]:
        return expand_problem_statements(self.statements)

    @property
    def expanded_tutorials(self) -> List[Statement]:
        return expand_problem_statements(self.tutorials)

    @property
    def expanded_vars(self) -> Vars:
        return expand_vars(self.vars)

    def expanded_vars_for_group(self, group_name: Optional[str]) -> Vars:
        """Package vars with the named group's overrides applied.

        The merge happens before expansion, so an override can feed the
        interpolation of any var derived from it.

        Falls back to the package vars when ``group_name`` is None or names no
        declared group (interactive validation, unit tests, samples).
        """
        if group_name is None:
            return self.expanded_vars
        for testcase_group in self.testcases:
            if testcase_group.name == group_name:
                return expand_vars(merge_recvars(self.vars, testcase_group.vars))
        return self.expanded_vars

    @model_validator(mode='after')
    def check_first_solution_is_main_if_there_is_ac(self):
        if all(sol.outcome != ExpectedOutcome.ACCEPTED for sol in self.solutions):
            # No main solution.
            return self
        if self.solutions:
            if self.solutions[0].outcome != ExpectedOutcome.ACCEPTED:
                raise PydanticCustomError(
                    'MISSING_MAIN_SOLUTION',
                    'The first solution in the package must have the "ACCEPTED" outcome if there are ACCEPTED solutions.',
                )
        return self

    @model_validator(mode='after')
    def samples_come_first(self):
        for i, group in enumerate(self.testcases):
            if group.name == 'samples' and i > 0:
                raise PydanticCustomError(
                    'SAMPLES_NOT_FIRST',
                    'The "samples" group must be the first group in the package, but is actually the {i}-th',
                    {'i': i + 1},
                )
        return self

    @model_validator(mode='after')
    def check_scoring_fields(self):
        if not self.scoring == ScoreType.POINTS:
            for group in self.testcases:
                if group.deps:
                    raise PydanticCustomError(
                        'DEPS_NOT_ALLOWED',
                        'Dependencies are not allowed for groups of problems with scoring != POINTS.',
                    )
                if group.score != 0:
                    raise PydanticCustomError(
                        'SCORE_NOT_ALLOWED',
                        'Non-zero score is not allowed for groups of problems with scoring != POINTS.',
                    )
            for solution in self.solutions:
                if solution.score is not None:
                    raise PydanticCustomError(
                        'SCORE_NOT_ALLOWED',
                        'Expected score is not allowed for solutions of problems with scoring != POINTS.',
                    )
                # A BINARY problem judges the testset as one pooled verdict, so a
                # per-group expectation has no scoring semantics to attach to.
                # Rejecting it here lets every consumer downstream assume the
                # per-group layer only ever exists under POINTS.
                if solution.outcomePerGroup:
                    raise PydanticCustomError(
                        'OUTCOME_PER_GROUP_NOT_ALLOWED',
                        'Per-group expected outcomes ("outcomePerGroup") are not allowed '
                        'for solutions of problems with scoring != POINTS, since such '
                        'problems are judged as a single pooled verdict over the whole '
                        'testset. Use "outcome", or set "scoring: points".',
                    )
        return self

    @model_validator(mode='after')
    def check_deps(self):
        depends = collections.defaultdict(list)
        for group in self.testcases:
            if group.name == 'samples':
                if group.deps:
                    raise PydanticCustomError(
                        'DEPS_NOT_ALLOWED',
                        'Dependencies are not allowed for the "samples" group.',
                    )
                continue
            depends[group.name].extend(group.deps)

        visiting = set()
        visited = set()

        def dfs(u):
            visiting.add(u)
            for v in depends[u]:
                if v in visiting:
                    return True
                if v not in visited:
                    if dfs(v):
                        return True
            visiting.remove(u)
            visited.add(u)
            return False

        for group in self.testcases:
            if group.name != 'samples' and group.name not in visited:
                if dfs(group.name):
                    raise PydanticCustomError(
                        'CYCLIC_DEPENDENCY',
                        'Cyclic dependency detected involving test group "{group_name}".',
                        {'group_name': group.name},
                    )
        return self

    # The three `outcomePerGroup` validators below run in declaration order, and
    # that order is load-bearing: an unknown group name is reported before any
    # verdict about satisfiability (a typo'd key resolves to nothing, so every
    # later conclusion about it would be noise), and the main-solution check
    # deliberately pre-empts the vaguer CONTRADICTORY_OUTCOME error, which would
    # otherwise fire first for a reference solution pinned to a bad outcome.
    @model_validator(mode='after')
    def check_outcome_per_group_names(self):
        group_names = set(group.name for group in self.testcases)
        for solution in self.solutions:
            for group_name in solution.outcomePerGroup:
                if group_name == PER_GROUP_OUTCOME_WILDCARD:
                    continue
                if group_name not in group_names:
                    raise PydanticCustomError(
                        'UNKNOWN_OUTCOME_GROUP',
                        'Solution "{path}" declares an expected outcome for group '
                        '"{group}", which is not a testcase group of this package. '
                        'Known groups: {known}.',
                        {
                            'path': str(solution.path),
                            'group': group_name,
                            'known': ', '.join(group.name for group in self.testcases),
                        },
                    )
        return self

    @model_validator(mode='after')
    def check_main_solution_outcome_per_group(self):
        main = next(
            (sol for sol in self.solutions if sol.outcome == ExpectedOutcome.ACCEPTED),
            None,
        )
        if main is None:
            # No reference solution, so there is nothing to hold to ACCEPTED.
            return self
        for group_name, expected in main.outcomePerGroup.items():
            if expected.match(Outcome.ACCEPTED):
                continue
            if group_name == PER_GROUP_OUTCOME_WILDCARD:
                raise PydanticCustomError(
                    'MAIN_SOLUTION_NOT_ACCEPTED',
                    'The first accepted solution generates the reference outputs, so '
                    'it must be accepted everywhere, but it expects "{expected}" as '
                    'the default for every group ("*").',
                    {'expected': expected.name},
                )
            raise PydanticCustomError(
                'MAIN_SOLUTION_NOT_ACCEPTED',
                'The first accepted solution generates the reference outputs, so it '
                'must be accepted everywhere, but it expects "{expected}" on '
                '"{group}".',
                {'expected': expected.name, 'group': group_name},
            )
        return self

    @model_validator(mode='after')
    def check_outcome_per_group_is_satisfiable(self):
        for solution in self.solutions:
            if not solution.outcomePerGroup:
                continue
            for group_name, expected in solution.outcomePerGroup.items():
                if expected.match(Outcome.ACCEPTED):
                    # The group admits a fully accepted run, which never
                    # conflicts with the pooled expectation.
                    continue
                # The group demands a bad verdict; the pooled expectation must
                # admit at least one of the verdicts that would satisfy it.
                if not solution.outcome.intersect(expected):
                    raise PydanticCustomError(
                        'CONTRADICTORY_OUTCOME',
                        'Solution "{path}" expects "{expected}" on "{group}", which '
                        'cannot be satisfied together with the expected outcome '
                        '"{outcome}" for the whole testset.',
                        {
                            'path': str(solution.path),
                            'expected': expected.name,
                            'group': group_name,
                            'outcome': solution.outcome.name,
                        },
                    )

            if solution.outcome.match(Outcome.ACCEPTED) or not self.testcases:
                continue
            # The pooled expectation demands a bad verdict *somewhere*. If every
            # group is individually pinned to an outcome that admits none, there
            # is nowhere for it to happen.
            pinned = [
                solution.expected_outcome_for_group(group.name)
                for group in self.testcases
            ]
            if any(expected is None for expected in pinned):
                # Some group is unconstrained, so it is free to host the failure.
                continue
            # `solution.outcome` does not match ACCEPTED here, so every verdict it
            # matches is a bad one: some group's expectation must admit one of them.
            some_group_can_fail = any(
                solution.outcome.match(verdict)
                for expected in pinned
                for verdict in expected.get_matches()
            )
            if not some_group_can_fail:
                raise PydanticCustomError(
                    'CONTRADICTORY_OUTCOME',
                    'Solution "{path}" expects "{outcome}" for the whole testset, '
                    'but every group is pinned to an outcome that cannot produce '
                    'it, so the expectation cannot be satisfied.',
                    {'path': str(solution.path), 'outcome': solution.outcome.name},
                )
        return self

    @model_validator(mode='after')
    def check_checker_and_interactor_for_task_type(self):
        if self.type == TaskType.BATCH:
            if self.interactor is not None:
                raise PydanticCustomError(
                    'INTERACTOR_NOT_ALLOWED',
                    'Interactor is not allowed for batch problems. Change the task type to COMMUNICATION.',
                )
        if self.type == TaskType.COMMUNICATION:
            if self.checker is not None and (
                self.interactor is None or not self.interactor.legacy
            ):
                raise PydanticCustomError(
                    'CHECKER_NOT_ALLOWED',
                    'Checkers should not be specified for communication problems.',
                )
        return self
