import typing

from pydantic import BaseModel

BocaLanguage = typing.Literal['c', 'cpp', 'cc', 'kt', 'java', 'py2', 'py3']

_MAX_REP_ERROR = 0.2  # 20% error allowed in time limit when adding reps


class BocaExtension(BaseModel):
    languages: typing.List[BocaLanguage] = list(typing.get_args(BocaLanguage))
    flags: typing.Dict[BocaLanguage, str] = {}
    maximumTimeError: float = _MAX_REP_ERROR
    preferContestLetter: bool = False

    def flags_with_defaults(self) -> typing.Dict[BocaLanguage, str]:
        res: typing.Dict[BocaLanguage, str] = {
            'c': '-std=gnu11 -O2 -lm -static',
            'cpp': '-O2 -lm -static',
            'cc': '-std=c++20 -O2 -lm -static',
        }
        res.update(self.flags)
        return res


class BocaLanguageExtension(BaseModel):
    # BocaLanguage this rbx language matches with.
    bocaLanguage: typing.Optional[str] = None
