from rbx.box import package
from rbx.box.packaging.polygon.packager import PolygonPackager


def test_polygon_offline_ships_and_rewrites_checker_deps(testing_pkg):
    testing_pkg.add_file('common/lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('checkers/check.cpp')
    testing_pkg.save()

    packager = PolygonPackager(testcase_entries=[])
    ns = packager._flatten_sources()  # noqa: SLF001

    # Closure shipped under flat names; checker keeps the reserved name.
    assert {f.flat_name for f in ns.files} == {'check.cpp', 'lib.h'}
    checker_text = ns.content_for(package.get_checker_or_builtin()).decode()
    assert '#include "lib.h"' in checker_text
    assert '#include "../common/lib.h"' not in checker_text
    assert '#include "testlib.h"' in checker_text  # builtin, untouched

    # Materialized into files/ with the rewritten bytes.
    files_dir = testing_pkg.root / 'out' / 'files'
    ns.materialize(files_dir)
    assert (files_dir / 'check.cpp').read_text() == checker_text
    assert (files_dir / 'lib.h').exists()

    # problem.xml declares the shipped dep alongside testlib/rbx.
    declared = {f.path for f in packager._get_files(ns)}  # noqa: SLF001
    assert 'files/testlib.h' in declared
    assert 'files/rbx.h' in declared
    assert 'files/lib.h' in declared


def test_polygon_offline_flat_checker_ships_only_check(testing_pkg):
    # A checker with no deps must produce exactly check.cpp (no extra files), and
    # _get_files must return only testlib/rbx. Protects the byte-identical path.
    testing_pkg.add_file('check.cpp').write_text('#include "testlib.h"\nint main(){}\n')
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()

    packager = PolygonPackager(testcase_entries=[])
    ns = packager._flatten_sources()  # noqa: SLF001

    assert {f.flat_name for f in ns.files} == {'check.cpp'}
    assert ns.dep_files() == []

    declared = {f.path for f in packager._get_files(ns)}  # noqa: SLF001
    assert declared == {'files/testlib.h', 'files/rbx.h'}
