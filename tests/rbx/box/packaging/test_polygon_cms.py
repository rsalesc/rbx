"""What the Polygon packages carry for CMS's Polygon importer.

CMS (cms-dev, `cmscontrib/loaders/polygon.py`) takes each contest problem's
directory from the basename of its `url`. The rest of what `--cms` adds is
tested with the CMS helpers, under `tests/rbx/box/packaging/cms/`.
"""

import types

from rbx.box import package
from rbx.box.packaging.cms import polygon_loader
from rbx.box.packaging.polygon import xml_schema as polygon_schema
from rbx.box.packaging.polygon.packager import (
    PolygonContestPackager,
    PolygonPackager,
)


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


def test_a_statementless_problem_has_no_names_without_cms(testing_pkg):
    assert PolygonPackager([])._get_names() == []  # noqa: SLF001


def test_a_statementless_problem_is_named_after_itself_for_cms(testing_pkg):
    # CMS's importer reads the task title off the first `<name>`, and crashes
    # on a problem.xml without `<names>`.
    names = PolygonPackager([], cms=True)._get_names()  # noqa: SLF001

    assert names == [
        polygon_schema.Name(language='english', value=testing_pkg.yml.name, main=True)
    ]


def test_a_statementless_problem_takes_its_first_title_for_cms(testing_pkg):
    testing_pkg.yml.titles = {'pt': 'Soma', 'en': 'Sum'}
    testing_pkg.save()

    names = PolygonPackager([], cms=True)._get_names()  # noqa: SLF001

    assert names == [
        polygon_schema.Name(language='portuguese', value='Soma', main=True)
    ]


def _checker_package(testing_pkg):
    testing_pkg.add_file('checkers/checker.cpp').write_text(
        '#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('checkers/checker.cpp')
    testing_pkg.save()


def test_the_checker_ships_as_check_cpp_without_cms(testing_pkg):
    _checker_package(testing_pkg)
    packager = PolygonPackager([])

    ns = packager._flatten_sources()  # noqa: SLF001

    assert ns.flat_name_for(package.get_checker_or_builtin()) == 'check.cpp'
    assert packager._get_checker().source.path == 'files/check.cpp'  # noqa: SLF001


def test_the_checker_moves_out_of_the_importers_way_for_cms(testing_pkg):
    # CMS's importer compiles `files/check.cpp` with its own flags and testlib,
    # and aborts the import when that fails (#971); that name is its stub.
    _checker_package(testing_pkg)
    packager = PolygonPackager([], cms=True)

    ns = packager._flatten_sources()  # noqa: SLF001

    checker = package.get_checker_or_builtin()
    assert ns.flat_name_for(checker) == polygon_loader.CHECKER_SOURCE
    assert 'check.cpp' not in {f.flat_name for f in ns.files}
    # Polygon reads the real checker; only CMS's importer reads the stub.
    assert packager._get_checker().source.path == (  # noqa: SLF001
        f'files/{polygon_loader.CHECKER_SOURCE}'
    )
