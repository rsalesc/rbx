from __future__ import annotations

import pathlib
from enum import Enum
from typing import Annotated, List, Literal, Optional, Tuple, Union

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from rbx.autoenum import AutoEnum, alias
from rbx.box.fields import RecVars, Vars, expand_vars
from rbx.box.lang import is_valid_lang_code

# Sentinel variant used when a statement does not declare one. The pair
# (language, variant) is the join key between a problem statement and the
# contest statement that imports it (design §3.1).
DEFAULT_VARIANT = 'default'


def validate_statement_language(lang: str):
    if not is_valid_lang_code(lang) or not lang.islower():
        raise ValueError(
            f'Invalid statement language: {lang}. Language must be a valid lowercase ISO 639-1 code.'
        )
    return lang


StatementLanguage = Annotated[str, AfterValidator(validate_statement_language)]


### Conversion types
#
# NOTE (statements v2): conversion steps are no longer part of the user-facing
# schema (`steps`/`configure` were removed from the statement models). They
# survive only as the *export-time* vocabulary the packagers use to force TikZ
# externalization / demacro at Polygon export (design §2 decision 6, #568). Do
# not reintroduce them as YAML fields.
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
class rbxToTeX(BaseModel):
    """Configures the conversion between rbxTeX and LaTeX."""

    type: Literal[ConversionType.rbxToTex]

    template: pathlib.Path = Field(
        default=pathlib.Path('template.rbx.tex'),
        description='Path to the template that should be used to render the rbx-tex blocks.',
    )

    externalize: bool = Field(
        default=False,
        description='Whether to externalize TikZ graphics.',
    )


class TexToPDF(BaseModel):
    """Configures the conversion between LaTeX and PDF using pdfLaTeX."""

    type: Literal[ConversionType.TexToPDF]

    externalize: bool = Field(
        default=False,
        description='Whether to externalize TikZ graphics.',
    )

    demacro: bool = Field(
        default=False,
        description='Whether to save macro definitions to a JSON file.',
    )


ConversionStep = Union[TexToPDF, rbxToTeX]


### Statement types
class StatementType(AutoEnum):
    rbxTeX = alias('rbx-tex')  # type: ignore
    """Statement written in rbxTeX format."""

    rbxMarkdown = alias('rbxMd', 'rbx-markdown', 'rbx-md')  # type: ignore
    """Statement written in rbxMarkdown format."""

    TeX = alias('tex')  # type: ignore
    """Statement written in pure LaTeX format."""

    Markdown = alias('md', 'markdown')  # type: ignore
    """Statement written in pure Markdown format."""

    JinjaTeX = alias('jinja-tex')  # type: ignore
    """Statement written in LaTeX format with Jinja2 expressions."""

    JinjaMarkdown = alias('jinja-md', 'jinja-markdown')  # type: ignore
    """Statement written in Markdown format with Jinja2 expressions."""

    PDF = alias('pdf')  # type: ignore
    """Statement is a PDF."""

    def get_file_suffix(self) -> str:
        if self == StatementType.TeX:
            return '.tex'
        if self == StatementType.Markdown:
            return '.md'
        if self == StatementType.rbxTeX:
            return '.rbx.tex'
        if self == StatementType.rbxMarkdown:
            return '.rbx.md'
        if self == StatementType.JinjaTeX:
            return '.jinja.tex'
        if self == StatementType.JinjaMarkdown:
            return '.jinja.md'
        if self == StatementType.PDF:
            return '.pdf'
        raise ValueError(f'Unknown statement type: {self}')

    def is_rbx(self) -> bool:
        """rbx* types are the only ones that can JOIN problems into a contest."""
        return self in (StatementType.rbxTeX, StatementType.rbxMarkdown)


# The types a `documents` entry may use: anything that never joins on problems.
DOCUMENT_TYPES = (
    StatementType.JinjaTeX,
    StatementType.JinjaMarkdown,
    StatementType.TeX,
    StatementType.Markdown,
    StatementType.PDF,
)


class StatementKind(str, Enum):
    """Which parallel section a statement build operates on (design §3): the
    primary ``statements`` or the ``tutorials`` (editorials). Both share the
    same models, engine and build paths — the kind only selects which list to
    read on the problem and the contest, and the output filename prefix."""

    STATEMENTS = 'statements'
    TUTORIALS = 'tutorials'

    @property
    def singular(self) -> str:
        """Noun used in messages and output filenames (statement / tutorial)."""
        return 'tutorial' if self == StatementKind.TUTORIALS else 'statement'


class StatementVariantRef(BaseModel):
    """A problem-statement `extends` target referenced by (language, variant).

    A bare string `extends: en` is shorthand for `{language: en}` with the
    default variant (design §5).
    """

    model_config = ConfigDict(extra='forbid')

    language: StatementLanguage
    variant: str = Field(default=DEFAULT_VARIANT)


# A problem statement extends either a language (string) or a (language, variant) pair.
ProblemStatementExtends = Union[str, StatementVariantRef]


class BaseStatement(BaseModel):
    """Fields shared by problem statements, contest statements and documents
    (design §2.5, "one shared schema")."""

    model_config = ConfigDict(extra='forbid')

    language: StatementLanguage = Field(
        default='en', description='Language code of this statement (ISO 639-1).'
    )

    variant: str = Field(
        default=DEFAULT_VARIANT,
        description='Optional discriminator between formats of the same language. '
        'Together with `language` it forms the join key with contest statements.',
    )

    title: Optional[str] = Field(
        default=None,
        description='Title as it appears in the statement. Can be left unset to '
        'fall back to the package/contest title.',
    )

    file: Optional[pathlib.Path] = Field(
        default=None,
        description='Path to the input statement file. Required unless this '
        'statement `extends` another one to inherit its file.',
    )

    type: StatementType = Field(
        default=StatementType.rbxTeX, description='Type of the input statement file.'
    )

    params: RecVars = Field(
        default={},
        description="This statement's own parameters, exposed to the template as "
        'the `params` namespace (kept separate from problem/contest `vars`).',
    )

    samples: bool = Field(
        default=True,
        description='Whether to build the statement with samples.',
    )

    assets: List[str] = Field(
        default_factory=list,
        description='Globs (relative to the package root) selecting files to ship '
        'as statement resources (e.g. images/PDFs). Inherited via `extends`. At '
        'build time the default image/PDF globs over the statement subtree and '
        'each sample subtree are concatenated to this list.',
    )

    @property
    def expanded_params(self) -> Vars:
        return expand_vars(self.params)


class Statement(BaseStatement):
    """A problem-level statement. Identified by (language, variant) — it has no
    `name` (design §3.1)."""

    extends: Optional[ProblemStatementExtends] = Field(
        default=None,
        description='Another problem statement to inherit the build recipe from, '
        'referenced by language (`extends: en`) or by '
        '`{language, variant}`.',
    )

    @model_validator(mode='after')
    def _require_file_or_extends(self):
        if self.file is None and self.extends is None:
            raise ValueError(
                'A statement must specify a `file` unless it `extends` another statement.'
            )
        return self

    @property
    def key(self) -> Tuple[str, str]:
        return (self.language, self.variant)


def is_unique_problem_statements(statements: List[Statement]) -> List[Statement]:
    keys = [(st.language, st.variant) for st in statements]
    if len(set(keys)) != len(keys):
        raise ValueError(
            'Statement (language, variant) pairs must be unique within a problem.'
        )
    return statements
