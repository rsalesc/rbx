import os
import pathlib

from rbx.box import header
from rbx.box.dependencies.cpp import CppScanner
from rbx.box.schema import Grader
from rbx.box.testing import testing_package

_GRADER = '#include "rbx.h"\n#include "task.h"\nint main() {}\n'


def _add_grader(testing_pkg: testing_package.TestingPackage, path: str):
    testing_pkg.add_file(path).write_text(_GRADER)
    testing_pkg.yml.grader = Grader(path=pathlib.Path(path), secret='s3cr3t-0123456789')
    testing_pkg.save()


class TestLinkNextToGrader:
    def test_generating_the_header_links_it_beside_the_grader(
        self, testing_pkg: testing_package.TestingPackage
    ):
        _add_grader(testing_pkg, 'graders/grader.cpp')

        header.generate_header()

        link = pathlib.Path('graders/rbx.h')
        assert link.is_symlink()
        assert os.readlink(link) == os.path.join('..', 'rbx.h')
        assert link.read_text() == pathlib.Path('rbx.h').read_text()

    def test_link_is_relative_to_a_nested_grader_dir(
        self, testing_pkg: testing_package.TestingPackage
    ):
        _add_grader(testing_pkg, 'src/graders/grader.cpp')

        header.generate_header()

        assert os.readlink('src/graders/rbx.h') == os.path.join('..', '..', 'rbx.h')

    def test_a_stale_link_is_repointed(
        self, testing_pkg: testing_package.TestingPackage
    ):
        _add_grader(testing_pkg, 'graders/grader.cpp')
        pathlib.Path('graders/rbx.h').symlink_to('elsewhere.h')

        header.generate_header()

        assert os.readlink('graders/rbx.h') == os.path.join('..', 'rbx.h')

    def test_a_regular_file_in_its_place_is_left_alone(
        self, testing_pkg: testing_package.TestingPackage
    ):
        _add_grader(testing_pkg, 'graders/grader.cpp')
        testing_pkg.add_file('graders/rbx.h').write_text('// mine\n')

        header.generate_header()

        assert not pathlib.Path('graders/rbx.h').is_symlink()
        assert pathlib.Path('graders/rbx.h').read_text() == '// mine\n'

    def test_an_override_header_is_linked_too(
        self, testing_pkg: testing_package.TestingPackage
    ):
        _add_grader(testing_pkg, 'graders/grader.cpp')
        testing_pkg.add_file('rbx.override.h').write_text('// override\n')

        header.generate_header()

        assert pathlib.Path('graders/rbx.h').read_text() == '// override\n'

    def test_no_link_without_a_grader(
        self, testing_pkg: testing_package.TestingPackage
    ):
        header.generate_header()

        assert not list(pathlib.Path().rglob('*/rbx.h'))

    def test_no_link_for_a_grader_at_the_package_root(
        self, testing_pkg: testing_package.TestingPackage
    ):
        _add_grader(testing_pkg, 'grader.cpp')

        header.generate_header()

        assert not pathlib.Path('rbx.h').is_symlink()


class TestScannerSeesThroughTheLink:
    def test_include_through_the_link_resolves_to_the_package_header(
        self, testing_pkg: testing_package.TestingPackage
    ):
        # Flattening ships one file per resolved target: resolving to the link
        # would ship the header twice (`rbx.h` and `graders__rbx.h`).
        _add_grader(testing_pkg, 'graders/grader.cpp')
        testing_pkg.add_file('graders/task.h').write_text('int f();\n')
        header.generate_header()

        refs = CppScanner().references(pathlib.Path('graders/grader.cpp'))

        assert {r.spelling: r.target for r in refs} == {
            'rbx.h': pathlib.Path('rbx.h'),
            'task.h': pathlib.Path('graders/task.h'),
        }
