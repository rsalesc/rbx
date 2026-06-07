from rbx.box import code
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package
from rbx.grading.steps import DigestOrDest, DigestOrSource


class TestAutoExpansionIntegration:
    async def test_subdir_cpp_autodiscovers_parent_include(
        self, testing_pkg: testing_package.TestingPackage
    ):
        testing_pkg.add_file('lib.h').write_text(
            '#pragma once\ninline int answer(){ return 42; }\n'
        )
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "../lib.h"\n#include <cstdio>\n'
            'int main(){ printf("%d\\n", answer()); }\n'
        )
        # No manual compilationFiles -- must be auto-discovered.
        assert await code.compile_item(CodeItem(path=gen, language='cpp'))

    async def test_flat_cpp_still_compiles(
        self, testing_pkg: testing_package.TestingPackage
    ):
        sol = testing_pkg.add_file('sol.cpp')
        sol.write_text('#include <cstdio>\nint main(){ printf("ok\\n"); }\n')
        assert await code.compile_item(CodeItem(path=sol, language='cpp'))

    async def test_python_subdir_sibling_import_runs(
        self, testing_pkg: testing_package.TestingPackage
    ):
        testing_pkg.add_file('sols/helper.py').write_text(
            'def value():\n    return 7\n'
        )
        main = testing_pkg.add_file('sols/main.py')
        # Absolute sibling import: resolves via sys.path[0] (the mirrored script dir)
        # when the script is executed directly, which is how rbx runs it.
        main.write_text('import helper\nprint(helper.value())\n')
        item = CodeItem(path=main, language='py')

        digest = await code.compile_item(item)
        output_path = testing_pkg.path('out.txt')
        run_log = await code.run_item(
            item,
            DigestOrSource.create(digest),
            stdout=DigestOrDest.create(output_path),
        )
        assert run_log is not None
        assert run_log.exitcode == 0
        assert output_path.read_text().strip() == '7'
