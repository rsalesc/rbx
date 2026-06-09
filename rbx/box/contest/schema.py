import pathlib
from typing import Annotated, Dict, List, Optional, Set

import pydantic
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from rbx.box.fields import (
    FNameField,
    NameField,
    RecVars,
    Vars,
    expand_vars,
)
from rbx.box.statements.expander import expand_contest_statements
from rbx.box.statements.schema import (
    DOCUMENT_TYPES,
    BaseStatement,
)

Alias = Annotated[str, NameField()]


def ShortNameField(**kwargs):
    return Field(pattern=r'^[A-Z]+[0-9]*$', min_length=1, max_length=4, **kwargs)


def is_unique_by_name(statements: List[BaseStatement]) -> List[BaseStatement]:
    names = {st.name for st in statements}  # type: ignore[attr-defined]
    if len(names) != len(statements):
        raise ValueError('Statement names must be unique.')
    return statements


class ContestStatement(BaseStatement):
    """A contest-level statement. Owns the templates used to render problems both
    standalone and inside the contest join (design §3.2)."""

    name: str = FNameField(
        description='Name of this statement. Unique within the contest.'
    )

    extends: Optional[str] = FNameField(
        default=None,
        description='Name of the contest statement to inherit the build recipe from.',
    )

    location: Optional[str] = Field(
        default=None, description='Location of the contest in this language.'
    )

    date: Optional[str] = Field(
        default=None, description='Date of the contest in this language.'
    )

    standaloneProblemTemplate: Optional[pathlib.Path] = Field(
        default=None,
        description='Template applied to build a problem-level statement as a '
        'standalone document (`rbx st b`). rbx* types only.',
    )

    contestProblemTemplate: Optional[pathlib.Path] = Field(
        default=None,
        description='Template applied to build the problem fragment that gets '
        'imported into the contest statement (`rbx contest st b`). rbx* types only.',
    )

    @model_validator(mode='after')
    def _rbx_only_fields(self):
        # `variant`, `params` and the two templates are meaningful only for the
        # joinable rbx* types (design §3.2/§3.3).
        if not self.type.is_rbx():
            offenders = []
            if 'variant' in self.model_fields_set:
                offenders.append('variant')
            if self.params:
                offenders.append('params')
            if self.standaloneProblemTemplate is not None:
                offenders.append('standaloneProblemTemplate')
            if self.contestProblemTemplate is not None:
                offenders.append('contestProblemTemplate')
            if offenders:
                raise ValueError(
                    f'Fields {offenders} are only allowed for rbx* statement types '
                    f"(rbxtex/rbxmd); statement '{self.name}' has type {self.type}."
                )
        return self

    @property
    def expanded_vars(self) -> Vars:
        # Backwards-compatible alias; a contest statement's own params.
        return expand_vars(self.params)


class Document(BaseStatement):
    """A contest-level document (infosheet, etc.). Shares the statement model but
    NEVER joins on problems, so it is restricted to non-rbx types (design §3.2)."""

    name: str = FNameField(
        description='Name of this document. Unique within the contest.'
    )

    extends: Optional[str] = FNameField(
        default=None,
        description='Name of the document to inherit the build recipe from.',
    )

    location: Optional[str] = Field(default=None, description='Location, per language.')
    date: Optional[str] = Field(default=None, description='Date, per language.')

    @model_validator(mode='after')
    def _non_rbx_type(self):
        # A child document inherits its `type` from the one it extends, so defer
        # the check when the type was not declared explicitly here.
        if 'type' not in self.model_fields_set and self.extends is not None:
            return self
        if self.type not in DOCUMENT_TYPES:
            raise ValueError(
                f"Documents never join on problems, so document '{self.name}' cannot "
                f'use the rbx* type {self.type}. Use one of '
                f'{[t.get_file_suffix() for t in DOCUMENT_TYPES]}.'
            )
        return self


