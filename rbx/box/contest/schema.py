import pathlib
from typing import Annotated, Dict, List, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from rbx.box.fields import (
    FNameField,
    NameField,
    Primitive,
    RecVars,
    Vars,
    expand_vars,
)
from rbx.box.statements.expander import expand_statements
from rbx.box.statements.schema import (
    ConversionStep,
    Joiner,
    StatementLanguage,
    StatementType,
)


def ShortNameField(**kwargs):
    return Field(pattern=r'^[A-Z]+[0-9]*$', min_length=1, max_length=4, **kwargs)


def is_unique_by_name(statements: List['ContestStatement']) -> List['ContestStatement']:
    names = {st.name for st in statements}
    if len(names) != len(statements):
        raise ValueError('Statement names must be unique.')
    return statements


class ProblemStatementOverride(BaseModel):
    model_config = ConfigDict(extra='forbid')

    configure: List[Annotated[ConversionStep, Field(discriminator='type')]] = Field(
        default=[],
        description="""
Configure how certain conversion steps should happen when applied to the statement file.

Different from the `steps` field, this does not force the steps to happen, but rather only
configure them in case they are applied.
""",
    )

    vars: Dict[str, Primitive] = Field(
        default={},
        description='Variables to be merged into the problem statement vars.',
    )


class ContestStatement(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = FNameField(description='Name of this statement.')

    extends: Optional[str] = FNameField(
        default=None, description='Name of the statement to inherit from.'
    )

    language: StatementLanguage = Field(
        default='en', description='Language code for this statement (ISO 639-1).'
    )

    title: str = Field(default='', description='Title of the contest in this language.')

    location: Optional[str] = Field(
        default=None, description='Location of the contest in this language.'
    )

    date: Optional[str] = Field(
        default=None, description='Date of the contest in this language.'
    )

    path: pathlib.Path = Field(
        default_factory=pathlib.Path,
        description='Path to the input statement file.',
    )

    type: StatementType = Field(
        default=StatementType.rbxTeX, description='Type of the input statement file.'
    )

    joiner: Optional[Joiner] = Field(
        default=None,
        description="""
Joiner to be used to build the statement.
                           
This determines how problem statements will be joined into a single contest statement.""",
    )

    steps: List[Annotated[ConversionStep, Field(discriminator='type')]] = Field(
        default=[],
        description="""
Describes a sequence of conversion steps that should be applied to the statement file
of this contest.

Usually, it is not necessary to specify these, as they can be inferred from the
input statement type and the output statement type, but you can use this to force
certain conversion steps to happen.
""",
    )

    configure: List[Annotated[ConversionStep, Field(discriminator='type')]] = Field(
        default=[],
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

    match: Optional[str] = FNameField(
        default=None,
        description="""
        Name of the problem-level statement to match this statement against.

        If not specified, will match against the first statement of the same language.
        """,
    )

    # Vars to be re-used in the statement.
    #   - It will be available as \VAR{vars} variable in the contest-level box statement.
    vars: RecVars = Field(
        default={}, description='Variables to be re-used across the package.'
    )

    @property
    def expanded_vars(self) -> Vars:
        return expand_vars(self.vars)


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
        description="""
Color that represents this problem in the contest.

Can be a hex color (#abcdef or #abc format), or a color name among available X11 colors.

See https://en.wikipedia.org/wiki/X11_color_names for the list of supported color names.
""",
    )

    colorName: Optional[str] = Field(
        default=None,
        description="""
A custom color name for the color provided by this problem.

If not provided, will try to infer a color name from the color provided.
""",
        pattern=r'^[a-zA-Z]+$',
    )

    @model_validator(mode='after')
    def check_color(self):
        from colour import Color

        if self.color is None:
            return self

        Color(self.color)
        return self

    @property
    def hex_color(self) -> Optional[str]:
        from colour import Color

        if self.color is None:
            return None

        return Color(self.color).hex_l

    @property
    def color_name(self) -> Optional[str]:
        if self.colorName is not None:
            return self.colorName

        if self.color is None:
            return None

        from colour import Color

        color = Color(self.color)
        web_color = color.web
        if web_color.startswith('#'):
            return 'unknown'
        return web_color

    def get_path(self) -> pathlib.Path:
        return self.path or pathlib.Path(self.short_name)


class Contest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = NameField(description='Name of this contest.')

    problems: List[ContestProblem] = Field(
        default=[], description='List of problems in this contest.'
    )

    statements: Annotated[
        List[ContestStatement],
        AfterValidator(is_unique_by_name),
    ] = Field(
        default=None,
        description='Configure statements in this contest, per language.',
    )

    # Vars to be re-used in the statements.
    #   - It will be available as \VAR{vars} variable in the contest-level box statement.
    vars: RecVars = Field(
        default={}, description='Variables to be re-used across the package.'
    )

    @property
    def expanded_statements(self) -> List[ContestStatement]:
        return expand_statements(self.statements)

    @property
    def expanded_vars(self) -> Vars:
        return expand_vars(self.vars)
