from __future__ import annotations

import os
import pathlib
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from rbx.autoenum import AutoEnum, alias
from rbx.box.statements.schema import Statement
from rbx.grading.steps import Outcome

Primitive = Union[str, int, float, bool]


def NameField(**kwargs):
    return Field(
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9\-_]*$', min_length=3, max_length=32, **kwargs
    )


def FNameField(**kwargs):
    return Field(
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9\-_]*$', min_length=3, max_length=128, **kwargs
    )


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


def expand_var(value: Primitive) -> Primitive:
    if not isinstance(value, str):
        return value
    if value.startswith('\\'):
        return value[1:]
    if not value.startswith('py`') or not value.endswith('`'):
        return value
    res = eval(value[3:-1])
    for supported_type in [str, int, float, bool]:
        if isinstance(res, supported_type):
            return res

    raise TypeError(
        f'Variable with backticks should evaluate to a primitive Python type: {value}'
    )


class ExpectedOutcome(AutoEnum):
    ANY = alias('any')  # type: ignore
    """Expected outcome for any outcome."""

    ACCEPTED = alias('accepted', 'ac', 'correct')  # type: ignore
    """Expected outcome for correct solutions (AC)."""

    ACCEPTED_OR_TLE = alias(
        'accepted or time limit exceeded',
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

    def style(self) -> str:
        if self == ExpectedOutcome.ANY:
            return 'orange'
        if self == ExpectedOutcome.ACCEPTED:
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
        return 'magenta'

    def is_slow(self) -> bool:
        return self in [ExpectedOutcome.TIME_LIMIT_EXCEEDED, ExpectedOutcome.TLE_OR_RTE]

    def matches_tle_and_is_incorrect(self) -> bool:
        return self.match(Outcome.TIME_LIMIT_EXCEEDED) and not self.match(
            Outcome.ACCEPTED
        )

    def match(self, outcome: Outcome) -> bool:
        if self == ExpectedOutcome.ANY:
            return True
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
        if self == ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED:
            return outcome == Outcome.OUTPUT_LIMIT_EXCEEDED
        return False

    def get_matches(self) -> List[Outcome]:
        return [outcome for outcome in Outcome if self.match(outcome)]

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


class CodeItem(BaseModel):
    model_config = ConfigDict(extra='forbid')

    path: pathlib.Path = Field(
        description="""The path to the code file, relative to the package directory."""
    )

    language: Optional[str] = Field(
        default=None, description="""The language of the code file."""
    )

    compilationFiles: Optional[List[str]] = Field(
        default=[],
        description="""
Extra files that should be placed alongside the code file during its compilation,
such as testlib.h, jngen.h, etc.

The paths should be given relative to the package directory, but will be included
relative to the `path` directory.

Testlib and jngen are already included by default.
""",
    )


class Testcase(BaseModel):
    model_config = ConfigDict(extra='forbid')

    inputPath: pathlib.Path = Field(description="""The path of the input file.""")

    outputPath: Optional[pathlib.Path] = Field(
        default=None, description="""The path of the output file."""
    )


class GeneratorCall(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = FNameField(description='The name of the generator to call.')

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

    generatorScript: Optional[CodeItem] = Field(
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

    subgroups: List[TestcaseSubgroup] = Field(
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

    weight: Optional[float] = Field(
        default=1.0,
        description="""
The weight of this group in the final score. Useful for
problems that have points.
""",
    )


class Generator(CodeItem):
    model_config = ConfigDict(extra='forbid')

    name: str = NameField(description="""The name of the generator.""")


class Solution(CodeItem):
    model_config = ConfigDict(extra='forbid')

    outcome: ExpectedOutcome = Field(
        description="""The expected outcome of this solution."""
    )


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


class ValidatorTest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    glob: str = Field(
        description='A glob pattern for the input files to be used as unit test input for the validator.'
    )
    outcome: ValidatorOutcome = Field(
        default=ValidatorOutcome.VALID,
        description='The expected outcome of the validator.',
    )

    validator: Optional[CodeItem] = Field(
        default=None,
        description='The validator to use for this test. If not specified, will use the package-level validator.',
    )


class CheckerTest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    glob: str = Field(
        description="""
A glob pattern for the files to be used as unit test input for the checker.
This glob should simultaneously match the input, output, and answer files (.in, .out, .ans).
If one of them is not present, an empty file will be used instead.
""",
    )

    outcome: ExpectedOutcome = Field(
        default=ExpectedOutcome.ACCEPTED,
        description='The expected outcome of the checker.',
    )


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


class Package(BaseModel):
    model_config = ConfigDict(extra='forbid')

    # Name of the problem.
    name: str = NameField(description='The name of the problem.')

    type: TaskType = Field(
        default=TaskType.BATCH, description='The type of the problem.'
    )

    timeLimit: int = Field(description='Time limit of the problem, in milliseconds.')

    memoryLimit: int = Field(description='Memory limit of the problem, in MB.')

    outputLimit: int = Field(
        default=4 * 1024, description='Output limit of the problem, in KB.'
    )

    modifiers: Dict[str, LimitModifiers] = Field(
        default={},
        description="""
    Limit modifiers that can be specified per language.
    """,
    )

    checker: Optional[CodeItem] = Field(
        default=None, description='The checker for this problem.'
    )

    interactor: Optional[CodeItem] = Field(
        default=None, description='The interactor for this problem.'
    )

    validator: Optional[CodeItem] = Field(
        default=None, description='The validator for this problem.'
    )

    generators: List[Generator] = Field(
        default=[], description='Generators for this problem.'
    )

    solutions: List[Solution] = Field(
        default=[],
        description="""
All tested solutions for this problem.

The first solution in this list should be the main solution -- the one
that is correct and used as reference -- and should have the `accepted` outcome.
""",
    )

    testcases: List[TestcaseGroup] = Field(
        default=[], description='Testcases for the problem.'
    )

    stresses: List[Stress] = Field(
        default=[], description='Stress tests for the problem.'
    )

    statements: List[Statement] = Field(
        default=[], description='Statements for the problem.'
    )

    # Vars to be re-used across the package.
    #   - It will be passed as --key=value arguments to the validator.
    #   - It will be available as \VAR{key} variables in the rbx statement.
    vars: Dict[str, Primitive] = Field(
        default={}, description='Variables to be re-used across the package.'
    )

    unitTests: UnitTests = Field(
        default_factory=UnitTests,
        description='Unit tests for components of this problem.',
    )

    @property
    def expanded_vars(self) -> Dict[str, Primitive]:
        return {key: expand_var(value) for key, value in self.vars.items()}

    def timelimit_for_language(self, language: Optional[str]) -> int:
        res = self.timeLimit
        if language is not None and language in self.modifiers:
            modifier = self.modifiers[language]
            if modifier.time is not None:
                res = modifier.time
            if modifier.timeMultiplier is not None:
                res = int(res * float(modifier.timeMultiplier))
        if 'RBX_TIME_MULTIPLIER' in os.environ:
            res = int(res * float(os.environ['RBX_TIME_MULTIPLIER']))
        return res

    def memorylimit_for_language(self, language: Optional[str]) -> int:
        res = self.memoryLimit
        if language is None:
            return res
        if language not in self.modifiers:
            return res
        modifier = self.modifiers[language]
        if modifier.memory is not None:
            return modifier.memory
        return res

    @model_validator(mode='after')
    def check_first_solution_is_main_if_there_is_ac(self):
        if all(sol.outcome != Outcome.ACCEPTED for sol in self.solutions):
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
