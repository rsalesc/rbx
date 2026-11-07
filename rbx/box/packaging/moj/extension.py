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


class MojSerialCalibration(RejectsRemovedFields):
    """How `rbx time --runner moj` measures when it testruns serially."""

    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(
        default=False,
        description='Estimate `rbx time --runner moj` from serial testruns, one '
        'solution and one test at a time, instead of one MOJ calibration that '
        'judges every solution at once. Slower, but a solution is never measured '
        'next to another one of the same run.',
    )
    runs: int = Field(
        default=1,
        ge=1,
        description='How many times to testrun each solution. Each testcase keeps '
        'one of the times, picked by `pick`.',
    )
    pick: typing.Literal['max', 'min'] = Field(
        default='max',
        description='Which of the `runs` times a testcase keeps: `max`, the slowest, '
        "or `min`, the fastest. A testcase keeps that run's verdict too.",
    )


class MojCalibration(RejectsRemovedFields):
    """How `rbx time --runner moj` measures solutions on MOJ."""

    model_config = ConfigDict(extra='forbid')

    serial: MojSerialCalibration = Field(
        default_factory=MojSerialCalibration,
        description='Measure with serial testruns instead of a MOJ calibration.',
    )


class MojPackageSettings(RejectsRemovedFields):
    """How `rbx package moj` asks MOJ to judge the package."""

    model_config = ConfigDict(extra='forbid')

    serial: bool = Field(
        default=False,
        description='Judge one test at a time (`ALLOWPARALLELTEST=n` in `conf`) and, '
        'on an all-or-nothing problem, stop at the first test over the time limit '
        '(`STOPWHEN_TLE=y`). Off, MOJ judges the tests in parallel and runs every one '
        'past a timeout.',
    )


class MojExtension(RejectsRemovedFields):
    """Environment-level extensions for MOJ packaging."""

    model_config = ConfigDict(extra='forbid')

    org: typing.Optional[str] = Field(
        default=None,
        description='The MOJ org to upload the package to, as `<org>#<problem>`. '
        'Leave unset to upload under your own login, which is a private personal '
        'org nobody else can see.',
    )
    unifiedTimeLimit: bool = Field(
        default=False,
        description='Give every language the same time limit on MOJ (`TLUNIFIED=y` '
        'in `conf`): MOJ calibrates it from the worst accepted time across all '
        'languages, as if they were one. Per-language limits pinned from the `moj` '
        'limits profile still apply on top of it. Toggling it makes MOJ recalibrate '
        'the problem.',
    )
    package: MojPackageSettings = Field(
        default_factory=MojPackageSettings,
        description='How `rbx package moj` asks MOJ to judge the package.',
    )
    calibration: MojCalibration = Field(
        default_factory=MojCalibration,
        description='How `rbx time --runner moj` measures solutions on MOJ.',
    )
    strictStatement: bool = Field(
        default=False,
        description='Fail `rbx package moj` when a statement uses TeX that MOJ may '
        'not show, instead of warning and packaging anyway. Same as '
        '`--strict-statement`; recommended in CI.',
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
