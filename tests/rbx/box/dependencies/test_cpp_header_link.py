import pathlib

from rbx.box.dependencies.cpp import CppScanner
from rbx.box.testing import testing_package


def test_include_through_a_link_to_rbx_h_resolves_to_rbx_h(
    testing_pkg: testing_package.TestingPackage,
):
    # A preset can link rbx.h next to a grader for editors. Flattening ships one
    # file per resolved target, so resolving to the link would ship the header
    # twice (`rbx.h` and `graders__rbx.h`).
    testing_pkg.add_file('rbx.h').write_text('// header\n')
    testing_pkg.add_file('graders/task.h').write_text('int f();\n')
    testing_pkg.add_file('graders/grader.cpp').write_text(
        '#include "rbx.h"\n#include "task.h"\nint main() {}\n'
    )
    pathlib.Path('graders/rbx.h').symlink_to('../rbx.h')

    refs = CppScanner().references(pathlib.Path('graders/grader.cpp'))

    assert {r.spelling: r.target for r in refs} == {
        'rbx.h': pathlib.Path('rbx.h'),
        'task.h': pathlib.Path('graders/task.h'),
    }


def test_other_in_package_links_keep_their_own_path(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_file('lib/real.h').write_text('int g();\n')
    testing_pkg.add_file('sol.cpp').write_text('#include "alias.h"\nint main() {}\n')
    pathlib.Path('alias.h').symlink_to('lib/real.h')

    [ref] = CppScanner().references(pathlib.Path('sol.cpp'))

    assert ref.target == pathlib.Path('alias.h')
