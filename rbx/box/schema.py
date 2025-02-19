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

    TIME_LIMIT_EXCEEDED = alias('time limit exceeded', 'timeout', 'tle')  # type: ignore
    """Expected outcome for solutions that do not finish in time."""

    MEMORY_LIMIT_EXCEEDED = alias('memory limit exceeded', 'mle')  # type: ignore
    """Expected outcome for solutions that use more memory than allowed."""

    OUTPUT_LIMIT_EXCEEDED = alias('output limit exceeded', 'ole')  # type: ignore
    """Expected outcome for solutions that use more output than allowed."""

    TLE_OR_RTE = alias('tle or rte', 'tle/rte', 'tle+rte')  # type: ignore
    """Expected outcome for solutions that finish with either TLE or RTE.

    Especially useful for environments where TLE and RTE are indistinguishable."""

    def style(self) -> str:
        if self == ExpectedOutcome.ACCEPTED:
            return 'green'
        if self == ExpectedOutcome.WRONG_ANSWER:
            return 'red'
        if self == ExpectedOutcome.INCORRECT:
            return 'red'
        if self.match(Outcome.TIME_LIMIT_EXCEEDED):
            return 'yellow'
        if self.match(Outcome.RUNTIME_ERROR):
            return 'lnumber'
        if self.match(Outcome.MEMORY_LIMIT_EXCEEDED):
            return 'cyan'
        return 'magenta'

    def is_slow(self) -> bool:
        return self in [ExpectedOutcome.TIME_LIMIT_EXCEEDED, ExpectedOutcome.TLE_OR_RTE]

    def match(self, outcome: Outcome) -> bool:
        if self == ExpectedOutcome.ACCEPTED:
            return outcome == Outcome.ACCEPTED
        if self == ExpectedOutcome.ACCEPTED_OR_TLE:
            return outcome in {Outcome.ACCEPTED, Outcome.TIME_LIMIT_EXCEEDED}
        if self == ExpectedOutcome.WRONG_ANSWER:
            return outcome == Outcome.WRONG_ANSWER
        if self == ExpectedOutcome.INCORRECT:
            return outcome in {
                Outcome.WRONG_ANSWER,
                Outcome.RUNTIME_ERROR,
                Outcome.MEMORY_LIMIT_EXCEEDED,
                Outcome.TIME_LIMIT_EXCEEDED,
                Outcome.OUTPUT_LIMIT_EXCEEDED,
            }
        if self == ExpectedOutcome.RUNTIME_ERROR:
            return outcome == Outcome.RUNTIME_ERROR
        if self == ExpectedOutcome.TIME_LIMIT_EXCEEDED:
            return outcome == Outcome.TIME_LIMIT_EXCEEDED
        if self == ExpectedOutcome.MEMORY_LIMIT_EXCEEDED:
            return outcome == Outcome.MEMORY_LIMIT_EXCEEDED
        if self == ExpectedOutcome.TLE_OR_RTE:
            return outcome in {Outcome.TIME_LIMIT_EXCEEDED, Outcome.RUNTIME_ERROR}
        if self == ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED:
            return outcome == Outcome.OUTPUT_LIMIT_EXCEEDED
        return False

    def get_matches(self) -> List[Outcome]:
        return [outcome for outcome in Outcome if self.match(outcome)]

    def intersect(self, rhs: 'ExpectedOutcome') -> bool:
        return bool(set(self.get_matches()) & set(rhs.get_matches()))


class CodeItem(BaseModel):
    model_config = ConfigDict(extra='forbid')

    path: pathlib.Path = Field(
        description="""The path to the code file, relative to the package directory."""
    )

    language: Optional[str] = Field(
        None, description="""The language of the code file."""
    )

    compilationFiles: Optional[List[str]] = Field(
        [],
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
        None, description="""The path of the output file."""
    )


class GeneratorCall(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = NameField(description='The name of the generator to call.')

    args: Optional[str] = Field(
        None, description='The arguments to pass to the generator.'
    )


class TestcaseSubgroup(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = NameField(description='The name of the test group.')

    testcases: List[Testcase] = Field(
        [],
        description="""
The path of testcases to add to this group,
in the order they're defined.""",
    )

    testcaseGlob: Optional[str] = Field(
        None,
        description="""
A Python glob that matches input file paths relative to the
package directory. The globbed files should end with the extension
".in", and their corresponding outputs, if defined, should have the same file name,
but ending with ".out".
""",
    )

    generators: List[GeneratorCall] = Field(
        [],
        description="""
A list of generators to call to generate testcases for this group.
""",
    )

    generatorScript: Optional[CodeItem] = Field(
        None,
        description="""
A generator script to call to generate testcases for this group.
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
        [],
        description="""
A list of test subgroups to define for this group.
        """,
    )

    validator: Optional[CodeItem] = Field(
        None,
        description="""
A validator to use to validate the testcases of this group.
If not specified, will use the package-level validator.
Useful in cases where the constraints vary across test groups.
""",
    )

    weight: Optional[float] = Field(
        1.0,
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


class Limits(BaseModel):
    time: Optional[int] = Field(
        None, description='Value to override time limit with, in milliseconds.'
    )
    memory: Optional[int] = Field(
        None, description='Value to override memory limit with, in MB.'
    )
    output: Optional[int] = Field(
        None, description='Value to override output limit with, in KB.'
    )

    isDoubleTL: bool = Field(
        False, description='Whether to use double TL for this language.'
    )


class LimitModifiers(BaseModel):
    timeMultiplier: Optional[float] = Field(
        None, description='Multiplier for time limit.'
    )
    time: Optional[int] = Field(
        None, description='Value to override time limit with, in milliseconds.'
    )
    memory: Optional[int] = Field(
        None, description='Value to override memory limit with, in MB.'
    )


class Package(BaseModel):
    model_config = ConfigDict(extra='forbid')

    # Name of the problem.
    name: str = NameField(description='The name of the problem.')

    timeLimit: int = Field(description='Time limit of the problem, in milliseconds.')

    memoryLimit: int = Field(description='Memory limit of the problem, in MB.')

    outputLimit: int = Field(
        4 * 1024, description='Output limit of the problem, in KB.'
    )

    modifiers: Dict[str, LimitModifiers] = Field(
        {},
        description="""
    Limit modifiers that can be specified per language.
    """,
    )

    checker: Optional[CodeItem] = Field(
        None, description='The checker for this problem.'
    )

    validator: Optional[CodeItem] = Field(
        None, description='The validator for this problem.'
    )

    generators: List[Generator] = Field([], description='Generators for this problem.')

    solutions: List[Solution] = Field(
        [],
        description="""
All tested solutions for this problem.

The first solution in this list should be the main solution -- the one
that is correct and used as reference -- and should have the `accepted` outcome.
""",
    )

    testcases: List[TestcaseGroup] = Field([], description='Testcases for the problem.')

    stresses: List[Stress] = Field([], description='Stress tests for the problem.')

    statements: List[Statement] = Field([], description='Statements for the problem.')

    # Vars to be re-used across the package.
    #   - It will be passed as --key=value arguments to the validator.
    #   - It will be available as \VAR{key} variables in the rbx statement.
    vars: Dict[str, Primitive] = Field(
        {}, description='Variables to be re-used across the package.'
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
    def check_first_solution_is_main(self):
        if self.solutions:
            if self.solutions[0].outcome != ExpectedOutcome.ACCEPTED:
                raise PydanticCustomError(
                    'MISSING_MAIN_SOLUTION',
                    'The first solution in the package must have the "ACCEPTED" outcome.',
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
