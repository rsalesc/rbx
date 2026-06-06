from rbx.box import code
from rbx.box.generators import generate_testcases
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package


class TestSandboxMirroringIntegration:
    """Real-compile coverage for sandbox directory mirroring (#522)."""

    async def test_parent_dir_include_compiles(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A subdir source can #include "../lib.h" from the package root."""
        lib = testing_pkg.add_file('lib.h')
        lib.write_text('#pragma once\ninline int answer() { return 42; }\n')
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "../lib.h"\n'
            '#include <cstdio>\n'
            'int main() { printf("%d\\n", answer()); return 0; }\n'
        )
        code_item = CodeItem(path=gen, language='cpp', compilationFiles=['lib.h'])
        digest = await code.compile_item(code_item)
        assert digest

    async def test_subdir_source_finds_testlib(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A subdir source resolves #include "testlib.h" from __internal__/ (via -I)."""
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "testlib.h"\n'
            'int main(int argc, char* argv[]) {\n'
            '  registerGen(argc, argv, 1);\n'
            '  printf("%d\\n", (int)rnd.next(1, 10));\n'
            '  return 0;\n'
            '}\n'
        )
        digest = await code.compile_item(CodeItem(path=gen, language='cpp'))
        assert digest

    async def test_subdir_source_with_bits_stdcpp_compiles(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A subdir source resolves <bits/stdc++.h> from __internal__/ (via -I).

        On hosts whose compiler lacks the header, rbx injects it at
        ``__internal__/bits/stdc++.h`` and exposes it with ``-I__internal__``; on
        hosts that ship it, the system copy is used. Either way this must compile.
        """
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include <bits/stdc++.h>\nint main() { std::printf("ok\\n"); return 0; }\n'
        )
        digest = await code.compile_item(CodeItem(path=gen, language='cpp'))
        assert digest

    async def test_flat_source_still_compiles(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Flat-layout sources keep compiling unchanged."""
        sol = testing_pkg.add_file('sol.cpp')
        sol.write_text('#include <cstdio>\nint main(){ printf("ok\\n"); }\n')
        digest = await code.compile_item(CodeItem(path=sol, language='cpp'))
        assert digest

    async def test_user_header_beside_source_shadows_builtin(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A declared user header beside the source wins over the __internal__/ builtin.

        The local ``testlib.h`` (declared as a compilation file so it lands beside the
        source) defines a sentinel the real testlib.h lacks, so the source only
        compiles if the source-relative copy is used instead of the builtin in
        ``__internal__/`` (quoted includes resolve source-dir first).
        """
        testing_pkg.add_file('gens/testlib.h').write_text(
            '#pragma once\ninline int sentinel() { return 7; }\n'
        )
        gen = testing_pkg.add_file('gens/gen.cpp')
        gen.write_text(
            '#include "testlib.h"\n'
            '#include <cstdio>\n'
            'int main() { printf("%d\\n", sentinel()); return 0; }\n'
        )
        code_item = CodeItem(
            path=gen, language='cpp', compilationFiles=['gens/testlib.h']
        )
        digest = await code.compile_item(code_item)
        assert digest

    async def test_subdir_python_generator_runs_from_mirrored_location(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A Python generator in a subdir runs from its mirrored sandbox location.

        Exercises the execution working directory (not just compilation): the
        Python source's ``executable`` maps to ``{source}``, so it must be placed
        and invoked at its package-relative path (``gens/gen.py``).
        """
        testing_pkg.add_generator('gens/gen.py').write_text(
            'import sys\nprint(sys.argv[1])\n'
        )
        testing_pkg.add_testgroup_from_plan('main', 'gens/gen.py 42\n')

        await generate_testcases()

        assert (
            testing_pkg.get_build_testgroup_path('main') / '000.in'
        ).read_text() == '42\n'
