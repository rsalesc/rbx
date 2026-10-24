"""What the Polygon packages carry for CMS's Polygon importer.

CMS (cms-dev, `cmscontrib/loaders/polygon.py`) takes each contest problem's
directory from the basename of its `url`. The rest of what `--cms` adds is
tested with the CMS helpers, under `tests/rbx/box/packaging/cms/`.
"""

import types

from rbx.box.packaging.polygon import xml_schema as polygon_schema
from rbx.box.packaging.polygon.packager import PolygonContestPackager


def _built_problem(short_name: str):
    # `_get_problems` only reads the contest problem's short name.
    return types.SimpleNamespace(problem=types.SimpleNamespace(short_name=short_name))


def test_contest_problem_url_only_for_cms():
    built = [_built_problem('A')]

    plain = PolygonContestPackager()._get_problems(built)  # noqa: SLF001
    cms = PolygonContestPackager(cms=True)._get_problems(built)  # noqa: SLF001

    # The Codeforces taskbook rejects a `url` that is not an absolute URL.
    assert plain == [polygon_schema.ContestProblem(index='A', path='problems/A')]
    assert cms == [
        polygon_schema.ContestProblem(index='A', path='problems/A', url='problems/A')
    ]


def test_judging_io_attributes_are_hyphenated():
    xml = polygon_schema.Judging().to_xml()

    assert b'input-file=""' in xml
    assert b'output-file=""' in xml
