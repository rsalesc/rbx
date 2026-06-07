from rbx.box.packaging.moj.packager import MojPackager


def test_moj_checker_rewrites_and_ships_deps(testing_pkg, tmp_path):
    testing_pkg.add_file('common/lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.add_file('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('checkers/check.cpp')
    testing_pkg.save()

    packager = MojPackager(testcase_entries=[])

    # The checker source MOJ writes is rewritten to the flat include.
    text = packager._get_checker()  # noqa: SLF001
    assert '#include "lib.h"' in text
    assert '#include "../common/lib.h"' not in text

    # The dep is shipped into scripts/ alongside checker.cpp.
    ns = packager._flatten_checker()  # noqa: SLF001
    assert {f.flat_name for f in ns.files} == {'checker.cpp', 'lib.h'}
    scripts = tmp_path / 'scripts'
    ns.materialize(scripts)
    assert (scripts / 'checker.cpp').read_text() == text
    assert (scripts / 'lib.h').exists()


def test_moj_flat_checker_ships_only_checker(testing_pkg):
    testing_pkg.add_file('check.cpp').write_text('#include "testlib.h"\nint main(){}\n')
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()
    ns = MojPackager(testcase_entries=[])._flatten_checker()  # noqa: SLF001
    assert {f.flat_name for f in ns.files} == {'checker.cpp'}
    assert ns.dep_files() == []
