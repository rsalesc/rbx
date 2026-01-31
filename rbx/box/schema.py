from __future__ import annotations

import collections
import pathlib
import re
import typing
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from rbx import utils
from rbx.autoenum import AutoEnum, alias
from rbx.box.fields import NameField, Primitive, RecVars, Vars, expand_vars
from rbx.box.formatting import href
from rbx.box.statements.expander import expand_statements
from rbx.box.statements.schema import Statement
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


def is_unique_by_name(statements: List['Statement']) -> List['Statement']:
    names = {st.name for st in statements}
    if len(names) != len(statements):
        raise ValueError('Statement names must be unique.')
    return statements


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

    JUDGE_FAILED = alias('judge failed', 'jf')  # type: ignore
    """Expected outcome for solutions that finish with a judge failed verdict.
    
    Only useful for checker tests."""

    COMPILATION_ERROR = alias('compilation error', 'ce')  # type: ignore
    """Expected outcome for solutions that finish with a compilation error verdict.
    
    Only useful for checker tests."""

    def style(self) -> str:
        if self == ExpectedOutcome.ANY:
            return 'orange'
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
        if self == ExpectedOutcome.OUTPUT_LIMIT_EXCEEDED:
            return outcome == Outcome.OUTPUT_LIMIT_EXCEEDED
        if self == ExpectedOutcome.JUDGE_FAILED:
            return outcome == Outcome.JUDGE_FAILED
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


class ScoreType(AutoEnum):
    BINARY = alias('binary')  # type: ignore
    """Scoring for ICPC-like problems, where the problem is considered a point if it pass all testcases."""

    POINTS = alias('points')  # type: ignore
    """Subtasks scoring, where each passing testgroup is worth a number of points that are summed up."""


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

    def href(self, hyperlink: bool = True) -> str:
        return href(self.path, hyperlink=hyperlink)

    def display(self) -> str:
        return self.href(hyperlink=False)


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


class Visualizer(CodeItem):
    model_config = ConfigDict(extra='forbid')

    extension: str = Field(
        description="""The extension of the visualization file generated by the visualizer.
        """,
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

    outputVisualizer: Optional[Visualizer] = Field(
        default=None,
        description='The output visualizer for this problem. Used to produced visualizations for the outputs of the testcases. '
        'Has priority over the output visualizer specified in the package.',
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


class Solution(CodeItem):
    model_config = ConfigDict(extra='forbid')

    outcome: ExpectedOutcome = Field(
        default=ExpectedOutcome.ANY,
        description="""The expected outcome of this solution.""",
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
    model_config = ConfigDict(extra='forbid')

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

    outputVisualizer: Optional[Visualizer] = Field(
        default=None,
        description='The output visualizer for this problem. Used to produced visualizations for the outputs of the testcases.',
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

    statements: Annotated[
        List[Statement],
        AfterValidator(is_unique_by_name),
    ] = Field(default=[], description='Statements for the problem.')

    # Vars to be re-used across the package.
    #   - It will be passed as --key=value arguments to the validator.
    #   - It will be available as \VAR{key} variables in the rbx statement.
    vars: RecVars = Field(
        default={}, description='Variables to be re-used across the package.'
    )

    unitTests: UnitTests = Field(
        default_factory=UnitTests,
        description='Unit tests for components of this problem.',
    )

    @property
    def expanded_statements(self) -> List[Statement]:
        return expand_statements(self.statements)

    @property
    def expanded_vars(self) -> Vars:
        return expand_vars(self.vars)

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
