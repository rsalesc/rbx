import typing

from pydantic import ConfigDict, Field, model_validator

from rbx.utils import RejectsRemovedFields

# The language ids mojtools ships a `lang/<id>/` directory for. `py2`/`py3` are legacy
# spellings that `build-and-test.sh` normalizes to `py`; they stay accepted so a
# package can still carry a `scripts/py3` override for a legacy judge.
MojLanguage = typing.Literal[
    'apl',
    'c',
    'cpp',
    'cs',
    'go',
    'hs',
    'java',
    'js',
    'kt',
    'ml',
    'pas',
    'pl',
    'py',
    'py2',
    'py3',
    'riscv',
    'rs',
    'sh',
    'spim',
]


# The figure scale MOJ statements get when nothing sets one: MOJ renders the
# statement at 16px (12pt) against the PDF's 11pt, so a figure the same size
# relative to its text is 12/11 of its PDF size.
DEFAULT_FIGURE_SCALE = 1.09


class MojStatementExtension(RejectsRemovedFields):
    """MOJ settings a contest or a problem may set, overriding the environment's."""

    model_config = ConfigDict(extra='forbid')

    figureScale: typing.Optional[float] = Field(
        default=None,
        gt=0,
        description='How much larger than in the PDF statement a figure is shown '
        'on MOJ. MOJ renders statements as HTML with larger text than the PDF, so '
        f'the default, {DEFAULT_FIGURE_SCALE}, keeps figures the same size '
        'relative to the text. A figure whose width is a fraction of '
        '`\\textwidth` is not affected.',
    )


class MojExtension(MojStatementExtension):
    """Environment-level extensions for MOJ packaging."""

    model_config = ConfigDict(extra='forbid')

    org: typing.Optional[str] = Field(
        default=None,
        description='The MOJ org to upload the package to, as `<org>#<problem>`. '
        'Leave unset to upload under your own login, which is a private personal '
        'org nobody else can see.',
    )


class MojLanguageExtension(RejectsRemovedFields):
    """Language-level extensions for MOJ packaging.

    Mirrors ``BocaLanguageExtension``: an rbx language declares which MOJ language ids
    it maps to, and which on-disk script template to emit for them.
    """

    model_config = ConfigDict(extra='forbid')

    languages: typing.Optional[typing.List[str]] = Field(
        default=None,
        description='MOJ language ids this rbx language maps to. The first entry is '
        'the canonical one; every entry gets its own scripts/<id>/ directory in the '
        'package.',
    )
    template: typing.Optional[str] = Field(
        default=None,
        description='On-disk template dir under '
        'rbx/resources/packagers/moj/scripts/ to source the per-language '
        'compile.sh and run.sh from. Required whenever `languages` is set.',
    )
    flags: typing.Optional[str] = Field(
        default=None,
        description='Compilation flags substituted into the template. Leave unset to '
        "use the template's own default.",
    )

    @model_validator(mode='after')
    def _require_template_with_languages(self) -> 'MojLanguageExtension':
        if self.languages and not self.template:
            raise ValueError(
                'A `template` is required when `languages` is set on a MOJ language '
                'extension. Set `template` to one of the on-disk template dirs '
                '(c, cpp, java, kt, py).'
            )
        return self

    @property
    def resolved_languages(self) -> typing.List[str]:
        return self.languages or []

    @property
    def primary_language(self) -> typing.Optional[str]:
        langs = self.resolved_languages
        return langs[0] if langs else None

    @property
    def resolved_template(self) -> typing.Optional[str]:
        return self.template
