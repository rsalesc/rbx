from typing import List, Literal, Optional

from pydantic_xml import BaseXmlModel, attr, element, wrapped


class Name(BaseXmlModel, search_mode='unordered'):
    language: str = attr()
    value: str = attr()
    main: bool = attr(default=False)


class Statement(BaseXmlModel, search_mode='unordered'):
    charset: Optional[str] = attr(default=None)

    language: str = attr()

    mathjax: bool = attr(default=False)

    path: str = attr()

    type: Literal['application/x-tex', 'application/pdf', 'text/html'] = attr()


class Tutorial(BaseXmlModel, search_mode='unordered'):
    pass


class NamedRef(BaseXmlModel, search_mode='unordered'):
    name: str = attr()


class File(BaseXmlModel, search_mode='unordered'):
    path: str = attr()
    type: Optional[str] = attr(default=None)

    # A grader: a resource compiled together with every solution of these types,
    # spelled as Polygon exports it (`for-types="cpp.*"`, stage `compile`, asset
    # `solution`).
    for_types: Optional[str] = attr('for-types', default=None)
    stages: List[NamedRef] = wrapped(
        'stages', element(tag='stage', default=[]), default=[]
    )
    assets: List[NamedRef] = wrapped(
        'assets', element(tag='asset', default=[]), default=[]
    )


class Test(BaseXmlModel, search_mode='unordered'):
    method: Literal['manual', 'generated'] = attr(default='manual')

    sample: Optional[bool] = attr(default=None)

    group: Optional[str] = attr(default=None)

    points: Optional[float] = attr(default=None)

    description: Optional[str] = attr(default=None)

    verdict: Optional[str] = attr(default=None)


class Dependency(BaseXmlModel, search_mode='unordered'):
    group: str = attr()


class Group(BaseXmlModel, search_mode='unordered'):
    name: str = attr()
    points: Optional[float] = attr(default=None)
    points_policy: Literal['complete-group', 'each-test'] = attr(
        'points-policy', default='complete-group'
    )
    feedback_policy: Literal['none', 'points', 'icpc', 'complete'] = attr(
        'feedback-policy', default='icpc'
    )
    dependencies: List[Dependency] = wrapped(
        'dependencies', element(tag='dependency', default=[]), default=[]
    )


class Testset(BaseXmlModel, search_mode='unordered'):
    name: Optional[str] = attr(default=None)

    timelimit: Optional[int] = element('time-limit', default=1000)
    memorylimit: Optional[int] = element('memory-limit', default=256 * 1024 * 1024)

    size: int = element('test-count', default=None)

    inputPattern: str = element('input-path-pattern')
    outputPattern: Optional[str] = element('output-path-pattern', default=None)
    answerPattern: Optional[str] = element('answer-path-pattern', default=None)

    tests: List[Test] = wrapped('tests', element(tag='test'), default_factory=list)

    groups: List[Group] = wrapped(
        'groups', element(tag='group', default=[]), default=[]
    )


class Judging(BaseXmlModel, search_mode='unordered'):
    inputFile: str = attr('input-file', default='')
    outputFile: str = attr('output-file', default='')
    # Reads a checker's `quitp(x)` as x percent of the test's points, the way rbx
    # does, instead of as x points.
    treatPointsAsPercent: Optional[Literal['true']] = attr(
        'treat-points-from-checker-as-percent', default=None
    )

    testsets: List[Testset] = element(tag='testset', default_factory=list)


class Checker(BaseXmlModel, search_mode='unordered'):
    name: Optional[str] = attr(default=None)
    type: Literal['testlib'] = attr(default='testlib')
    source: File = element()
    binary: Optional[File] = element(default=None)
    cpy: Optional[File] = element(tag='copy', default=None)

    testset: Optional[Testset] = element(default=None)


class Interactor(BaseXmlModel, search_mode='unordered'):
    source: File = element()


class Solution(BaseXmlModel, search_mode='unordered'):
    tag: Literal[
        'main',
        'accepted',
        'rejected',
        'time-limit-exceeded',
        'time-limit-exceeded-or-accepted',
        'time-limit-exceeded-or-memory-limit-exceeded',
        'wrong-answer',
        'presentation-error',
        'memory-limit-exceeded',
        'failed',
    ] = attr()
    source: File = element()


class Problem(BaseXmlModel, tag='problem', search_mode='unordered'):
    short_name: str = attr('short-name')

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

    checker: Optional[Checker] = wrapped(
        'assets', element(tag='checker', default=None), default=None
    )

    interactor: Optional[Interactor] = wrapped(
        'assets', element(tag='interactor', default=None), default=None
    )

    solutions: List[Solution] = wrapped(
        'assets/solutions',
        element(tag='solution', default=[]),
        default=[],
    )


class ContestProblem(BaseXmlModel, search_mode='unordered'):
    index: str = attr()
    path: str = attr()
    url: Optional[str] = attr(default=None)


class Contest(BaseXmlModel, tag='contest', search_mode='unordered'):
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
