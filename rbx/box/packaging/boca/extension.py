import typing

from pydantic import BaseModel, Field

BocaLanguage = typing.Literal['c', 'cpp', 'cc', 'kt', 'java', 'py2', 'py3']


class BocaExtension(BaseModel):
    languages: typing.List[BocaLanguage] = []
    flags: typing.Dict[BocaLanguage, str] = {}
    # Optional floor (in milliseconds) on the TOTAL BOCA time budget. When set, the
    # solution is run ceil(minRunningTime / timeLimit) times so the accumulated budget
    # reaches the floor, amortizing fixed startup/JIT overhead and measurement noise on
    # small TLs. The effective per-run TL always stays exactly equal to the real TL.
    minRunningTime: typing.Optional[int] = Field(default=None, gt=0)
    # Deprecated (issue #494): BOCA/safeexec supports fractional time budgets, so rbx no
    # longer rounds TLs. This field is ignored; use `minRunningTime` instead.
    maximumTimeError: typing.Optional[float] = Field(
        default=None,
        deprecated='Ignored since #494; rbx emits exact fractional TLs. Use minRunningTime.',
    )
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
    # Deprecated: use `languages` instead. Kept for back-compat (see issue #471).
    bocaLanguage: typing.Optional[str] = Field(
        default=None,
        deprecated='Use `languages` instead.',
    )
    # BOCA languages this rbx language maps to. First entry is the canonical/primary,
    # used as the forward (rbx -> BOCA) mapping. All entries are emitted as separate
    # per-language script dirs in the BOCA package (e.g. ['cc', 'cpp'] emits both).
    languages: typing.Optional[typing.List[str]] = None
    # On-disk BOCA template dir (under rbx/resources/packagers/boca/{compile,run,
    # interactive}/) to source per-language scripts from. Falls back to
    # primary_language for back-compat (see issue #471).
    template: typing.Optional[str] = None

    @property
    def resolved_languages(self) -> typing.List[str]:
        if self.languages:
            return self.languages
        if self.bocaLanguage:
            return [self.bocaLanguage]
        return []

    @property
    def primary_language(self) -> typing.Optional[str]:
        langs = self.resolved_languages
        return langs[0] if langs else None

    @property
    def resolved_template(self) -> typing.Optional[str]:
        return self.template or self.primary_language
