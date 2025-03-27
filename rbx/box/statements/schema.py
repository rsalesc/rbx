from __future__ import annotations

import pathlib
from enum import Enum
from typing import List, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from rbx.autoenum import AutoEnum, alias


### Conversion types
class ConversionType(str, Enum):
    rbxToTex = 'rbx-tex'
    """Conversion from rbxTeX to LaTeX."""

    TexToPDF = 'tex2pdf'
    """Conversion from LaTeX to PDF using pdfLaTeX."""

    JinjaTeX = 'jinja-tex'
    """Conversion from LaTeX with Jinja2 expressions to LaTeX."""

    def __repr__(self):
        return str.__repr__(self.value)


### Conversion nodes.
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


ConversionStep = Union[TexToPDF, JinjaTeX, rbxToTeX]
Joiner = JoinTexToPDF


### Statement types
class StatementType(AutoEnum):
    rbxTeX = alias('rbx-tex', 'rbx-tex', 'rbx')  # type: ignore
    """Statement written in rbxTeX format."""

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
        if self == StatementType.JinjaTeX:
            return '.jinja.tex'
        if self == StatementType.PDF:
            return '.pdf'
        raise ValueError(f'Unknown statement type: {self}')


class Statement(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str = Field(
        description='Name of the problem, as it appears in the statement.'
    )

    path: pathlib.Path = Field(description='Path to the input statement file.')

    type: StatementType = Field(description='Type of the input statement file.')

    steps: List[ConversionStep] = Field(
        default=[],
        discriminator='type',
        description="""
Describes a sequence of conversion steps that should be applied to the statement file.

Usually, it is not necessary to specify these, as they can be inferred from the
input statement type and the output statement type, but you can use this to force
certain conversion steps to happen.
""",
    )

    configure: List[ConversionStep] = Field(
        default=[],
        discriminator='type',
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

    language: str = Field(
        default='en', description='Language this is statement is written in.'
    )
