import pathlib
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from rbx.box.schema import NameField, Primitive, expand_var
from rbx.box.statements.schema import (
    ConversionStep,
    Joiner,
    StatementType,
)


def ShortNameField(**kwargs):
    return Field(pattern=r'^[A-Z]+[0-9]*$', min_length=1, max_length=4, **kwargs)


class ProblemStatementOverride(BaseModel):
    model_config = ConfigDict(extra='forbid')

    configure: List[ConversionStep] = Field(
        [],
        discriminator='type',
        description="""
Configure how certain conversion steps should happen when applied to the statement file.

Different from the `steps` field, this does not force the steps to happen, but rather only
configure them in case they are applied.
""",
    )


class ContestStatement(BaseModel):
    model_config = ConfigDict(extra='forbid')

    language: str = Field('en', description='Language code for this statement.')

    title: str = Field(description='Title of the contest in this language.')

    location: Optional[str] = Field(
        default=None, description='Location of the contest in this language.'
    )

    date: Optional[str] = Field(
        default=None, description='Date of the contest in this language.'
    )

    path: pathlib.Path = Field(description='Path to the input statement file.')

    type: StatementType = Field(description='Type of the input statement file.')

    joiner: Optional[Joiner] = Field(
        None,
        description="""
Joiner to be used to build the statement.
                           
This determines how problem statements will be joined into a single contest statement.""",
    )

    steps: List[ConversionStep] = Field(
        default=[],
        discriminator='type',
        description="""
Describes a sequence of conversion steps that should be applied to the statement file
of this contest.

Usually, it is not necessary to specify these, as they can be inferred from the
input statement type and the output statement type, but you can use this to force
certain conversion steps to happen.
""",
    )

    configure: List[ConversionStep] = Field(
        default=[],
        discriminator='type',
        description="""
Configure how certain conversion steps should happen when applied to the statement file of
this contest.

Different from the `steps` field, this does not force the steps to happen, but rather only
configure them in case they are applied.
""",
    )

    assets: List[str] = Field(
        default=[],
        description="""
Assets relative to the contest directory that should be included while building
the statement. Files will be included in the same folder as the statement file.
Can be glob pattern as well, such as `imgs/*.png`.
""",
    )

    override: Optional[ProblemStatementOverride] = Field(
        default=None, description='Override configuration for problem statements.'
    )

    # Vars to be re-used in the statement.
    #   - It will be available as \VAR{vars} variable in the contest-level box statement.
    vars: Dict[str, Primitive] = Field(
        {}, description='Variables to be re-used across the package.'
    )

    @property
    def expanded_vars(self) -> Dict[str, Primitive]:
        return {key: expand_var(value) for key, value in self.vars.items()}


class ContestProblem(BaseModel):
    short_name: str = ShortNameField(
        description="""
Short name of the problem. Usually, just an uppercase letter,
but can be a sequence of uppercase letters followed by a number."""
    )
    path: Optional[pathlib.Path] = Field(
        default=None,
        description="""
Path to the problem relative to the contest package directory.
If not specified, will expect the problem to be in ./{short_name}/ folder.""",
    )

    color: Optional[str] = Field(
        default=None,
        description="""Hex-based color that represents this problem in the contest.""",
        pattern=r'^[A-Za-z0-9]+$',
        max_length=6,
    )

    def get_path(self) -> pathlib.Path:
        return self.path or pathlib.Path(self.short_name)


class Contest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = NameField(description='Name of this contest.')

    problems: List[ContestProblem] = Field(
        default=[], description='List of problems in this contest.'
    )

    statements: List[ContestStatement] = Field(
        default=None,
        description='Configure statements in this contest, per language.',
    )

    # Vars to be re-used in the statements.
    #   - It will be available as \VAR{vars} variable in the contest-level box statement.
    vars: Dict[str, Primitive] = Field(
        {}, description='Variables to be re-used across the package.'
    )

    @property
    def expanded_vars(self) -> Dict[str, Primitive]:
        return {key: expand_var(value) for key, value in self.vars.items()}
