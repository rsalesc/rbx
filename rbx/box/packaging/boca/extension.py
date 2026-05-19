import typing

from pydantic import BaseModel, Field

BocaLanguage = typing.Literal['c', 'cpp', 'cc', 'kt', 'java', 'py2', 'py3']

_MAX_REP_ERROR = 0.2  # 20% error allowed in time limit when adding reps


class BocaExtension(BaseModel):
    languages: typing.List[BocaLanguage] = []
    flags: typing.Dict[BocaLanguage, str] = {}
    maximumTimeError: float = _MAX_REP_ERROR
    preferContestLetter: bool = False
    usePypy: bool = False

    def flags_with_defaults(self) -> typing.Dict[BocaLanguage, str]:
        res: typing.Dict[BocaLanguage, str] = {
            'c': '-std=gnu11 -O2 -lm -static',
            'cpp': '-std=c++20 -O2 -lm -static',
            'cc': '-std=c++20 -O2 -lm -static',
        }
        res.update(self.flags)
        return res


class BocaLanguageExtension(BaseModel):
    # Deprecated: use `bocaLanguages` instead. Kept for back-compat (see issue #471).
    bocaLanguage: typing.Optional[str] = Field(
        default=None,
        deprecated='Use `bocaLanguages` instead.',
    )
    # BOCA languages this rbx language maps to. First entry is the canonical/primary,
    # used as the forward (rbx -> BOCA) mapping. All entries are emitted as separate
    # per-language script dirs in the BOCA package (e.g. ['cc', 'cpp'] emits both).
    bocaLanguages: typing.Optional[typing.List[str]] = None
    # On-disk BOCA template dir (under rbx/resources/packagers/boca/{compile,run,
    # interactive}/) to source per-language scripts from. Falls back to
    # primary_boca_language for back-compat (see issue #471).
    bocaTemplate: typing.Optional[str] = None

    @property
    def resolved_boca_languages(self) -> typing.List[str]:
        if self.bocaLanguages:
            return self.bocaLanguages
        if self.bocaLanguage:
            return [self.bocaLanguage]
        return []

    @property
    def primary_boca_language(self) -> typing.Optional[str]:
        langs = self.resolved_boca_languages
        return langs[0] if langs else None

    @property
    def resolved_boca_template(self) -> typing.Optional[str]:
        return self.bocaTemplate or self.primary_boca_language
