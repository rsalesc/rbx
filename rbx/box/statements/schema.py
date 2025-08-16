from __future__ import annotations

import pathlib
from enum import Enum
from typing import Annotated, List, Literal, Optional, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from rbx.autoenum import AutoEnum, alias
from rbx.box.fields import FNameField, RecVars, Vars, expand_vars
from rbx.box.lang import is_valid_lang_code


def validate_statement_language(lang: str):
    if not is_valid_lang_code(lang) or not lang.islower():
        raise ValueError(
            f'Invalid statement language: {lang}. Language must be a valid lowercase ISO 639-1 code.'
        )
    return lang


StatementLanguage = Annotated[str, AfterValidator(validate_statement_language)]


### Conversion types
class ConversionType(str, Enum):
    rbxToTex = 'rbx-tex'
    """Conversion from rbxTeX to LaTeX."""

    rbxMarkdownToTeX = 'rbx-md-tex'
    """Conversion from rbxMarkdown to LaTeX."""
    TexToPDF = 'tex2pdf'
    """Conversion from LaTeX to PDF using pdfLaTeX."""

    JinjaTeX = 'jinja-tex'
    """Conversion from LaTeX with Jinja2 expressions to LaTeX."""

    def __repr__(self):
        return str.__repr__(self.value)


### Conversion nodes.
class rbxMarkdownToTeX(BaseModel):
    """Configures the conversion between rbxMarkdown and LaTeX."""

    type: Literal[ConversionType.rbxMarkdownToTeX]


class rbxToTeX(BaseModel):
    """Configures the conversion between rbxTeX and LaTeX."""

    type: Literal[ConversionType.rbxToTex]

    template: pathlib.Path = Field(
        default=pathlib.Path('template.rbx.tex'),
        description='Path to the template that should be used to render the rbx-tex blocks.',
    )


class TexToPDF(BaseModel):
    """Configures the conversion between LaTeX and PDF using pdfLaTeX."""

    type: Literal[ConversionType.TexToPDF]


class JinjaTeX(BaseModel):
    type: Literal[ConversionType.JinjaTeX]


### Joiner types.
class JoinerType(str, Enum):
    TexToPDF = 'tex2pdf'
    """Join contest tex and problem texs to PDF using pdfLaTeX."""

    def __repr__(self):
        return str.__repr__(self.value)


### Joiner nodes.
class JoinTexToPDF(BaseModel):
    """Configures the joining of contest and problem texes to PDF."""

    type: Literal[JoinerType.TexToPDF]


ConversionStep = Union[TexToPDF, JinjaTeX, rbxToTeX, rbxMarkdownToTeX]
Joiner = JoinTexToPDF


### Statement types
class StatementType(AutoEnum):
    rbxTeX = alias('rbx-tex')  # type: ignore
    """Statement written in rbxTeX format."""

    rbxMarkdown = alias('rbxMd', 'rbx-markdown', 'rbx-md')  # type: ignore
    """Statement written in rbxMarkdown format."""

    TeX = alias('tex')
    """Statement written in pure LaTeX format."""

    JinjaTeX = alias('jinja-tex')
    """Statement written in LaTeX format with Jinja2 expressions."""

    PDF = alias('pdf')
    """Statement is a PDF."""

    def get_file_suffix(self) -> str:
        if self == StatementType.TeX:
            return '.tex'
        if self == StatementType.rbxTeX:
            return '.rbx.tex'
        if self == StatementType.rbxMarkdown:
            return '.rbx.md'
        if self == StatementType.JinjaTeX:
            return '.jinja.tex'
        if self == StatementType.PDF:
            return '.pdf'
        raise ValueError(f'Unknown statement type: {self}')


class Statement(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = FNameField(description='Name of this statement.')

    extends: Optional[str] = FNameField(
        default=None,
        description='Name of the statement that this statement extends.',
    )

    language: StatementLanguage = Field(
        default='en', description='Language code of this statement (ISO 639-1).'
    )

    title: Optional[str] = Field(
        default=None,
        description='Title of the problem, as it appears in the statement. '
        'Can be left unset if the problem has no title or if title comes '
        'from the `titles` field of the package.',
    )

    path: pathlib.Path = Field(
        default_factory=pathlib.Path, description='Path to the input statement file.'
    )

    type: StatementType = Field(
        default=StatementType.rbxTeX, description='Type of the input statement file.'
    )

    steps: List[Annotated[ConversionStep, Field(discriminator='type')]] = Field(
        default=[],
        description="""
Describes a sequence of conversion steps that should be applied to the statement file.

Usually, it is not necessary to specify these, as they can be inferred from the
input statement type and the output statement type, but you can use this to force
certain conversion steps to happen.
""",
    )

    configure: List[Annotated[ConversionStep, Field(discriminator='type')]] = Field(
        default=[],
        description="""
Configure how certain conversion steps should happen when applied to the statement file.

Different from the `steps` field, this does not force the steps to happen, but rather only
configure them in case they are applied.
""",
    )

    assets: List[str] = Field(
        default=[],
        description="""
Assets relative to the package directory that should be included while building
the statement. Files will be included in the same folder as the statement file, preserving
their relativeness. Can be glob pattern as well, such as `imgs/*.png`.
""",
    )

    vars: RecVars = Field(
        default={},
        description='Variables to be used in the statement.',
    )

    @property
    def expanded_vars(self) -> Vars:
        return expand_vars(self.vars)
