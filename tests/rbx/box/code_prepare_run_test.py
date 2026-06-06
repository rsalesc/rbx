import pathlib

from rbx.box import code
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package
from rbx.grading.steps import DigestOrSource


class TestPrepareRunExecutionFiles:
    async def test_python_sibling_module_mirrored(
        self, testing_pkg: testing_package.TestingPackage
    ):
        testing_pkg.add_file('sols/helper.py').write_text('X = 1\n')
        main = testing_pkg.add_file('sols/main.py')
        # Absolute sibling import is the runnable idiom for a directly-executed
        # script (a relative `from .` import cannot run as a bare __main__).
        main.write_text('import helper\nprint(helper.X)\n')
        item = CodeItem(path=main, language='py')

        digest = await code.compile_item(item)  # passthrough digest for Python
        prepared = await code._prepare_run(  # noqa: SLF001
            item, DigestOrSource.create(digest)
        )

        dests = {inp.dest for inp in prepared.artifacts.inputs}
        assert pathlib.Path('sols/helper.py') in dests

    async def test_manual_execution_file_mirrored(
        self, testing_pkg: testing_package.TestingPackage
    ):
        testing_pkg.add_file('data.txt')
        main = testing_pkg.add_file('m.py')
        main.write_text('print(1)\n')
        item = CodeItem(path=main, language='py', executionFiles=['data.txt'])

        digest = await code.compile_item(item)
        prepared = await code._prepare_run(  # noqa: SLF001
            item, DigestOrSource.create(digest)
        )

        dests = {inp.dest for inp in prepared.artifacts.inputs}
        assert pathlib.Path('data.txt') in dests

    async def test_cpp_contributes_no_runtime_deps(
        self, testing_pkg: testing_package.TestingPackage
    ):
        # A C++ source's includes are compile-time only: no auto runtime mirroring.
        testing_pkg.add_file('lib.h').write_text('#pragma once\n')
        main = testing_pkg.add_file('m.cpp')
        main.write_text('#include "lib.h"\nint main(){}\n')
        item = CodeItem(path=main, language='cpp')

        prepared = await code._prepare_run(  # noqa: SLF001
            item, DigestOrSource.create('deadbeef' * 5)
        )
        dests = {inp.dest for inp in prepared.artifacts.inputs}
        assert pathlib.Path('lib.h') not in dests
