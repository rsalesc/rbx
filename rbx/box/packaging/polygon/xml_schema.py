from typing import List, Literal, Optional

from pydantic_xml import BaseXmlModel, attr, element, wrapped


class Name(BaseXmlModel):
    language: str = attr()
    value: str = attr()
    main: bool = attr(default=False)


class Statement(BaseXmlModel):
    charset: Optional[Literal['UTF-8']] = attr(default=None)

    language: str = attr()

    mathjax: bool = attr(default=False)

    path: str = attr()

    type: Literal['application/x-tex', 'application/pdf', 'text/html'] = attr()


class File(BaseXmlModel):
    path: str = attr()
    type: Optional[str] = attr(default=None)


class Test(BaseXmlModel):
    method: Literal['manual', 'generated'] = attr()

    sample: Optional[bool] = attr(default=None)

    description: Optional[str] = attr(default=None)


class Testset(BaseXmlModel):
    name: Optional[str] = attr(default=None)

    timelimit: Optional[int] = element('time-limit', default=1000)
    memorylimit: Optional[int] = element('memory-limit', default=256 * 1024 * 1024)

    size: int = element('test-count', default=None)

    inputPattern: str = element('input-path-pattern')
    answerPattern: str = element('answer-path-pattern')

    tests: List[Test] = wrapped('tests', element(tag='test'), default_factory=list)


class Judging(BaseXmlModel):
    inputFile: str = attr(default='')
    outputFile: str = attr(default='')

    testsets: List[Testset] = element(tag='testset', default_factory=list)


class Checker(BaseXmlModel):
    name: str = attr()
    type: Literal['testlib'] = attr()
    source: File = element()
    binary: Optional[File] = element(default=None)
    cpy: Optional[File] = element(tag='copy', default=None)

    testset: Optional[Testset] = element(default=None)


class Interactor(BaseXmlModel):
    source: File = element()


class Problem(BaseXmlModel, tag='problem'):
    names: List[Name] = wrapped('names', element(tag='name'), default_factory=list)

    statements: List[Statement] = wrapped(
        'statements',
        element(tag='statement', default=[]),
        default=[],
    )

    judging: Judging = element()

    files: List[File] = wrapped(
        'files/resources',
        element(tag='file', default=[]),
        default=[],
    )

    checker: Checker = wrapped('assets', element(tag='checker'))

    interactor: Optional[Interactor] = wrapped('assets', element(tag='interactor'))


class ContestProblem(BaseXmlModel):
    index: str = attr()
    path: str = attr()


class Contest(BaseXmlModel, tag='contest'):
    names: List[Name] = wrapped('names', element(tag='name'), default_factory=list)

    statements: List[Statement] = wrapped(
        'statements',
        element(tag='statement', default=[]),
        default=[],
    )

    problems: List[ContestProblem] = wrapped(
        'problems',
        element(tag='problem', default=[]),
        default=[],
    )
