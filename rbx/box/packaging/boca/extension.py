import typing

from pydantic import ConfigDict, Field, model_validator

from rbx.utils import RejectsRemovedFields, Removed

BocaLanguage = typing.Literal['c', 'cpp', 'cc', 'kt', 'java', 'py2', 'py3']


class BocaExtension(RejectsRemovedFields):
    model_config = ConfigDict(extra='forbid')

    flags: typing.Dict[BocaLanguage, str] = {}
    # Optional floor (in milliseconds) on the TOTAL BOCA time budget. When set, the
    # solution is run ceil(minRunningTime / timeLimit) times so the accumulated budget
    # reaches this floor, while the effective per-run TL stays exactly equal to the real TL.
    minRunningTime: typing.Optional[int] = Field(default=None, gt=0)
    preferContestLetter: bool = False
    usePypy: bool = False

    # Removed in rbx v1 (see the "Migrating to rbx v1" troubleshooting guide).
    languages: typing.Annotated[typing.Optional[typing.List[str]], Removed()] = Field(
        default=None,
        deprecated=(
            'Env-level `extensions.boca.languages` was removed in rbx v1. Declare '
            '`languages` per rbx language under its `extensions.boca` instead; the '
            "emitted set is the union of every language's `languages`."
        ),
    )
    maximumTimeError: typing.Annotated[typing.Optional[float], Removed()] = Field(
        default=None,
        deprecated=(
            '`maximumTimeError` was removed in rbx v1. It has been ignored since #494 '
            '(rbx emits exact fractional time limits). Use `minRunningTime` instead.'
        ),
    )

    def flags_with_defaults(self) -> typing.Dict[BocaLanguage, str]:
        res: typing.Dict[BocaLanguage, str] = {
            'c': '-std=gnu11 -O2 -lm -static',
            'cpp': '-std=c++20 -O2 -lm -static',
            'cc': '-std=c++20 -O2 -lm -static',
        }
        res.update(self.flags)
        return res


class BocaLanguageExtension(RejectsRemovedFields):
    model_config = ConfigDict(extra='forbid')

    # BOCA languages this rbx language maps to. The first entry is the canonical/primary
    # one, used as the forward (rbx -> BOCA) mapping. Every entry is emitted as a separate
    # per-language script dir in the BOCA package (e.g. ['cc', 'cpp'] emits both).
    languages: typing.Optional[typing.List[str]] = None
    # On-disk BOCA template dir (under rbx/resources/packagers/boca/{compile,run,
    # interactive}/) to source per-language scripts from. Required whenever `languages`
    # is set.
    template: typing.Optional[str] = None

    # Removed in rbx v1 (see the "Migrating to rbx v1" troubleshooting guide).
    bocaLanguage: typing.Annotated[typing.Optional[str], Removed()] = Field(
        default=None,
        deprecated=(
            '`bocaLanguage` was removed in rbx v1. Use `languages` (a list) instead, '
            'with an explicit `template`.'
        ),
    )

    @model_validator(mode='after')
    def _require_template_with_languages(self) -> 'BocaLanguageExtension':
        if self.languages and not self.template:
            raise ValueError(
                'A `template` is required when `languages` is set on a BOCA language '
                'extension. Set `template` to one of the on-disk template dirs '
                '(c, cc, cpp, java, kt, py2, py3).'
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