class ContestProblem(BaseModel):
    short_name: str = ShortNameField(
        description="""
Short name of the problem. Usually, just an uppercase letter,
but can be a sequence of uppercase letters followed by a number."""
    )

    aliases: List[Alias] = Field(
        default_factory=list,
        description="""
Optional list of aliases for this problem. You can refer to the problem by its
short_name or by any of these aliases in commands such as [item]rbx on <name> run[/item].
Aliases must be unique across all problems (case-insensitive).""",
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

    def all_identifiers(self) -> Set[str]:
        """All names that can be used to refer to this problem (short_name + aliases), lowercased."""
        return {self.short_name.lower()} | {a.lower() for a in self.aliases}


_CONTEST_NAME_VALIDATOR = TypeAdapter(Annotated[str, NameField()])


class Contest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    use_variants: bool = Field(
        default=False,
        description=(
            'When true, this file is a sentinel marking the directory as a '
            'multi-contest dispatcher. The actual contests live in sibling '
            'files matching contest.<id>.rbx.yml. When set, no other Contest '
            'fields may be specified.'
        ),
    )

    name: str = Field(
        default='',
        description='Name of this contest.',
    )

    titles: Dict[str, str] = Field(
        default={},
        description='Titles for the contest in each language. '
        'Languages should be specified as lowercase ISO 639-1 codes.',
    )

    problems: List[ContestProblem] = Field(
        default=[], description='List of problems in this contest.'
    )

    @model_validator(mode='after')
    def _validate_dispatcher_or_real(self):
        # Maintenance contract: keep this tuple in sync with Contest's non-dispatcher
        # fields. `use_variants` is the only field allowed alongside dispatcher mode.
        if self.use_variants:
            for field in (
                'name',
                'titles',
                'problems',
                'statements',
                'tutorials',
                'documents',
                'vars',
            ):
                value = getattr(self, field)
                if value:
                    raise ValueError(
                        f'Field {field!r} cannot be set when use_variants is true.'
                    )
            return self
        try:
            _CONTEST_NAME_VALIDATOR.validate_python(self.name)
        except pydantic.ValidationError as exc:
            raise ValueError(f'Invalid contest name: {exc}') from exc
        return self

    @property
    def is_dispatcher(self) -> bool:
        return self.use_variants

    @model_validator(mode='after')
    def check_problem_identifiers_unique(self):
        seen: Dict[str, str] = {}
        for problem in self.problems:
            identifiers = [problem.short_name.lower()] + [
                a.lower() for a in problem.aliases
            ]
            for ident in identifiers:
                if ident in seen:
                    raise ValueError(
                        f'Problem identifier {ident!r} is used by more than one problem '
                        f'(short_name or alias in problem {seen[ident]!r} and in {problem.short_name!r}).'
                    )
                seen[ident] = problem.short_name
        return self

    statements: Annotated[
        List[ContestStatement],
        AfterValidator(is_unique_by_name),
    ] = Field(
        default=[],
        description='Configure statements in this contest, per language.',
    )

    tutorials: Annotated[
        List[ContestStatement],
        AfterValidator(is_unique_by_name),
    ] = Field(
        default=[],
        description='Configure tutorials (editorials) in this contest, per language.',
    )

    documents: Annotated[
        List[Document],
        AfterValidator(is_unique_by_name),
    ] = Field(
        default=[],
        description='Configure standalone documents (infosheets, etc.) for this '
        'contest. Documents never join on problems.',
    )

    # Vars to be re-used in the statements.
    #   - It will be available as \VAR{vars} variable in the contest-level box statement.
    vars: RecVars = Field(
        default={}, description='Variables to be re-used across the package.'
    )

    @property
    def expanded_statements(self) -> List[ContestStatement]:
        return expand_contest_statements(self.statements)

    @property
    def expanded_tutorials(self) -> List[ContestStatement]:
        return expand_contest_statements(self.tutorials)

    @property
    def expanded_documents(self) -> List[Document]:
        return expand_contest_statements(self.documents)

    @property
    def expanded_vars(self) -> Vars:
        return expand_vars(self.vars)
